"""Unit tests for Aether hierarchical configuration loading and precedence."""
import pytest
from pathlib import Path
from src.config import AetherConfig, get_config, load_config, reset_config


def test_default_config() -> None:
    reset_config()
    cfg = load_config(config_path="nonexistent_config.yaml")
    assert cfg.version == "1.0"
    assert cfg.llm.provider == "ollama"
    assert cfg.llm.context_window_tokens == 16384
    assert cfg.llm.num_ctx == 16384
    assert cfg.llm.coding_model == "qwen2.5-coder:7b"
    assert cfg.llm.general_model == "qwen2.5:7b-instruct"
    assert cfg.llm.reasoning_model == "deepseek-r1:7b"
    assert cfg.llm.flash_attention is True
    assert cfg.storage.database_path == "./data/aether.db"
    assert cfg.safety.require_approval_on_mutation is True


def test_yaml_config_loading(tmp_path: Path) -> None:
    yaml_content = """
version: "1.0"
llm:
  model: "custom-test-model:14b"
  temperature: 0.2
storage:
  vault_path: "./custom_vault"
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    cfg = load_config(config_path=yaml_file)
    assert cfg.llm.model == "custom-test-model:14b"
    assert cfg.llm.temperature == 0.2
    assert cfg.storage.vault_path == "./custom_vault"
    # Defaults preserved
    assert cfg.llm.context_window_tokens == 16384
    assert cfg.llm.num_ctx == 16384


def test_env_var_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_content = """
llm:
  model: "from-yaml:7b"
"""
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text(yaml_content, encoding="utf-8")

    monkeypatch.setenv("AETHER_MODEL", "from-env:8b")
    monkeypatch.setenv("AETHER_VAULT_DIR", "/custom/env/vault")

    cfg = load_config(config_path=yaml_file)
    # Env var takes precedence over YAML
    assert cfg.llm.model == "from-env:8b"
    assert cfg.storage.vault_path == "/custom/env/vault"


def test_cli_override_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    yaml_file = tmp_path / "config.yaml"
    yaml_file.write_text("llm:\n  model: 'yaml-model'\n", encoding="utf-8")

    monkeypatch.setenv("AETHER_MODEL", "env-model")

    cli_overrides = {"llm": {"model": "cli-model"}}
    cfg = load_config(config_path=yaml_file, cli_overrides=cli_overrides)

    # CLI takes highest precedence
    assert cfg.llm.model == "cli-model"


def test_singleton_get_config() -> None:
    reset_config()
    cfg1 = get_config()
    cfg2 = get_config()
    assert cfg1 is cfg2
