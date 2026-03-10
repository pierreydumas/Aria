from __future__ import annotations

from aria_models.loader import normalize_temperature


def test_normalize_temperature_for_kimi_forces_one():
    assert normalize_temperature("kimi", 0.3) == 1.0


def test_normalize_temperature_for_non_moonshot_model_preserves_value():
    assert normalize_temperature("qwen3.5_mlx", 0.3) == 0.3