from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).resolve().parent / "models.yaml"

# TTL-based cache (replaces @lru_cache to avoid staleness)
_CACHE_TTL_SECONDS = 300  # 5 minutes
_cache: dict[str, Any] = {}
_cache_timestamp: float = 0.0


def _load_yaml_or_json(path: Path) -> dict[str, Any]:
    content = path.read_text(encoding="utf-8")
    # JSON is valid YAML; parse JSON first for zero dependencies.
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        try:
            import yaml  # type: ignore
        except Exception as exc:  # pragma: no cover - optional dependency
            raise RuntimeError("PyYAML not installed and JSON parse failed") from exc
        return yaml.safe_load(content) or {}


def load_catalog(path: Path | None = None) -> dict[str, Any]:
    """Load the model catalog with 5-minute TTL cache.

    The cache is invalidated after ``_CACHE_TTL_SECONDS`` or when
    ``reload_models()`` is called.
    """
    global _cache, _cache_timestamp

    now = time.monotonic()
    cache_key = str(path or CATALOG_PATH)

    if _cache and (now - _cache_timestamp) < _CACHE_TTL_SECONDS:
        if cache_key in _cache:
            return _cache[cache_key]

    catalog_path = path or CATALOG_PATH
    if not catalog_path.exists():
        return {}
    result = _load_yaml_or_json(catalog_path)
    _cache[cache_key] = result
    _cache_timestamp = now
    return result


def reload_models() -> dict[str, Any]:
    """Clear the TTL cache and reload models.yaml from disk."""
    global _cache, _cache_timestamp
    _cache = {}
    _cache_timestamp = 0.0
    return load_catalog()


def validate_models(path: Path | None = None) -> list[str]:
    """Validate models.yaml structure. Returns list of error strings (empty = valid).

    Checks:
    - File exists and is valid JSON
    - Has ``schema_version`` and ``models`` keys
    - Each model entry has required fields (provider, litellm, contextWindow)
    - litellm sub-dict has ``model`` key
    """
    errors: list[str] = []
    catalog_path = path or CATALOG_PATH

    if not catalog_path.exists():
        errors.append(f"models.yaml not found at {catalog_path}")
        return errors

    try:
        catalog = _load_yaml_or_json(catalog_path)
    except (json.JSONDecodeError, RuntimeError) as exc:
        errors.append(f"Failed to parse models.yaml: {exc}")
        return errors
    except Exception as exc:
        errors.append(f"Failed to parse models.yaml: {exc}")
        return errors

    if "schema_version" not in catalog:
        errors.append("Missing 'schema_version' key")
    if "models" not in catalog:
        errors.append("Missing 'models' key")
        return errors

    models = catalog["models"]
    if not isinstance(models, dict):
        errors.append("'models' must be a dict")
        return errors

    required_fields = {"provider", "contextWindow"}
    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            errors.append(f"Model '{model_id}': entry must be a dict")
            continue
        for field in required_fields:
            if field not in entry:
                errors.append(f"Model '{model_id}': missing required field '{field}'")
        litellm_block = entry.get("litellm")
        if litellm_block is not None:
            if not isinstance(litellm_block, dict):
                errors.append(f"Model '{model_id}': 'litellm' must be a dict")
            elif "model" not in litellm_block:
                errors.append(f"Model '{model_id}': litellm block missing 'model' key")

    return errors


def normalize_model_id(model_id: str) -> str:
    if not model_id:
        return model_id
    if "/" in model_id:
        return model_id.split("/", 1)[1]
    return model_id


def get_model_entry(model_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any] | None:
    catalog = catalog or load_catalog()
    models = catalog.get("models", {}) if catalog else {}
    normalized = normalize_model_id(model_id)
    return models.get(normalized)


def get_route_skill(model_id: str, catalog: dict[str, Any] | None = None) -> str | None:
    entry = get_model_entry(model_id, catalog=catalog)
    if not entry:
        return None
    return entry.get("routeSkill")


def get_focus_default(focus_type: str, catalog: dict[str, Any] | None = None) -> str | None:
    catalog = catalog or load_catalog()
    criteria = catalog.get("criteria", {}) if catalog else {}
    focus_defaults = criteria.get("focus_defaults", {}) if criteria else {}
    return focus_defaults.get(focus_type)


# ---------------------------------------------------------------------------
# Task-based resolvers (schema v4) — purpose→model lookups from tasks section
# ---------------------------------------------------------------------------

def get_task_model(task: str, catalog: dict[str, Any] | None = None) -> str:
    """Return the model key assigned to a task/purpose in models.yaml.

    Reads ``tasks.<task>`` from models.yaml.  Returns empty string if not found.
    This is the PRIMARY resolver — all external code should call this
    or one of its shortcuts (get_primary_model, get_embedding_model, etc.).
    """
    catalog = catalog or load_catalog()
    tasks = catalog.get("tasks", {}) if catalog else {}
    return tasks.get(task, "")


def get_primary_model(catalog: dict[str, Any] | None = None) -> str:
    """Return the primary model key (bare name, e.g. 'kimi')."""
    return get_task_model("primary", catalog)


def get_primary_model_full(catalog: dict[str, Any] | None = None) -> str:
    """Return the primary model with litellm/ prefix (e.g. 'litellm/kimi')."""
    return get_task_model("primary_full", catalog)


def get_embedding_model(catalog: dict[str, Any] | None = None) -> str:
    """Return the embedding model key (e.g. 'nomic-embed-text')."""
    return get_task_model("embedding", catalog)


def get_fallback_chain(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Build structured fallback chain from routing.fallbacks + model tiers.

    Returns list of {"model": "litellm/X", "tier": "free", "priority": 1}.
    No hardcoded models — entirely from models.yaml.
    """
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {}) if catalog else {}
    models_def = catalog.get("models", {}) if catalog else {}
    chain: list[dict[str, Any]] = []
    for i, model_id in enumerate(routing.get("fallbacks", [])):
        bare = normalize_model_id(model_id)
        tier = models_def.get(bare, {}).get("tier", "unknown")
        chain.append({"model": model_id, "tier": tier, "priority": i + 1})
    return chain


def get_provider_label(model_id: str, catalog: dict[str, Any] | None = None) -> str:
    """Return the provider_label for a model (e.g. 'moonshot', 'openrouter').

    Reads ``models.<id>.provider_label`` from models.yaml.
    Returns 'unknown' if not found.
    """
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return "unknown"
    return entry.get("provider_label", entry.get("provider", "unknown"))


def get_thinking_config(model_id: str, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return thinking/reasoning extra params for a model.

    Reads ``models.<id>.thinking_params`` from models.yaml.
    Returns empty dict if model doesn't support thinking mode.
    """
    entry = get_model_entry(model_id, catalog)
    if not entry:
        return {}
    return entry.get("thinking_params", {})


def build_litellm_models(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    catalog = catalog or load_catalog()
    models = catalog.get("models", {}) if catalog else {}
    result: list[dict[str, Any]] = []
    for model_id, entry in models.items():
        if entry.get("provider") != "litellm":
            continue
        # maxTokens MUST be a positive integer — UI may send NaN for
        # empty fields, so we provide an explicit value to prevent issues.
        # Providing an explicit value prevents NaN round-trips.
        ctx = entry.get("contextWindow", 8192)
        max_tok = entry.get("maxTokens") or min(8192, ctx)
        result.append({
            "id": model_id,
            "name": entry.get("name", model_id),
            "reasoning": entry.get("reasoning", False),
            "input": entry.get("input", ["text"]),
            "cost": entry.get("cost", {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}),
            "contextWindow": ctx,
            "maxTokens": max_tok,
        })
    return result


def build_agent_aliases(catalog: dict[str, Any] | None = None) -> dict[str, dict[str, str]]:
    catalog = catalog or load_catalog()
    aliases = catalog.get("agent_aliases", {}) if catalog else {}
    return {key: {"alias": value} for key, value in aliases.items()}


def build_agent_routing(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build agent model routing (primary + fallbacks only).
    
    Note: Model object must contain ONLY primary and fallbacks.
    Timeout should be set at agents.defaults.timeoutSeconds level, not in model object.
    """
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {}) if catalog else {}
    return {
        "primary": routing.get("primary"),
        "fallbacks": routing.get("fallbacks", []),
    }


def get_routing_config(catalog: dict[str, Any] | None = None) -> dict[str, Any]:
    """Return normalized routing config from models.yaml."""
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {}) if catalog else {}
    tier_order = routing.get("tier_order") or ["local", "free", "paid"]
    if not isinstance(tier_order, list):
        tier_order = ["local", "free", "paid"]
    return {
        "primary": routing.get("primary"),
        "fallbacks": routing.get("fallbacks", []),
        "timeout": routing.get("timeout", 600),
        "retries": routing.get("retries", 2),
        "bypass": bool(routing.get("bypass", False)),
        "tier_order": tier_order,
    }


def get_model_for_task(
    task: str | None = None,
    preferred_tier: str | None = None,
    catalog: dict[str, Any] | None = None,
) -> str | None:
    """Resolve the best model ID for a task from YAML routing + criteria.

    If `routing.bypass` is true, this returns `routing.primary` directly.
    """
    catalog = catalog or load_catalog()
    if not catalog:
        return None

    routing = get_routing_config(catalog)
    if routing.get("bypass"):
        return routing.get("primary")

    criteria = catalog.get("criteria", {})
    use_cases = criteria.get("use_cases", {}) if isinstance(criteria, dict) else {}
    tiers = criteria.get("tiers", {}) if isinstance(criteria, dict) else {}

    if task and isinstance(use_cases.get(task), list) and use_cases.get(task):
        return use_cases[task][0]

    tier_order = routing.get("tier_order", ["local", "free", "paid"])
    if preferred_tier and preferred_tier in tiers and tiers[preferred_tier]:
        return tiers[preferred_tier][0]

    for tier in tier_order:
        tier_models = tiers.get(tier, []) if isinstance(tiers, dict) else []
        if tier_models:
            return tier_models[0]

    return routing.get("primary")


def list_all_model_ids(catalog: dict[str, Any] | None = None) -> list[str]:
    """Return sorted list of all model IDs from the catalog (including aliases)."""
    catalog = catalog or load_catalog()
    models = catalog.get("models", {}) if catalog else {}
    ids: list[str] = []
    for model_id, entry in models.items():
        ids.append(model_id)
        for alias in entry.get("aliases", []):
            ids.append(alias)
    return sorted(ids)


def list_models_with_reasoning(catalog: dict[str, Any] | None = None) -> list[str]:
    """Return model IDs that support reasoning/thinking mode."""
    catalog = catalog or load_catalog()
    models = catalog.get("models", {}) if catalog else {}
    return [mid for mid, entry in models.items() if entry.get("reasoning")]


def build_litellm_config_entries(catalog: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """Generate litellm model_list entries from models.yaml.
    
    Each model with a 'litellm' key produces one entry (plus one per alias).
    This is the bridge that means you only need to edit models.yaml to add a model.
    """
    catalog = catalog or load_catalog()
    models = catalog.get("models", {}) if catalog else {}
    entries: list[dict[str, Any]] = []
    
    for model_id, entry in models.items():
        litellm_params = entry.get("litellm")
        if not litellm_params:
            continue
        
        item: dict[str, Any] = {
            "model_name": model_id,
            "litellm_params": dict(litellm_params),  # copy
            "model_info": {
                # max_tokens = output token cap, NOT context window
                "max_tokens": entry.get("maxTokens") or min(8192, entry.get("contextWindow", 8192)),
            },
        }
        cost = entry.get("cost", {})
        if cost.get("input", 0) == 0 and cost.get("output", 0) == 0:
            item["model_info"]["input_cost_per_token"] = 0
            item["model_info"]["output_cost_per_token"] = 0
        entries.append(item)
        
        # Also emit alias entries (e.g. kimi-k2.5 → same litellm_params)
        for alias in entry.get("aliases", []):
            alias_item = {
                "model_name": alias,
                "litellm_params": dict(litellm_params),
                "model_info": dict(item["model_info"]),
            }
            entries.append(alias_item)
    
    return entries


def get_timeout_seconds(catalog: dict[str, Any] | None = None) -> int:
    """Get timeout from routing config (for agents.defaults.timeoutSeconds)."""
    catalog = catalog or load_catalog()
    routing = catalog.get("routing", {}) if catalog else {}
    return routing.get("timeout", 600)  # Default 600s


def validate_catalog(path: Path | None = None) -> list[str]:
    """Validate models.yaml against its own validation.required_fields.

    Returns a list of error strings (empty list = valid catalog).
    Uses the ``validation.required_fields`` section from models.yaml itself.
    """
    errors: list[str] = []
    catalog_path = path or CATALOG_PATH

    if not catalog_path.exists():
        errors.append(f"models.yaml not found at {catalog_path}")
        return errors

    try:
        catalog = _load_yaml_or_json(catalog_path)
    except Exception as exc:
        errors.append(f"Failed to parse models.yaml: {exc}")
        return errors

    if "validation" not in catalog:
        errors.append("Missing 'validation' section")
        return errors

    if "models" not in catalog:
        errors.append("Missing 'models' section")
        return errors

    required = catalog["validation"].get("required_fields", [])
    # Map canonical field names to the actual keys used in models.yaml
    field_map = {
        "id": None,  # id is the dict key, checked separately
        "name": "name",
        "provider": "provider",
        "tier": "tier",
        "context_window": "contextWindow",
    }

    models = catalog["models"]
    if not isinstance(models, dict):
        errors.append("'models' must be a dict")
        return errors

    for model_id, entry in models.items():
        if not isinstance(entry, dict):
            errors.append(f"Model '{model_id}': entry must be a dict")
            continue
        for req_field in required:
            actual_key = field_map.get(req_field, req_field)
            if actual_key is None:
                continue  # 'id' is the dict key itself
            if actual_key not in entry:
                errors.append(f"Model '{model_id}': missing required field '{req_field}'")

    return errors


def build_litellm_config_yaml(catalog: dict[str, Any] | None = None) -> str:
    """Generate a complete litellm-config.yaml from models.yaml.

    Returns a YAML-formatted string (actually JSON written as YAML-compatible)
    with an ``# AUTO-GENERATED`` header.  The output is suitable for writing
    directly to ``stacks/brain/litellm-config.yaml``.
    """
    try:
        import yaml as _yaml  # type: ignore
        _has_yaml = True
    except ImportError:
        _has_yaml = False

    entries = build_litellm_config_entries(catalog)

    config: dict[str, Any] = {
        "model_list": entries,
        "litellm_settings": {
            "drop_params": True,
            "disable_streaming": True,
            "set_verbose": False,
        },
    }

    header = "# AUTO-GENERATED from aria_models/models.yaml — do not edit manually\n# Regenerate: python scripts/generate_configs.py\n"

    if _has_yaml:
        body = _yaml.dump(config, default_flow_style=False, sort_keys=False)
    else:
        body = json.dumps(config, indent=2)

    return header + body
