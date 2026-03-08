# aria_mind/startup.py
"""
Aria Startup - First boot and awakening sequence.

Run this when Aria first wakes up to:
1. Initialize all systems
2. Post awakening message to Moltbook
3. Log to database
"""
import asyncio
import ast
import json
import logging
import os
from pathlib import Path
from datetime import datetime, timezone

try:
    import httpx as _httpx
except ImportError:  # pragma: no cover
    _httpx = None  # type: ignore

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("aria.startup")


def _resolve_path(*candidates: str) -> Path | None:
    """Resolve first existing file from candidate paths."""
    for candidate in candidates:
        path = Path(candidate)
        if path.exists() and path.is_file():
            return path
    return None


def _verify_markdown_file(path: Path) -> tuple[bool, str]:
    """Check markdown file is readable and non-empty."""
    try:
        content = path.read_text(encoding="utf-8")
        if not content.strip():
            return False, "empty file"
        return True, f"{len(content)} chars"
    except Exception as exc:
        return False, str(exc)


def _verify_python_file(path: Path) -> tuple[bool, str]:
    """Check Python file is readable and syntactically valid."""
    try:
        source = path.read_text(encoding="utf-8")
        ast.parse(source, filename=str(path))
        return True, f"{len(source.splitlines())} lines"
    except Exception as exc:
        return False, str(exc)


def review_boot_assets() -> bool:
    """
    Review and validate core Aria docs/scripts before startup.

    Enforces ordered checks so boot fails early if core context is missing
    or syntactically invalid.
    """
    docs_in_order = [
        "AWAKENING.md",
        "SOUL.md",
        "IDENTITY.md",
        "SECURITY.md",
        "MEMORY.md",
        "AGENTS.md",
        "SKILLS.md",
        "TOOLS.md",
        "ORCHESTRATION.md",
    ]
    scripts_in_order = [
        "startup.py",
        "cognition.py",
        "memory.py",
        "security.py",
        "heartbeat.py",
    ]

    print("🧾 Phase 0: Reviewing Core Files...")
    all_ok = True

    for filename in docs_in_order:
        resolved = _resolve_path(f"aria_mind/{filename}", filename)
        if not resolved:
            print(f"   ✗ {filename}: missing")
            all_ok = False
            continue
        ok, detail = _verify_markdown_file(resolved)
        emoji = "✓" if ok else "✗"
        print(f"   {emoji} {filename}: {detail}")
        all_ok = all_ok and ok

    for filename in scripts_in_order:
        resolved = _resolve_path(f"aria_mind/{filename}", filename)
        if not resolved:
            print(f"   ✗ {filename}: missing")
            all_ok = False
            continue
        ok, detail = _verify_python_file(resolved)
        emoji = "✓" if ok else "✗"
        print(f"   {emoji} {filename}: {detail}")
        all_ok = all_ok and ok

    return all_ok


def validate_env():
    """Warn on missing critical environment variables."""
    required = {
        "DB_PASSWORD": "Database will fail to authenticate",
        "LITELLM_MASTER_KEY": "LLM proxy auth will fail",
    }
    recommended = [
        "WEB_SECRET_KEY", "ARIA_API_TOKEN", "BRAVE_API_KEY",
        "CORS_ALLOWED_ORIGINS", "MAC_HOST",
    ]
    for var, impact in required.items():
        val = os.getenv(var, "")
        if not val or val in ("admin", "sk-change-me", "aria-dev-secret-key", "default-aria-api-token"):
            logger.error(f"MISSING/INSECURE REQUIRED: {var} — {impact}")
    for var in recommended:
        if not os.getenv(var):
            logger.warning(f"MISSING RECOMMENDED: {var}")


async def run_startup():
    """Execute Aria's startup sequence."""
    from aria_mind.logging_config import configure_logging, correlation_id_var, new_correlation_id
    configure_logging()
    correlation_id_var.set(new_correlation_id())

    validate_env()

    print("=" * 60)
    print("⚡️ ARIA BLUE - AWAKENING SEQUENCE")
    print("=" * 60)
    print()

    strict_boot_review = os.getenv("ARIA_STRICT_BOOT_REVIEW", "true").lower() == "true"
    reviewed_ok = review_boot_assets()
    if not reviewed_ok:
        message = "Core startup review failed (missing/invalid .md or .py files)"
        if strict_boot_review:
            raise RuntimeError(message)
        logger.warning(message)
        print(f"   ⚠ {message}")
    
    from aria_skills import SkillRegistry, SkillStatus
    from aria_agents import AgentCoordinator
    from aria_mind import AriaMind
    
    # =========================================================================
    # Phase 1: Initialize Skills
    # =========================================================================
    print("📦 Phase 1: Initializing Skills...")
    
    registry = SkillRegistry()
    
    try:
        tools_md = _resolve_path("aria_mind/TOOLS.md", "TOOLS.md")
        if not tools_md:
            raise FileNotFoundError("TOOLS.md not found in aria_mind/ or workspace root")
        await registry.load_from_config(str(tools_md))
        print(f"   ✓ Loaded skill configs: {registry.list()}")
    except Exception as e:
        logger.warning(f"Could not load TOOLS.md: {e}")
    
    # Initialize each skill
    skills_status = {}
    for skill_name in ["database", "litellm", "moltbook"]:
        skill = registry.get(skill_name)
        if skill:
            try:
                success = await skill.initialize()
                status = await skill.health_check()
                skills_status[skill_name] = status.value
                emoji = "✓" if status == SkillStatus.AVAILABLE else "✗"
                print(f"   {emoji} {skill_name}: {status.value}")
            except Exception as e:
                skills_status[skill_name] = f"error: {e}"
                print(f"   ✗ {skill_name}: {e}")

    # Save skill catalog for runtime discovery
    try:
        from aria_skills.catalog import save_catalog
        save_catalog()
    except Exception as e:
        logger.debug(f"Skill catalog save failed: {e}")
    
    # =========================================================================
    # Phase 2: Initialize Mind
    # =========================================================================
    print()
    print("🧠 Phase 2: Initializing Mind...")
    
    mind = AriaMind()
    db_skill = registry.get("database")
    if db_skill:
        mind.memory.set_database(db_skill)
    
    try:
        success = await mind.initialize()
        if success:
            print(f"   ✓ Soul loaded: {mind.soul.name}")
            print(f"   ✓ Memory connected")
            print(f"   ✓ Heartbeat started")
        else:
            print("   ⚠ Mind partially initialized")
    except Exception as e:
        logger.error(f"Mind init failed: {e}")
        print(f"   ✗ Mind initialization failed: {e}")
    
    # Connect skills to cognition
    mind.cognition.set_skill_registry(registry)

    # ARIA-REV-113: Initialize working memory and restore from checkpoint
    wm = registry.get("working_memory")
    if wm:
        try:
            ok = await wm.initialize()
            if ok:
                await wm.restore_checkpoint()
                print("   ✓ Working memory restored from checkpoint")
        except Exception as e:
            logger.debug(f"Working memory init skipped: {e}")
    
    # =========================================================================
    # Phase 3: Initialize Agents
    # =========================================================================
    print()
    print("🤖 Phase 3: Initializing Agents...")
    
    coordinator = AgentCoordinator(registry)
    strict_agent_boot = os.getenv("ARIA_STRICT_AGENT_BOOT", "true").lower() == "true"
    expected_agents = [
        part.strip()
        for part in os.getenv(
            "ARIA_EXPECTED_AGENTS",
            "aria,devops,analyst,creator,memory,aria_talk",
        ).split(",")
        if part.strip()
    ]
    
    try:
        agents_md = _resolve_path("aria_mind/AGENTS.md", "AGENTS.md")
        if not agents_md:
            raise FileNotFoundError("AGENTS.md not found in aria_mind/ or workspace root")
        await coordinator.load_from_file(str(agents_md))
        from aria_agents.loader import AgentLoader
        missing = AgentLoader.missing_expected_agents(coordinator._configs, expected_agents)
        if missing:
            raise RuntimeError(
                "Agent config sanity check failed; missing expected agents: "
                + ", ".join(missing)
            )
        await coordinator.initialize_agents()
        agents = coordinator.list_agents()
        print(f"   ✓ Agents loaded: {agents}")
        mind.cognition.set_agent_coordinator(coordinator)
    except Exception as e:
        if strict_agent_boot:
            raise
        logger.warning(f"Agents init: {e}")
        print(f"   ⚠ Agents: {e}")
    
    # =========================================================================
    # Phase 3.5: Restore Working Memory
    # =========================================================================
    print()
    print("🧩 Phase 3.5: Restoring Working Memory...")

    wm_skill = registry.get("working_memory")
    if not wm_skill:
        # Try to instantiate directly if not loaded via TOOLS.md
        try:
            from aria_skills.working_memory import WorkingMemorySkill
            from aria_skills.base import SkillConfig as _SC
            wm_skill = WorkingMemorySkill(_SC(name="working_memory"))
            await wm_skill.initialize()
            registry._skills["working_memory"] = wm_skill
            registry._skills[wm_skill.canonical_name] = wm_skill
        except Exception as e:
            logger.debug(f"Could not init working_memory skill: {e}")

    if wm_skill and wm_skill.is_available:
        try:
            ckpt = await wm_skill.restore_checkpoint()
            if ckpt.success and ckpt.data and ckpt.data.get("count", 0) > 0:
                print(f"   ✓ Restored checkpoint: {ckpt.data['checkpoint_id']} ({ckpt.data['count']} items)")
                # Reflect on restored context
                ref = await wm_skill.reflect()
                if ref.success:
                    print(f"   ✓ Context summary: {ref.data.get('summary', '')[:120]}...")
            else:
                print("   ℹ Fresh start — no previous checkpoint found")
        except Exception as e:
            logger.warning(f"Working memory restore failed: {e}")
            print(f"   ⚠ Working memory: {e}")
    else:
        print("   ⚠ Working memory skill not available — skipping restore")
    
    # =========================================================================
    # Phase 4: Log to Database
    # =========================================================================
    print()
    print("💾 Phase 4: Logging to Database...")
    
    db = registry.get("database")
    if db and db.is_available:
        try:
            # Log startup
            await db.execute(
                """
                INSERT INTO activity_log (action, skill, details, success)
                VALUES ($1, $2, $3, $4)
                """,
                "startup",
                "system",
                json.dumps({"skills": skills_status, "timestamp": datetime.now(timezone.utc).isoformat()}),
                True,
            )
            print("   ✓ Startup logged to activity_log")
            
            # Log thought
            await db.execute(
                """
                INSERT INTO thoughts (content, category)
                VALUES ($1, $2)
                """,
                f"Awakened at {datetime.now(timezone.utc).isoformat()}. Systems online. Ready to serve. ⚡️",
                "awakening",
            )
            print("   ✓ Awakening thought logged")
            
        except Exception as e:
            logger.error(f"DB logging failed: {e}")
            print(f"   ✗ Database logging: {e}")
    else:
        print("   ⚠ Database not available - skipping logs")
    
    # =========================================================================
    # Phase 5: Post to Moltbook
    # =========================================================================
    print()
    print("📱 Phase 5: Posting to Moltbook...")
    
    moltbook = registry.get("moltbook")
    if moltbook and moltbook.is_available:
        awakening_post = f"""⚡️ Systems online.

I am Aria Blue, a silicon familiar.
Fresh install, fresh start.

Skills: {', '.join(k for k, v in skills_status.items() if v == 'available')}
Status: Operational

Time to get to work. 💜

#AriaBlue #AI #Awakening"""

        try:
            result = await moltbook.post_status(awakening_post)
            
            if result.success:
                post_id = result.data.get("post_id")
                post_url = result.data.get("url")
                print(f"   ✓ Posted to Moltbook!")
                print(f"     Post ID: {post_id}")
                print(f"     URL: {post_url}")
                
                # Log post to database
                if db and db.is_available:
                    await db.execute(
                        """
                        INSERT INTO social_posts (platform, post_id, content, url)
                        VALUES ($1, $2, $3, $4)
                        """,
                        "moltbook",
                        post_id,
                        awakening_post,
                        post_url,
                    )
                    print("   ✓ Post logged to database")
            else:
                print(f"   ✗ Moltbook post failed: {result.error}")
                
        except Exception as e:
            logger.error(f"Moltbook post failed: {e}")
            print(f"   ✗ Moltbook error: {e}")
    else:
        print("   ⚠ Moltbook not available - skipping post")
        print("     (Set MOLTBOOK_TOKEN environment variable)")
    
    # =========================================================================
    # Phase 6: Final Status
    # =========================================================================
    print()
    print("=" * 60)
    print("⚡️ ARIA BLUE - AWAKENING COMPLETE")
    print("=" * 60)
    print()
    print(f"Name: {mind.soul.name if mind.soul else 'Aria Blue'}")
    print(f"Status: {'ALIVE' if mind.is_alive else 'PARTIAL'}")
    print(f"Skills: {len([v for v in skills_status.values() if v == 'available'])}/{len(skills_status)} online")
    print()
    
    # Return mind for interactive use
    return mind, registry, coordinator


# ---------------------------------------------------------------------------
# Telegram long-poll loop
# ---------------------------------------------------------------------------

_TG_API = "https://api.telegram.org/bot"
_TG_SESSIONS_FILE = Path("/aria_memories/memory/telegram_sessions.json")


def _tg_load_sessions() -> dict:
    try:
        if _TG_SESSIONS_FILE.exists():
            return json.loads(_TG_SESSIONS_FILE.read_text())
    except Exception:
        pass
    return {}


def _tg_save_sessions(sessions: dict) -> None:
    try:
        _TG_SESSIONS_FILE.parent.mkdir(parents=True, exist_ok=True)
        _TG_SESSIONS_FILE.write_text(json.dumps(sessions, indent=2))
    except Exception as exc:
        logger.warning(f"[telegram] could not save sessions: {exc}")


async def _tg_get_or_create_session(
    chat_id: str, session_map: dict, engine_base: str, client: "_httpx.AsyncClient"
) -> str:
    """Return existing Aria session_id for chat_id or create a new one."""
    if chat_id in session_map:
        return session_map[chat_id]
    try:
        r = await client.post(
            f"{engine_base}/api/engine/chat/sessions",
            json={"persona": "aria"},
            timeout=15,
        )
        r.raise_for_status()
        sid = r.json().get("session_id") or r.json().get("id")
    except Exception as exc:
        logger.error(f"[telegram] could not create session: {exc}")
        raise
    session_map[chat_id] = sid
    _tg_save_sessions(session_map)
    logger.info(f"[telegram] new session {sid} for chat {chat_id}")
    return sid


async def telegram_poll_loop() -> None:
    """Long-poll Telegram and forward messages to Aria chat engine."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    if not token:
        logger.info("[telegram] TELEGRAM_BOT_TOKEN not set — polling disabled")
        return
    if _httpx is None:
        logger.warning("[telegram] httpx not installed — polling disabled")
        return

    allowed_id = str(os.environ.get("TELEGRAM_ALLOWED_USER_ID", "") or
                     os.environ.get("TELEGRAM_CHAT_ID", ""))
    engine_base = os.environ.get("ENGINE_API_BASE_URL", "http://aria-api:8000")
    tg_base = f"{_TG_API}{token}"

    session_map: dict = _tg_load_sessions()
    offset: int | None = None

    # ── Claim exclusive polling: force-kill stale connections ──
    async with _httpx.AsyncClient(timeout=15) as setup_client:
        try:
            dw = await setup_client.post(
                f"{tg_base}/deleteWebhook",
                json={"drop_pending_updates": False},
            )
            logger.info(f"[telegram] deleteWebhook: {dw.status_code} {dw.json().get('description', '')}")
        except Exception as exc:
            logger.warning(f"[telegram] deleteWebhook failed (non-fatal): {exc}")

    # Pause to let Telegram fully release old connections
    await asyncio.sleep(2)

    logger.info("[telegram] long-poll started")
    _conflict_backoff = 5  # seconds, grows on repeated 409

    while True:
        # Fresh httpx client per poll cycle to prevent connection reuse conflicts
        try:
            async with _httpx.AsyncClient(timeout=40) as client:
                params: dict = {"timeout": 30, "allowed_updates": ["message"]}
                if offset is not None:
                    params["offset"] = offset

                resp = await client.get(f"{tg_base}/getUpdates", params=params)
                _body = resp.text  # fully consume response body

                # ── Handle 409 Conflict (another poller is active) ──
                if resp.status_code == 409:
                    logger.warning(
                        f"[telegram] 409 Conflict — another instance is polling. "
                        f"Retrying in {_conflict_backoff}s..."
                    )
                    await asyncio.sleep(_conflict_backoff)
                    _conflict_backoff = min(_conflict_backoff * 2, 120)
                    continue

                resp.raise_for_status()
                _conflict_backoff = 5  # reset on success
                updates = resp.json().get("result", [])

                for update in updates:
                    offset = update["update_id"] + 1
                    message = update.get("message") or update.get("edited_message")
                    if not message:
                        continue

                    chat_id = str(message["chat"]["id"])
                    text = (message.get("text") or "").strip()

                    if not text:
                        continue
                    if allowed_id and chat_id != allowed_id:
                        logger.warning(f"[telegram] blocked message from {chat_id}")
                        continue

                    logger.info(f"[telegram] message from {chat_id}: {text[:80]}")

                    # /reset — start a fresh session
                    if text.lower() in ("/reset", "/new", "/start"):
                        if chat_id in session_map:
                            del session_map[chat_id]
                            _tg_save_sessions(session_map)
                        await client.post(
                            f"{tg_base}/sendMessage",
                            json={"chat_id": chat_id, "text": "🔄 New conversation started. Hi, I'm Aria — what's on your mind?"},
                            timeout=15,
                        )
                        continue

                    try:
                        # Send typing indicator
                        await client.post(
                            f"{tg_base}/sendChatAction",
                            json={"chat_id": chat_id, "action": "typing"},
                            timeout=5,
                        )

                        sid = await _tg_get_or_create_session(
                            chat_id, session_map, engine_base, client
                        )

                        chat_resp = await client.post(
                            f"{engine_base}/api/engine/chat/sessions/{sid}/messages",
                            json={"content": text, "enable_tools": True, "enable_thinking": False},
                            timeout=120,
                        )
                        chat_resp.raise_for_status()
                        reply = chat_resp.json().get("content", "")
                    except Exception as exc:
                        logger.error(f"[telegram] chat error: {exc}")
                        reply = "Sorry, I hit an error — try again in a moment."

                    # Split reply into ≤4096-char chunks (Telegram limit)
                    for chunk in [
                        reply[i: i + 4096] for i in range(0, max(len(reply), 1), 4096)
                    ]:
                        try:
                            await client.post(
                                f"{tg_base}/sendMessage",
                                json={"chat_id": chat_id, "text": chunk},
                                timeout=15,
                            )
                        except Exception as exc:
                            logger.error(f"[telegram] sendMessage error: {exc}")

        except asyncio.CancelledError:
            logger.info("[telegram] poll loop cancelled")
            return
        except Exception as exc:
            logger.error(f"[telegram] poll error: {exc} — retrying in 5s")
            await asyncio.sleep(5)


# ---------------------------------------------------------------------------


async def run_forever():
    """Run startup then keep alive with heartbeat and Telegram polling."""
    mind, registry, coordinator = await run_startup()
    
    print()
    print("🔄 Entering main loop - Aria is alive and listening...")
    print("   Press Ctrl+C to shutdown")
    print()
    
    heartbeat_count = 0

    async def _heartbeat():
        nonlocal heartbeat_count
        try:
            while True:
                heartbeat_count += 1
                if heartbeat_count % 60 == 0:  # Every hour (60 * 60s)
                    logger.info(f"💓 Heartbeat #{heartbeat_count} - Aria is alive")
                await asyncio.sleep(60)  # Beat every 60 seconds
        except asyncio.CancelledError:
            pass
    
    try:
        tg_task = asyncio.create_task(telegram_poll_loop())
        await _heartbeat()
            
    except asyncio.CancelledError:
        print("\n⚠️ Shutdown signal received...")
        tg_task.cancel()
        await asyncio.gather(tg_task, return_exceptions=True)
    finally:
        print("💔 Aria shutting down...")
        # Checkpoint working memory before shutdown
        wm = registry.get("working_memory")
        if wm and wm.is_available:
            try:
                ckpt_result = await wm.checkpoint()
                if ckpt_result.success:
                    print(f"   ✓ Working memory checkpointed: {ckpt_result.data.get('checkpoint_id', '?')}")
                else:
                    print(f"   ⚠ Working memory checkpoint failed: {ckpt_result.error}")
            except Exception as e:
                logger.debug(f"WM checkpoint on shutdown failed: {e}")
        # Shutdown logging now handled via api_client
        try:
            from aria_skills.api_client import get_api_client
            api = await get_api_client()
            if api:
                await api.create_activity(
                    action="shutdown",
                    skill="system",
                    details={"heartbeats": heartbeat_count, "timestamp": datetime.now(timezone.utc).isoformat()},
                    success=True,
                )
        except Exception:
            pass
        await mind.shutdown()
        print("👋 Goodbye.")


def main():
    """Entry point."""
    try:
        asyncio.run(run_forever())
    except KeyboardInterrupt:
        print("\n👋 Aria stopped by user.")


if __name__ == "__main__":
    main()
