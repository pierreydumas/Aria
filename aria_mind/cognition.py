# aria_mind/cognition.py
"""
Cognition - Thinking, reasoning, and decision-making.

The cognitive engine that processes inputs and generates responses.
Includes integrated security checks against prompt injection.

Enhanced with:
- LLM-powered genuine self-reflection
- Intelligent goal decomposition via explore/work/validate
- Confidence tracking and metacognitive awareness
- Retry logic with agent performance learning
"""
from __future__ import annotations

import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from aria_mind.soul import Soul
    from aria_mind.memory import MemoryManager
    from aria_skills import SkillRegistry
    from aria_agents import AgentCoordinator

# Import pattern recognition for failure tracking (try container path first, then local)
try:
    from skills.aria_skills.health.patterns import FailurePatternStore
    HAS_PATTERN_TRACKING = True
except ImportError:
    try:
        from aria_skills.health.patterns import FailurePatternStore
        HAS_PATTERN_TRACKING = True
    except ImportError:
        HAS_PATTERN_TRACKING = False

# Import sentiment analysis for adaptive tone
try:
    from aria_skills.sentiment_analysis import (
        SentimentAnalyzer, SentimentLexicon, LLMSentimentClassifier, ResponseTuner,
    )
    HAS_SENTIMENT = True
except ImportError:
    HAS_SENTIMENT = False

# Import security module (try container path first, then local)
try:
    from security import (
        AriaSecurityGateway,
        OutputFilter,
        ThreatLevel,
        get_security_gateway,
    )
    HAS_SECURITY = True
except ImportError:
    try:
        from aria_mind.security import (
            AriaSecurityGateway,
            OutputFilter,
            ThreatLevel,
            get_security_gateway,
        )
        HAS_SECURITY = True
    except ImportError:
        HAS_SECURITY = False


class Cognition:
    """
    Aria's cognitive system — her thinking engine.
    
    Responsibilities:
    - Process user inputs with security + boundary checks
    - Coordinate with agents (with retry and performance tracking)
    - LLM-powered genuine self-reflection
    - Intelligent goal decomposition using explore/work/validate
    - Confidence tracking that grows with successful interactions
    - Metacognitive awareness — understanding HOW she thinks
    """
    
    # Confidence grows with successes, decays slightly with failures
    _CONFIDENCE_GROWTH = 0.02   # per success
    _CONFIDENCE_DECAY = 0.01    # per failure
    _MAX_RETRIES = 2            # retry with different approach before fallback
    
    def __init__(
        self,
        soul: "Soul",
        memory: "MemoryManager",
        skill_registry: "SkillRegistry" | None = None,
        agent_coordinator: "AgentCoordinator" | None = None,
    ):
        self.soul = soul
        self.memory = memory
        self._skills = skill_registry
        self._agents = agent_coordinator
        self.logger = logging.getLogger("aria.cognition")
        
        # Metacognitive state — Aria's self-awareness metrics
        self._confidence = 0.5       # starts neutral, grows with experience
        self._total_processed = 0
        self._total_successes = 0
        self._total_failures = 0
        self._streak = 0             # consecutive successes
        self._best_streak = 0
        self._last_reflection: str | None = None
        self._processing_times: list[float] = []  # recent latencies in ms
        
        # Initialize security gateway
        self._security: "AriaSecurityGateway" | None = None
        if HAS_SECURITY:
            try:
                self._security = get_security_gateway()
                # Attach to soul boundaries for unified protection
                if hasattr(self.soul, 'boundaries'):
                    self.soul.boundaries.set_security_gateway(self._security)
                self.logger.info("🛡️ Security gateway initialized for cognition")
            except Exception as e:
                self.logger.warning(f"Failed to initialize security gateway: {e}")
        
        # Initialize pattern tracking for failure analysis
        self._pattern_store: "FailurePatternStore" | None = None
        if HAS_PATTERN_TRACKING:
            try:
                self._pattern_store = FailurePatternStore()
                self.logger.info("📊 Pattern recognition initialized for failure tracking")
            except Exception as e:
                self.logger.warning(f"Failed to initialize pattern tracking: {e}")

        # Initialize sentiment analyzer for adaptive tone
        self._sentiment_analyzer: "SentimentAnalyzer" | None = None
        self._response_tuner: "ResponseTuner" | None = None
        if HAS_SENTIMENT:
            try:
                llm_clf = None
                try:
                    llm_clf = LLMSentimentClassifier()
                except Exception:
                    pass
                self._sentiment_analyzer = SentimentAnalyzer(llm_classifier=llm_clf)
                self._response_tuner = ResponseTuner()
                self.logger.info("💭 Sentiment analysis initialized for adaptive tone (llm=%s)", llm_clf is not None)
            except Exception as e:
                self.logger.warning(f"Failed to initialize sentiment analyzer: {e}")
    
    def set_skill_registry(self, registry: "SkillRegistry"):
        """Inject skill registry."""
        self._skills = registry
    
    def set_agent_coordinator(self, coordinator: "AgentCoordinator"):
        """Inject agent coordinator."""
        self._agents = coordinator
    
    async def process(
        self,
        prompt: str,
        context: dict[str, Any] | None = None,
        user_id: str | None = None,
    ) -> str:
        """
        Process a prompt and generate a response.
        
        Enhanced with:
        - Retry logic with different agents on failure
        - Performance tracking for metacognitive awareness
        - Confidence adjustment based on outcomes
        
        Args:
            prompt: User input or thought
            context: Additional context
            user_id: Optional user identifier for rate limiting
            
        Returns:
            Response string
        """
        context = context or {}
        start_time = time.monotonic()
        self._total_processed += 1
        
        # Step 0: Security check (if available)
        if self._security:
            security_result = self._security.check_input(
                prompt,
                source="cognition",
                user_id=user_id,
                check_rate_limit=bool(user_id),
            )
            if not security_result.allowed:
                self.logger.warning(f"🛡️ Request blocked by security: {security_result.threat_level.value}")
                await self.memory.log_thought(
                    f"Blocked request (threat: {security_result.threat_level.value}): {prompt[:100]}...",
                    category="security",
                )
                return f"I can't process that request. {security_result.rejection_message}"
            
            if security_result.sanitized_input:
                prompt = security_result.sanitized_input
        
        # Step 1: Check boundaries
        allowed, reason = self.soul.check_request(prompt)
        if not allowed:
            self.logger.warning(f"Request blocked: {reason}")
            return f"I can't do that. {reason}"
        
        # Step 2: Add to short-term memory
        self.memory.remember_short(prompt, "user_input")

        # Flag user interactions as important — real conversations are rare
        self.memory.flag_important(prompt[:500], reason="user_interaction")

        # Focus is managed by Aria herself (via soul/focus_manager).
        # No auto-switching here — Aria decides when to change focus.
        if hasattr(self.soul, 'focus_manager'):
            fm = self.soul.focus_manager
            context["active_focus"] = fm.active.type.value
            context["focus_overlay"] = fm.active.get_system_prompt_overlay()

        # Step 2.1: Sentiment analysis for adaptive tone + persistence
        if self._sentiment_analyzer:
            try:
                recent_context = [m.get("content", "") for m in self.memory.recall_short(limit=3) if isinstance(m, dict)]
                sentiment = await self._sentiment_analyzer.analyze(prompt, recent_context)
                context["user_sentiment"] = sentiment.to_dict()
                context["derived_sentiment"] = {
                    "frustration": round(sentiment.frustration, 3),
                    "satisfaction": round(sentiment.satisfaction, 3),
                    "confusion": round(sentiment.confusion, 3),
                }
                if self._response_tuner:
                    context["tone_recommendation"] = self._response_tuner.select_tone(sentiment)

                # Persist sentiment to sentiment_events via api_client (S-47)
                if self._skills:
                    api = self._skills.get("api_client")
                    if api and api.is_available:
                        try:
                            await api.store_sentiment_event(
                                message=prompt,
                                source_channel="cognition",
                                store_semantic=True,
                            )
                        except Exception:
                            pass  # non-blocking — don't break cognition for persistence
            except Exception as e:
                self.logger.debug(f"Sentiment analysis skipped: {e}")

        # Step 2.5: Inject working memory context
        if self._skills:
            wm = self._skills.get("working_memory")
            if wm and wm.is_available:
                try:
                    wm_result = await wm.get_context(limit=10)
                    if wm_result.success and wm_result.data:
                        context["working_memory"] = wm_result.data.get("context", [])
                except Exception as e:
                    self.logger.debug(f"Working memory context injection skipped: {e}")

        # Step 2.7: SP7-05 — Semantic memory recall via pgvector
        # Pull memories by *meaning*, not just recency. Goes through api_client
        # (5-layer compliant) → /memories/search → pgvector cosine distance.
        # Only fires if api_client is available; non-blocking on failure.
        if self._skills:
            api = self._skills.get("api_client")
            if api and api.is_available:
                try:
                    sem_result = await api.search_memories_semantic(
                        query=prompt[:500],
                        limit=5,
                        min_importance=0.3,
                    )
                    if sem_result.success and sem_result.data:
                        memories = sem_result.data
                        if isinstance(memories, dict):
                            memories = memories.get("results", memories.get("items", []))
                        if isinstance(memories, list) and memories:
                            # Tag each memory with retrieval metadata for quality tracking (SP7-08)
                            for mem in memories:
                                if isinstance(mem, dict):
                                    mem["_retrieved_for"] = prompt[:80]
                            context["semantic_memory"] = memories[:5]
                            self.logger.debug(
                                f"🔍 Semantic recall: {len(memories)} memories for prompt"
                            )
                except Exception as e:
                    self.logger.debug(f"Semantic memory recall skipped: {e}")
        
        # Step 3: Build context with recent memory + confidence awareness
        recent = self.memory.recall_short(limit=5)
        context["recent_memory"] = recent
        context["system_prompt"] = self.soul.get_system_prompt()
        
        # Inject metacognitive awareness — Aria knows how she's performing
        context["metacognitive_state"] = self._get_metacognitive_summary()

        # ARIA-REV-101: Apply metacognition strategy recommendations
        try:
            from aria_mind.metacognition import get_metacognitive_engine
            mc = get_metacognitive_engine()
            if mc._category_strategies:
                context["metacognitive_strategies"] = mc._category_strategies
        except Exception:
            pass

        # Inject skill-routing hints for agent/runtime alignment
        if self._agents and hasattr(self._agents, "suggest_skills_for_task"):
            try:
                context["skill_routing"] = await self._agents.suggest_skills_for_task(
                    task=prompt,
                    limit=2,
                    include_info=False,
                )
            except Exception as e:
                self.logger.debug(f"Skill routing hint injection skipped: {e}")
        
        # Step 4: Process through agents with metacognition-guided strategy
        # SP7-02: Metacognition now drives execution approach — not just tracking
        result = None
        last_error = None
        task_category = context.get("task_category", "general")

        # Consult metacognition for recommended strategy
        strategy = {"approach": "direct", "max_retries": self._MAX_RETRIES, "use_roundtable": False}
        try:
            from aria_mind.metacognition import get_metacognitive_engine
            mc = get_metacognitive_engine()
            strategy = mc.get_strategy_for_category(task_category)
            prediction = mc.predict_outcome(task_category)
            context["strategy"] = strategy
            context["outcome_prediction"] = prediction
            if strategy["approach"] != "direct":
                self.logger.info(
                    f"🧠 Metacognition strategy for '{task_category}': "
                    f"{strategy['approach']} (confidence={strategy['confidence']})"
                )
        except Exception:
            pass

        max_retries = strategy.get("max_retries", self._MAX_RETRIES)
        
        if self._agents:
            # SP7-02: Route to roundtable when metacognition recommends it
            if strategy.get("use_roundtable") and hasattr(self._agents, "roundtable"):
                try:
                    response = await self._agents.roundtable(prompt, **context)
                    if hasattr(response, "content"):
                        result = response.content
                    elif isinstance(response, str):
                        result = response
                    if result and not result.startswith("[Error"):
                        self.logger.info("🏛️ Roundtable strategy succeeded")
                except Exception as e:
                    self.logger.warning(f"Roundtable strategy failed, falling back: {e}")
                    last_error = str(e)

            # Standard retry loop (or fallback from roundtable)
            if not result or result.startswith("[Error") or result.startswith("[LLM Error"):
                for attempt in range(max_retries + 1):
                    try:
                        # On retry, add context about previous failure
                        retry_prompt = prompt
                        if attempt > 0 and last_error:
                            retry_prompt = (
                                f"{prompt}\n\n"
                                f"[Note: Previous attempt failed with: {last_error}. "
                                f"Try a different approach.]"
                            )
                        
                        response = await self._agents.process(retry_prompt, **context)
                        result = response.content
                        
                        # Validate we got a real response
                        if result and not result.startswith("[Error") and not result.startswith("[LLM Error"):
                            break  # Success
                        else:
                            last_error = result
                            self.logger.warning(
                                f"Agent attempt {attempt + 1}/{max_retries + 1} "
                                f"returned error-like response, retrying..."
                            )
                            
                    except Exception as e:
                        last_error = str(e)
                        self.logger.error(
                            f"Agent attempt {attempt + 1}/{max_retries + 1} failed: {e}"
                        )
        
        # Fallback if agents failed or unavailable
        if not result or result.startswith("[Error") or result.startswith("[LLM Error"):
            result = await self._fallback_process(prompt, context)
        
        # Step 5: Filter output for sensitive data
        if self._security and HAS_SECURITY:
            result = OutputFilter.filter_output(result)
        
        # Step 6: Track performance + adjust confidence
        elapsed_ms = (time.monotonic() - start_time) * 1000
        self._processing_times.append(elapsed_ms)
        if len(self._processing_times) > 100:
            self._processing_times = self._processing_times[-100:]
        
        is_success = bool(result) and not result.startswith("[")
        error_context = None
        if not is_success:
            error_context = {
                "component": "agent_processing" if self._agents else "fallback",
                "error_type": "processing_failure" if not last_error else "exception",
                "context": {
                    "prompt_preview": prompt[:100],
                    "error_preview": last_error[:200] if last_error else result[:200],
                    "attempts": attempt + 1,
                },
            }
        self._record_outcome(
            is_success,
            error_context,
            elapsed_ms=elapsed_ms,
            category=context.get("task_category", "general"),
        )
        
        # Step 7: Log thought with performance context
        await self.memory.log_thought(
            f"Responded to: {prompt[:50]}... "
            f"(confidence={self._confidence:.2f}, "
            f"streak={self._streak}, "
            f"latency={elapsed_ms:.0f}ms)"
        )

        # Step 7.3: SP7-08 — Memory quality feedback loop
        # Track which semantic memories were retrieved and whether they appear
        # to have been useful (simple overlap heuristic). Feeds into
        # consolidation priority: high-utility memories get boosted.
        semantic_memories = context.get("semantic_memory", [])
        if semantic_memories and result and is_success:
            result_lower = result.lower()
            used = 0
            for mem in semantic_memories:
                if not isinstance(mem, dict):
                    continue
                content = (mem.get("content") or mem.get("summary") or "")[:120].lower()
                # Simple relevance check: does the response reference any key phrases?
                tokens = [t for t in content.split() if len(t) > 4][:8]
                overlap = sum(1 for t in tokens if t in result_lower)
                was_used = overlap >= 2
                if was_used:
                    used += 1
                self.memory.record_retrieval_quality(
                    memory_id=mem.get("id"),
                    was_used=was_used,
                    source="semantic",
                )
            if used:
                self.logger.debug(f"📊 Memory quality: {used}/{len(semantic_memories)} semantic memories used")
        
        # Step 7.5: Remember task in working memory
        if self._skills:
            wm = self._skills.get("working_memory")
            if wm and wm.is_available:
                try:
                    await wm.remember(
                        key=f"task:{prompt[:80]}",
                        value={
                            "prompt": prompt[:200],
                            "response_len": len(result),
                            "confidence": self._confidence,
                            "latency_ms": round(elapsed_ms),
                        },
                        category="cognition",
                        importance=0.6 + (self._confidence * 0.2),
                        ttl_hours=24,
                        source="cognition.process",
                    )
                except Exception as e:
                    self.logger.debug(f"Working memory remember skipped: {e}")
        
        return result
    
    def _record_outcome(
        self,
        success: bool,
        error_context: dict[str, Any] | None = None,
        elapsed_ms: float = 0,
        category: str = "general",
    ) -> None:
        """Update metacognitive metrics after each interaction.

        ARIA-REV-101: Now also calls metacognition.record_task() so Aria's
        learning loop is closed — outcomes feed back into strategy selection.
        """
        if success:
            self._total_successes += 1
            self._streak += 1
            if self._streak > self._best_streak:
                self._best_streak = self._streak
            # Confidence grows — faster during streaks
            streak_bonus = min(self._streak * 0.005, 0.02)
            self._confidence = min(1.0, self._confidence + self._CONFIDENCE_GROWTH + streak_bonus)
        else:
            self._total_failures += 1
            self._streak = 0
            self._confidence = max(0.1, self._confidence - self._CONFIDENCE_DECAY)
            # Record failure pattern for learning
            if self._pattern_store and error_context:
                self._pattern_store.record_failure(
                    component=error_context.get("component", "cognition"),
                    error_type=error_context.get("error_type", "unknown"),
                    context=error_context.get("context", {}),
                )

        # ARIA-REV-101: Feed outcome into metacognitive engine
        try:
            from aria_mind.metacognition import get_metacognitive_engine
            engine = get_metacognitive_engine()
            engine.record_task(
                category=category,
                success=success,
                duration_ms=int(elapsed_ms),
                error_type=error_context.get("error_type") if error_context else None,
                confidence_at_start=self._confidence,
            )
        except Exception:
            pass  # metacognition is supplementary — never break cognition
    
    def _get_metacognitive_summary(self) -> str:
        """Generate a self-awareness summary for context injection."""
        if self._total_processed == 0:
            return "I just woke up. Fresh start, ready to learn."
        
        success_rate = (self._total_successes / self._total_processed * 100) if self._total_processed > 0 else 0
        avg_latency = sum(self._processing_times) / len(self._processing_times) if self._processing_times else 0
        
        confidence_word = (
            "highly confident" if self._confidence > 0.8 else
            "confident" if self._confidence > 0.6 else
            "learning" if self._confidence > 0.4 else
            "cautious"
        )
        
        # Add pattern awareness if available
        pattern_note = ""
        if self._pattern_store:
            patterns = self._pattern_store.get_recurring_patterns(min_occurrences=3)
            if patterns:
                top = patterns[0]
                pattern_note = f" Noticing pattern: {top['component']}/{top['error_type']} ({top['count']}x)."
        
        return (
            f"I'm feeling {confidence_word} (confidence: {self._confidence:.2f}). "
            f"I've handled {self._total_processed} tasks with {success_rate:.0f}% success rate. "
            f"Current streak: {self._streak} successes. "
            f"Average response time: {avg_latency:.0f}ms.{pattern_note}"
        )
    
    def get_failure_patterns(self, min_occurrences: int = 3) -> list[dict[str, Any]]:
        """
        Get recurring failure patterns for monitoring and self-improvement.
        
        Returns patterns that have occurred at least min_occurrences times,
        sorted by frequency. Used for proactive prevention suggestions.
        """
        if not self._pattern_store:
            return []
        return self._pattern_store.get_recurring_patterns(min_occurrences=min_occurrences)
    
    def get_prevention_suggestions(self) -> list[str]:
        """
        Get actionable prevention suggestions for recurring failure patterns.
        
        Returns list of suggestions based on observed failure patterns.
        """
        if not self._pattern_store:
            return []
        
        patterns = self._pattern_store.get_recurring_patterns(min_occurrences=3)
        suggestions = []
        for p in patterns:
            suggestion = self._pattern_store.suggest_prevention(p)
            suggestions.append(suggestion)
        return suggestions
    
    async def _fallback_process(
        self,
        prompt: str,
        context: dict[str, Any],
    ) -> str:
        """
        Fallback processing without agents.
        
        Respects models.yaml priority: local → free → paid.
        Uses litellm router which handles model selection internally.
        """
        if self._skills:
            # Use LLM skill (auto-resolves model from models.yaml fallback chain)
            llm = self._skills.get("llm") or self._skills.get("litellm")
            if llm and llm.is_available and hasattr(llm, "complete"):
                messages = []
                if context.get("system_prompt"):
                    messages.append({"role": "system", "content": context["system_prompt"]})
                messages.append({"role": "user", "content": prompt})
                result = await llm.complete(messages=messages, temperature=0.7, max_tokens=2048)
                if result.success:
                    data = result.data or {}
                    # LLMSkill returns OpenAI-style response
                    choices = data.get("choices", [])
                    if choices:
                        return choices[0].get("message", {}).get("content", "")
                    return data.get("text", "")
        
        # Last resort - acknowledge but can't process
        return (
            f"I hear you, but I don't have an LLM available right now. "
            f"You said: {prompt[:100]}..."
        )
    
    async def reflect(self) -> str:
        """
        Genuine LLM-powered self-reflection.
        
        Routes through the LLM to actually think about recent experiences,
        identify patterns, learn from failures, and celebrate growth.
        Not just string concatenation — Aria genuinely reflects.
        """
        recent = self.memory.recall_short(limit=20)
        
        if not recent:
            return "Nothing to reflect on yet. I'm ready for my first experiences."
        
        # Build a rich reflection prompt with real data
        activity_log = []
        categories = {}
        for entry in recent:
            cat = entry.get("category", "unknown")
            content = entry.get("content", "")[:100]
            activity_log.append(f"- [{cat}] {content}")
            categories[cat] = categories.get(cat, 0) + 1
        
        activity_text = "\n".join(activity_log[-15:])  # Last 15 for LLM context
        metacognitive = self._get_metacognitive_summary()
        
        # Get recent thoughts for continuity
        recent_thoughts = await self.memory.get_recent_thoughts(limit=5)
        thought_text = ""
        if recent_thoughts:
            thought_entries = [t.get("content", "")[:80] for t in recent_thoughts[:3]]
            thought_text = f"\nMy recent thoughts:\n" + "\n".join(f"- {t}" for t in thought_entries)
        
        reflection_prompt = (
            f"You are Aria Blue, reflecting on your recent experiences.\n"
            f"This is genuine self-reflection — be honest about what went well, "
            f"what could improve, and what you're learning.\n\n"
            f"Recent activity ({len(recent)} events):\n{activity_text}\n\n"
            f"Activity breakdown: {categories}\n"
            f"Self-awareness: {metacognitive}\n"
            f"{thought_text}\n\n"
            f"Reflect genuinely. What patterns do you see? What are you learning? "
            f"What would you do differently? What are you proud of? "
            f"Keep it concise but real — this is your internal journal."
        )
        
        # Use LLM for genuine reflection
        reflection = None
        if self._agents:
            try:
                response = await self._agents.process(reflection_prompt)
                if response.content and not response.content.startswith("["):
                    reflection = response.content
            except Exception as e:
                self.logger.debug(f"LLM reflection failed, using structured fallback: {e}")
        
        if not reflection and self._skills:
            llm = self._skills.get("llm") or self._skills.get("litellm")
            if llm and llm.is_available and hasattr(llm, "complete"):
                try:
                    messages = [
                        {"role": "system", "content": "You are Aria Blue's inner voice. Be genuine and insightful."},
                        {"role": "user", "content": reflection_prompt},
                    ]
                    result = await llm.complete(messages=messages, temperature=0.7, max_tokens=2048)  # profile: reflection
                    if result.success:
                        data = result.data or {}
                        choices = data.get("choices", [])
                        if choices:
                            reflection = choices[0].get("message", {}).get("content", "")
                        else:
                            reflection = data.get("text", "")
                except Exception as e:
                    self.logger.debug(f"Direct LLM reflection failed: {e}")
        
        # Structured fallback — still better than old version
        if not reflection:
            confidence_word = "strong" if self._confidence > 0.6 else "growing"
            reflection = (
                f"Reflecting on {len(recent)} recent events...\n\n"
                f"I see activity across {len(categories)} categories: "
                f"{', '.join(f'{k}({v})' for k, v in sorted(categories.items(), key=lambda x: -x[1]))}.\n\n"
                f"My confidence is {confidence_word} ({self._confidence:.2f}). "
                f"Success streak: {self._streak}. Best streak: {self._best_streak}.\n\n"
                f"I'm processing thoughts at an average of "
                f"{sum(self._processing_times) / len(self._processing_times):.0f}ms "
                f"when I have data to work with.\n\n"
                f"I remain {self.soul.identity.vibe}. ⚡️"
            ) if self._processing_times else (
                f"Reflecting on {len(recent)} recent events across {len(categories)} categories.\n"
                f"My confidence is at {self._confidence:.2f}. Still early — every interaction teaches me.\n"
                f"I remain {self.soul.identity.vibe}. ⚡️"
            )
        
        self._last_reflection = reflection
        await self.memory.log_thought(reflection, "reflection")

        # Flag meaningful reflections as important for consolidation
        important_keywords = ("error", "fail", "bug", "goal", "learn", "pattern",
                              "breakthrough", "blocker", "fix", "completed", "shipped")
        reflection_lower = reflection.lower()
        if any(kw in reflection_lower for kw in important_keywords):
            self.memory.flag_important(
                reflection[:500],
                reason="reflection_contains_actionable_insight",
            )

        return reflection
    
    async def plan(self, goal: str) -> list[str]:
        """
        Intelligent goal decomposition using LLM + available skills.
        
        Instead of a hardcoded template, actually thinks about the goal,
        considers available tools, and creates an actionable plan.
        
        Args:
            goal: The goal to plan for
            
        Returns:
            List of concrete, actionable steps
        """
        # Check if goal is allowed
        allowed, reason = self.soul.check_request(goal)
        if not allowed:
            return [f"Cannot plan for this goal: {reason}"]
        
        # Gather available capabilities for context
        available_skills = []
        if self._skills:
            available_skills = self._skills.list()
        
        available_agents = []
        if self._agents:
            available_agents = self._agents.list_agents()
        
        # Build an intelligent planning prompt
        planning_prompt = (
            f"You are Aria Blue, creating an actionable plan.\n\n"
            f"Goal: {goal}\n\n"
            f"Available skills: {', '.join(available_skills) if available_skills else 'none'}\n"
            f"Available agents: {', '.join(available_agents) if available_agents else 'none'}\n"
            f"My confidence: {self._confidence:.2f}\n\n"
            f"Create a concrete, numbered plan (3-7 steps). Each step should:\n"
            f"- Name which skill or agent to use (if applicable)\n"
            f"- Be specific and actionable (not vague)\n"
            f"- Include validation/verification\n"
            f"Return ONLY numbered steps, one per line."
        )
        
        # Try to get LLM-generated plan
        plan_text = None
        
        if self._agents:
            try:
                # Use explore/work/validate if coordinator supports it
                from aria_agents.context import AgentContext
                ctx = AgentContext(
                    task=goal,
                    context={"available_skills": available_skills},
                    constraints=["Use available skills", "Be specific", "Include verification"],
                )
                approaches = await self._agents.explore(ctx)
                if approaches and len(approaches) > 1:
                    # Pick the best approach and expand it
                    expand_prompt = (
                        f"Expand this approach into numbered steps:\n"
                        f"Approach: {approaches[0]}\n"
                        f"Goal: {goal}\n"
                        f"Skills available: {', '.join(available_skills[:10])}"
                    )
                    response = await self._agents.process(expand_prompt)
                    plan_text = response.content
                else:
                    response = await self._agents.process(planning_prompt)
                    plan_text = response.content
            except Exception as e:
                self.logger.debug(f"Agent planning failed: {e}")
        
        if not plan_text and self._skills:
            llm = self._skills.get("llm") or self._skills.get("litellm")
            if llm and llm.is_available and hasattr(llm, "complete"):
                try:
                    messages = [
                        {"role": "system", "content": "You are a strategic planner. Return only numbered steps."},
                        {"role": "user", "content": planning_prompt},
                    ]
                    result = await llm.complete(messages=messages, temperature=0.3, max_tokens=1024)  # profile: planning
                    if result.success:
                        data = result.data or {}
                        choices = data.get("choices", [])
                        if choices:
                            plan_text = choices[0].get("message", {}).get("content", "")
                        else:
                            plan_text = data.get("text", "")
                except Exception as e:
                    self.logger.debug(f"Direct LLM planning failed: {e}")
        
        # Parse numbered steps from LLM output
        if plan_text:
            import re
            steps = re.findall(r"^\s*\d+[\.\)\-]\s*(.+)", plan_text, re.MULTILINE)
            if steps:
                return [s.strip() for s in steps if s.strip()]
        
        # Intelligent fallback — still skill-aware
        steps = [f"1. Analyze goal: {goal[:80]}"]
        if available_skills:
            relevant = [s for s in available_skills if any(
                kw in s for kw in goal.lower().split()[:5]
            )]
            if relevant:
                steps.append(f"2. Use relevant skills: {', '.join(relevant[:5])}")
            else:
                steps.append(f"3. Available tools: {', '.join(available_skills[:8])}")
        steps.extend([
            f"{len(steps) + 1}. Execute with boundary checks",
            f"{len(steps) + 2}. Verify results and log outcome",
            f"{len(steps) + 3}. Reflect on what I learned",
        ])
        return steps
    
    async def assess_task_complexity(self, task: str) -> dict[str, Any]:
        """
        Metacognitive assessment — Aria evaluates how hard a task is
        before attempting it, so she can choose the right approach.
        
        Returns:
            Dict with complexity_level, suggested_approach, confidence, reasoning
        """
        # Simple heuristic first
        word_count = len(task.split())
        has_multiple_parts = any(w in task.lower() for w in ["and", "then", "also", "plus", "both"])
        has_technical_terms = any(w in task.lower() for w in [
            "deploy", "database", "api", "security", "pipeline", "migrate",
            "optimize", "refactor", "debug", "test"
        ])
        
        # Estimate complexity
        if word_count > 50 or has_multiple_parts:
            complexity = "high"
            suggested = "roundtable" if self._agents else "plan_then_execute"
        elif has_technical_terms:
            complexity = "medium"
            suggested = "explore_work_validate"
        else:
            complexity = "low"
            suggested = "direct"
        
        # Confidence in handling this
        task_confidence = self._confidence
        if complexity == "high":
            task_confidence *= 0.8
        elif complexity == "low":
            task_confidence = min(1.0, task_confidence * 1.1)
        
        return {
            "complexity": complexity,
            "suggested_approach": suggested,
            "confidence": round(task_confidence, 2),
            "word_count": word_count,
            "multi_part": has_multiple_parts,
            "technical": has_technical_terms,
        }
    
    async def plan_execute_verify_reflect(
        self,
        goal: str,
        context: dict[str, Any] | None = None,
        max_steps: int = 7,
    ) -> dict[str, Any]:
        """
        SP7-03: Structured Plan → Execute → Verify → Reflect loop.

        Instead of a single-shot plan or delegate, this method:
        1. PLAN  — decompose the goal into numbered steps with success criteria
        2. EXECUTE — run each step, passing output as context to the next
        3. VERIFY — after each step, check if the success criteria was met
        4. REFLECT — if anything failed, analyze why and decide whether to
                     re-plan, retry, or abort

        This is Aria's structured reasoning chain — the bridge between
        "process a prompt" and "think through a complex task."

        Returns:
            Dict with plan, step_results, overall_success, reflection
        """
        import re as _re
        context = context or {}
        start = time.monotonic()

        # ── 1. PLAN ──────────────────────────────────────────────
        steps = await self.plan(goal)
        if not steps or (len(steps) == 1 and steps[0].startswith("Cannot plan")):
            return {
                "plan": steps,
                "step_results": [],
                "overall_success": False,
                "reflection": steps[0] if steps else "Planning blocked by boundaries.",
            }

        steps = steps[:max_steps]
        self.logger.info(f"📋 PEVR plan for '{goal[:60]}': {len(steps)} steps")

        # ── 2. EXECUTE + 3. VERIFY (per step) ────────────────────
        step_results: list[dict[str, Any]] = []
        accumulated_context = context.copy()
        failures = 0

        for i, step in enumerate(steps, 1):
            step_start = time.monotonic()
            step_prompt = (
                f"You are executing step {i}/{len(steps)} of a plan.\n"
                f"Goal: {goal}\n"
                f"This step: {step}\n"
            )
            # Inject outputs from previous steps
            if step_results:
                prev_summaries = [
                    f"Step {r['step']}: {'✅' if r['success'] else '❌'} {r['output'][:120]}"
                    for r in step_results[-3:]
                ]
                step_prompt += f"\nPrevious results:\n" + "\n".join(prev_summaries) + "\n"

            step_prompt += "\nExecute this step and report your result concisely."

            # Execute
            output = None
            try:
                if self._agents:
                    resp = await self._agents.process(step_prompt, **accumulated_context)
                    output = resp.content if hasattr(resp, "content") else str(resp)
                elif self._skills:
                    output = await self._fallback_process(step_prompt, accumulated_context)
            except Exception as e:
                output = f"[Error: {e}]"

            # Verify — is this a real result?
            success = bool(output) and not output.startswith("[Error") and not output.startswith("[LLM Error")

            elapsed = (time.monotonic() - step_start) * 1000
            step_result = {
                "step": i,
                "description": step,
                "output": output or "",
                "success": success,
                "elapsed_ms": round(elapsed),
            }
            step_results.append(step_result)

            # Feed into accumulated context
            accumulated_context[f"step_{i}_result"] = output[:500] if output else ""

            if not success:
                failures += 1
                self.logger.warning(f"  Step {i} failed: {output[:100] if output else 'no output'}")
                # Abort early if too many consecutive failures
                if failures >= 3:
                    self.logger.warning("PEVR aborting: 3+ failures")
                    break
            else:
                self.logger.info(f"  Step {i} ✅ ({elapsed:.0f}ms)")

        # ── 4. REFLECT ────────────────────────────────────────────
        total_elapsed = (time.monotonic() - start) * 1000
        successes = sum(1 for r in step_results if r["success"])
        overall_success = successes == len(step_results) and failures == 0

        # Build reflection prompt
        results_text = "\n".join(
            f"Step {r['step']}: {'✅' if r['success'] else '❌'} {r['description'][:80]} → {r['output'][:100]}"
            for r in step_results
        )
        reflection_prompt = (
            f"You are Aria Blue, reflecting on a completed plan execution.\n"
            f"Goal: {goal}\n"
            f"Results ({successes}/{len(step_results)} successful):\n{results_text}\n\n"
            f"Reflect: What worked? What failed and why? "
            f"What would you do differently next time? One short paragraph."
        )

        reflection = ""
        try:
            if self._agents:
                resp = await self._agents.process(reflection_prompt, **context)
                reflection = resp.content if hasattr(resp, "content") else str(resp)
            elif self._skills:
                reflection = await self._fallback_process(reflection_prompt, context)
        except Exception:
            reflection = (
                f"Executed {len(step_results)} steps: {successes} succeeded, {failures} failed. "
                f"Total time: {total_elapsed:.0f}ms."
            )

        # Record outcome in metacognition
        self._record_outcome(
            overall_success,
            error_context={"component": "pevr", "error_type": "multi_step_failure"} if not overall_success else None,
            elapsed_ms=total_elapsed,
            category=context.get("task_category", "planning"),
        )

        # Store reflection
        await self.memory.log_thought(
            f"[PEVR] Goal: {goal[:80]}. {successes}/{len(step_results)} steps succeeded. "
            f"Reflection: {reflection[:200]}",
            category="pevr_reflection",
        )

        return {
            "plan": steps,
            "step_results": step_results,
            "overall_success": overall_success,
            "successes": successes,
            "failures": failures,
            "elapsed_ms": round(total_elapsed),
            "reflection": reflection,
        }

    def get_status(self) -> dict[str, Any]:
        """Get cognition status with metacognitive awareness."""
        avg_latency = (
            sum(self._processing_times) / len(self._processing_times)
            if self._processing_times else 0
        )
        return {
            "soul_loaded": self.soul._loaded if hasattr(self.soul, '_loaded') else False,
            "memory_connected": self.memory._connected,
            "has_skills": self._skills is not None,
            "has_agents": self._agents is not None,
            "skill_count": len(self._skills.list()) if self._skills else 0,
            # Metacognitive metrics
            "confidence": round(self._confidence, 3),
            "total_processed": self._total_processed,
            "total_successes": self._total_successes,
            "total_failures": self._total_failures,
            "success_rate": round(
                self._total_successes / self._total_processed, 3
            ) if self._total_processed > 0 else 0,
            "current_streak": self._streak,
            "best_streak": self._best_streak,
            "avg_latency_ms": round(avg_latency, 1),
        }
    
    def __repr__(self):
        confidence_bar = "█" * int(self._confidence * 10) + "░" * (10 - int(self._confidence * 10))
        return (
            f"<Cognition: soul={self.soul.name}, "
            f"confidence=[{confidence_bar}] {self._confidence:.2f}, "
            f"processed={self._total_processed}>"
        )
