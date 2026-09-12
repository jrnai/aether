"""Local LLM client interface for Ollama."""
import json
import logging
import urllib.error
import urllib.request
from collections.abc import Generator
from typing import Any

logger = logging.getLogger("aether.client")


class OllamaClient:
    """Interface to communicate with local Ollama instance for chat and tool-calling."""

    _cached_models: list[str] | None = None
    _cached_models_time: float = 0.0

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:11434",
        default_model: str = "qwen2.5:7b-instruct",
        default_num_ctx: int = 16384,
        keep_alive: str = "24h",
    ) -> None:
        # Always normalize localhost to 127.0.0.1 to prevent Windows IPv6 resolution stall (2.08s TCP SYN timeout)
        clean_url = base_url.rstrip("/")
        if clean_url.startswith("http://localhost:"):
            clean_url = clean_url.replace("http://localhost:", "http://127.0.0.1:", 1)
        elif clean_url.startswith("https://localhost:"):
            clean_url = clean_url.replace("https://localhost:", "https://127.0.0.1:", 1)
        elif clean_url in ("http://localhost", "localhost"):
            clean_url = "http://127.0.0.1:11434"
        self.base_url = clean_url
        self.default_model = default_model
        self.default_num_ctx = default_num_ctx
        self.keep_alive = keep_alive

    def is_connected(self) -> bool:
        """Check if local Ollama daemon is reachable."""
        try:
            req = urllib.request.Request(f"{self.base_url}/api/version", method="GET")
            with urllib.request.urlopen(req, timeout=1.5) as response:
                return response.status == 200
        except Exception:
            return False

    def list_models(self, force_refresh: bool = False) -> list[str]:
        """Fetch list of models available in the local Ollama instance with 30s cache."""
        import time
        now = time.time()
        if not force_refresh and OllamaClient._cached_models is not None and (now - OllamaClient._cached_models_time < 30.0):
            return list(OllamaClient._cached_models)

        try:
            req = urllib.request.Request(f"{self.base_url}/api/tags", method="GET")
            with urllib.request.urlopen(req, timeout=3.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                models = [m["name"] for m in data.get("models", [])]
                OllamaClient._cached_models = models
                OllamaClient._cached_models_time = now
                return models
        except Exception as e:
            logger.warning("Could not list Ollama models: %s", e)
            return list(OllamaClient._cached_models) if OllamaClient._cached_models else []

    def pull_model(self, model_name: str) -> bool:
        """Pull a model into local Ollama daemon (e.g. deepseek-r1:7b)."""
        try:
            req_data = json.dumps({"name": model_name, "stream": False}).encode("utf-8")
            req = urllib.request.Request(
                f"{self.base_url}/api/pull",
                data=req_data,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=600.0) as response:
                return response.status == 200
        except Exception as e:
            logger.warning("Failed to pull model %s: %s", model_name, e)
            return False

    def _prepare_payload(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int | None = None,
        stream: bool = False,
    ) -> tuple[dict[str, Any], str]:
        target_model = model or self.default_model

        try:
            available = self.list_models()
            if available and target_model not in available:
                prefix = target_model.split(":")[0]
                matched = next((m for m in available if m.startswith(prefix)), None)
                fallback = matched or available[0]
                logger.info(
                    "Model '%s' not found locally in Ollama. Using available model '%s'.",
                    target_model,
                    fallback,
                )
                target_model = fallback
        except Exception as e:
            logger.debug("Failed checking model availability: %s", e)

        ctx_window = num_ctx if num_ctx is not None else self.default_num_ctx
        payload: dict[str, Any] = {
            "model": target_model,
            "messages": messages,
            "stream": stream,
            "keep_alive": self.keep_alive,
            "options": {
                "temperature": temperature,
                "num_ctx": ctx_window,
            },
        }
        if tools:
            payload["tools"] = tools

        return payload, target_model

    def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int | None = None,
    ) -> dict[str, Any]:
        """Send chat messages and tool definitions to Ollama and return raw message dict.

        Returns:
            dict containing at least {"role": "assistant", "content": ..., "tool_calls": [...]}
        """
        payload, target_model = self._prepare_payload(
            messages=messages,
            tools=tools,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
            stream=False,
        )

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=120.0) as response:
                data = json.loads(response.read().decode("utf-8"))
                message = data.get("message", {})
                return message
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
                err_data = json.loads(err_body)
                err_msg = err_data.get("error", err_body)
            except Exception:
                err_msg = err_body or str(e)

            if e.code == 404:
                available = self.list_models()
                logger.error("Model '%s' not found on Ollama: %s", target_model, err_msg)
                raise RuntimeError(
                    f"Model '{target_model}' not found in local Ollama instance. "
                    f"Installed models: {available}. "
                    f"Run `ollama pull {target_model}` or configure an available model."
                ) from e
            logger.error("Ollama HTTP Error %s: %s", e.code, err_msg)
            raise RuntimeError(f"Ollama server returned error {e.code}: {err_msg}") from e
        except urllib.error.URLError as e:
            logger.error("Failed to connect to Ollama at %s: %s", self.base_url, e)
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running (`ollama serve`)."
            ) from e

    def chat_stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        model: str | None = None,
        temperature: float = 0.1,
        num_ctx: int | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """Send chat request to Ollama with streaming enabled, yielding chunks.

        Yields:
            dict: Event objects including:
                - {"type": "token", "delta": "word"}
                - {"type": "tool_calls", "tool_calls": [...]}
                - {"type": "done", "message": full_message, "stats": {...}}
        """
        payload, target_model = self._prepare_payload(
            messages=messages,
            tools=tools,
            model=model,
            temperature=temperature,
            num_ctx=num_ctx,
            stream=True,
        )

        req_data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=req_data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=180.0) as response:
                full_content: list[str] = []
                accumulated_tool_calls: list[dict[str, Any]] = []
                for line in response:
                    line_clean = line.strip()
                    if not line_clean:
                        continue
                    chunk = json.loads(line_clean.decode("utf-8"))
                    msg = chunk.get("message", {})
                    delta = msg.get("content", "")
                    if delta:
                        full_content.append(delta)
                        yield {"type": "token", "delta": delta}

                    t_calls = msg.get("tool_calls")
                    if t_calls:
                        accumulated_tool_calls.extend(t_calls)
                        yield {"type": "tool_calls", "tool_calls": t_calls}

                    if chunk.get("done"):
                        final_msg = {
                            "role": "assistant",
                            "content": "".join(full_content),
                        }
                        if accumulated_tool_calls:
                            final_msg["tool_calls"] = accumulated_tool_calls
                        yield {
                            "type": "done",
                            "message": final_msg,
                            "eval_count": chunk.get("eval_count"),
                            "total_duration": chunk.get("total_duration"),
                            "model": target_model,
                        }
                        return
        except urllib.error.HTTPError as e:
            err_body = ""
            try:
                err_body = e.read().decode("utf-8")
                err_data = json.loads(err_body)
                err_msg = err_data.get("error", err_body)
            except Exception:
                err_msg = err_body or str(e)

            if e.code == 404:
                available = self.list_models()
                logger.error("Model '%s' not found on Ollama: %s", target_model, err_msg)
                raise RuntimeError(
                    f"Model '{target_model}' not found in local Ollama instance. "
                    f"Installed models: {available}. "
                    f"Run `ollama pull {target_model}` or configure an available model."
                ) from e
            logger.error("Ollama HTTP Error %s during stream: %s", e.code, err_msg)
            raise RuntimeError(f"Ollama server returned error {e.code}: {err_msg}") from e
        except urllib.error.URLError as e:
            logger.error("Failed to connect to Ollama at %s: %s", self.base_url, e)
            raise ConnectionError(
                f"Cannot connect to Ollama at {self.base_url}. Ensure Ollama is running (`ollama serve`)."
            ) from e
