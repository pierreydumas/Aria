"""
Skill Guide — on-demand skill documentation reader.

Layer 2 (Core). Lets Aria read any skill's SKILL.md before using its tools,
enabling self-onboarding for new capabilities.
"""
import json
from pathlib import Path

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

# Resolve the aria_skills root once.
_SKILLS_ROOT = Path(__file__).resolve().parent.parent


@SkillRegistry.register
class SkillGuideSkill(BaseSkill):
    """Read skill documentation (SKILL.md) so Aria can learn on demand."""

    def __init__(self, config: SkillConfig):
        super().__init__(config)

    @property
    def name(self) -> str:
        return "skill_guide"

    async def initialize(self) -> bool:
        self._status = SkillStatus.AVAILABLE
        return True

    async def health_check(self) -> SkillStatus:
        return SkillStatus.AVAILABLE

    # ── Tools ───────────────────────────────────────────────────────────

    async def skill_guide__read(self, skill_name: str) -> SkillResult:
        """Read a skill's SKILL.md documentation."""
        # Sanitise: only allow simple snake_case names (no path traversal)
        safe = "".join(c for c in skill_name if c.isalnum() or c == "_")
        if safe != skill_name or not safe:
            return SkillResult(
                success=False,
                data={"error": f"Invalid skill name: {skill_name!r}"},
            )

        skill_dir = _SKILLS_ROOT / safe
        if not skill_dir.is_dir():
            return SkillResult(
                success=False,
                data={"error": f"Skill '{safe}' not found in aria_skills/"},
            )

        md_path = skill_dir / "SKILL.md"
        if not md_path.is_file():
            # Fallback to README.md
            md_path = skill_dir / "README.md"
        if not md_path.is_file():
            return SkillResult(
                success=False,
                data={"error": f"No SKILL.md or README.md found for '{safe}'"},
            )

        content = md_path.read_text(encoding="utf-8")
        # Cap at 8000 chars to avoid token explosion
        if len(content) > 8000:
            content = content[:8000] + "\n\n…(truncated)"

        return SkillResult(
            success=True,
            data={"skill": safe, "content": content},
        )

    async def skill_guide__list(self) -> SkillResult:
        """List all available skills with metadata."""
        skills = []
        for skill_dir in sorted(_SKILLS_ROOT.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith(("_", ".")):
                continue
            manifest_path = skill_dir / "skill.json"
            if not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            skills.append({
                "name": manifest.get("name", skill_dir.name),
                "layer": manifest.get("layer", "?"),
                "status": manifest.get("status", "unknown"),
                "description": manifest.get("description", "")[:120],
                "has_docs": (skill_dir / "SKILL.md").is_file(),
            })

        return SkillResult(
            success=True,
            data={"count": len(skills), "skills": skills},
        )
