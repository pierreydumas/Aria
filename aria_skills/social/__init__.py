# aria_skills/social.py
"""
Social media posting skill.

Manages social media content creation and posting.
Persists via REST API (TICKET-12: eliminate in-memory stubs).
"""
from datetime import datetime, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus, logged_method
from aria_skills.registry import SkillRegistry
from aria_skills.social.future_platforms import TelegramSimulationPlatform
from aria_skills.social.platform import SocialPlatform


@SkillRegistry.register
class SocialSkill(BaseSkill):
    """
    Social media management.
    
    Handles post creation, scheduling, and tracking.
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._posts: list[dict] = []  # fallback cache
        self._post_counter = 0
        self._api = None
        self._platforms: dict[str, SocialPlatform] = {}
    
    def register_platform(self, name: str, platform: SocialPlatform) -> None:
        """Register a social platform implementation."""
        self._platforms[name] = platform
    
    @property
    def name(self) -> str:
        return "social"
    
    async def initialize(self) -> bool:
        """Initialize social skill."""
        self._api = await get_api_client()
        self.register_platform("telegram", TelegramSimulationPlatform())
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Social skill initialized (API-backed)")
        return True
    
    async def close(self):
        """Cleanup (shared API client is managed by api_client module)."""
        self._api = None
    
    async def health_check(self) -> SkillStatus:
        """Check availability."""
        return self._status

    async def _persist_social_row(
        self,
        *,
        platform: str,
        content: str,
        visibility: str,
        metadata: dict[str, Any] | None = None,
        reply_to: str | None = None,
    ) -> dict[str, Any] | None:
        payload = {
            "platform": platform,
            "content": content,
            "visibility": visibility,
            "reply_to": reply_to,
            "metadata": metadata or {},
        }

        # S-116: Route all persistence through api_client (no direct httpx)
        if self._api:
            try:
                result = await self._api.post("/social", data=payload)
                if not result:
                    raise Exception(result.error)
                return result.data
            except Exception as e:
                self.logger.warning(f"_persist_social_row failed: {e}")

        return None
    
    @logged_method()
    async def create_post(
        self,
        content: str,
        platform: str = "moltbook",
        tags: list[str] | None = None,
        media_urls: list[str] | None = None,
        mood: str | None = None,
        visibility: str = "public",
        simulate: bool = True,
        chat_id: str | None = None,
        reply_to: str | None = None,
    ) -> SkillResult:
        """
        Create a social media post, routed to the specified platform.
        
        Args:
            content: Post content
            platform: Target platform
            tags: Hashtags
            media_urls: Attached media
            
        Returns:
            SkillResult with post data
        """
        # Route to registered platform if available
        normalized_platform = (platform or "moltbook").strip().lower()
        if normalized_platform in {"x", "x.com", "twitter", "email", "proton"}:
            return SkillResult.fail(f"platform '{normalized_platform}' is disabled")

        if normalized_platform in self._platforms:
            target = self._platforms[normalized_platform]
            try:
                routed = await target.post(
                    content,
                    tags,
                    simulate=simulate,
                    visibility=visibility,
                    chat_id=chat_id,
                    mood=mood,
                    media_urls=media_urls,
                    reply_to=reply_to,
                )
                if routed.success and normalized_platform in {"telegram"}:
                    simulated_state = simulate
                    if isinstance(routed.data, dict) and "simulated" in routed.data:
                        simulated_state = bool(routed.data.get("simulated"))
                    persisted = await self._persist_social_row(
                        platform=normalized_platform,
                        content=content,
                        visibility=visibility,
                        metadata={
                            "simulated": simulated_state,
                            "source": "aria-social",
                            "platform_result": routed.data,
                            "tags": tags or [],
                            "mood": mood,
                            "chat_id": chat_id,
                        },
                    )
                    if isinstance(routed.data, dict):
                        routed.data["persisted"] = bool(persisted)
                        routed.data["persisted_record"] = persisted
                return routed
            except TypeError:
                routed = await target.post(content, tags)
                if routed.success and normalized_platform in {"telegram"}:
                    simulated_state = simulate
                    if isinstance(routed.data, dict) and "simulated" in routed.data:
                        simulated_state = bool(routed.data.get("simulated"))
                    persisted = await self._persist_social_row(
                        platform=normalized_platform,
                        content=content,
                        visibility=visibility,
                        metadata={
                            "simulated": simulated_state,
                            "source": "aria-social",
                            "platform_result": routed.data,
                            "tags": tags or [],
                            "mood": mood,
                            "chat_id": chat_id,
                        },
                    )
                    if isinstance(routed.data, dict):
                        routed.data["persisted"] = bool(persisted)
                        routed.data["persisted_record"] = persisted
                return routed
        
        # Fallback: store via API if no platform registered
        self._post_counter += 1
        post_id = f"post_{self._post_counter}"
        
        post = {
            "id": post_id,
            "content": content,
            "platform": normalized_platform,
            "tags": tags or [],
            "media_urls": media_urls or [],
            "mood": mood,
            "visibility": visibility,
            "simulated": simulate,
            "chat_id": chat_id,
            "reply_to": reply_to,
            "status": "draft",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "published_at": None,
        }
        
        try:
            result = await self._api.post("/social", data=post)
            if not result:
                raise Exception(result.error)
            api_data = result.data
            return SkillResult.ok(api_data if api_data else post)
        except Exception as e:
            self.logger.warning(f"API create_post failed, using fallback: {e}")
            self._posts.append(post)
            return SkillResult.ok(post)

    @logged_method()
    async def social_post(
        self,
        content: str,
        platform: str = "moltbook",
        tags: list[str] | None = None,
        mood: str | None = None,
        visibility: str = "public",
        simulate: bool = True,
        chat_id: str | None = None,
        reply_to: str | None = None,
    ) -> SkillResult:
        """Tool-compatible wrapper for creating posts across platforms."""
        return await self.create_post(
            content=content,
            platform=platform,
            tags=tags,
            mood=mood,
            visibility=visibility,
            simulate=simulate,
            chat_id=chat_id,
            reply_to=reply_to,
        )

    @logged_method()
    async def social_list(self, platform: str | None = None, limit: int = 20) -> SkillResult:
        """Tool-compatible wrapper for listing social posts."""
        return await self.get_posts(platform=platform, limit=limit)

    @logged_method()
    async def social_schedule(
        self,
        content: str,
        platform: str,
        scheduled_for: str,
        tags: list[str] | None = None,
        mood: str | None = None,
        visibility: str = "public",
        simulate: bool = True,
    ) -> SkillResult:
        """Schedule intent record (simulation-first) for future publisher automation."""
        try:
            _ = datetime.fromisoformat(scheduled_for.replace("Z", "+00:00"))
        except Exception:
            return SkillResult.fail("scheduled_for must be an ISO timestamp")

        payload = {
            "platform": (platform or "").lower(),
            "content": content,
            "visibility": visibility,
            "metadata": {
                "scheduled_for": scheduled_for,
                "tags": tags or [],
                "mood": mood,
                "simulated": simulate,
                "status": "scheduled",
            },
        }

        if simulate:
            persisted = await self._persist_social_row(
                platform=payload["platform"],
                content=content,
                visibility=visibility,
                metadata={
                    "scheduled_for": scheduled_for,
                    "tags": tags or [],
                    "mood": mood,
                    "simulated": True,
                    "status": "scheduled",
                    "source": "aria-social",
                },
            )
            return SkillResult.ok(
                {
                    "scheduled": True,
                    "simulated": True,
                    "platform": payload["platform"],
                    "scheduled_for": scheduled_for,
                    "preview": content,
                    "persisted": bool(persisted),
                    "persisted_record": persisted,
                }
            )

        try:
            result = await self._api.post("/social", data=payload)
            if not result:
                raise Exception(result.error)
            return SkillResult.ok(
                {
                    "scheduled": True,
                    "simulated": False,
                    "platform": payload["platform"],
                    "scheduled_for": scheduled_for,
                    "record": result.data,
                }
            )
        except Exception as e:
            return SkillResult.fail(f"schedule persist failed: {e}")
    
    @logged_method()
    async def publish_post(self, post_id: str) -> SkillResult:
        """Publish a draft post."""
        update_data = {
            "status": "published",
            "published_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            result = await self._api.put(f"/social/{post_id}", data=update_data)
            if not result:
                raise Exception(result.error)
            return SkillResult.ok(result.data)
        except Exception as e:
            self.logger.warning(f"API publish_post failed, using fallback: {e}")
            for post in self._posts:
                if post["id"] == post_id:
                    post["status"] = "published"
                    post["published_at"] = update_data["published_at"]
                    return SkillResult.ok(post)
            return SkillResult.fail(f"Post not found: {post_id}")
    
    async def get_posts(
        self,
        status: str | None = None,
        platform: str | None = None,
        limit: int = 20,
    ) -> SkillResult:
        """Get posts with optional filters."""
        try:
            params: dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            if platform:
                params["platform"] = platform
            resp = await self._api.get("/social", params=params)
            if not resp:
                raise Exception(resp.error)
            api_data = resp.data
            if isinstance(api_data, list):
                return SkillResult.ok({"posts": api_data[-limit:], "total": len(api_data)})
            return SkillResult.ok(api_data)
        except Exception as e:
            self.logger.warning(f"API get_posts failed, using fallback: {e}")
            posts = self._posts
            if status:
                posts = [p for p in posts if p["status"] == status]
            if platform:
                posts = [p for p in posts if p["platform"] == platform]
            return SkillResult.ok({"posts": posts[-limit:], "total": len(posts)})
    
    async def delete_post(self, post_id: str) -> SkillResult:
        """Delete a post."""
        try:
            result = await self._api.delete(f"/social/{post_id}")
            if not result:
                raise Exception(result.error)
            return SkillResult.ok({"deleted": post_id})
        except Exception as e:
            self.logger.warning(f"API delete_post failed, using fallback: {e}")
            for i, post in enumerate(self._posts):
                if post["id"] == post_id:
                    deleted = self._posts.pop(i)
                    return SkillResult.ok({"deleted": post_id, "content": deleted["content"][:50]})
            return SkillResult.fail(f"Post not found: {post_id}")

    # ── Website Sources (journalist/research) ────────────────────────────

    @logged_method()
    async def source_add(
        self,
        url: str,
        name: str,
        category: str = "general",
        rating: str = "preferred",
        reason: str | None = None,
        alternative: str | None = None,
        last_used: str | None = None,
    ) -> SkillResult:
        """Add or update a website source for research recall."""
        try:
            result = await self._api.create_source(
                url=url,
                name=name,
                category=category,
                rating=rating,
                reason=reason,
                alternative=alternative,
                last_used=last_used,
            )
            if not result:
                raise Exception(result.error)
            return result
        except Exception as e:
            return SkillResult.fail(f"Failed to add source: {e}")

    @logged_method()
    async def source_list(
        self,
        category: str | None = None,
        rating: str | None = None,
        q: str | None = None,
        limit: int = 50,
    ) -> SkillResult:
        """List website sources with optional filters."""
        try:
            result = await self._api.get_sources(
                limit=limit,
                category=category,
                rating=rating,
                q=q,
            )
            if not result:
                raise Exception(result.error)
            return result
        except Exception as e:
            return SkillResult.fail(f"Failed to list sources: {e}")

    @logged_method()
    async def source_remove(self, source_id: str) -> SkillResult:
        """Remove a website source."""
        try:
            result = await self._api.delete_source(source_id)
            if not result:
                raise Exception(result.error)
            return result
        except Exception as e:
            return SkillResult.fail(f"Failed to remove source: {e}")

    @logged_method()
    async def source_stats(self) -> SkillResult:
        """Get website source statistics by rating and category."""
        try:
            result = await self._api.get_sources_stats()
            if not result:
                raise Exception(result.error)
            return result
        except Exception as e:
            return SkillResult.fail(f"Failed to get source stats: {e}")
