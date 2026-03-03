"""
Tests for the model_switcher skill (Layer 2).

Covers:
- build_thinking_params for different model families
- Initialization and default model
- switch_model and history tracking
- get_current_model
- set_thinking_mode / get_thinking_mode
- list_models fallback to models.yaml
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from aria_skills.model_switcher import ModelSwitcherSkill, build_thinking_params
from aria_skills.base import SkillConfig, SkillResult, SkillStatus


# ---------------------------------------------------------------------------
# build_thinking_params (pure function — no async needed)
# ---------------------------------------------------------------------------

def test_build_thinking_params_disabled():
    """When enable=False, returns empty dict regardless of model."""
    assert build_thinking_params("claude-3.5-sonnet", enable=False) == {}
    assert build_thinking_params("qwen-72b", enable=False) == {}


def test_build_thinking_params_claude():
    """Claude models (not in YAML) return empty params — YAML is the source of truth."""
    params = build_thinking_params("claude-3.5-sonnet", enable=True)
    assert params == {}


def test_build_thinking_params_qwen():
    """Qwen models registered in YAML get enable_thinking flag."""
    params = build_thinking_params("qwen3-mlx", enable=True)
    assert params["extra_body"]["enable_thinking"] is True


def test_build_thinking_params_deepseek():
    """DeepSeek models not in YAML return empty params (removed from catalog)."""
    params = build_thinking_params("deepseek-free", enable=True)
    assert params == {}


def test_build_thinking_params_unknown_model():
    """Unknown model returns empty dict (no special params)."""
    params = build_thinking_params("gpt-4o", enable=True)
    assert params == {}


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def switcher():
    """Return a ModelSwitcherSkill with mocked dependencies."""
    cfg = SkillConfig(name="model_switcher", config={})
    skill = ModelSwitcherSkill(cfg)
    return skill


# ---------------------------------------------------------------------------
# Initialization
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_initialize_default_model(switcher):
    """Skill initializes with a default model when models.yaml is unavailable."""
    with (
        patch("aria_skills.api_client.get_api_client", new_callable=AsyncMock, side_effect=Exception("no api")),
        patch("aria_models.loader.load_catalog", side_effect=ImportError),
    ):
        ok = await switcher.initialize()
    assert ok is True
    assert switcher._current_model == ""  # YAML unavailable → empty fallback
    assert switcher._status == SkillStatus.AVAILABLE


@pytest.mark.asyncio
async def test_initialize_reads_models_yaml(switcher):
    """If models.yaml is loadable, the primary model is picked from routing."""
    fake_catalog = {
        "tasks": {"primary": "gpt-4o", "primary_full": "litellm/gpt-4o"},
        "routing": {"primary": "litellm/gpt-4o"},
        "models": {},
    }
    with (
        patch("aria_skills.api_client.get_api_client", new_callable=AsyncMock, side_effect=Exception("no api")),
        patch("aria_models.loader.load_catalog", return_value=fake_catalog),
    ):
        ok = await switcher.initialize()
    assert ok is True
    assert switcher._current_model == "gpt-4o"


# ---------------------------------------------------------------------------
# switch_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_switch_model(switcher):
    """Switching models updates current_model and records history."""
    switcher._status = SkillStatus.AVAILABLE
    result = await switcher.switch_model(model="claude-3.5-sonnet", reason="testing")
    assert result.success is True
    assert result.data["current_model"] == "claude-3.5-sonnet"
    assert result.data["previous_model"] == "kimi"
    assert result.data["switch_count"] == 1


@pytest.mark.asyncio
async def test_switch_model_no_model(switcher):
    """Switching without a model name fails."""
    switcher._status = SkillStatus.AVAILABLE
    result = await switcher.switch_model(model="")
    assert result.success is False


@pytest.mark.asyncio
async def test_switch_model_history_accumulates(switcher):
    """History grows with each switch."""
    switcher._status = SkillStatus.AVAILABLE
    await switcher.switch_model(model="a")
    await switcher.switch_model(model="b")
    result = await switcher.get_switch_history()
    assert result.success is True
    assert result.data["total_switches"] == 2
    assert len(result.data["history"]) == 2


# ---------------------------------------------------------------------------
# get_current_model
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_get_current_model(switcher):
    """get_current_model reflects the active model."""
    switcher._status = SkillStatus.AVAILABLE
    switcher._current_model = "deepseek-r1"
    result = await switcher.get_current_model()
    assert result.success is True
    assert result.data["model"] == "deepseek-r1"


# ---------------------------------------------------------------------------
# Thinking mode
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_set_thinking_mode_enable(switcher):
    """Enabling thinking mode stores the flag and returns params."""
    switcher._status = SkillStatus.AVAILABLE
    switcher._current_model = "qwen3-mlx"  # Must be in YAML with thinking_params
    result = await switcher.set_thinking_mode(enabled=True)
    assert result.success is True
    assert result.data["thinking_enabled"] is True
    assert result.data["thinking_params"]["extra_body"]["enable_thinking"] is True


@pytest.mark.asyncio
async def test_set_thinking_mode_disable(switcher):
    """Disabling thinking mode returns no model params."""
    switcher._status = SkillStatus.AVAILABLE
    switcher._thinking_enabled = True
    result = await switcher.set_thinking_mode(enabled=False)
    assert result.success is True
    assert result.data["thinking_enabled"] is False
    assert result.data["thinking_params"] == {}


@pytest.mark.asyncio
async def test_get_thinking_mode(switcher):
    """get_thinking_mode reflects current state."""
    switcher._status = SkillStatus.AVAILABLE
    switcher._thinking_enabled = True
    switcher._current_model = "qwen3-mlx"  # Must be in YAML with thinking_params
    result = await switcher.get_thinking_mode()
    assert result.success is True
    assert result.data["thinking_enabled"] is True
    assert result.data["thinking_params"]["extra_body"]["enable_thinking"] is True


# ---------------------------------------------------------------------------
# list_models
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_list_models_from_catalog(switcher):
    """list_models falls back to models.yaml when API is unavailable."""
    switcher._status = SkillStatus.AVAILABLE
    switcher._api = None
    fake_catalog = {
        "models": {
            "gpt-4o": {"name": "GPT-4o", "tier": "high", "provider": "openai"},
            "kimi": {"name": "Kimi", "tier": "mid", "provider": "moonshot"},
        },
        "routing": {},
    }
    with patch("aria_models.loader.load_catalog", return_value=fake_catalog):
        result = await switcher.list_models()
    assert result.success is True
    assert result.data["total"] == 2
    ids = [m["id"] for m in result.data["models"]]
    assert "gpt-4o" in ids
    assert "kimi" in ids
