#!/usr/bin/env python3
"""Create .gitkeep files in all canonical aria_memories directories."""
import os

CANONICAL_DIRS = [
    "aria_memories/archive",
    "aria_memories/backups",
    "aria_memories/bugs",
    "aria_memories/deep",
    "aria_memories/deliveries",
    "aria_memories/deliveries/analysis",
    "aria_memories/deliveries/reports",
    "aria_memories/deliveries/summaries",
    "aria_memories/drafts",
    "aria_memories/drafts/archive",
    "aria_memories/exports",
    "aria_memories/income_ops",
    "aria_memories/knowledge",
    "aria_memories/logs",
    "aria_memories/logs/work_cycles",
    "aria_memories/medium",
    "aria_memories/medium/topics",
    "aria_memories/memory",
    "aria_memories/memory/context",
    "aria_memories/memory/logs",
    "aria_memories/memory/rpg",
    "aria_memories/memory/sync",
    "aria_memories/memory/work_cycles",
    "aria_memories/moltbook",
    "aria_memories/moltbook/drafts",
    "aria_memories/moltbook/drafts/posted",
    "aria_memories/plans",
    "aria_memories/plans/rpg",
    "aria_memories/plans/rpg/campaigns",
    "aria_memories/research",
    "aria_memories/research/articles",
    "aria_memories/research/processed",
    "aria_memories/research/raw",
    "aria_memories/research/websites",
    "aria_memories/rpg",
    "aria_memories/rpg/campaigns",
    "aria_memories/rpg/characters",
    "aria_memories/rpg/encounters",
    "aria_memories/rpg/sessions",
    "aria_memories/rpg/world",
    "aria_memories/sandbox",
    "aria_memories/semantic_graph",
    "aria_memories/skills",
    "aria_memories/skills/goals",
    "aria_memories/skills/health",
    "aria_memories/skills/moltbook",
    "aria_memories/skills/sandbox",
    "aria_memories/skills/unified_search",
    "aria_memories/specs",
    "aria_memories/surface",
    "aria_memories/tickets",
    "aria_memories/tickets/extraction",
    "aria_memories/websites",
    "aria_memories/work",
    "aria_memories/work/backlog",
    "aria_memories/work/current",
]

if __name__ == "__main__":
    created = 0
    for d in CANONICAL_DIRS:
        os.makedirs(d, exist_ok=True)
        gk = os.path.join(d, ".gitkeep")
        if not os.path.exists(gk):
            open(gk, "w").close()
            created += 1
    print(f"Created {created} new .gitkeep files ({len(CANONICAL_DIRS)} dirs total)")
