"""Hierarchical configuration loader and schema validation for Project Aether."""
import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class LLMConfig(BaseModel):
    """LLM inference configuration."""
    provider: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen2.5:7b-instruct"
    coding_model: str = "qwen2.5-coder:7b"
    general_model: str = "qwen2.5:7b-instruct"
    reasoning_model: str = "deepseek-r1:7b"
    vision_model: str = "qwen2.5vl:7b"
    auto_route: bool = True
    temperature: float = 0.1
    context_window_tokens: int = 16384
    num_ctx: int = 16384
    flash_attention: bool = True
    dynamic_tool_masking: bool = True
    max_turn_steps: int = 25
    keep_alive: str = "24h"


class StorageConfig(BaseModel):
    """Data and vault storage directories."""
    database_path: str = "./data/aether.db"
    vault_path: str = "./data/vault"
    trash_path: str = "./data/vault/.trash"

    @property
    def vault_dir(self) -> Path:
        p = Path(self.vault_path).resolve()
        p.mkdir(parents=True, exist_ok=True)
        return p

    @property
    def db_path(self) -> Path:
        p = Path(self.database_path).resolve()
        p.parent.mkdir(parents=True, exist_ok=True)
        return p


class SafetyConfig(BaseModel):
    """Human-in-the-loop and mutation interceptor safety rules."""
    require_approval_on_mutation: bool = True
    approval_timeout_seconds: int = 60
    safe_tools_override: list[str] = Field(default_factory=list)


class DaemonConfig(BaseModel):
    """Background daemon scheduling and intervals."""
    enabled: bool = True
    morning_briefing_time: str = "07:30"
    email_poll_interval_minutes: int = 15
    sync_calendar_interval_minutes: int = 30


class LoggingConfig(BaseModel):
    """Logging and audit settings."""
    level: str = "INFO"
    log_to_stdout: bool = True
    audit_to_db: bool = True


class VoiceConfig(BaseModel):
    """Voice activation and hands-free assistant settings."""
    enabled: bool = False
    wake_word: str = "aether"
    threshold: float = 0.5
    stt_model: str = "base.en"
    tts_enabled: bool = True
    tts_voice: str = "en-US-AriaNeural"
    input_device_index: int | None = None
    silence_timeout_seconds: float = 1.2
    max_recording_seconds: float = 15.0
    pop_window_on_wake: bool = False


class AetherConfig(BaseModel):
    """Root configuration model for Project Aether."""
    version: str = "1.0"
    llm: LLMConfig = Field(default_factory=LLMConfig)
    storage: StorageConfig = Field(default_factory=StorageConfig)
    safety: SafetyConfig = Field(default_factory=SafetyConfig)
    daemon: DaemonConfig = Field(default_factory=DaemonConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    voice: VoiceConfig = Field(default_factory=VoiceConfig)


_CONFIG_INSTANCE: AetherConfig | None = None


def find_default_config_path() -> Path | None:
    """Locate the default configuration YAML file if available."""
    candidates = [
        Path("config/config.yaml"),
        Path(__file__).resolve().parent.parent / "config" / "config.yaml",
        Path("config/config.example.yaml"),
    ]
    for c in candidates:
        if c.exists():
            return c
    return None


def _apply_dict_updates(target: dict[str, Any], source: dict[str, Any]) -> None:
    """Recursively update target dict with source dict."""
    for key, value in source.items():
        if isinstance(value, dict) and key in target and isinstance(target[key], dict):
            _apply_dict_updates(target[key], value)
        else:
            target[key] = value


def load_config(
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
) -> AetherConfig:
    """Load configuration respecting precedence:
    1. CLI overrides (highest)
    2. Environment variables
    3. YAML config file
    4. Built-in defaults (lowest)
    """
    raw_config: dict[str, Any] = {}

    # Step 1: Load from YAML file if available
    yaml_file = Path(config_path) if config_path else find_default_config_path()
    if yaml_file and yaml_file.exists():
        try:
            with open(yaml_file, encoding="utf-8") as f:
                loaded = yaml.safe_load(f)
                if isinstance(loaded, dict):
                    raw_config = loaded
        except Exception:
            raw_config = {}

    # Step 2: Apply Environment Variables (AETHER_*)
    env_updates: dict[str, Any] = {}

    # Model & LLM
    if "AETHER_MODEL" in os.environ:
        env_updates.setdefault("llm", {})["model"] = os.environ["AETHER_MODEL"]
    if "AETHER_CODING_MODEL" in os.environ:
        env_updates.setdefault("llm", {})["coding_model"] = os.environ["AETHER_CODING_MODEL"]
    if "AETHER_GENERAL_MODEL" in os.environ:
        env_updates.setdefault("llm", {})["general_model"] = os.environ["AETHER_GENERAL_MODEL"]
    if "AETHER_REASONING_MODEL" in os.environ:
        env_updates.setdefault("llm", {})["reasoning_model"] = os.environ["AETHER_REASONING_MODEL"]
    if "AETHER_NUM_CTX" in os.environ:
        try:
            env_updates.setdefault("llm", {})["num_ctx"] = int(os.environ["AETHER_NUM_CTX"])
            env_updates.setdefault("llm", {})["context_window_tokens"] = int(os.environ["AETHER_NUM_CTX"])
        except ValueError:
            pass
    if "AETHER_FLASH_ATTENTION" in os.environ:
        env_updates.setdefault("llm", {})["flash_attention"] = os.environ["AETHER_FLASH_ATTENTION"].lower() in ("1", "true", "yes")
    if "AETHER_DYNAMIC_TOOL_MASKING" in os.environ:
        env_updates.setdefault("llm", {})["dynamic_tool_masking"] = os.environ["AETHER_DYNAMIC_TOOL_MASKING"].lower() in ("1", "true", "yes")
    if "AETHER_LLM_URL" in os.environ or "OLLAMA_HOST" in os.environ:
        url = os.environ.get("AETHER_LLM_URL") or os.environ.get("OLLAMA_HOST")
        env_updates.setdefault("llm", {})["base_url"] = url

    # Storage paths
    if "AETHER_VAULT_DIR" in os.environ:
        env_updates.setdefault("storage", {})["vault_path"] = os.environ["AETHER_VAULT_DIR"]
    if "AETHER_DB_PATH" in os.environ:
        env_updates.setdefault("storage", {})["database_path"] = os.environ["AETHER_DB_PATH"]

    # Logging
    if "AETHER_LOG_LEVEL" in os.environ:
        env_updates.setdefault("logging", {})["level"] = os.environ["AETHER_LOG_LEVEL"]

    _apply_dict_updates(raw_config, env_updates)

    # Step 3: Apply CLI Overrides
    if cli_overrides:
        _apply_dict_updates(raw_config, cli_overrides)

    config = AetherConfig(**raw_config)

    # Automatically set OLLAMA_FLASH_ATTENTION if enabled
    if config.llm.flash_attention:
        os.environ.setdefault("OLLAMA_FLASH_ATTENTION", "1")

    return config


def get_config(
    config_path: str | Path | None = None,
    cli_overrides: dict[str, Any] | None = None,
    reload: bool = False,
) -> AetherConfig:
    """Get or initialize singleton AetherConfig."""
    global _CONFIG_INSTANCE
    if _CONFIG_INSTANCE is None or reload:
        _CONFIG_INSTANCE = load_config(config_path=config_path, cli_overrides=cli_overrides)
    return _CONFIG_INSTANCE


def reset_config() -> None:
    """Reset the singleton instance (primarily for test isolation)."""
    global _CONFIG_INSTANCE
    _CONFIG_INSTANCE = None
