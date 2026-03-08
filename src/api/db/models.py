"""
SQLAlchemy 2.0 ORM models for Aria Brain (aria_warehouse).

Canonical source of truth for all database tables.
Driver: psycopg 3 via SQLAlchemy async.

Schemas:
  - aria_data:   Aria's knowledge, memories, activities, execution history
  - aria_engine: Engine infrastructure — sessions, agents, cron, models
  - litellm:     LiteLLM proxy tables (managed by LiteLLM itself)
"""

import uuid as uuid_mod
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Integer, Numeric, String, Text, Index, UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy import inspect as sa_inspect

try:
    from pgvector.sqlalchemy import Vector
    HAS_PGVECTOR = True
except ImportError:
    HAS_PGVECTOR = False
    Vector = None  # type: ignore


# ── Base ─────────────────────────────────────────────────────────────────────

class Base(DeclarativeBase):
    """Shared base for all Aria ORM models."""

    def to_dict(self) -> dict:
        """Serialize model instance to a JSON-friendly dict.

        Uses DB column names as keys (e.g. ``metadata`` not ``metadata_json``).
        Skips large vector/embedding columns to keep responses lean.
        """
        result: dict[str, Any] = {}
        mapper = sa_inspect(type(self))
        for attr in mapper.column_attrs:
            col_name = attr.columns[0].name          # DB column name
            col_type = str(attr.columns[0].type)
            # Skip embedding vectors — too large for API responses
            if "VECTOR" in col_type.upper():
                continue
            val = getattr(self, attr.key)             # Python attribute value
            if isinstance(val, datetime):
                result[col_name] = val.isoformat()
            elif isinstance(val, uuid_mod.UUID):
                result[col_name] = str(val)
            elif isinstance(val, Decimal):
                result[col_name] = float(val)
            else:
                result[col_name] = val
        return result


# ── Core domain ──────────────────────────────────────────────────────────────

class Memory(Base):
    __tablename__ = "memories"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    key: Mapped[str] = mapped_column(String(255), unique=True, nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    category: Mapped[str] = mapped_column(String(100), server_default=text("'general'"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_memories_key", Memory.key)
Index("idx_memories_category", Memory.category)
Index("idx_memories_updated", Memory.updated_at.desc())
Index("idx_memories_created", Memory.created_at.desc())
Index("idx_memories_value_gin", Memory.value, postgresql_using="gin")


class Thought(Base):
    __tablename__ = "thoughts"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(100), server_default=text("'general'"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_thoughts_category", Thought.category)
Index("idx_thoughts_created", Thought.created_at.desc())
Index("idx_thoughts_content_trgm", Thought.content, postgresql_using="gin", postgresql_ops={"content": "gin_trgm_ops"})


class Goal(Base):
    __tablename__ = "goals"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    goal_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(50), server_default=text("'pending'"))
    priority: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    progress: Mapped[float] = mapped_column(Numeric(5, 2), server_default=text("0"))
    due_date: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    # Sprint Board fields (S3-01)
    sprint: Mapped[str | None] = mapped_column(String(100), server_default=text("'backlog'"))
    board_column: Mapped[str | None] = mapped_column(String(50), server_default=text("'backlog'"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    assigned_to: Mapped[str | None] = mapped_column(String(100))
    tags: Mapped[dict | None] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_goals_status", Goal.status)
Index("idx_goals_priority", Goal.priority.desc())
Index("idx_goals_created", Goal.created_at.desc())
Index("idx_goals_status_priority_created", Goal.status, Goal.priority.desc(), Goal.created_at.desc())
Index("idx_goals_sprint", Goal.sprint)
Index("idx_goals_board_column", Goal.board_column)
Index("idx_goals_sprint_column_position", Goal.sprint, Goal.board_column, Goal.position)


class ActivityLog(Base):
    __tablename__ = "activity_log"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    action: Mapped[str] = mapped_column(String(100), nullable=False)
    skill: Mapped[str | None] = mapped_column(String(100))
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    success: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_activity_action", ActivityLog.action)
Index("idx_activity_skill", ActivityLog.skill)
Index("idx_activity_created", ActivityLog.created_at.desc())
Index("idx_activity_action_created", ActivityLog.action, ActivityLog.created_at.desc())
Index("idx_activity_skill_created", ActivityLog.skill, ActivityLog.created_at.desc())
Index("idx_activity_details_gin", ActivityLog.details, postgresql_using="gin")


# ── Social / Community ───────────────────────────────────────────────────────

class SocialPost(Base):
    __tablename__ = "social_posts"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    platform: Mapped[str] = mapped_column(String(50), server_default=text("'moltbook'"))
    post_id: Mapped[str | None] = mapped_column(String(100), unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    visibility: Mapped[str] = mapped_column(String(50), server_default=text("'public'"))
    reply_to: Mapped[str | None] = mapped_column(String(100), ForeignKey("aria_data.social_posts.post_id", ondelete="SET NULL"))
    url: Mapped[str | None] = mapped_column(Text)
    posted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

    parent_post: Mapped["SocialPost | None"] = relationship("SocialPost", remote_side="SocialPost.post_id", lazy="selectin")


Index("idx_posts_platform", SocialPost.platform)
Index("idx_posts_posted", SocialPost.posted_at.desc())
Index("idx_posts_post_id", SocialPost.post_id)


# ── Scheduling / Operations ──────────────────────────────────────────────────

class HourlyGoal(Base):
    __tablename__ = "hourly_goals"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hour_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    goal_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_hourly_status", HourlyGoal.status)
Index("idx_hourly_hour_slot", HourlyGoal.hour_slot)
Index("idx_hourly_created", HourlyGoal.created_at.desc())


# ── Knowledge Graph ──────────────────────────────────────────────────────────

class KnowledgeEntity(Base):
    __tablename__ = "knowledge_entities"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    outgoing_relations: Mapped[list["KnowledgeRelation"]] = relationship("KnowledgeRelation", foreign_keys="KnowledgeRelation.from_entity", back_populates="source_entity", cascade="all, delete-orphan")
    incoming_relations: Mapped[list["KnowledgeRelation"]] = relationship("KnowledgeRelation", foreign_keys="KnowledgeRelation.to_entity", back_populates="target_entity", cascade="all, delete-orphan")


Index("idx_kg_entity_name", KnowledgeEntity.name)
Index("idx_kg_entity_type", KnowledgeEntity.type)
Index("idx_kg_properties_gin", KnowledgeEntity.properties, postgresql_using="gin")


class KnowledgeRelation(Base):
    __tablename__ = "knowledge_relations"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    from_entity: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.knowledge_entities.id", ondelete="CASCADE"), nullable=False)
    to_entity: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.knowledge_entities.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(Text, nullable=False)
    properties: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    source_entity: Mapped["KnowledgeEntity"] = relationship("KnowledgeEntity", foreign_keys=[from_entity], lazy="selectin")
    target_entity: Mapped["KnowledgeEntity"] = relationship("KnowledgeEntity", foreign_keys=[to_entity], lazy="selectin")


Index("idx_kg_relation_from", KnowledgeRelation.from_entity)
Index("idx_kg_relation_to", KnowledgeRelation.to_entity)
Index("idx_kg_relation_type", KnowledgeRelation.relation_type)


# ── Skill Graph (separate from organic knowledge) ────────────────────────────
# Dedicated tables so skill-selection logic never collides with Aria's social /
# research / manual knowledge.  Regenerated idempotently from skill.json files.

class SkillGraphEntity(Base):
    __tablename__ = "skill_graph_entities"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    name: Mapped[str] = mapped_column(String(500), nullable=False)
    type: Mapped[str] = mapped_column(String(100), nullable=False)  # skill, tool, focus_mode, category
    properties: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("name", "type", name="uq_sg_entity_name_type"),
        {"schema": "aria_data"},
    )

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "name": self.name,
            "type": self.type,
            "properties": self.properties or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


class SkillGraphRelation(Base):
    __tablename__ = "skill_graph_relations"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    from_entity: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.skill_graph_entities.id", ondelete="CASCADE"), nullable=False)
    to_entity: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.skill_graph_entities.id", ondelete="CASCADE"), nullable=False)
    relation_type: Mapped[str] = mapped_column(String(100), nullable=False)  # provides, belongs_to, affinity, depends_on
    properties: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    def to_dict(self) -> dict:
        return {
            "id": str(self.id),
            "from_entity": str(self.from_entity),
            "to_entity": str(self.to_entity),
            "relation_type": self.relation_type,
            "properties": self.properties or {},
            "created_at": self.created_at.isoformat() if self.created_at else None,
        }


Index("idx_sg_entity_name", SkillGraphEntity.name)
Index("idx_sg_entity_type", SkillGraphEntity.type)
Index("idx_sg_relation_from", SkillGraphRelation.from_entity)
Index("idx_sg_relation_to", SkillGraphRelation.to_entity)
Index("idx_sg_relation_type", SkillGraphRelation.relation_type)


# S4-05: Knowledge Query Log
class KnowledgeQueryLog(Base):
    __tablename__ = "knowledge_query_log"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    query_type: Mapped[str] = mapped_column(String(50), nullable=False)  # traverse, search, skill_for_task
    params: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    result_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    tokens_saved: Mapped[int | None] = mapped_column(Integer)
    used_result: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    source: Mapped[str | None] = mapped_column(String(100))  # api, graphql, cognitive_loop
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_kql_query_type", KnowledgeQueryLog.query_type)
Index("idx_kql_created", KnowledgeQueryLog.created_at.desc())
Index("idx_kql_source", KnowledgeQueryLog.source)


# ── Performance / Review ─────────────────────────────────────────────────────

class PerformanceLog(Base):
    __tablename__ = "performance_log"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    review_period: Mapped[str] = mapped_column(String(20), nullable=False)
    successes: Mapped[str | None] = mapped_column(Text)
    failures: Mapped[str | None] = mapped_column(Text)
    improvements: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_perflog_created", PerformanceLog.created_at.desc())


class PendingComplexTask(Base):
    __tablename__ = "pending_complex_tasks"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    task_type: Mapped[str] = mapped_column(String(50), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    agent_type: Mapped[str] = mapped_column(String(50), nullable=False)
    priority: Mapped[str] = mapped_column(String(20), server_default=text("'medium'"))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'pending'"))
    result: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


Index("idx_pct_status", PendingComplexTask.status)
Index("idx_pct_task_id", PendingComplexTask.task_id)
Index("idx_pct_created", PendingComplexTask.created_at.desc())


# ── Heartbeat ────────────────────────────────────────────────────────────────

class HeartbeatLog(Base):
    __tablename__ = "heartbeat_log"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    beat_number: Mapped[int] = mapped_column(Integer, server_default=text("0"), nullable=False)
    job_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(50), server_default=text("'healthy'"))
    details: Mapped[str | None] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), nullable=True)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_heartbeat_created", HeartbeatLog.created_at.desc())


# ── Scheduling ─────────────────────────────────────────────────────────────

class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(50), server_default=text("'aria'"))
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    schedule_kind: Mapped[str] = mapped_column(String(20), server_default=text("'cron'"))
    schedule_expr: Mapped[str] = mapped_column(String(50), nullable=False)
    session_target: Mapped[str | None] = mapped_column(String(50))
    wake_mode: Mapped[str | None] = mapped_column(String(50))
    payload_kind: Mapped[str | None] = mapped_column(String(50))
    payload_text: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    run_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    fail_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    created_at_ms: Mapped[int | None] = mapped_column(Integer)
    updated_at_ms: Mapped[int | None] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    @property
    def created_at(self) -> datetime | None:
        if self.created_at_ms is None:
            return None
        return datetime.fromtimestamp(self.created_at_ms / 1000, tz=timezone.utc)

    @property
    def updated_at(self) -> datetime | None:
        if self.updated_at_ms is None:
            return None
        return datetime.fromtimestamp(self.updated_at_ms / 1000, tz=timezone.utc)


Index("idx_jobs_name", ScheduledJob.name)
Index("idx_jobs_enabled", ScheduledJob.enabled)
Index("idx_jobs_next_run", ScheduledJob.next_run_at)


# ── Security ─────────────────────────────────────────────────────────────────

class SecurityEvent(Base):
    __tablename__ = "security_events"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    threat_level: Mapped[str] = mapped_column(String(20), nullable=False)
    threat_type: Mapped[str] = mapped_column(String(100), nullable=False)
    threat_patterns: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    input_preview: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(100))
    user_id: Mapped[str | None] = mapped_column(String(100))
    blocked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    details: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_security_threat_level", SecurityEvent.threat_level)
Index("idx_security_threat_type", SecurityEvent.threat_type)
Index("idx_security_created", SecurityEvent.created_at.desc())
Index("idx_security_blocked", SecurityEvent.blocked)
Index("idx_security_threat_created", SecurityEvent.threat_level, SecurityEvent.created_at.desc())


# ── Schedule Tick ────────────────────────────────────────────────────────────

class ScheduleTick(Base):
    __tablename__ = "schedule_tick"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    last_tick: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    tick_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    heartbeat_interval: Mapped[int] = mapped_column(Integer, server_default=text("3600"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    jobs_total: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    jobs_successful: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    jobs_failed: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_job_name: Mapped[str | None] = mapped_column(String(255))
    last_job_status: Mapped[str | None] = mapped_column(String(50))
    next_job_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


# ── Operations: Sessions / Usage ─────────────────────────────────────────────

class AgentSession(Base):
    __tablename__ = "agent_sessions"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    session_type: Mapped[str] = mapped_column(String(50), server_default=text("'interactive'"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    messages_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    tokens_used: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), server_default=text("0"))
    status: Mapped[str] = mapped_column(String(50), server_default=text("'active'"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))

    usage_records: Mapped[list["ModelUsage"]] = relationship("ModelUsage", back_populates="session", lazy="select")


Index("idx_agent_sessions_agent", AgentSession.agent_id)
Index("idx_agent_sessions_started", AgentSession.started_at.desc())
Index("idx_agent_sessions_status", AgentSession.status)
Index("idx_agent_sessions_type", AgentSession.session_type)
Index("idx_agent_sessions_agent_started", AgentSession.agent_id, AgentSession.started_at.desc())
Index("idx_agent_sessions_metadata_gin", AgentSession.metadata_json, postgresql_using="gin")
Index("idx_agent_sessions_aria_sid", text("(metadata ->> 'aria_session_id')"))
Index("idx_agent_sessions_external_sid", text("(metadata ->> 'external_session_id')"))


class SessionMessage(Base):
    __tablename__ = "session_messages"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.agent_sessions.id", ondelete="SET NULL"))
    external_session_id: Mapped[str | None] = mapped_column(String(120))
    agent_id: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    source_channel: Mapped[str | None] = mapped_column(String(50))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("external_session_id", "role", "content_hash", name="uq_session_message_ext_role_hash"),
        {"schema": "aria_data"},
    )


Index("idx_session_messages_session", SessionMessage.session_id)
Index("idx_session_messages_external", SessionMessage.external_session_id)
Index("idx_session_messages_role", SessionMessage.role)
Index("idx_session_messages_created", SessionMessage.created_at.desc())
Index("idx_session_messages_session_created", SessionMessage.session_id, SessionMessage.created_at.desc())
Index("idx_session_messages_ext_created", SessionMessage.external_session_id, SessionMessage.created_at.desc())


class SentimentEvent(Base):
    __tablename__ = "sentiment_events"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    message_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.session_messages.id", ondelete="CASCADE"), nullable=False)
    session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.agent_sessions.id", ondelete="SET NULL"))
    external_session_id: Mapped[str | None] = mapped_column(String(120))
    speaker: Mapped[str | None] = mapped_column(String(20))       # user | assistant | system
    agent_id: Mapped[str | None] = mapped_column(String(100))     # e.g. "main", "coder", …
    sentiment_label: Mapped[str] = mapped_column(String(20), nullable=False)
    primary_emotion: Mapped[str | None] = mapped_column(String(50))
    valence: Mapped[float] = mapped_column(Float, nullable=False)
    arousal: Mapped[float] = mapped_column(Float, nullable=False)
    dominance: Mapped[float] = mapped_column(Float, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    importance: Mapped[float] = mapped_column(Float, server_default=text("0.3"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("message_id", name="uq_sentiment_event_message"),
        {"schema": "aria_data"},
    )


Index("idx_sentiment_events_message", SentimentEvent.message_id)
Index("idx_sentiment_events_session", SentimentEvent.session_id)
Index("idx_sentiment_events_external", SentimentEvent.external_session_id)
Index("idx_sentiment_events_label", SentimentEvent.sentiment_label)
Index("idx_sentiment_events_created", SentimentEvent.created_at.desc())
Index("idx_sentiment_events_session_created", SentimentEvent.session_id, SentimentEvent.created_at.desc())
Index("idx_sentiment_events_label_created", SentimentEvent.sentiment_label, SentimentEvent.created_at.desc())
Index("idx_sentiment_events_speaker", SentimentEvent.speaker)
Index("idx_sentiment_events_agent_id", SentimentEvent.agent_id)


class ModelUsage(Base):
    __tablename__ = "model_usage"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    model: Mapped[str] = mapped_column(String(100), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(50))
    input_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    output_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    cost_usd: Mapped[float] = mapped_column(Numeric(10, 6), server_default=text("0"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    error_message: Mapped[str | None] = mapped_column(Text)
    session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_data.agent_sessions.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    session: Mapped["AgentSession | None"] = relationship("AgentSession", lazy="selectin")


Index("idx_model_usage_model", ModelUsage.model)
Index("idx_model_usage_created", ModelUsage.created_at.desc())
Index("idx_model_usage_session", ModelUsage.session_id)
Index("idx_model_usage_provider", ModelUsage.provider)
Index("idx_model_usage_success", ModelUsage.success)
Index("idx_model_usage_model_created", ModelUsage.model, ModelUsage.created_at.desc())
Index("idx_model_usage_model_provider", ModelUsage.model, ModelUsage.provider)


class RateLimit(Base):
    __tablename__ = "rate_limits"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    skill: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    last_action: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    action_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    last_post: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_rate_limits_skill", RateLimit.skill)


class ApiKeyRotation(Base):
    __tablename__ = "api_key_rotations"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    service: Mapped[str] = mapped_column(String(100), nullable=False)
    rotated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    reason: Mapped[str | None] = mapped_column(Text)
    rotated_by: Mapped[str] = mapped_column(String(100), server_default=text("'system'"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))


Index("idx_akr_service", ApiKeyRotation.service)
Index("idx_akr_rotated", ApiKeyRotation.rotated_at.desc())


# ── Agent Performance (pheromone scoring) ─────────────────────────────────

class AgentPerformance(Base):
    __tablename__ = "agent_performance"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    task_type: Mapped[str] = mapped_column(String(100), nullable=False)
    success: Mapped[bool] = mapped_column(Boolean, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    token_cost: Mapped[float | None] = mapped_column(Numeric(10, 6))
    pheromone_score: Mapped[float] = mapped_column(Numeric(5, 3), server_default=text("0.500"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_agent_perf_agent", AgentPerformance.agent_id)
Index("idx_agent_perf_task", AgentPerformance.task_type)
Index("idx_agent_perf_created", AgentPerformance.created_at.desc())


# ── Working Memory ───────────────────────────────────────────────────────────

class WorkingMemory(Base):
    __tablename__ = "working_memory"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    key: Mapped[str] = mapped_column(String(200), nullable=False)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    importance: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    ttl_hours: Mapped[int | None] = mapped_column(Integer, nullable=True)
    source: Mapped[str | None] = mapped_column(String(100))
    checkpoint_id: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


Index("idx_wm_category", WorkingMemory.category)
Index("idx_wm_key", WorkingMemory.key)
Index("idx_wm_importance", WorkingMemory.importance.desc())
Index("idx_wm_checkpoint", WorkingMemory.checkpoint_id)
Index("idx_wm_importance_created", WorkingMemory.importance.desc(), WorkingMemory.created_at.desc())
Index("uq_wm_category_key", WorkingMemory.category, WorkingMemory.key, unique=True)


# ── Skill Registry ───────────────────────────────────────────────────────────

class SkillStatusRecord(Base):
    __tablename__ = "skill_status"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    canonical_name: Mapped[str] = mapped_column(String(100), nullable=False)
    layer: Mapped[str | None] = mapped_column(String(20), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'unavailable'"))
    last_health_check: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_execution: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    use_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    error_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    metadata_json: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_skill_status_name", SkillStatusRecord.skill_name)
Index("idx_skill_status_status", SkillStatusRecord.status)
Index("idx_skill_status_layer", SkillStatusRecord.layer)


# ── Semantic Memory (S5-01: pgvector) ────────────────────────────────────────

class SemanticMemory(Base):
    __tablename__ = "semantic_memories"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str] = mapped_column(String(50), server_default=text("'general'"))
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=False) if HAS_PGVECTOR else mapped_column(JSONB, nullable=False)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    importance: Mapped[float] = mapped_column(Float, server_default=text("0.5"))
    source: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    accessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    access_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))


Index("idx_semantic_category", SemanticMemory.category)
Index("idx_semantic_importance", SemanticMemory.importance)
Index("idx_semantic_created", SemanticMemory.created_at.desc())
Index("idx_semantic_source", SemanticMemory.source)
Index("idx_semantic_cat_importance", SemanticMemory.category, SemanticMemory.importance.desc())


# ── Lessons Learned (S5-02) ──────────────────────────────────────────────────

class LessonLearned(Base):
    __tablename__ = "lessons_learned"

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    error_pattern: Mapped[str] = mapped_column(String(200), nullable=False)
    error_type: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_name: Mapped[str | None] = mapped_column(String(100))
    context: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    resolution: Mapped[str] = mapped_column(Text, nullable=False)
    resolution_code: Mapped[str | None] = mapped_column(Text)
    occurrences: Mapped[int] = mapped_column(Integer, server_default=text("1"))
    last_occurred: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    effectiveness: Mapped[float] = mapped_column(Float, server_default=text("1.0"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    __table_args__ = (
        UniqueConstraint("error_pattern", name="uq_lesson_pattern"),
        {"schema": "aria_data"},
    )


Index("idx_lesson_pattern", LessonLearned.error_pattern)
Index("idx_lesson_type", LessonLearned.error_type)
Index("idx_lesson_skill", LessonLearned.skill_name)


# ── Improvement Proposals (S5-06) ────────────────────────────────────────────

class ImprovementProposal(Base):
    __tablename__ = "improvement_proposals"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))
    risk_level: Mapped[str] = mapped_column(String(20), server_default=text("'low'"))
    file_path: Mapped[str | None] = mapped_column(String(500))
    current_code: Mapped[str | None] = mapped_column(Text)
    proposed_code: Mapped[str | None] = mapped_column(Text)
    rationale: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), server_default=text("'proposed'"))
    reviewed_by: Mapped[str | None] = mapped_column(String(100))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_proposal_status", ImprovementProposal.status)
Index("idx_proposal_risk", ImprovementProposal.risk_level)
Index("idx_proposal_category", ImprovementProposal.category)


# ── Skill Invocations (S5-07) ────────────────────────────────────────────────

class SkillInvocation(Base):
    __tablename__ = "skill_invocations"
    __table_args__ = {"schema": "aria_data"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    tool_name: Mapped[str] = mapped_column(String(100), nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    success: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    error_type: Mapped[str | None] = mapped_column(String(100))
    tokens_used: Mapped[int | None] = mapped_column(Integer)
    model_used: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_invocation_skill", SkillInvocation.skill_name)
Index("idx_invocation_created", SkillInvocation.created_at.desc())
Index("idx_invocation_success", SkillInvocation.success)


# ── Aria Engine (v2.0) ───────────────────────────────────────────────────────
# Standalone engine tables — native runtime state


class EngineChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False, server_default=text("'aria'"))
    session_type: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'interactive'"))
    title: Mapped[str | None] = mapped_column(String(500))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    temperature: Mapped[float] = mapped_column(Float, server_default=text("0.7"))
    max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("4096"))
    context_window: Mapped[int] = mapped_column(Integer, server_default=text("50"))
    status: Mapped[str] = mapped_column(String(20), nullable=False, server_default=text("'active'"))
    message_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_cost: Mapped[float] = mapped_column(Numeric(10, 6), server_default=text("0"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    messages: Mapped[list["EngineChatMessage"]] = relationship("EngineChatMessage", back_populates="session", cascade="all, delete-orphan")


Index("idx_ecs_agent", EngineChatSession.agent_id)
Index("idx_ecs_status", EngineChatSession.status)
Index("idx_ecs_created", EngineChatSession.created_at)
# Performance indexes for session listing (S6-perf)
Index("idx_ecs_updated_desc", EngineChatSession.updated_at.desc())
Index("idx_ecs_session_type", EngineChatSession.session_type)
Index("idx_ecs_status_updated", EngineChatSession.status, EngineChatSession.updated_at.desc())


class EngineChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    session_id: Mapped[Any] = mapped_column(UUID(as_uuid=True), ForeignKey("aria_engine.chat_sessions.id", ondelete="CASCADE"), nullable=False)
    agent_id: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    tool_results: Mapped[dict | None] = mapped_column(JSONB)
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(200))
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=True) if HAS_PGVECTOR else mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    session: Mapped["EngineChatSession"] = relationship("EngineChatSession", back_populates="messages")


Index("idx_ecm_session", EngineChatMessage.session_id)
Index("idx_ecm_role", EngineChatMessage.role)
Index("idx_ecm_created", EngineChatMessage.created_at)
Index("idx_ecm_client_message_id", EngineChatMessage.client_message_id)
# Composite index for message retrieval by session (S6-perf)
Index("idx_ecm_session_created", EngineChatMessage.session_id, EngineChatMessage.created_at)


class EngineChatSessionArchive(Base):
    """Archived copy of engine chat sessions (internal, non-public)."""

    __tablename__ = "chat_sessions_archive"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    session_type: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str | None] = mapped_column(String(500))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str | None] = mapped_column(String(200))
    temperature: Mapped[float] = mapped_column(Float, server_default=text("0.7"))
    max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("4096"))
    context_window: Mapped[int] = mapped_column(Integer, server_default=text("50"))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    message_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_tokens: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    total_cost: Mapped[float] = mapped_column(Numeric(10, 6), server_default=text("0"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    messages: Mapped[list["EngineChatMessageArchive"]] = relationship(
        "EngineChatMessageArchive",
        back_populates="session",
        cascade="all, delete-orphan",
    )


Index("idx_ecsa_archived", EngineChatSessionArchive.archived_at.desc())
Index("idx_ecsa_session_type", EngineChatSessionArchive.session_type)
Index("idx_ecsa_status", EngineChatSessionArchive.status)
Index("idx_ecsa_updated", EngineChatSessionArchive.updated_at.desc())


class EngineChatMessageArchive(Base):
    """Archived copy of engine chat messages (internal, non-public)."""

    __tablename__ = "chat_messages_archive"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True)
    session_id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("aria_engine.chat_sessions_archive.id", ondelete="CASCADE"),
        nullable=False,
    )
    agent_id: Mapped[str | None] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    thinking: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[dict | None] = mapped_column(JSONB)
    tool_results: Mapped[dict | None] = mapped_column(JSONB)
    client_message_id: Mapped[str | None] = mapped_column(String(128))
    model: Mapped[str | None] = mapped_column(String(200))
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    cost: Mapped[float | None] = mapped_column(Numeric(10, 6))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    embedding: Mapped[Any] = mapped_column(Vector(768), nullable=True) if HAS_PGVECTOR else mapped_column(JSONB, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    archived_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))

    session: Mapped["EngineChatSessionArchive"] = relationship(
        "EngineChatSessionArchive",
        back_populates="messages",
    )


Index("idx_ecma_session", EngineChatMessageArchive.session_id)
Index("idx_ecma_role", EngineChatMessageArchive.role)
Index("idx_ecma_created", EngineChatMessageArchive.created_at)
Index("idx_ecma_archived", EngineChatMessageArchive.archived_at.desc())
Index("idx_ecma_session_created", EngineChatMessageArchive.session_id, EngineChatMessageArchive.created_at)


class EngineCronJob(Base):
    __tablename__ = "cron_jobs"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    schedule: Mapped[str] = mapped_column(String(100), nullable=False)
    agent_id: Mapped[str] = mapped_column(String(100), server_default=text("'aria'"))
    model: Mapped[str | None] = mapped_column(String(200), nullable=True, doc="LLM model override for this cron job")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    payload_type: Mapped[str] = mapped_column(String(50), server_default=text("'prompt'"))
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    session_mode: Mapped[str] = mapped_column(String(50), server_default=text("'isolated'"))
    max_duration_seconds: Mapped[int] = mapped_column(Integer, server_default=text("300"))
    retry_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_duration_ms: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    run_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    success_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    fail_count: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_ecj_enabled", EngineCronJob.enabled)
Index("idx_ecj_next_run", EngineCronJob.next_run_at)


class EngineAgentState(Base):
    __tablename__ = "agent_state"
    __table_args__ = {"schema": "aria_engine"}

    agent_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200))
    agent_type: Mapped[str] = mapped_column(String(30), server_default=text("'agent'"), comment="agent, sub_agent, sub_aria, swarm, focus")
    parent_agent_id: Mapped[str | None] = mapped_column(String(100), comment="Parent agent for hierarchy")
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    fallback_model: Mapped[str | None] = mapped_column(String(200), comment="Fallback model if primary fails")
    temperature: Mapped[float] = mapped_column(Float, server_default=text("0.7"))
    max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("4096"))
    system_prompt: Mapped[str | None] = mapped_column(Text)
    focus_type: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(20), server_default=text("'idle'"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    skills: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), comment="Assigned skill names")
    capabilities: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"), comment="Agent capabilities")
    current_session_id: Mapped[Any | None] = mapped_column(UUID(as_uuid=True))
    current_task: Mapped[str | None] = mapped_column(Text)
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    pheromone_score: Mapped[float] = mapped_column(Numeric(5, 3), server_default=text("0.500"))
    timeout_seconds: Mapped[int] = mapped_column(Integer, server_default=text("600"))
    rate_limit: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), comment="Rate limit config")
    last_active_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    app_managed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), comment="True = edited via API/UI, sync will skip")
    metadata_json: Mapped[dict] = mapped_column("metadata", JSONB, server_default=text("'{}'::jsonb"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


class FocusProfileEntry(Base):
    """
    A named personality layer for agents.
    Composes additively on top of an agent's base system_prompt.
    effective_prompt = base_prompt + "\\n\\n---\\n" + system_prompt_addon
    """
    __tablename__ = "focus_profiles"
    __table_args__ = {"schema": "aria_engine"}

    focus_id: Mapped[str] = mapped_column(
        String(50), primary_key=True,
        comment="Slug key, e.g. 'devsecops', 'creative'"
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    emoji: Mapped[str] = mapped_column(String(10), server_default=text("'🎯'"))
    description: Mapped[str | None] = mapped_column(Text)

    # Personality
    tone: Mapped[str] = mapped_column(
        String(30), server_default=text("'neutral'"),
        comment="precise | analytical | playful | formal | warm | blunt"
    )
    style: Mapped[str] = mapped_column(
        String(30), server_default=text("'directive'"),
        comment="directive | socratic | analytical | narrative | concise"
    )

    # Delegation: 1=L1(orchestrator), 2=L2(specialist), 3=L3(ephemeral)
    delegation_level: Mapped[int] = mapped_column(
        Integer, server_default=text("2")
    )

    # Token discipline — hard ceiling enforced by agent_pool.py S-74
    token_budget_hint: Mapped[int] = mapped_column(
        Integer, server_default=text("2000"),
        comment="Soft max_tokens ceiling when this focus is active"
    )

    # Temperature — additive delta, applied to agent.temperature in S-73
    temperature_delta: Mapped[float] = mapped_column(
        Float, server_default=text("0.0"),
        comment="+0.3 for creative, -0.2 for precise. Clamped 0.0–1.0."
    )

    # Routing keywords — replaces hardcoded SPECIALTY_PATTERNS in S-72
    expertise_keywords: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"),
        comment="Keyword fragments for specialty routing. Built into regex alternation."
    )

    # Prompt layer — appended to base system_prompt at call time (S-73)
    system_prompt_addon: Mapped[str | None] = mapped_column(
        Text,
        comment="Injected after agent base prompt. Additive only, never replaces."
    )

    # Optional model override — stores slug from models.yaml, not hardcoded name
    model_override: Mapped[str | None] = mapped_column(
        String(200),
        comment="model_id slug (e.g. 'qwen3-coder-free'). Resolved via models.yaml."
    )

    # Skills auto-injected when focus is activated
    auto_skills: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )

    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()")
    )

    def to_dict(self) -> dict:
        """Return JSON-serializable dict. Used by engine_focus router (S-71)."""
        return {
            "focus_id": self.focus_id,
            "display_name": self.display_name,
            "emoji": self.emoji,
            "description": self.description,
            "tone": self.tone,
            "style": self.style,
            "delegation_level": self.delegation_level,
            "token_budget_hint": self.token_budget_hint,
            "temperature_delta": self.temperature_delta,
            "expertise_keywords": self.expertise_keywords or [],
            "system_prompt_addon": self.system_prompt_addon,
            "model_override": self.model_override,
            "auto_skills": self.auto_skills or [],
            "enabled": self.enabled,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


Index("idx_focus_profiles_enabled", FocusProfileEntry.enabled)


class EngineConfigEntry(Base):
    __tablename__ = "config"
    __table_args__ = {"schema": "aria_engine"}

    key: Mapped[str] = mapped_column(String(200), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_by: Mapped[str] = mapped_column(String(100), server_default=text("'system'"))


class EngineAgentTool(Base):
    __tablename__ = "agent_tools"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[Any] = mapped_column(UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"))
    agent_id: Mapped[str] = mapped_column(String(100), nullable=False)
    skill_name: Mapped[str] = mapped_column(String(100), nullable=False)
    function_name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    parameters: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_eat_agent", EngineAgentTool.agent_id)


# ── LLM Model Catalog (DB-backed) ────────────────────────────────────────────
# Persistent model catalog — seeded from models.yaml, editable via API/UI.


class LlmModelEntry(Base):
    """One LLM model available in the system.

    Seeded from ``models.yaml`` at startup; thereafter editable through the
    admin UI so operators can add/remove/tweak models without redeploying.
    """
    __tablename__ = "llm_models"
    __table_args__ = {"schema": "aria_engine"}

    id: Mapped[str] = mapped_column(String(100), primary_key=True, comment="Short unique key, e.g. 'kimi'")
    name: Mapped[str] = mapped_column(String(300), nullable=False, comment="Human-readable display name")
    provider: Mapped[str] = mapped_column(String(50), nullable=False, server_default=text("'litellm'"), comment="Provider group (litellm, ollama, openrouter …)")
    tier: Mapped[str] = mapped_column(String(30), nullable=False, server_default=text("'free'"), comment="Cost tier: local / free / paid")
    reasoning: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    vision: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    tool_calling: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    input_types: Mapped[list] = mapped_column(JSONB, server_default=text("'[\"text\"]'::jsonb"), comment="['text'], ['text','image'], …")
    context_window: Mapped[int] = mapped_column(Integer, server_default=text("8192"))
    max_tokens: Mapped[int] = mapped_column(Integer, server_default=text("4096"))
    cost_input: Mapped[float] = mapped_column(Numeric(12, 6), server_default=text("0"), comment="$/1M input tokens")
    cost_output: Mapped[float] = mapped_column(Numeric(12, 6), server_default=text("0"), comment="$/1M output tokens")
    cost_cache_read: Mapped[float] = mapped_column(Numeric(12, 6), server_default=text("0"))
    litellm_model: Mapped[str | None] = mapped_column(String(300), comment="litellm SDK model string, e.g. moonshot/kimi-k2.5")
    litellm_api_key: Mapped[str | None] = mapped_column(String(500), comment="'os.environ/VAR' or raw key")
    litellm_api_base: Mapped[str | None] = mapped_column(String(500), comment="Per-model API base URL")
    route_skill: Mapped[str | None] = mapped_column(String(100))
    aliases: Mapped[list] = mapped_column(JSONB, server_default=text("'[]'::jsonb"))
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    sort_order: Mapped[int] = mapped_column(Integer, server_default=text("100"))
    app_managed: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), comment="True = edited via API/UI, sync will skip")
    extra: Mapped[dict] = mapped_column(JSONB, server_default=text("'{}'::jsonb"), comment="Arbitrary extra config")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("NOW()"))


Index("idx_llm_models_provider", LlmModelEntry.provider)
Index("idx_llm_models_tier", LlmModelEntry.tier)
Index("idx_llm_models_enabled", LlmModelEntry.enabled)


# ── Engine Resilience State (R-01 / R-02) ────────────────────────────────────
# Persisted to aria_engine schema via SQLAlchemy — no Redis, no raw SQL.


class EngineCircuitBreakerState(Base):
    """Persisted circuit-breaker state for cross-restart recovery (R-01).

    Written by ``CircuitBreaker.persist(db)`` and read by
    ``CircuitBreaker.restore(name, db)``.  The in-memory hot-path is
    unchanged; DB writes are fire-and-forget upserts.
    """

    __tablename__ = "circuit_breaker_state"
    __table_args__ = {"schema": "aria_engine"}

    name: Mapped[str] = mapped_column(
        String(100), primary_key=True,
        comment="Breaker identity key, e.g. 'llm' or 'skill:api_client'",
    )
    failures: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    opened_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        comment="Wall-clock UTC instant when breaker was opened; NULL when closed",
    )
    state: Mapped[str] = mapped_column(
        String(20), server_default=text("'closed'"),
        comment="closed | open | half-open",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


Index("idx_ecb_state", EngineCircuitBreakerState.state)
Index("idx_ecb_updated", EngineCircuitBreakerState.updated_at.desc())


class EngineRateLimitWindow(Base):
    """Persisted sliding-window event log for rate limiting (R-02).

    Each row is keyed by ``(window_key, window_type)`` and stores a JSONB
    array of ISO-8601 UTC timestamps representing recent events.
    Old timestamps are pruned on every write — rows stay small.

    ``window_type`` is one of ``'session'`` or ``'agent'``.
    ``window_key``  is a session UUID string or an agent_id string.
    """

    __tablename__ = "rate_limit_windows"
    __table_args__ = (
        UniqueConstraint("window_key", "window_type", name="uq_rlw_key_type"),
        {"schema": "aria_engine"},
    )

    id: Mapped[Any] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=text("uuid_generate_v4()"),
    )
    window_key: Mapped[str] = mapped_column(String(200), nullable=False)
    window_type: Mapped[str] = mapped_column(
        String(10), nullable=False,
        comment="'session' or 'agent'",
    )
    events: Mapped[list] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb"),
        comment="ISO-8601 UTC timestamps of rate-limit events within the last hour",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("NOW()"),
        onupdate=text("NOW()"),
    )


Index("idx_rlw_key_type", EngineRateLimitWindow.window_key, EngineRateLimitWindow.window_type)
Index("idx_rlw_updated", EngineRateLimitWindow.updated_at.desc())
