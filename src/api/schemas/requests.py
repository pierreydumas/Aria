from __future__ import annotations

from pydantic import BaseModel, Field, field_validator


# ── activities.py ──────────────────────────────────────────────────────────

class CreateActivity(BaseModel):
    """Request body for POST /activities."""
    action: str = ""
    skill: str | None = None
    details: dict = Field(default_factory=dict)
    success: bool = True
    error_message: str | None = None

    @field_validator("skill", mode="before")
    @classmethod
    def coerce_skill(cls, v: object) -> str | None:
        """Accept null/None without raising."""
        if v is None:
            return None
        return str(v)

    @field_validator("details", mode="before")
    @classmethod
    def coerce_details(cls, v: object) -> dict:
        """Accept a plain string and wrap it so agents don't get a 422."""
        if isinstance(v, str):
            return {"message": v}
        return v if isinstance(v, dict) else {"value": str(v)}


# ── goals.py ───────────────────────────────────────────────────────────────

class CreateGoal(BaseModel):
    """Request body for POST /goals."""
    goal_id: str | None = None
    title: str = ""
    description: str = ""
    status: str = "pending"
    progress: int = 0
    priority: int = 2
    due_date: str | None = None
    target_date: str | None = None
    sprint: str = "backlog"
    board_column: str = "backlog"
    position: int = 0
    assigned_to: str | None = None
    tags: list[str] = Field(default_factory=list)


class UpdateGoal(BaseModel):
    """Request body for PUT /goals/{goal_id}."""
    title: str | None = None
    description: str | None = None
    status: str | None = None
    progress: int | None = None
    priority: int | None = None
    sprint: str | None = None
    board_column: str | None = None
    position: int | None = None
    assigned_to: str | None = None
    tags: list[str] | None = None
    due_date: str | None = None


class MoveGoal(BaseModel):
    """Request body for PUT /goals/{goal_id}/move."""
    board_column: str
    position: int = 0


class CreateHourlyGoal(BaseModel):
    """Request body for POST /goals/hourly."""
    hour_slot: str | None = None
    goal_type: str | None = None
    description: str = ""
    status: str = "pending"


class UpdateHourlyGoal(BaseModel):
    """Request body for PUT /goals/hourly/{goal_id}."""
    status: str | None = None


# ── memories.py ────────────────────────────────────────────────────────────

class CreateMemory(BaseModel):
    """Request body for POST /memories."""
    key: str
    value: str = ""
    category: str = "general"


class CreateSemanticMemory(BaseModel):
    """Request body for POST /memories/semantic."""
    content: str
    category: str = "general"
    importance: float = 0.5
    source: str = "api"
    summary: str | None = None
    metadata: dict = Field(default_factory=dict)


class SearchByVector(BaseModel):
    """Request body for POST /memories/semantic/search-by-vector."""
    embedding: list[float]
    category: str | None = None
    source: str | None = None
    limit: int = 7
    min_importance: float = 0.0


class SummarizeSession(BaseModel):
    """Request body for POST /memories/summarize."""
    hours_back: int = 24


# ── operations.py ──────────────────────────────────────────────────────────

class RateLimitCheck(BaseModel):
    """Request body for POST /operations/rate-limits/check."""
    skill: str
    max_actions: int = 100
    window_seconds: int = 3600


class RateLimitIncrement(BaseModel):
    """Request body for POST /operations/rate-limits/increment."""
    skill: str
    action_type: str = "action"


class CreateKeyRotation(BaseModel):
    """Request body for POST /operations/key-rotations."""
    service: str | None = None
    reason: str | None = None
    rotated_by: str = "system"
    metadata: dict = Field(default_factory=dict)


class CreateHeartbeat(BaseModel):
    """Request body for POST /operations/heartbeats."""
    beat_number: int = 0
    job_name: str | None = None
    status: str = "healthy"
    details: dict | str | list | None = Field(default_factory=dict)
    executed_at: str | None = None
    duration_ms: int | None = None


class CreatePerformanceReview(BaseModel):
    """Request body for POST /operations/performance-reviews."""
    review_period: str | None = None
    successes: list | None = None
    failures: list | None = None
    improvements: list | None = None


class CreateTask(BaseModel):
    """Request body for POST /operations/tasks."""
    task_id: str | None = None
    task_type: str | None = None
    description: str = ""
    agent_type: str | None = None
    priority: str = "medium"
    status: str = "pending"


class UpdateTask(BaseModel):
    """Request body for PUT /operations/tasks/{task_id}."""
    status: str | None = None
    result: str | None = None


class PurgeTasks(BaseModel):
    """Request body for POST /operations/tasks/purge."""
    task_ids: list[str] = Field(default_factory=list)
    statuses: list[str] = Field(default_factory=list)
    older_than_days: int | None = None
    include_all: bool = False


# ── proposals.py ───────────────────────────────────────────────────────────

class CreateProposal(BaseModel):
    """Request body for POST /proposals."""
    title: str
    description: str
    category: str | None = None
    risk_level: str = "low"
    file_path: str | None = None
    current_code: str | None = None
    proposed_code: str | None = None
    rationale: str | None = None


class ReviewProposal(BaseModel):
    """Request body for PUT /proposals/{proposal_id}/review."""
    status: str
    reviewed_by: str = "najia"


# ── security.py ────────────────────────────────────────────────────────────

class CreateSecurityEvent(BaseModel):
    """Request body for POST /security/events."""
    threat_level: str = "LOW"
    threat_type: str = "unknown"
    threat_patterns: list = Field(default_factory=list)
    input_preview: str | None = None
    source: str = "api"
    user_id: str | None = None
    blocked: bool = False
    details: dict = Field(default_factory=dict)


# ── sessions.py ────────────────────────────────────────────────────────────

class CreateSession(BaseModel):
    """Request body for POST /sessions."""
    status: str = "active"
    started_at: str | None = None
    ended_at: str | None = None
    metadata: dict = Field(default_factory=dict)
    external_session_id: str | None = None
    agent_id: str = "aria"
    session_type: str = "interactive"
    messages_count: int = 0
    tokens_used: int = 0
    cost_usd: float = 0


class UpdateSession(BaseModel):
    """Request body for PUT /sessions/{session_id}."""
    status: str | None = None
    messages_count: int | None = None
    tokens_used: int | None = None
    cost_usd: float | None = None


# ── sources.py ─────────────────────────────────────────────────────────────

class CreateWebsiteSource(BaseModel):
    """Request body for POST /sources."""
    url: str
    name: str
    category: str = "general"
    rating: str = "preferred"
    reason: str | None = None
    alternative: str | None = None
    last_used: str | None = None
    metadata: dict = Field(default_factory=dict)


class UpdateWebsiteSource(BaseModel):
    """Request body for PATCH /sources/{source_id}."""
    url: str | None = None
    name: str | None = None
    category: str | None = None
    rating: str | None = None
    reason: str | None = None
    alternative: str | None = None
    last_used: str | None = None
    metadata: dict | None = None


# ── social.py ──────────────────────────────────────────────────────────────

class CreateSocialPost(BaseModel):
    """Request body for POST /social/posts."""
    platform: str = "moltbook"
    content: str | None = None
    metadata: dict = Field(default_factory=dict)
    post_id: str | None = None
    visibility: str = "public"
    reply_to: str | None = None
    url: str | None = None


class SocialCleanup(BaseModel):
    """Request body for POST /social/cleanup."""
    patterns: list[str] = Field(default_factory=list)
    platform: str | None = None
    dry_run: bool = False


class SocialDedupe(BaseModel):
    """Request body for POST /social/dedupe."""
    dry_run: bool = True
    platform: str | None = None


class ImportMoltbook(BaseModel):
    """Request body for POST /social/import/moltbook."""
    include_comments: bool = True
    cleanup_test: bool = True
    dry_run: bool = False
    max_items: int = 200
    api_url: str | None = None
    api_key: str | None = None


# ── working_memory.py ──────────────────────────────────────────────────────

class CreateWorkingMemory(BaseModel):
    """Request body for POST /working-memory."""
    key: str
    value: str
    category: str = "general"
    importance: float = 0.5
    ttl_hours: int | None = None
    source: str | None = None


class UpdateWorkingMemory(BaseModel):
    """Request body for PUT /working-memory/{key}."""
    value: str | None = None
    importance: float | None = None


# ── thoughts.py ────────────────────────────────────────────────────────────

class CreateThought(BaseModel):
    """Request body for POST /thoughts."""
    content: str = ""
    category: str = "general"
    metadata: dict = Field(default_factory=dict)


# ── skills.py ──────────────────────────────────────────────────────────────

class CreateSkillInvocation(BaseModel):
    """Request body for POST /skills/invocations."""
    skill_name: str = "unknown"
    tool_name: str = "unknown"
    duration_ms: int | None = None
    success: bool = True
    error_type: str | None = None
    tokens_used: int | None = None
    model_used: str | None = None


# ── model_usage.py ─────────────────────────────────────────────────────────

class CreateModelUsage(BaseModel):
    """Request body for POST /model-usage."""
    model: str | None = None
    provider: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0
    latency_ms: int | None = None
    success: bool = True
    error_message: str | None = None
    session_id: str | None = None


# ── lessons.py ─────────────────────────────────────────────────────────────

class CreateLesson(BaseModel):
    """Request body for POST /lessons."""
    error_pattern: str
    error_type: str
    resolution: str | None = None
    skill_name: str | None = None
    context: dict = Field(default_factory=dict)
    resolution_code: str | None = None
    effectiveness: float = 1.0


# ── analysis.py ────────────────────────────────────────────────────────────

class SentimentFeedback(BaseModel):
    """Request body for POST /analysis/sentiment/feedback."""
    event_id: str
    confirmed: bool = True


# ── S-29: Update schemas ───────────────────────────────────────────────────

class UpdateActivity(BaseModel):
    """Request body for PATCH /activities/{activity_id}."""
    action: str | None = None
    content: str | None = None
    metadata_json: dict | None = None


class UpdateThought(BaseModel):
    """Request body for PATCH /thoughts/{thought_id}."""
    content: str | None = None
    category: str | None = None
    tags: list[str] | None = None


class UpdateSocialPost(BaseModel):
    """Request body for PATCH /social/{post_id}."""
    platform: str | None = None
    content: str | None = None
    posted: bool | None = None


class UpdateLesson(BaseModel):
    """Request body for PATCH /lessons/{lesson_id}."""
    lesson: str | None = None
    resolution: str | None = None
    skill_name: str | None = None


class UpdateMemory(BaseModel):
    """Request body for PATCH /memories/{key}."""
    value: str | None = None
    category: str | None = None
