from __future__ import annotations

import json
from pathlib import Path

import pytest


def test_deepseek_v4_flash_defaults_and_runtime_cap(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import _validate_profile_policy
    from factor_factory.console.model_broker import (
        CONSOLE_MODEL_MAX_OUTPUT_TOKENS,
        DEEPSEEK_PROVIDER,
        DEEPSEEK_V4_FLASH_CONTEXT_WINDOW,
        DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS,
        DEEPSEEK_V4_FLASH_MODEL,
        DEEPSEEK_V4_FLASH_OPENCLAW_MODEL,
        ModelBrokerConfig,
    )

    monkeypatch.delenv("FACTORFORGE_CONSOLE_MODEL", raising=False)
    monkeypatch.delenv("FACTORFORGE_CONSOLE_OPENCLAW_AUTH_PROVIDER", raising=False)
    config = ConsoleConfig.from_env(
        source_repo=tmp_path / "source",
        state_root=tmp_path / "state",
        worktree_root=tmp_path / "runs",
        auth_disabled=True,
    )
    assert config.openclaw_model == DEEPSEEK_V4_FLASH_OPENCLAW_MODEL
    assert config.openclaw_auth_provider == DEEPSEEK_PROVIDER

    broker = ModelBrokerConfig(
        api_key_file=tmp_path / "unused-key",
        client_token_file=tmp_path / "unused-client-token",
    )
    assert broker.allowed_model == DEEPSEEK_V4_FLASH_MODEL

    template = (
        Path(__file__).resolve().parents[1]
        / "deploy"
        / "factorforge-console"
        / "openclaw.json.example"
    )
    payload = json.loads(template.read_text(encoding="utf-8"))
    model = payload["models"]["providers"][DEEPSEEK_PROVIDER]["models"][0]
    assert model["id"] == DEEPSEEK_V4_FLASH_MODEL
    assert model["contextWindow"] == DEEPSEEK_V4_FLASH_CONTEXT_WINDOW
    assert model["maxTokens"] == DEEPSEEK_V4_FLASH_MAX_OUTPUT_TOKENS
    assert payload["agents"]["defaults"]["models"][DEEPSEEK_V4_FLASH_OPENCLAW_MODEL] == {
        "params": {"maxTokens": CONSOLE_MODEL_MAX_OUTPUT_TOKENS}
    }
    _validate_profile_policy(payload)


def test_container_config_and_task_override_reject_retired_model(tmp_path: Path) -> None:
    from factor_factory.console.config import ConsoleConfig
    from factor_factory.console.container_agent_adapter import _pinned_container_model
    from factor_factory.console.model_broker import (
        DEEPSEEK_V4_FLASH_MODEL,
        DEEPSEEK_V4_FLASH_OPENCLAW_MODEL,
        normalize_deepseek_openclaw_model,
    )

    with pytest.raises(ValueError, match="DeepSeek V4 Flash"):
        ConsoleConfig(
            source_repo=tmp_path / "source",
            state_root=tmp_path / "state",
            worktree_root=tmp_path / "runs",
            openclaw_model="deepseek/deepseek-reasoner",
            auth_disabled=True,
        )
    with pytest.raises(RuntimeError, match="DeepSeek V4 Flash"):
        _pinned_container_model("deepseek/deepseek-reasoner")
    assert _pinned_container_model(DEEPSEEK_V4_FLASH_OPENCLAW_MODEL) == (
        DEEPSEEK_V4_FLASH_OPENCLAW_MODEL
    )
    assert _pinned_container_model(DEEPSEEK_V4_FLASH_MODEL) == (
        DEEPSEEK_V4_FLASH_OPENCLAW_MODEL
    )
    assert normalize_deepseek_openclaw_model(DEEPSEEK_V4_FLASH_MODEL) == (
        DEEPSEEK_V4_FLASH_OPENCLAW_MODEL
    )
    with pytest.raises(ValueError, match="DeepSeek V4 Flash"):
        normalize_deepseek_openclaw_model("deepseek-reasoner")
