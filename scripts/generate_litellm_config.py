#!/usr/bin/env python3
"""
Generate stacks/brain/litellm-config.yaml from aria_models/models.yaml.

models.yaml is the SINGLE SOURCE OF TRUTH for all model configuration.
This script bridges models.yaml → litellm-config.yaml so you never need
to hand-edit the LiteLLM config after adding a model to models.yaml.

Usage:
    python scripts/generate_litellm_config.py
    python scripts/generate_litellm_config.py --dry-run
    python scripts/generate_litellm_config.py --output /custom/path.yaml
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

# Allow running from repo root or scripts/
REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

MODELS_YAML_PATH = REPO_ROOT / "aria_models" / "models.yaml"
LITELLM_CONFIG_PATH = REPO_ROOT / "stacks" / "brain" / "litellm-config.yaml"


def _load_models_yaml(path: Path) -> dict:
    """Load models.yaml (JSON or YAML)."""
    content = path.read_text(encoding="utf-8")
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        import yaml
        return yaml.safe_load(content) or {}


def _sha256(path: Path) -> str:
    """Compute SHA-256 hex digest of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_existing_config(path: Path) -> dict:
    """Load existing litellm-config.yaml to preserve non-model sections."""
    if not path.exists():
        return {}
    try:
        import yaml
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except ImportError:
        # Fallback: can't parse YAML without PyYAML, return empty
        print("WARNING: PyYAML not installed, cannot preserve existing settings")
        return {}


def _format_yaml_value(value, indent: int = 0) -> str:
    """Format a Python value as YAML string."""
    prefix = "  " * indent
    if isinstance(value, dict):
        lines = []
        for k, v in value.items():
            if isinstance(v, (dict, list)):
                lines.append(f"{prefix}{k}:")
                lines.append(_format_yaml_value(v, indent + 1))
            else:
                lines.append(f"{prefix}{k}: {_format_scalar(v)}")
        return "\n".join(lines)
    elif isinstance(value, list):
        lines = []
        for item in value:
            if isinstance(item, dict):
                first = True
                for k, v in item.items():
                    if first:
                        if isinstance(v, (dict, list)):
                            lines.append(f"{prefix}- {k}:")
                            lines.append(_format_yaml_value(v, indent + 2))
                        else:
                            lines.append(f"{prefix}- {k}: {_format_scalar(v)}")
                        first = False
                    else:
                        if isinstance(v, (dict, list)):
                            lines.append(f"{prefix}  {k}:")
                            lines.append(_format_yaml_value(v, indent + 2))
                        else:
                            lines.append(f"{prefix}  {k}: {_format_scalar(v)}")
            else:
                lines.append(f"{prefix}- {_format_scalar(item)}")
        return "\n".join(lines)
    else:
        return f"{prefix}{_format_scalar(value)}"


def _format_scalar(value) -> str:
    """Format a scalar value for YAML output."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return "null"
    # Strings that look like env refs or contain special chars
    s = str(value)
    if s.startswith("os.environ/") or s.startswith("${"):
        return s  # LiteLLM env refs are unquoted
    # Quote strings with special YAML characters
    if any(c in s for c in ":#{}[]|>&*!%@`"):
        return f'"{s}"'
    return s


def generate_model_list(catalog: dict) -> list[dict]:
    """Generate litellm model_list entries from models.yaml catalog."""
    models = catalog.get("models", {})
    entries = []

    for model_id, entry in models.items():
        litellm_params = entry.get("litellm")
        if not litellm_params:
            continue

        # Build litellm_params section
        params = {}
        params["model"] = litellm_params["model"]
        if "api_base" in litellm_params:
            params["api_base"] = litellm_params["api_base"]
        if "api_key" in litellm_params:
            params["api_key"] = litellm_params["api_key"]

        # Build model_info section
        cost = entry.get("cost", {})
        model_info = {
            "max_tokens": entry.get("contextWindow", 8192),
            "input_cost_per_token": cost.get("input", 0),
            "output_cost_per_token": cost.get("output", 0),
        }

        entries.append({
            "model_name": model_id,
            "litellm_params": params,
            "model_info": model_info,
        })

        # Emit alias entries
        for alias in entry.get("aliases", []):
            entries.append({
                "model_name": alias,
                "litellm_params": dict(params),
                "model_info": dict(model_info),
            })

    return entries


def _write_model_list_yaml(entries: list[dict], indent: str = "  ") -> str:
    """Write model_list entries as YAML text."""
    lines = []
    for entry in entries:
        mn = entry["model_name"]
        lines.append(f"  - model_name: {mn}")

        # litellm_params
        lines.append(f"    litellm_params:")
        for k, v in entry["litellm_params"].items():
            lines.append(f"      {k}: {_format_scalar(v)}")

        # model_info
        lines.append(f"    model_info:")
        for k, v in entry["model_info"].items():
            lines.append(f"      {k}: {_format_scalar(v)}")

        lines.append("")  # blank line between entries

    return "\n".join(lines)


def _write_settings_section(name: str, settings: dict) -> str:
    """Write a settings section (router_settings, general_settings, etc.)."""
    if not settings:
        return ""
    lines = [f"{name}:"]
    for k, v in settings.items():
        lines.append(f"  {k}: {_format_scalar(v)}")
    return "\n".join(lines)


def generate_config(
    catalog: dict,
    existing_config: dict,
    models_yaml_path: Path,
) -> str:
    """Generate complete litellm-config.yaml content."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha = _sha256(models_yaml_path)

    model_entries = generate_model_list(catalog)

    parts = []

    # Header comment
    parts.append(f"# AUTO-GENERATED from aria_models/models.yaml")
    parts.append(f"# Generated: {now}")
    parts.append(f"# Source SHA-256: {sha}")
    parts.append(f"# Do not hand-edit model_list — edit models.yaml and re-run:")
    parts.append(f"#   python scripts/generate_litellm_config.py")
    parts.append("")

    # model_list
    parts.append("model_list:")
    parts.append(_write_model_list_yaml(model_entries))

    # Preserve router_settings from existing config
    router_settings = existing_config.get("router_settings", {})
    if router_settings:
        parts.append(_write_settings_section("router_settings", router_settings))
        parts.append("")

    # Preserve general_settings
    general_settings = existing_config.get("general_settings", {})
    if general_settings:
        parts.append(_write_settings_section("general_settings", general_settings))
        parts.append("")

    # Preserve litellm_settings
    litellm_settings = existing_config.get("litellm_settings", {})
    if litellm_settings:
        parts.append(_write_settings_section("litellm_settings", litellm_settings))
        parts.append("")

    return "\n".join(parts).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate litellm-config.yaml from models.yaml"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print to stdout instead of writing file"
    )
    parser.add_argument(
        "--output", type=Path, default=LITELLM_CONFIG_PATH,
        help=f"Output path (default: {LITELLM_CONFIG_PATH})"
    )
    parser.add_argument(
        "--models", type=Path, default=MODELS_YAML_PATH,
        help=f"models.yaml path (default: {MODELS_YAML_PATH})"
    )
    args = parser.parse_args()

    if not args.models.exists():
        print(f"ERROR: models.yaml not found at {args.models}", file=sys.stderr)
        return 1

    catalog = _load_models_yaml(args.models)
    existing_config = _load_existing_config(args.output)
    output = generate_config(catalog, existing_config, args.models)

    if args.dry_run:
        print(output)
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(output, encoding="utf-8")
        n_models = len(generate_model_list(catalog))
        print(f"Generated {args.output} ({n_models} model entries)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
