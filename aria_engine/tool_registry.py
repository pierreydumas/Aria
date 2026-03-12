"""
Tool Registry — Translates aria_skills into LiteLLM tool definitions.

Bridges the gap between:
- aria_skills with their skill.json manifests and Python methods
- LiteLLM's OpenAI-compatible function calling format

Handles:
- Auto-discovery from skill.json manifests
- Function signature → JSON Schema conversion
- Direct Python execution (no subprocess)
- Result formatting for LLM consumption
- Timeout enforcement and error handling
"""
import asyncio
import inspect
import json
import logging
import os
import time
from datetime import datetime, timezone
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from aria_engine.exceptions import ToolError

logger = logging.getLogger("aria.engine.tools")


@dataclass
class ToolDefinition:
    """A tool that can be called by the LLM."""
    name: str
    description: str
    parameters: dict[str, Any]
    skill_name: str
    function_name: str
    _handler: Callable | None = field(default=None, repr=False)


@dataclass
class ToolResult:
    """Result of a tool execution."""
    tool_call_id: str
    name: str
    content: str
    success: bool = True
    duration_ms: int = 0


class ToolRegistry:
    """
    Discovers and manages tools from aria_skills.

    Usage:
        registry = ToolRegistry()
        registry.discover_from_skills(skill_registry)

        # Get tool definitions for LLM:
        tools = registry.get_tools_for_llm()

        # Execute a tool call:
        result = await registry.execute(tool_call_id, function_name, arguments)
    """

    def __init__(self, timeout_seconds: int = 300):
        self._tools: dict[str, ToolDefinition] = {}
        self._skill_instances: dict[str, Any] = {}
        self._manifests: dict[str, dict] = {}  # skill_name → full skill.json
        self._initialized_skills: set[str] = set()
        self._timeout = timeout_seconds
        self._consent_mode = os.getenv("ARIA_CONSENT_MODE", "enforced").strip().lower()
        # ARIA-REV-115: Idempotency cache for tool calls (prevents double-execution on retry)
        self._executed_cache: dict[str, ToolResult] = {}
        self._executed_cache_max = 200

    @staticmethod
    def _has_explicit_consent(args: dict[str, Any]) -> bool:
        """Check whether the tool arguments include explicit human consent."""
        consent_keys = (
            "consent",
            "consent_granted",
            "human_approved",
            "approval_granted",
            "approved_by_user",
        )
        for key in consent_keys:
            value = args.get(key)
            if value is True:
                return True
            if isinstance(value, str) and value.strip().lower() in {"true", "yes", "approved", "consented"}:
                return True
        return False

    @staticmethod
    def _is_high_impact(function_name: str) -> tuple[bool, str]:
        """Classify tool calls that require human consent before execution."""
        fn = function_name.lower()

        # Explicitly safe categories (always allowed)
        safe_prefixes = (
            "working_memory__",
            "sandbox__",
            "pytest_runner__",
        )
        safe_exact = {
            "api_client__set_memory",
            "api_client__get_memory",
            "api_client__create_thought",
            "api_client__create_activity",
            "api_client__propose_improvement",
        }
        if fn.startswith(safe_prefixes) or fn in safe_exact:
            return False, "safe"

        # External posting / outward actions
        # Social presence (moltbook, social, telegram) posting/reading is NOT
        # destructive — Aria is allowed to post autonomously without consent.
        # Destructive operations on those platforms (delete, wipe, purge, etc.)
        # fall through to the destructive_tokens check below so they remain gated.
        _social_destructive = ("delete", "remove", "drop", "wipe", "purge", "destroy", "reset", "cleanup")
        if fn.startswith("social__") or fn.startswith("moltbook__") or fn.startswith("telegram__"):
            if not any(token in fn for token in _social_destructive):
                return False, "safe"
            # fall through → picked up by destructive_tokens check

        # Raw SQL executor is high-impact
        if fn == "database__execute":
            return True, "raw_sql_execute"

        # Destructive patterns across tools
        destructive_tokens = (
            "delete",
            "remove",
            "drop",
            "truncate",
            "wipe",
            "purge",
            "destroy",
            "reset",
            "cleanup",
        )
        if any(token in fn for token in destructive_tokens):
            return True, "destructive_operation"

        # Config/scope modifying actions
        config_tokens = (
            "set_config",
            "update_config",
            "apply_config",
            "sync_jobs",
            "create_task",
            "update_job",
            "remove_job",
        )
        if any(token in fn for token in config_tokens):
            return True, "config_or_scope_change"

        return False, "safe"

    async def _invoke_handler(self, handler: Callable, kwargs: dict[str, Any]) -> Any:
        """Invoke a skill handler with timeout support for async/sync handlers."""
        if asyncio.iscoroutinefunction(handler):
            return await asyncio.wait_for(handler(**kwargs), timeout=self._timeout)
        loop = asyncio.get_event_loop()
        return await asyncio.wait_for(
            loop.run_in_executor(None, lambda: handler(**kwargs)),
            timeout=self._timeout,
        )

    async def _queue_pending_consent_action(
        self,
        function_name: str,
        args: dict[str, Any],
        reason: str,
    ) -> None:
        """Best-effort queue for blocked actions: API memory key first, file fallback."""
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tool": function_name,
            "reason": reason,
            "arguments": args,
            "status": "pending_human_consent",
        }

        # Primary path: persistent key-value memory for UI consumption
        try:
            get_tool = self._tools.get("api_client__get_memory")
            set_tool = self._tools.get("api_client__set_memory")
            if get_tool and set_tool:
                if not get_tool._handler:
                    get_tool._handler = self._lazy_import_handler(get_tool)
                if not set_tool._handler:
                    set_tool._handler = self._lazy_import_handler(set_tool)

                if get_tool._handler and set_tool._handler:
                    skill_name = set_tool.skill_name
                    if skill_name not in self._initialized_skills:
                        instance = self._skill_instances.get(skill_name)
                        if instance is not None and hasattr(instance, "initialize"):
                            try:
                                await instance.initialize()
                            except Exception:
                                pass
                        self._initialized_skills.add(skill_name)

                    existing_items: list[Any] = []
                    get_result = await self._invoke_handler(
                        get_tool._handler,
                        {"key": "pending_consent_actions"},
                    )

                    get_data = getattr(get_result, "data", None)
                    current_value: Any = None
                    if isinstance(get_data, dict) and "value" in get_data:
                        current_value = get_data.get("value")
                    elif isinstance(get_data, list):
                        current_value = get_data
                    elif isinstance(get_data, dict):
                        current_value = get_data
                    else:
                        current_value = get_data

                    if isinstance(current_value, list):
                        existing_items = current_value
                    elif isinstance(current_value, dict):
                        existing_items = [current_value]

                    existing_items.append(entry)
                    existing_items = existing_items[-50:]

                    await self._invoke_handler(
                        set_tool._handler,
                        {
                            "key": "pending_consent_actions",
                            "value": existing_items,
                            "category": "governance",
                        },
                    )
                    return
        except Exception:
            pass

        # Fallback path: local artifact log (non-blocking)
        try:
            consent_dir = Path("aria_memories/memory")
            consent_dir.mkdir(parents=True, exist_ok=True)
            consent_file = consent_dir / "pending_consent_actions.jsonl"
            with consent_file.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def discover_from_skills(self, skill_registry) -> int:
        """
        Auto-discover tools from the skill registry.

        Reads skill.json manifests and public methods to build tool definitions.
        Returns count of registered tools.
        """
        count = 0
        skills_dir = Path(__file__).parent.parent / "aria_skills"

        for skill_dir in skills_dir.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue

            manifest_path = skill_dir / "skill.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text())
                skill_name = manifest.get("name", skill_dir.name)

                # Get the skill instance from registry
                skill = skill_registry.get(skill_dir.name)
                if not skill:
                    continue

                self._skill_instances[skill_dir.name] = skill

                # Register each tool from manifest
                tools = manifest.get("tools", [])
                for tool_def in tools:
                    tool_name = f"{skill_dir.name}__{tool_def['name']}"
                    self._tools[tool_name] = ToolDefinition(
                        name=tool_name,
                        description=tool_def.get("description", ""),
                        parameters=tool_def.get("parameters", {"type": "object", "properties": {}}),
                        skill_name=skill_dir.name,
                        function_name=tool_def["name"],
                        _handler=getattr(skill, tool_def["name"], None),
                    )
                    count += 1

            except Exception as e:
                logger.warning("Failed to discover tools from %s: %s", skill_dir.name, e)

        logger.info("Discovered %d tools from %d skills", count, len(self._skill_instances))
        return count

    def discover_from_manifests(self, skills_base: str | Path | None = None) -> int:
        """
        Auto-discover tools from skill.json manifests only (no live instances needed).

        Reads each aria_skills/*/skill.json to register tool definitions for
        LLM function calling. Handlers are bound lazily on first execution via
        _lazy_import_handler().

        After registration, validates each handler is importable and removes
        orphan tools (manifest exists but no Python handler).

        Args:
            skills_base: Optional path to aria_skills directory. Defaults to
                ``/aria_skills`` (Docker mount) or sibling ``aria_skills/``.

        Returns:
            Number of verified tools registered.
        """
        if skills_base:
            skills_dir = Path(skills_base)
        else:
            # Try Docker mount path first, then relative to this file
            docker_path = Path("/aria_skills")
            local_path = Path(__file__).parent.parent / "aria_skills"
            skills_dir = docker_path if docker_path.is_dir() else local_path

        if not skills_dir.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return 0

        count = 0
        skill_stats: dict[str, dict] = {}
        for skill_dir in sorted(skills_dir.iterdir()):
            if not skill_dir.is_dir() or skill_dir.name.startswith("_"):
                continue

            manifest_path = skill_dir / "skill.json"
            if not manifest_path.exists():
                continue

            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                self._manifests[skill_dir.name] = manifest
                tools = manifest.get("tools", [])
                registered = 0
                for tool_def in tools:
                    tool_name = f"{skill_dir.name}__{tool_def['name']}"
                    if tool_name in self._tools:
                        continue  # Already registered by discover_from_skills

                    self._tools[tool_name] = ToolDefinition(
                        name=tool_name,
                        description=tool_def.get("description", ""),
                        parameters=tool_def.get("parameters") or tool_def.get("input_schema", {
                            "type": "object", "properties": {},
                        }),
                        skill_name=skill_dir.name,
                        function_name=tool_def["name"],
                        _handler=None,  # Lazy — bound on first call
                    )
                    registered += 1
                    count += 1

                skill_stats[skill_dir.name] = {"manifest_tools": len(tools), "registered": registered}

            except Exception as e:
                logger.warning("Failed to read manifest from %s: %s", skill_dir.name, e)

        logger.info("Discovered %d tool definitions from %d skill manifests", count, len(skill_stats))

        # ── Handler Validation ────────────────────────────────────────────
        # Try to import each skill and bind handlers eagerly.
        # Skills that fail to import stay registered with lazy handlers.
        # Only truly un-importable skills (no __init__.py) are removed.
        verified = 0
        lazy = 0
        removed = 0
        verified_skills: list[str] = []
        removed_skills: list[str] = []

        for skill_name, stats in skill_stats.items():
            try:
                import importlib
                mod = importlib.import_module(f"aria_skills.{skill_name}")

                # Find the primary skill class (inherits BaseSkill or has execute methods)
                skill_cls = None
                for attr_name in dir(mod):
                    cls = getattr(mod, attr_name)
                    if not isinstance(cls, type) or cls.__module__ != mod.__name__:
                        continue
                    # Prefer classes that inherit BaseSkill
                    if any(base.__name__ == "BaseSkill" for base in cls.__mro__):
                        skill_cls = cls
                        break
                    # Fallback: any class defined in this module
                    if skill_cls is None:
                        skill_cls = cls

                if skill_cls is None:
                    # Namespace package or empty module — no usable class, remove tools
                    skill_tools = [name for name, t in self._tools.items() if t.skill_name == skill_name]
                    for tool_name in skill_tools:
                        del self._tools[tool_name]
                    removed += len(skill_tools)
                    removed_skills.append(f"{skill_name}({len(skill_tools)})")
                    continue

                # Try instantiation with SkillConfig (most skills need it)
                instance = None
                try:
                    from aria_skills.base import SkillConfig
                    instance = skill_cls(SkillConfig(name=skill_name))
                except TypeError:
                    try:
                        instance = skill_cls()
                    except Exception as e:
                        logger.debug("Cannot instantiate skill %s: %s", skill_name, e)

                if instance is None:
                    # Can't instantiate — keep tools as lazy (will try again at call time)
                    lazy += stats["registered"]
                    continue

                self._skill_instances[skill_name] = instance

                # Bind handlers for all tools from this skill
                skill_tools = [t for t in self._tools.values() if t.skill_name == skill_name]
                bound = 0
                for tool in skill_tools:
                    handler = getattr(instance, tool.function_name, None)
                    if handler is not None:
                        tool._handler = handler
                        bound += 1
                    else:
                        lazy += 1  # Method name mismatch — stays lazy

                if bound > 0:
                    verified += bound
                    verified_skills.append(f"{skill_name}({bound})")

            except ImportError:
                # No __init__.py — genuine orphan, remove tools
                skill_tools = [name for name, t in self._tools.items() if t.skill_name == skill_name]
                for tool_name in skill_tools:
                    del self._tools[tool_name]
                removed += len(skill_tools)
                removed_skills.append(f"{skill_name}({len(skill_tools)})")
            except Exception as e:
                # Other error (syntax, dependency) — keep as lazy
                lazy += stats["registered"]
                logger.debug("Skill %s init failed (kept lazy): %s", skill_name, e)

        logger.info(
            "Tool validation: %d verified, %d lazy, %d removed. "
            "Verified: [%s]. Removed: [%s]",
            verified, lazy, removed,
            ", ".join(verified_skills[:15]),
            ", ".join(removed_skills) if removed_skills else "none",
        )
        return len(self._tools)

    def _lazy_import_handler(self, tool: ToolDefinition) -> Callable | None:
        """Attempt to import and bind a skill handler on first call."""
        if tool.skill_name in self._skill_instances:
            handler = getattr(self._skill_instances[tool.skill_name], tool.function_name, None)
            tool._handler = handler
            return handler

        # Try dynamic import: aria_skills.<skill>
        try:
            import importlib
            mod = importlib.import_module(f"aria_skills.{tool.skill_name}")

            # Find the primary skill class
            skill_cls = None
            for attr_name in dir(mod):
                cls = getattr(mod, attr_name)
                if not isinstance(cls, type) or cls.__module__ != mod.__name__:
                    continue
                if any(base.__name__ == "BaseSkill" for base in cls.__mro__):
                    skill_cls = cls
                    break
                if skill_cls is None:
                    skill_cls = cls

            if skill_cls is None:
                return None

            # Try instantiation with SkillConfig, then without
            instance = None
            try:
                from aria_skills.base import SkillConfig
                instance = skill_cls(SkillConfig(name=tool.skill_name))
            except (TypeError, ImportError):
                try:
                    instance = skill_cls()
                except Exception as e:
                    logger.debug("Cannot instantiate skill %s: %s", tool.skill_name, e)

            if instance is None:
                return None

            self._skill_instances[tool.skill_name] = instance
            handler = getattr(instance, tool.function_name, None)
            tool._handler = handler
            return handler
        except Exception as e:
            logger.debug("Lazy import failed for %s: %s", tool.skill_name, e)

        return None

    def register_tool(
        self,
        name: str,
        description: str,
        parameters: dict[str, Any],
        handler: Callable,
        skill_name: str = "custom",
    ):
        """Manually register a tool."""
        self._tools[name] = ToolDefinition(
            name=name,
            description=description,
            parameters=parameters,
            skill_name=skill_name,
            function_name=name,
            _handler=handler,
        )

    def get_tools_for_llm(self, filter_skills: list[str] | None = None) -> list[dict[str, Any]]:
        """
        Get tool definitions in OpenAI function calling format.

        Returns list of tool dicts compatible with litellm's tools parameter.
        """
        tools = []
        for name, tool in self._tools.items():
            if filter_skills and tool.skill_name not in filter_skills:
                continue

            tools.append({
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool.description,
                    "parameters": tool.parameters,
                },
            })

        return tools

    # ── Agent Skill Auto-Wiring ──────────────────────────────────────────

    # Focus types that map to affinity tags in skill.json manifests.
    FOCUS_TYPE_TO_AFFINITIES: dict[str, list[str]] = {
        "orchestrator":   ["orchestrator"],
        "devsecops":      ["devsecops"],
        "data":           ["data", "trader", "research"],
        "social":         ["social", "creative", "journalist"],
        "memory":         ["memory", "cognitive"],
        "rpg_master":     ["rpg_master"],
        "conversational": [],
    }

    # Only these skills may declare layer 0 (global injection).
    ALLOWED_L0_SKILLS: frozenset[str] = frozenset(["input_guard"])

    # Hard cap to prevent token explosion.
    MAX_SKILLS_PER_AGENT: int = 25

    def build_agent_skill_map(
        self,
        agents: list[dict[str, Any]],
    ) -> dict[str, list[str]]:
        """
        Compute agent → skills mapping using manifest metadata.

        Rules:
        1. Layer 0 skills → ALL agents (if in ALLOWED_L0_SKILLS allowlist)
        2. Layer 1-2 skills → ALL agents (core infrastructure)
        3. Layer 3-4 skills → agents whose focus_type matches any focus_affinity
        4. Manual skills from the current DB list are preserved (union)
        5. exclude_skills removes specific skills (opt-out)
        6. Dependencies are auto-included (transitive, cycle-safe)

        Args:
            agents: list of dicts with keys: agent_id, focus_type, skills, exclude_skills

        Returns:
            {agent_id: sorted_skill_list}
        """
        result: dict[str, list[str]] = {}

        for agent in agents:
            agent_id = agent["agent_id"]
            focus_type = agent.get("focus_type") or ""
            agent_affinities = self.FOCUS_TYPE_TO_AFFINITIES.get(focus_type, [])
            computed: set[str] = set(agent.get("skills") or [])

            for skill_name, manifest in self._manifests.items():
                layer = manifest.get("layer", 3)
                if not isinstance(layer, int) or not (0 <= layer <= 4):
                    layer = 4
                affinity = manifest.get("focus_affinity", [])
                if not isinstance(affinity, list):
                    affinity = []

                if layer == 0:
                    if skill_name not in self.ALLOWED_L0_SKILLS:
                        logger.warning(
                            "Blocked skill '%s' claiming layer 0 — not in allowlist",
                            skill_name,
                        )
                        continue
                    computed.add(skill_name)
                elif layer <= 2:
                    # Core infrastructure — available to all agents
                    computed.add(skill_name)
                else:
                    # Domain (L3-L4) — affinity match required
                    if any(a in agent_affinities for a in affinity):
                        computed.add(skill_name)

            # Resolve transitive dependencies (cycle-safe)
            computed |= self._resolve_deps(computed)

            # Apply exclusions
            for ex in agent.get("exclude_skills") or []:
                computed.discard(ex)

            # Cap skill count (keep L0 + L1-L2 first, then by layer)
            if len(computed) > self.MAX_SKILLS_PER_AGENT:
                logger.warning(
                    "Agent %s has %d skills (cap=%d) — trimming",
                    agent_id, len(computed), self.MAX_SKILLS_PER_AGENT,
                )
                prioritized = sorted(
                    computed,
                    key=lambda s: self._manifests.get(s, {}).get("layer", 3),
                )
                computed = set(prioritized[: self.MAX_SKILLS_PER_AGENT])

            result[agent_id] = sorted(computed)

        return result

    def _resolve_deps(self, skills: set[str], _max_depth: int = 3) -> set[str]:
        """Resolve transitive dependencies for a skill set (cycle-safe)."""
        added: set[str] = set()
        visited: set[str] = set()

        def _walk(name: str, depth: int) -> None:
            if depth > _max_depth or name in visited:
                return
            visited.add(name)
            for dep in self._manifests.get(name, {}).get("dependencies", []):
                if dep not in skills and dep not in added:
                    added.add(dep)
                _walk(dep, depth + 1)

        for skill in list(skills):
            _walk(skill, 0)
        return added

    async def get_allowed_skills(self, db: Any, agent_id: str) -> list[str] | None:
        """
        Read the per-agent skill filter from the DB.

        Shared by ChatEngine and StreamingEngine to avoid DRY violations.
        Returns the allowed skills list, or None if no filtering.
        Falls closed: if skills column is NULL/empty, returns L0-only list.
        """
        from sqlalchemy import select

        try:
            from db.models import EngineAgentState
        except ImportError:
            return None

        result = await db.execute(
            select(EngineAgentState.skills).where(
                EngineAgentState.agent_id == agent_id
            )
        )
        row = result.first()
        if row and row[0]:
            try:
                skills_list = (
                    json.loads(row[0]) if isinstance(row[0], str) else row[0]
                )
                if isinstance(skills_list, list) and skills_list:
                    # Ensure L0 global skills are always present
                    for l0 in self.ALLOWED_L0_SKILLS:
                        if l0 not in skills_list:
                            skills_list.append(l0)
                    return skills_list
            except (json.JSONDecodeError, TypeError, KeyError):
                pass

        # Fail-closed: NULL or empty skills → only L0 globals
        return list(self.ALLOWED_L0_SKILLS)

    async def execute(
        self,
        tool_call_id: str,
        function_name: str,
        arguments: str | dict[str, Any],
    ) -> ToolResult:
        """
        Execute a tool call from the LLM.

        Args:
            tool_call_id: ID from the LLM's tool call
            function_name: Function name (format: skill__method)
            arguments: JSON string or dict of arguments

        Returns:
            ToolResult with stringified content
        """
        # ARIA-REV-115: Idempotency — return cached result for duplicate tool_call_id
        if tool_call_id and tool_call_id in self._executed_cache:
            logger.debug("Idempotent replay for tool_call_id=%s", tool_call_id)
            return self._executed_cache[tool_call_id]

        start = time.monotonic()

        tool = self._tools.get(function_name)
        if not tool:
            return ToolResult(
                tool_call_id=tool_call_id,
                name=function_name,
                content=json.dumps({"error": f"Unknown tool: {function_name}"}),
                success=False,
            )

        if not tool._handler:
            # Try lazy import before giving up
            tool._handler = self._lazy_import_handler(tool)
            if not tool._handler:
                return ToolResult(
                    tool_call_id=tool_call_id,
                    name=function_name,
                    content=json.dumps({"error": f"No handler for tool: {function_name}"}),
                    success=False,
                )

        # Lazy-initialize skill instance on first use
        skill_name = tool.skill_name
        if skill_name not in self._initialized_skills:
            instance = self._skill_instances.get(skill_name)
            if instance is not None and hasattr(instance, "initialize"):
                try:
                    ok = await instance.initialize()
                    if ok:
                        logger.info("Lazy-initialized skill: %s", skill_name)
                    else:
                        logger.warning("Skill %s initialize() returned False", skill_name)
                except Exception as init_err:
                    logger.warning("Skill %s initialize() failed: %s", skill_name, init_err)
            self._initialized_skills.add(skill_name)

        # Parse arguments
        if isinstance(arguments, str):
            try:
                args = json.loads(arguments)
            except json.JSONDecodeError:
                args = {"input": arguments}
        else:
            args = arguments

        if not isinstance(args, dict):
            args = {"input": str(args)}

        # Parameter name mapping for common LLM variations.
        # Some models use generic "input" field instead of specific parameter names.
        if "input" in args and "content" not in args and function_name == "api_client__write_artifact":
            args["content"] = args.pop("input")
            logger.debug("Mapped 'input' -> 'content' for %s", function_name)

        # Consent checkpoint (small central guardrail)
        if self._consent_mode == "enforced":
            requires_consent, reason = self._is_high_impact(function_name)
            if requires_consent and not self._has_explicit_consent(args):
                await self._queue_pending_consent_action(function_name, args, reason)
                elapsed_ms = int((time.monotonic() - start) * 1000)
                return ToolResult(
                    tool_call_id=tool_call_id,
                    name=function_name,
                    content=json.dumps({
                        "error": "human_consent_required",
                        "reason": reason,
                        "message": (
                            "High-impact action blocked until explicit human consent is provided. "
                            "Allowed alternatives: write proposal, run sandbox tests, write memory, "
                            "or produce a draft plan."
                        ),
                    }),
                    success=False,
                    duration_ms=elapsed_ms,
                )

        try:
            # Execute with timeout
            if asyncio.iscoroutinefunction(tool._handler):
                result = await asyncio.wait_for(
                    tool._handler(**args),
                    timeout=self._timeout,
                )
            else:
                loop = asyncio.get_event_loop()
                result = await asyncio.wait_for(
                    loop.run_in_executor(None, lambda: tool._handler(**args)),
                    timeout=self._timeout,
                )

            elapsed_ms = int((time.monotonic() - start) * 1000)

            # Format result
            if hasattr(result, "to_dict"):
                content = json.dumps(result.to_dict())
            elif hasattr(result, "data"):
                # Preserve error message from SkillResult.fail()
                payload: dict[str, Any] = {
                    "success": getattr(result, "success", True),
                    "data": result.data,
                }
                error_msg = getattr(result, "error", None)
                if error_msg:
                    payload["error"] = str(error_msg)
                content = json.dumps(payload)
            elif isinstance(result, (dict, list)):
                content = json.dumps(result)
            else:
                content = str(result)

            # Propagate skill-level success/failure
            skill_success = getattr(result, "success", True) if hasattr(result, "success") else True

            tool_result = ToolResult(
                tool_call_id=tool_call_id,
                name=function_name,
                content=content,
                success=bool(skill_success),
                duration_ms=elapsed_ms,
            )

            # ARIA-REV-115: Cache successful results for idempotency
            if tool_call_id and tool_result.success:
                if len(self._executed_cache) >= self._executed_cache_max:
                    # Evict oldest entry
                    self._executed_cache.pop(next(iter(self._executed_cache)))
                self._executed_cache[tool_call_id] = tool_result

            return tool_result

        except asyncio.TimeoutError:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=function_name,
                content=json.dumps({"error": f"Tool timed out after {self._timeout}s"}),
                success=False,
                duration_ms=elapsed_ms,
            )
        except Exception as e:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            logger.error("Tool execution failed: %s — %s", function_name, e)
            return ToolResult(
                tool_call_id=tool_call_id,
                name=function_name,
                content=json.dumps({"error": str(e)}),
                success=False,
                duration_ms=elapsed_ms,
            )

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools (for debugging)."""
        return [
            {
                "name": t.name,
                "skill": t.skill_name,
                "function": t.function_name,
                "description": t.description[:100],
            }
            for t in self._tools.values()
        ]
