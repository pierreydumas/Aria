"""
Agent Sync — parse AGENTS.md and upsert into aria_engine.agent_state.

Called by POST /agents/db/sync and optionally on startup.
Respects ``app_managed`` flag — rows edited via API/UI are skipped
unless ``force=True`` is passed.

When ``ARIA_SKILL_AUTO_WIRE=true`` (default), the ``skills`` column is
NOT overwritten on existing rows — the auto-wiring engine in
ToolRegistry.build_agent_skill_map() manages it instead.
"""
import logging
import os
import re
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import yaml
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import async_sessionmaker

logger = logging.getLogger("aria.api.agents_sync")

# Known paths to AGENTS.md (try in order)
_AGENTS_MD_PATHS = [
    Path("/aria_mind/AGENTS.md"),       # Docker mount
    Path("aria_mind/AGENTS.md"),         # Local dev
]


def _find_agents_md() -> Path | None:
    for p in _AGENTS_MD_PATHS:
        if p.exists():
            return p
    return None


def _parse_agents_md(text: str) -> list[dict[str, Any]]:
    """
    Parse AGENTS.md and extract agent YAML blocks.

    Each agent section has a ```yaml block with fields like:
    id, focus, model, fallback, parent, skills, capabilities, timeout, rate_limit
    """
    agents: list[dict[str, Any]] = []

    # Find all yaml code blocks
    yaml_blocks = re.findall(r"```yaml\s*\n(.*?)```", text, re.DOTALL)

    for block in yaml_blocks:
        try:
            data = yaml.safe_load(block)
        except yaml.YAMLError:
            continue

        if not isinstance(data, dict):
            continue

        # Skip non-agent blocks (e.g. "Web Access Rules")
        if "id" not in data:
            continue

        agent_id = str(data["id"])
        focus = data.get("focus", "")
        model = data.get("model", "unknown")
        fallback = data.get("fallback")
        parent = data.get("parent")
        skills = data.get("skills", [])
        capabilities = data.get("capabilities", [])
        timeout_str = data.get("timeout", "600s")
        rate_limit = data.get("rate_limit", {})

        # Parse timeout: "600s" → 600
        timeout_seconds = 600
        if isinstance(timeout_str, str) and timeout_str.endswith("s"):
            try:
                timeout_seconds = int(timeout_str[:-1])
            except ValueError:
                pass
        elif isinstance(timeout_str, (int, float)):
            timeout_seconds = int(timeout_str)

        # Determine agent_type based on relationship
        if parent:
            agent_type = "sub_agent"
        elif agent_id == "aria":
            agent_type = "agent"
        else:
            agent_type = "agent"

        # Map focus to display name
        display_names = {
            "aria": "Aria (Orchestrator)",
            "devops": "DevOps (DevSecOps)",
            "analyst": "Analyst (Data + Trader)",
            "creator": "Creator (Creative + Social)",
            "memory": "Memory (Knowledge Manager)",
            "aria_talk": "Aria Talk (Conversational)",
        }

        # Parse mind_files (per-agent aria_mind file selection)
        mind_files = data.get("mind_files", [])
        if not isinstance(mind_files, list):
            mind_files = []

        agents.append({
            "agent_id": agent_id,
            "display_name": display_names.get(agent_id, agent_id.title()),
            "agent_type": agent_type,
            "parent_agent_id": parent,
            "model": model,
            "fallback_model": fallback,
            "focus_type": focus if focus else None,
            "skills": skills if isinstance(skills, list) else [],
            "capabilities": capabilities if isinstance(capabilities, list) else [],
            "timeout_seconds": timeout_seconds,
            "rate_limit": rate_limit if isinstance(rate_limit, dict) else {},
            "mind_files": mind_files,
        })

    return agents


async def sync_agents_from_markdown(
    session_factory: async_sessionmaker,
    *,
    force: bool = False,
) -> dict[str, Any]:
    """
    Parse AGENTS.md and upsert into aria_engine.agent_state.

    Args:
        session_factory: Async session factory.
        force: If True, overwrite even ``app_managed`` rows.

    Returns stats: {inserted, updated, skipped, total, agents[]}.
    """
    from db.models import EngineAgentState

    md_path = _find_agents_md()
    if not md_path:
        return {"inserted": 0, "updated": 0, "total": 0, "error": "AGENTS.md not found"}

    text = md_path.read_text(encoding="utf-8")
    agents_data = _parse_agents_md(text)

    if not agents_data:
        return {"inserted": 0, "updated": 0, "total": 0, "error": "No agent definitions found in AGENTS.md"}

    inserted = 0
    updated = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    auto_wire = os.getenv("ARIA_SKILL_AUTO_WIRE", "true").lower() in {"1", "true", "yes"}

    async with session_factory() as db:
        for agent in agents_data:
            result = await db.execute(
                select(EngineAgentState).where(
                    EngineAgentState.agent_id == agent["agent_id"]
                )
            )
            existing = result.scalar_one_or_none()

            if existing:
                if existing.app_managed and not force:
                    # Row was edited through the API/UI — don't overwrite
                    skipped += 1
                    continue

                # Update only config fields, preserve runtime state
                existing.display_name = agent["display_name"]
                existing.agent_type = agent["agent_type"]
                existing.parent_agent_id = agent["parent_agent_id"]
                existing.model = agent["model"]
                existing.fallback_model = agent["fallback_model"]
                existing.focus_type = agent["focus_type"]
                if not auto_wire:
                    existing.skills = agent["skills"]
                existing.capabilities = agent["capabilities"]
                existing.timeout_seconds = agent["timeout_seconds"]
                existing.rate_limit = agent["rate_limit"]
                # Persist mind_files in metadata_json
                meta = existing.metadata_json or {}
                if agent.get("mind_files"):
                    meta["mind_files"] = agent["mind_files"]
                existing.metadata_json = meta
                existing.updated_at = now
                updated += 1
            else:
                row = EngineAgentState(
                    agent_id=agent["agent_id"],
                    display_name=agent["display_name"],
                    agent_type=agent["agent_type"],
                    parent_agent_id=agent["parent_agent_id"],
                    model=agent["model"],
                    fallback_model=agent["fallback_model"],
                    focus_type=agent["focus_type"],
                    skills=agent["skills"],
                    capabilities=agent["capabilities"],
                    enabled=True,
                    timeout_seconds=agent["timeout_seconds"],
                    rate_limit=agent["rate_limit"],
                    metadata_json={"mind_files": agent.get("mind_files", [])} if agent.get("mind_files") else {},
                )
                db.add(row)
                inserted += 1

        await db.commit()

        # Count total
        total_result = await db.execute(select(func.count()).select_from(EngineAgentState))
        total = total_result.scalar() or 0

    logger.info("Agent sync complete: %d inserted, %d updated, %d skipped, %d total", inserted, updated, skipped, total)
    return {
        "inserted": inserted,
        "updated": updated,
        "skipped": skipped,
        "total": total,
        "agents": [a["agent_id"] for a in agents_data],
    }
