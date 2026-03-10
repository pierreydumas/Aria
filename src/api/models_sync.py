"""
Sync models.yaml → llm_models DB table on startup.

Idempotent: inserts new models, updates existing ones, never deletes.
Respects ``app_managed`` flag — rows edited via API/UI are skipped
unless ``force=True`` is passed.
Called from main.py lifespan.
"""
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("aria.api.models_sync")


async def sync_models_from_yaml(db_factory, *, force: bool = False) -> dict[str, int]:
    """Read models.yaml and upsert every entry into ``llm_models``.

    Args:
        db_factory: Async session factory.
        force: If True, overwrite even ``app_managed`` rows.

    Returns {"inserted": N, "updated": N, "skipped": N, "total": N}.
    """
    from db.models import LlmModelEntry

    # Load catalog from disk
    try:
        from aria_models.loader import reload_models
    except ImportError:
        # Fallback: load directly from file
        import json
        from pathlib import Path
        yaml_path = Path("/models/models.yaml")
        if not yaml_path.exists():
            yaml_path = Path(__file__).resolve().parent.parent.parent / "aria_models" / "models.yaml"
        if not yaml_path.exists():
            logger.warning("models.yaml not found — skipping seed")
            return {"inserted": 0, "updated": 0, "total": 0}
        content = yaml_path.read_text(encoding="utf-8")
        try:
            catalog = json.loads(content)
        except json.JSONDecodeError:
            import yaml
            catalog = yaml.safe_load(content) or {}
        reload_models = lambda: catalog  # noqa: E731

    catalog = reload_models()
    models_raw: dict[str, Any] = catalog.get("models", {})

    if not models_raw:
        logger.info("No models in catalog — nothing to seed")
        return {"inserted": 0, "updated": 0, "total": 0}

    inserted = 0
    updated = 0
    skipped = 0

    async with db_factory() as db:
        for model_id, entry in models_raw.items():
            litellm_block = entry.get("litellm", {})
            cost = entry.get("cost", {})
            input_types = entry.get("input", ["text"])

            values = {
                "name": entry.get("name", model_id),
                "provider": entry.get("provider", "litellm"),
                "tier": entry.get("tier", "free"),
                "reasoning": entry.get("reasoning", False),
                "vision": "image" in input_types,
                "tool_calling": entry.get("tool_calling", False),
                "input_types": input_types,
                "context_window": entry.get("contextWindow", 8192),
                "max_tokens": entry.get("maxTokens", 4096),
                "cost_input": cost.get("input", 0),
                "cost_output": cost.get("output", 0),
                "cost_cache_read": cost.get("cacheRead", 0),
                "litellm_model": litellm_block.get("model", ""),
                "litellm_api_key": litellm_block.get("api_key", ""),
                "litellm_api_base": litellm_block.get("api_base", ""),
                "route_skill": entry.get("routeSkill", ""),
                "aliases": entry.get("aliases", []),
                "enabled": entry.get("enabled", True),
            }

            existing = await db.execute(
                select(LlmModelEntry).where(LlmModelEntry.id == model_id)
            )
            row = existing.scalar_one_or_none()

            if row is None:
                row = LlmModelEntry(id=model_id, **values)
                db.add(row)
                inserted += 1
            elif row.app_managed and not force:
                # Row was edited through the API/UI — don't overwrite
                skipped += 1
            else:
                for k, v in values.items():
                    setattr(row, k, v)
                row.updated_at = datetime.now(timezone.utc)
                updated += 1

        await db.commit()

    total = inserted + updated
    logger.info(
        "Models sync: %d inserted, %d updated, %d skipped (%d total)",
        inserted, updated, skipped, total,
    )
    return {"inserted": inserted, "updated": updated, "skipped": skipped, "total": total}
