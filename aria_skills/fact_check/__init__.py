# aria_skills/fact_check/__init__.py
"""
Fact-checking and claim verification skill.

Structured claim extraction, assessment, and verdict generation
for Aria's Journalist persona. Uses LLM-assisted analysis.
"""
import uuid
from datetime import datetime, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class FactCheckSkill(BaseSkill):
    """Fact-checking and claim verification."""

    def __init__(self, config: SkillConfig | None = None):
        super().__init__(config or SkillConfig(name="fact_check"))
        self._claims: dict[str, dict] = {}
        self._verdicts: dict[str, dict] = {}
        self._api = None

    @property
    def name(self) -> str:
        return "fact_check"

    async def initialize(self) -> bool:
        try:
            self._api = await get_api_client()
        except Exception as e:
            self.logger.info(f"API unavailable, fact-check activity logging disabled: {e}")
            self._api = None
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Fact-check skill initialized")
        return True

    async def health_check(self) -> SkillStatus:
        return self._status

    @logged_method()
    async def extract_claims(
        self, text: str = "", source: str = "", **kwargs
    ) -> SkillResult:
        """Extract verifiable claims from text."""
        text = text or kwargs.get("text", "")
        if not text:
            return SkillResult.fail("No text provided")

        # Simple claim extraction: split on sentences, identify assertive ones
        import re
        sentences = re.split(r'(?<=[.!?])\s+', text.strip())
        claims = []
        claim_indicators = [
            "is", "are", "was", "were", "has", "have", "will",
            "can", "could", "should", "must", "always", "never",
            "every", "all", "none", "most", "many", "few",
            "%", "percent", "million", "billion", "according",
        ]
        for sent in sentences:
            sent = sent.strip()
            if not sent or len(sent) < 10:
                continue
            lower = sent.lower()
            if any(ind in lower for ind in claim_indicators):
                claim_id = str(uuid.uuid4())[:8]
                claim = {
                    "id": claim_id,
                    "text": sent,
                    "source": source or kwargs.get("source", "unknown"),
                    "status": "unverified",
                    "confidence": 0.0,
                    "extracted_at": datetime.now(timezone.utc).isoformat(),
                }
                self._claims[claim_id] = claim
                claims.append(claim)

        await self._persist_activity("fact_check_claims_extracted", {
            "source": source or kwargs.get("source", "unknown"),
            "claim_count": len(claims),
            "claim": claims[0] if claims else None,
        })

        return SkillResult.ok({
            "claims": claims,
            "total_extracted": len(claims),
            "source_text_length": len(text),
            "message": f"Extracted {len(claims)} verifiable claims from {len(sentences)} sentences",
        })

    @logged_method()
    async def assess_claim(
        self, claim_id: str = "", evidence: str = "",
        confidence: float = 0.5, verdict: str = "unverified", **kwargs
    ) -> SkillResult:
        """Assess a claim with evidence and confidence."""
        claim_id = claim_id or kwargs.get("claim_id", "")
        if claim_id not in self._claims:
            return SkillResult.fail(f"Claim '{claim_id}' not found")

        claim = self._claims[claim_id]
        claim["evidence"] = evidence or kwargs.get("evidence", "")
        claim["confidence"] = confidence
        claim["verdict"] = verdict or kwargs.get("verdict", "unverified")
        claim["status"] = "assessed"
        claim["assessed_at"] = datetime.now(timezone.utc).isoformat()

        self._verdicts[claim_id] = claim
        await self._persist_activity("fact_check_claim_assessed", {
            "claim": claim,
            "verdict": claim.get("verdict"),
            "confidence": claim.get("confidence"),
            "status": claim.get("status"),
        })
        return SkillResult.ok({
            "claim": claim,
            "message": f"Claim assessed: {verdict} (confidence: {confidence})",
        })

    @logged_method()
    async def quick_check(
        self, statement: str = "", **kwargs
    ) -> SkillResult:
        """Quick assessment of a single statement."""
        statement = statement or kwargs.get("statement", "")
        if not statement:
            return SkillResult.fail("No statement provided")

        claim_id = str(uuid.uuid4())[:8]
        claim = {
            "id": claim_id,
            "text": statement,
            "source": "direct_input",
            "status": "quick_checked",
            "analysis": {
                "has_numbers": any(c.isdigit() for c in statement),
                "has_absolutes": any(
                    w in statement.lower()
                    for w in ["always", "never", "every", "none", "all"]
                ),
                "word_count": len(statement.split()),
                "needs_verification": True,
            },
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        self._claims[claim_id] = claim

        # Flag if it contains absolutes (often exaggerated)
        risk = "high" if claim["analysis"]["has_absolutes"] else "medium" if claim["analysis"]["has_numbers"] else "low"
        await self._persist_activity("fact_check_quick_checked", {
            "claim": claim,
            "risk_level": risk,
            "status": claim.get("status"),
        })
        return SkillResult.ok({
            "claim": claim,
            "risk_level": risk,
            "recommendation": (
                "Claims with absolute terms (always/never/every) should be verified carefully"
                if risk == "high"
                else "Numeric claims should be cross-referenced with authoritative sources"
                if risk == "medium"
                else "Standard factual claim — verify with primary sources"
            ),
        })

    @logged_method()
    async def compare_sources(
        self, claim_id: str = "", sources: list[dict] | None = None, **kwargs
    ) -> SkillResult:
        """Compare multiple sources for a claim."""
        claim_id = claim_id or kwargs.get("claim_id", "")
        sources = sources or kwargs.get("sources", [])
        if not sources:
            return SkillResult.fail("No sources provided")

        claim = self._claims.get(claim_id)
        agreements = sum(1 for s in sources if s.get("supports", False))
        contradictions = sum(1 for s in sources if not s.get("supports", True))
        await self._persist_activity("fact_check_sources_compared", {
            "claim": claim,
            "claim_id": claim_id,
            "sources_count": len(sources),
            "agreements": agreements,
            "contradictions": contradictions,
        })
        return SkillResult.ok({
            "claim_id": claim_id,
            "claim_text": claim["text"] if claim else "unknown",
            "sources_count": len(sources),
            "agreements": agreements,
            "contradictions": contradictions,
            "consensus_ratio": round(agreements / max(len(sources), 1), 2),
            "assessment": (
                "Strong consensus" if agreements / max(len(sources), 1) > 0.8
                else "Mixed evidence" if agreements / max(len(sources), 1) > 0.5
                else "Disputed claim"
            ),
        })

    @logged_method()
    async def get_verdict_summary(self, **kwargs) -> SkillResult:
        """Get summary of all assessed claims and verdicts."""
        assessed = [c for c in self._claims.values() if c["status"] in ("assessed", "quick_checked")]
        verdicts = {}
        for c in assessed:
            v = c.get("verdict", "unverified")
            verdicts[v] = verdicts.get(v, 0) + 1

        return SkillResult.ok({
            "total_claims": len(self._claims),
            "assessed": len(assessed),
            "unverified": len(self._claims) - len(assessed),
            "verdict_breakdown": verdicts,
            "average_confidence": round(
                sum(c.get("confidence", 0) for c in assessed) / max(len(assessed), 1), 2
            ),
            "recent_claims": [
                {"id": c["id"], "text": c["text"][:80], "status": c["status"]}
                for c in list(self._claims.values())[-5:]
            ],
        })

    async def _persist_activity(self, action: str, details: dict, success: bool = True) -> None:
        """Best-effort API persistence. Never blocks fact-check execution."""
        if not self._api:
            return
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(
                    self._api.create_activity(
                        action=action,
                        skill=self.name,
                        details=details,
                        success=success,
                    )
                )
        except Exception:
            self.logger.debug("Fact-check activity persistence skipped")
