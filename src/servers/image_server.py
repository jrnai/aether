"""ComfyUI Image Generation Server for Project Aether.

Interfaces with a local ComfyUI instance (http://127.0.0.1:8188) to generate
high-performance images using SDXL-Turbo, SDXL-Lightning, or SD checkpoints
on local NVIDIA GPUs.
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import random
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

logger = logging.getLogger("aether.image")

COMFYUI_HOST = os.environ.get("COMFYUI_HOST", "127.0.0.1")
COMFYUI_PORT = int(os.environ.get("COMFYUI_PORT", "8188"))
COMFYUI_BASE_URL = f"http://{COMFYUI_HOST}:{COMFYUI_PORT}"

GENERATED_IMAGES_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "generated_images"
GENERATED_IMAGES_DIR.mkdir(parents=True, exist_ok=True)


class ComfyUIClient:
    """Client for interacting with local ComfyUI REST API."""

    def __init__(self, base_url: str = COMFYUI_BASE_URL):
        self.base_url = base_url.rstrip("/")

    def check_health(self, timeout: float = 1.5) -> bool:
        """Check if ComfyUI server is online and responding."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/system_stats",
                headers={"User-Agent": "Aether/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception:
            return False

    def get_system_stats(self, timeout: float = 2.0) -> dict[str, Any]:
        """Fetch system and GPU statistics from ComfyUI."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/system_stats",
                headers={"User-Agent": "Aether/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as err:
            logger.debug("ComfyUI stats error: %s", err)
            return {}

    def free_memory(self, unload_models: bool = True, free_memory: bool = True, timeout: float = 5.0) -> bool:
        """Call ComfyUI /free endpoint to unload models from VRAM and run garbage collection."""
        try:
            payload = json.dumps({"unload_models": unload_models, "free_memory": free_memory}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/free",
                data=payload,
                headers={"Content-Type": "application/json", "User-Agent": "Aether/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status == 200
        except Exception as err:
            logger.debug("ComfyUI free_memory error: %s", err)
            return False

    def get_available_checkpoints(self, timeout: float = 2.0) -> list[str]:
        """Query ComfyUI to discover installed checkpoint model filenames."""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/object_info/CheckpointLoaderSimple",
                headers={"User-Agent": "Aether/1.0"},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                info = data.get("CheckpointLoaderSimple", {}).get("input", {}).get("required", {})
                ckpt_tuple = info.get("ckpt_name", [])
                if ckpt_tuple and isinstance(ckpt_tuple, list) and isinstance(ckpt_tuple[0], list):
                    return ckpt_tuple[0]
                return []
        except Exception as err:
            logger.debug("Could not query ComfyUI checkpoints: %s", err)
            return []

    def select_best_checkpoint(self, available: list[str]) -> str | None:
        """Heuristically select best checkpoint (Juggernaut/Photorealism > Turbo > Lightning > SDXL > others)."""
        if not available:
            return None

        # 1. High-fidelity SDXL Photorealism (Juggernaut XL, RealVisXL)
        for c in available:
            lower = c.lower()
            if "juggernaut" in lower or "realvis" in lower:
                return c

        # 2. SDXL-Turbo
        for c in available:
            lower = c.lower()
            if "turbo" in lower and ("xl" in lower or "sdxl" in lower):
                return c
        for c in available:
            if "turbo" in c.lower():
                return c

        # 3. SDXL-Lightning
        for c in available:
            if "lightning" in c.lower():
                return c

        # 4. SDXL base
        for c in available:
            if "sd_xl" in c.lower() or "sdxl" in c.lower():
                return c

        # 5. Any SD 1.5 or general checkpoint
        return available[0]

    def build_workflow(
        self,
        prompt: str,
        negative_prompt: str = "blurry, low quality, distorted, deformed, text artifacts",
        width: int = 1024,
        height: int = 1024,
        checkpoint: str | None = None,
        seed: int | None = None,
    ) -> tuple[dict[str, Any], str]:
        """Build a standard ComfyUI txt2img workflow graph tuned for the selected model."""
        if seed is None:
            seed = random.randint(1, 2**32 - 1)

        available = self.get_available_checkpoints()
        if not available:
            comfy_dir = Path.home() / "ComfyUI"
            ckpt_dir = comfy_dir / "models" / "checkpoints"
            if ckpt_dir.is_dir():
                available = [f.name for f in ckpt_dir.glob("*.safetensors")]

        ckpt_name = (
            checkpoint
            or self.select_best_checkpoint(available)
            or "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"
        )
        lower_ckpt = ckpt_name.lower()

        # Determine optimal sampler settings based on model family
        if "juggernaut" in lower_ckpt or "realvis" in lower_ckpt:
            steps = 25
            cfg = 6.0
            sampler_name = "dpmpp_2m"
            scheduler = "karras"
        elif "turbo" in lower_ckpt:
            steps = 2
            cfg = 1.5
            sampler_name = "euler_ancestral"
            scheduler = "karras"
        elif "lightning" in lower_ckpt:
            steps = 4
            cfg = 1.5
            sampler_name = "euler"
            scheduler = "sgm_uniform"
        elif "flux" in lower_ckpt:
            steps = 4
            cfg = 1.0
            sampler_name = "euler"
            scheduler = "simple"
        else:
            steps = 20
            cfg = 7.0
            sampler_name = "euler"
            scheduler = "normal"

        workflow = {
            "3": {
                "class_type": "KSampler",
                "inputs": {
                    "cfg": cfg,
                    "denoise": 1,
                    "latent_image": ["5", 0],
                    "model": ["4", 0],
                    "negative": ["7", 0],
                    "positive": ["6", 0],
                    "sampler_name": sampler_name,
                    "scheduler": scheduler,
                    "seed": seed,
                    "steps": steps,
                },
            },
            "4": {
                "class_type": "CheckpointLoaderSimple",
                "inputs": {
                    "ckpt_name": ckpt_name,
                },
            },
            "5": {
                "class_type": "EmptyLatentImage",
                "inputs": {
                    "batch_size": 1,
                    "height": height,
                    "width": width,
                },
            },
            "6": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": prompt,
                },
            },
            "7": {
                "class_type": "CLIPTextEncode",
                "inputs": {
                    "clip": ["4", 1],
                    "text": negative_prompt,
                },
            },
            "8": {
                "class_type": "VAEDecode",
                "inputs": {
                    "samples": ["3", 0],
                    "vae": ["4", 2],
                },
            },
            "9": {
                "class_type": "SaveImage",
                "inputs": {
                    "filename_prefix": "Aether",
                    "images": ["8", 0],
                },
            },
        }
        return workflow, ckpt_name

    def queue_prompt(self, workflow: dict[str, Any], client_id: str | None = None) -> str:
        """Submit a prompt workflow to ComfyUI and return prompt_id."""
        cid = client_id or str(uuid.uuid4())
        payload = json.dumps({"prompt": workflow, "client_id": cid}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/prompt",
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "Aether/1.0"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10.0) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            prompt_id = data.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"ComfyUI rejected prompt: {data}")
            return prompt_id

    def wait_for_prompt_completion(
        self,
        prompt_id: str,
        timeout: float = 60.0,
        poll_interval: float = 0.5,
    ) -> list[dict[str, str]]:
        """Poll ComfyUI /history until the prompt finishes, returning output image info."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                req = urllib.request.Request(
                    f"{self.base_url}/history/{prompt_id}",
                    headers={"User-Agent": "Aether/1.0"},
                )
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    history = json.loads(resp.read().decode("utf-8"))
                    if prompt_id in history:
                        outputs = history[prompt_id].get("outputs", {})
                        images = []
                        for node_id, node_output in outputs.items():
                            if "images" in node_output:
                                images.extend(node_output["images"])
                        if images:
                            return images
            except Exception as err:
                logger.debug("Error polling history for prompt %s: %s", prompt_id, err)

            time.sleep(poll_interval)

        raise TimeoutError(f"ComfyUI prompt {prompt_id} timed out after {timeout} seconds.")

    def fetch_image_bytes(self, filename: str, subfolder: str = "", image_type: str = "output") -> bytes:
        """Download output image from ComfyUI view endpoint."""
        params = urllib.parse.urlencode({"filename": filename, "subfolder": subfolder, "type": image_type})
        url = f"{self.base_url}/view?{params}"
        req = urllib.request.Request(url, headers={"User-Agent": "Aether/1.0"})
        with urllib.request.urlopen(req, timeout=15.0) as resp:
            return resp.read()


class ComfyUILifecycleManager:
    """Manages on-demand wake-up, warm iteration, and auto-sleep for ComfyUI."""

    def __init__(
        self,
        client: ComfyUIClient,
        idle_timeout_seconds: float = 600.0,
    ):
        self.client = client
        self.idle_timeout_seconds = idle_timeout_seconds
        self._process: subprocess.Popen | None = None
        self._managed = False
        self._state: str = "stopped"  # "stopped" | "warming_up" | "running" | "stopping"
        self._last_used_timestamp: float = 0.0
        self._lock = threading.Lock()
        self._stop_watchdog = threading.Event()
        self._watchdog_thread: threading.Thread | None = None

    def find_comfyui_dir(self) -> Path | None:
        """Locate ComfyUI installation directory."""
        candidates: list[Path] = []
        custom_dir = os.environ.get("COMFYUI_DIR")
        if custom_dir:
            candidates.append(Path(custom_dir))

        candidates.append(Path.home() / "ComfyUI")
        project_root = Path(__file__).resolve().parent.parent.parent
        candidates.append(project_root.parent / "ComfyUI")

        for cand in candidates:
            if cand.is_dir() and (cand / "main.py").is_file():
                return cand.resolve()
        return None

    def find_python_exec(self) -> str:
        """Locate Python executable with PyTorch/ComfyUI dependencies."""
        project_root = Path(__file__).resolve().parent.parent.parent
        venv_py = project_root / ".venv" / "Scripts" / "python.exe"
        if venv_py.is_file():
            return str(venv_py)
        return sys.executable

    def touch(self) -> None:
        """Update activity timestamp to reset idle countdown."""
        with self._lock:
            self._last_used_timestamp = time.time()
            if self._state != "running" and self.client.check_health(timeout=0.5):
                self._state = "running"
            self._ensure_watchdog_running()

    def _ensure_watchdog_running(self) -> None:
        """Start background watchdog thread if not already running."""
        if self._watchdog_thread is None or not self._watchdog_thread.is_alive():
            self._stop_watchdog.clear()
            self._watchdog_thread = threading.Thread(
                target=self._watchdog_loop,
                name="ComfyUI-Watchdog",
                daemon=True,
            )
            self._watchdog_thread.start()

    def _watchdog_loop(self) -> None:
        """Monitor inactivity and trigger auto-sleep after idle timeout."""
        while not self._stop_watchdog.is_set():
            time.sleep(5.0)
            if self._stop_watchdog.is_set():
                break

            with self._lock:
                if self._state != "running":
                    continue
                last_used = self._last_used_timestamp
                idle_secs = time.time() - last_used if last_used > 0 else 0

            if last_used > 0 and idle_secs >= self.idle_timeout_seconds:
                logger.info(
                    "ComfyUI idle for %.1f minutes. Triggering auto-sleep...",
                    idle_secs / 60.0,
                )
                self.stop()

    def ensure_running(self, timeout: float = 60.0) -> bool:
        """Ensure ComfyUI is up and running. If offline, launches as background process."""
        # Fast path: already running
        if self.client.check_health(timeout=1.0):
            with self._lock:
                self._state = "running"
                self._last_used_timestamp = time.time()
                self._ensure_watchdog_running()
            return True

        with self._lock:
            comfy_dir = self.find_comfyui_dir()
            if not comfy_dir:
                logger.warning("ComfyUI directory not found. Cannot auto-wake.")
                return False

            py_exec = self.find_python_exec()
            logger.info("Spawning ComfyUI in background on port %d...", COMFYUI_PORT)
            self._state = "warming_up"

            log_dir = Path(__file__).resolve().parent.parent.parent / "data" / "logs"
            log_dir.mkdir(parents=True, exist_ok=True)
            log_file = log_dir / "comfyui_server.log"

            try:
                creationflags = 0
                if os.name == "nt":
                    creationflags = subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS

                cmd = [
                    py_exec,
                    "main.py",
                    "--listen",
                    COMFYUI_HOST,
                    "--port",
                    str(COMFYUI_PORT),
                ]
                log_handle = open(log_file, "a", encoding="utf-8")
                self._process = subprocess.Popen(
                    cmd,
                    cwd=str(comfy_dir),
                    stdout=log_handle,
                    stderr=subprocess.STDOUT,
                    creationflags=creationflags,
                )
                self._managed = True
            except Exception as err:
                logger.error("Failed to spawn ComfyUI process: %s", err)
                self._state = "stopped"
                return False

        # Wait outside lock for server to become responsive
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.client.check_health(timeout=1.0):
                with self._lock:
                    self._state = "running"
                    self._last_used_timestamp = time.time()
                    self._ensure_watchdog_running()
                logger.info("ComfyUI auto-wake successful in %.2fs.", time.time() - start_time)
                return True
            time.sleep(1.0)

        logger.warning("ComfyUI auto-wake timed out after %ss.", timeout)
        with self._lock:
            self._state = "stopped"
        return False

    def free_vram(self) -> bool:
        """Instruct ComfyUI to deallocate models from VRAM and free GPU memory."""
        return self.client.free_memory(unload_models=True, free_memory=True)

    def stop(self) -> None:
        """Stop ComfyUI service: release VRAM and terminate process if managed."""
        with self._lock:
            if self._state == "stopped" and self._process is None:
                return

            logger.info("Stopping ComfyUI service...")
            self._state = "stopping"

        # 1. Unload VRAM first
        try:
            self.free_vram()
        except Exception:
            pass

        # 2. Terminate managed process
        with self._lock:
            if self._process is not None:
                try:
                    if self._process.poll() is None:
                        self._process.terminate()
                        try:
                            self._process.wait(timeout=4.0)
                        except subprocess.TimeoutExpired:
                            self._process.kill()
                            self._process.wait(timeout=2.0)
                except Exception as err:
                    logger.debug("Error stopping ComfyUI process: %s", err)
                self._process = None

            self._state = "stopped"
            self._last_used_timestamp = 0.0
            logger.info("ComfyUI service stopped successfully.")

    def get_status_info(self) -> dict[str, Any]:
        """Return lifecycle and idle metrics for status endpoint."""
        with self._lock:
            healthy = self.client.check_health(timeout=0.5)
            state = "running" if healthy else self._state
            if state == "running" and not healthy:
                state = "stopped"

            idle_secs = None
            if state == "running" and self._last_used_timestamp > 0:
                idle_secs = max(0, round(time.time() - self._last_used_timestamp))

            return {
                "lifecycle_state": state,
                "idle_seconds": idle_secs,
                "auto_sleep_timeout_seconds": self.idle_timeout_seconds,
                "is_managed": self._managed,
            }


_default_client = ComfyUIClient()
lifecycle_manager = ComfyUILifecycleManager(_default_client)
ensure_comfyui_running = lifecycle_manager.ensure_running
stop_comfyui = lifecycle_manager.stop

atexit.register(lifecycle_manager.stop)


def generate_image(
    prompt: str,
    negative_prompt: str = "blurry, low quality, distorted, deformed, text artifacts",
    width: int = 1024,
    height: int = 1024,
    client: ComfyUIClient | None = None,
) -> dict[str, Any]:
    """Generate an image using the local ComfyUI diffusion backend.

    Args:
        prompt: Description of the scene/subject to generate.
        negative_prompt: Elements to avoid in generation.
        width: Image width in pixels (typically 1024 for SDXL).
        height: Image height in pixels (typically 1024 for SDXL).
        client: Optional custom ComfyUIClient instance.

    Returns:
        Structured result with status, image path, image URL, and markdown preview.
    """
    cli = client or _default_client

    # 1. Health check & on-demand wake-up
    if not cli.check_health():
        if client is None:
            logger.info("ComfyUI is offline. Attempting on-demand auto-wake...")
            wake_success = lifecycle_manager.ensure_running(timeout=60.0)
        else:
            wake_success = False

        if not wake_success or not cli.check_health():
            logger.warning("ComfyUI server is offline at %s", cli.base_url)
            return {
                "status": "error",
                "error": "ComfyUI is not currently running.",
                "message": (
                    "ComfyUI is not running on your machine (http://127.0.0.1:8188).\n\n"
                    "To generate images with your RTX 5060 GPU:\n"
                    "1. Run `scripts/setup_comfyui.bat` to download or prepare ComfyUI.\n"
                    "2. Run `scripts/run_comfyui.bat` to start the local server.\n\n"
                    "Once launched, ask me again and I will generate the image directly!"
                ),
                "markdown": "*(ComfyUI local server is offline at http://127.0.0.1:8188. Please start ComfyUI to enable local image generation.)*",
                "image_url": None,
            }

    # Reset activity watchdog
    lifecycle_manager.touch()

    try:
        # 2. Build graph and select checkpoint
        workflow, ckpt_name = cli.build_workflow(
            prompt=prompt,
            negative_prompt=negative_prompt,
            width=width,
            height=height,
        )

        logger.info("Submitting ComfyUI prompt with checkpoint '%s': %s", ckpt_name, prompt[:80])
        prompt_id = cli.queue_prompt(workflow)

        # 3. Wait for generation to complete
        images_info = cli.wait_for_prompt_completion(prompt_id, timeout=120.0)
        if not images_info:
            return {
                "status": "error",
                "error": "No output images produced by ComfyUI.",
                "message": "ComfyUI finished execution but produced no output images.",
                "image_url": None,
            }

        first_img = images_info[0]
        img_bytes = cli.fetch_image_bytes(
            filename=first_img["filename"],
            subfolder=first_img.get("subfolder", ""),
            image_type=first_img.get("type", "output"),
        )

        # 4. Save to Aether's data/generated_images/
        save_filename = f"{uuid.uuid4().hex[:12]}_{first_img['filename']}"
        local_path = GENERATED_IMAGES_DIR / save_filename
        local_path.write_bytes(img_bytes)

        image_url = f"/api/generated_images/{save_filename}"
        markdown_str = f"![{prompt}]({image_url})"

        # Keep alive for further iteration
        lifecycle_manager.touch()

        logger.info("Successfully generated image saved to %s", local_path)

        return {
            "status": "success",
            "prompt": prompt,
            "filename": save_filename,
            "local_path": str(local_path),
            "image_url": image_url,
            "markdown": markdown_str,
            "checkpoint": ckpt_name,
            "dimensions": f"{width}x{height}",
        }

    except Exception as err:
        logger.error("Error during image generation: %s", err, exc_info=True)
        return {
            "status": "error",
            "error": str(err),
            "message": f"Failed to generate image via ComfyUI: {err}",
            "image_url": None,
        }


def get_comfyui_status(client: ComfyUIClient | None = None) -> dict[str, Any]:
    """Retrieve ComfyUI connection status, GPU info, installed checkpoints, and lifecycle."""
    cli = client or _default_client
    online = cli.check_health()
    lifecycle_info = lifecycle_manager.get_status_info()

    if not online:
        return {
            "online": False,
            "base_url": cli.base_url,
            "checkpoints": [],
            "devices": [],
            **lifecycle_info,
        }

    stats = cli.get_system_stats()
    checkpoints = cli.get_available_checkpoints()
    best_ckpt = cli.select_best_checkpoint(checkpoints)

    devices = stats.get("devices", [])
    gpu_names = [d.get("name", "Unknown GPU") for d in devices if isinstance(d, dict)]

    return {
        "online": True,
        "base_url": cli.base_url,
        "checkpoints": checkpoints,
        "active_checkpoint": best_ckpt,
        "gpu_devices": gpu_names,
        **lifecycle_info,
    }
