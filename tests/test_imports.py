"""Import smoke tests for the quick verification target."""

from __future__ import annotations

import importlib

import pytest


MODULES = [
    "aria_agents",
    "aria_engine",
    "aria_mind",
    "aria_models",
    "aria_skills",
    "aria_skills.llm",
    "aria_skills.pytest_runner",
    "aria_skills.session_manager",
]


@pytest.mark.parametrize("module_name", MODULES)
def test_module_imports(module_name: str) -> None:
    """Critical packages should import cleanly in the local dev environment."""
    importlib.import_module(module_name)