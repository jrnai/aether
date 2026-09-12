"""Unit tests for ComfyUI Image Generation Server and Web API endpoints."""
import json
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path

from starlette.testclient import TestClient

from src.servers.image_server import (
    ComfyUIClient,
    ComfyUILifecycleManager,
    generate_image,
    get_comfyui_status,
    lifecycle_manager,
    stop_comfyui,
    ensure_comfyui_running,
    GENERATED_IMAGES_DIR,
)
from src.agent.loop import AgentLoop, detect_intent_domains
from src.web.server import app


class TestComfyUIClient(unittest.TestCase):
    """Test suite for ComfyUIClient and workflow construction."""

    def setUp(self):
        self.client = ComfyUIClient(base_url="http://127.0.0.1:8188")

    @patch("urllib.request.urlopen")
    def test_check_health_online(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        self.assertTrue(self.client.check_health())

    @patch("urllib.request.urlopen")
    def test_check_health_offline(self, mock_urlopen):
        mock_urlopen.side_effect = Exception("Connection refused")
        self.assertFalse(self.client.check_health())

    def test_select_best_checkpoint(self):
        # Prefers high-fidelity photorealism (Juggernaut XL) over turbo and lightning
        ckpts = [
            "v1-5-pruned.safetensors",
            "sd_xl_turbo_1.0_fp16.safetensors",
            "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors",
            "sdxl_lightning_4step.safetensors",
        ]
        self.assertEqual(self.client.select_best_checkpoint(ckpts), "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors")

        # Prefers turbo when juggernaut not present
        ckpts = ["v1-5-pruned.safetensors", "sd_xl_base_1.0.safetensors", "sd_xl_turbo_1.0_fp16.safetensors"]
        self.assertEqual(self.client.select_best_checkpoint(ckpts), "sd_xl_turbo_1.0_fp16.safetensors")

        # Prefers lightning over standard SDXL
        ckpts = ["v1-5-pruned.safetensors", "sd_xl_base_1.0.safetensors", "sdxl_lightning_4step.safetensors"]
        self.assertEqual(self.client.select_best_checkpoint(ckpts), "sdxl_lightning_4step.safetensors")

        # Prefers SDXL over 1.5
        ckpts = ["v1-5-pruned.safetensors", "sd_xl_base_1.0.safetensors"]
        self.assertEqual(self.client.select_best_checkpoint(ckpts), "sd_xl_base_1.0.safetensors")

        # Empty fallback
        self.assertIsNone(self.client.select_best_checkpoint([]))

    def test_build_workflow_juggernaut(self):
        with patch.object(self.client, "get_available_checkpoints", return_value=["Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors"]):
            workflow, ckpt = self.client.build_workflow(
                prompt="photorealistic portrait of an astronaut",
                negative_prompt="blurry, distorted",
                width=1024,
                height=1024,
            )
            self.assertEqual(ckpt, "Juggernaut-XL_v9_RunDiffusionPhoto_v2.safetensors")
            ksampler = workflow["3"]["inputs"]
            self.assertEqual(ksampler["steps"], 25)
            self.assertEqual(ksampler["cfg"], 6.0)
            self.assertEqual(ksampler["sampler_name"], "dpmpp_2m")
            self.assertEqual(ksampler["scheduler"], "karras")
            self.assertEqual(workflow["6"]["inputs"]["text"], "photorealistic portrait of an astronaut")
            self.assertEqual(workflow["5"]["inputs"]["width"], 1024)

    def test_build_workflow_turbo(self):
        with patch.object(self.client, "get_available_checkpoints", return_value=["sd_xl_turbo_1.0_fp16.safetensors"]):
            workflow, ckpt = self.client.build_workflow(
                prompt="a cyberpunk city at night",
                negative_prompt="blurry",
                width=1024,
                height=1024,
            )
            self.assertEqual(ckpt, "sd_xl_turbo_1.0_fp16.safetensors")
            ksampler = workflow["3"]["inputs"]
            self.assertEqual(ksampler["steps"], 2)
            self.assertEqual(ksampler["cfg"], 1.5)
            self.assertEqual(ksampler["sampler_name"], "euler_ancestral")
            self.assertEqual(workflow["6"]["inputs"]["text"], "a cyberpunk city at night")
            self.assertEqual(workflow["5"]["inputs"]["width"], 1024)

    def test_build_workflow_lightning(self):
        with patch.object(self.client, "get_available_checkpoints", return_value=["sdxl_lightning_4step.safetensors"]):
            workflow, ckpt = self.client.build_workflow(
                prompt="a majestic mountain",
                width=1024,
                height=768,
            )
            self.assertEqual(ckpt, "sdxl_lightning_4step.safetensors")
            ksampler = workflow["3"]["inputs"]
            self.assertEqual(ksampler["steps"], 4)
            self.assertEqual(ksampler["sampler_name"], "euler")
            self.assertEqual(ksampler["scheduler"], "sgm_uniform")


class TestGenerateImage(unittest.TestCase):
    """Test suite for generate_image function and mock execution."""

    def test_generate_image_offline_returns_instructional_error(self):
        mock_client = MagicMock(spec=ComfyUIClient)
        mock_client.check_health.return_value = False
        mock_client.base_url = "http://127.0.0.1:8188"

        res = generate_image(prompt="test prompt", client=mock_client)
        self.assertEqual(res["status"], "error")
        self.assertIn("ComfyUI is not currently running", res["error"])
        self.assertIn("scripts/setup_comfyui.bat", res["message"])
        self.assertIsNone(res["image_url"])

    def test_generate_image_success_flow(self):
        mock_client = MagicMock(spec=ComfyUIClient)
        mock_client.check_health.return_value = True
        mock_client.build_workflow.return_value = ({}, "sd_xl_turbo_1.0_fp16.safetensors")
        mock_client.queue_prompt.return_value = "prompt-uuid-123"
        mock_client.wait_for_prompt_completion.return_value = [
            {"filename": "Aether_0001.png", "subfolder": "", "type": "output"}
        ]
        # Fake 1x1 PNG bytes
        mock_client.fetch_image_bytes.return_value = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR..."

        res = generate_image(
            prompt="futuristic neon desktop",
            width=1024,
            height=1024,
            client=mock_client,
        )

        self.assertEqual(res["status"], "success")
        self.assertIn("/api/generated_images/", res["image_url"])
        self.assertTrue(res["markdown"].startswith("![futuristic neon desktop]"))
        self.assertTrue(Path(res["local_path"]).exists())

        # Cleanup generated test file
        Path(res["local_path"]).unlink(missing_ok=True)

    def test_intent_domain_detection(self):
        domains = detect_intent_domains("please generate an image of a neon cat")
        self.assertIn("image_generation", domains)

        domains2 = detect_intent_domains("draw a sketch of a futuristic city")
        self.assertIn("image_generation", domains2)

        domains3 = detect_intent_domains("create an illustration of a spaceship")
        self.assertIn("image_generation", domains3)


class TestWebImageEndpoints(unittest.TestCase):
    """Test suite for /api/generated_images and /api/image/status endpoints."""

    def setUp(self):
        self.client = TestClient(app)

    def test_api_image_status(self):
        with patch("src.web.server.get_comfyui_status") as mock_status:
            mock_status.return_value = {
                "online": True,
                "base_url": "http://127.0.0.1:8188",
                "checkpoints": ["sd_xl_turbo_1.0_fp16.safetensors"],
                "active_checkpoint": "sd_xl_turbo_1.0_fp16.safetensors",
                "gpu_devices": ["NVIDIA GeForce RTX 5060"],
            }
            resp = self.client.get("/api/image/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertTrue(data["online"])
            self.assertEqual(data["gpu_devices"], ["NVIDIA GeForce RTX 5060"])

    def test_api_generated_image_traversal_prevention(self):
        resp = self.client.get("/api/generated_images/..%2fsecret.png")
        self.assertIn(resp.status_code, [400, 404])

    def test_api_generated_image_serving(self):
        # Create a test image in data/generated_images
        test_file = GENERATED_IMAGES_DIR / "test_sample_image.png"
        test_file.write_bytes(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest")

        try:
            resp = self.client.get("/api/generated_images/test_sample_image.png")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers["content-type"], "image/png")
            self.assertEqual(resp.content, b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDRtest")
        finally:
            test_file.unlink(missing_ok=True)


class TestComfyUILifecycleManager(unittest.TestCase):
    """Test suite for ComfyUILifecycleManager wake-on-demand, watchdog, and auto-sleep."""

    def setUp(self):
        self.mock_client = MagicMock(spec=ComfyUIClient)
        self.manager = ComfyUILifecycleManager(self.mock_client, idle_timeout_seconds=0.1)

    def tearDown(self):
        self.manager.stop()

    def test_touch_updates_timestamp(self):
        self.assertEqual(self.manager._last_used_timestamp, 0.0)
        self.mock_client.check_health.return_value = True
        self.manager.touch()
        self.assertGreater(self.manager._last_used_timestamp, 0.0)
        self.assertEqual(self.manager._state, "running")

    def test_ensure_running_fast_path_when_already_healthy(self):
        self.mock_client.check_health.return_value = True
        result = self.manager.ensure_running()
        self.assertTrue(result)
        self.assertEqual(self.manager._state, "running")

    @patch("subprocess.Popen")
    def test_ensure_running_spawns_process_when_offline(self, mock_popen):
        # Starts offline, then becomes healthy
        self.mock_client.check_health.side_effect = [False, True]
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch.object(self.manager, "find_comfyui_dir", return_value=Path("C:/Mock/ComfyUI")):
            result = self.manager.ensure_running(timeout=5.0)

        self.assertTrue(result)
        self.assertEqual(self.manager._state, "running")
        self.assertTrue(self.manager._managed)
        mock_popen.assert_called_once()

    def test_stop_calls_free_vram_and_terminates(self):
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        self.manager._process = mock_proc
        self.manager._managed = True
        self.manager._state = "running"

        self.manager.stop()

        self.mock_client.free_memory.assert_called_once_with(unload_models=True, free_memory=True)
        mock_proc.terminate.assert_called_once()
        self.assertEqual(self.manager._state, "stopped")
        self.assertIsNone(self.manager._process)

    def test_get_status_info(self):
        self.mock_client.check_health.return_value = True
        self.manager.touch()
        info = self.manager.get_status_info()
        self.assertEqual(info["lifecycle_state"], "running")
        self.assertIsNotNone(info["idle_seconds"])
        self.assertEqual(info["auto_sleep_timeout_seconds"], 0.1)

    @patch("urllib.request.urlopen")
    def test_free_memory_client_call(self, mock_urlopen):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_urlopen.return_value.__enter__.return_value = mock_resp

        client = ComfyUIClient(base_url="http://127.0.0.1:8188")
        success = client.free_memory(unload_models=True, free_memory=True)
        self.assertTrue(success)


if __name__ == "__main__":
    unittest.main()
