"""S-49: Baseline migration — create ALL 36 ORM tables.

Idempotent: each CREATE TABLE / CREATE INDEX is wrapped in try/except
so existing installs skip already-present objects.

Revision ID: s49_baseline_all_tables
Revises: — (chain root)
Create Date: 2026-02-19
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSONB

revision = "s49_baseline_all_tables"
down_revision = None
branch_labels = None
depends_on = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_create_table(name, *columns, **kw):
    """Create a table, silently skipping if it already exists."""
    try:
        op.create_table(name, *columns, **kw)
    except Exception:
        pass


def _safe_create_index(name, table, columns, **kw):
    """Create an index, silently skipping if it already exists."""
    try:
        op.create_index(name, table, columns, **kw)
    except Exception:
        pass


def _safe_execute(sql):
    """Execute raw SQL, silently skipping on error."""
    try:
        op.execute(sql)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# upgrade
# ---------------------------------------------------------------------------

def upgrade():
    # ── Extensions ────────────────────────────────────────────────────
    for ext in ("uuid-ossp", "pg_trgm", "vector"):
        try:
            op.execute(f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
        except Exception:
            pass

    # ==================================================================
    # 1. memories
    # ==================================================================
    _safe_create_table(
        "memories",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("key", sa.String(255), unique=True, nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("category", sa.String(100), server_default=sa.text("'general'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_memories_key", "memories", ["key"])
    _safe_create_index("idx_memories_category", "memories", ["category"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories (updated_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_memories_created ON memories (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_memories_value_gin ON memories USING gin (value)")

    # ==================================================================
    # 2. thoughts
    # ==================================================================
    _safe_create_table(
        "thoughts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("category", sa.String(100), server_default=sa.text("'general'")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_thoughts_category", "thoughts", ["category"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_thoughts_created ON thoughts (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_thoughts_content_trgm ON thoughts USING gin (content gin_trgm_ops)")

    # ==================================================================
    # 3. goals
    # ==================================================================
    _safe_create_table(
        "goals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("goal_id", sa.String(100), unique=True, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("status", sa.String(50), server_default=sa.text("'pending'")),
        sa.Column("priority", sa.Integer, server_default=sa.text("2")),
        sa.Column("progress", sa.Numeric(5, 2), server_default=sa.text("0")),
        sa.Column("due_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sprint", sa.String(100), server_default=sa.text("'backlog'")),
        sa.Column("board_column", sa.String(50), server_default=sa.text("'backlog'")),
        sa.Column("position", sa.Integer, server_default=sa.text("0")),
        sa.Column("assigned_to", sa.String(100), nullable=True),
        sa.Column("tags", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_goals_status", "goals", ["status"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_goals_priority ON goals (priority DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_goals_created ON goals (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_goals_status_priority_created ON goals (status, priority DESC, created_at DESC)")
    _safe_create_index("idx_goals_sprint", "goals", ["sprint"])
    _safe_create_index("idx_goals_board_column", "goals", ["board_column"])
    _safe_create_index("idx_goals_sprint_column_position", "goals", ["sprint", "board_column", "position"])

    # ==================================================================
    # 4. activity_log
    # ==================================================================
    _safe_create_table(
        "activity_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("skill", sa.String(100), nullable=True),
        sa.Column("details", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("success", sa.Boolean, server_default=sa.text("true")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_activity_action", "activity_log", ["action"])
    _safe_create_index("idx_activity_skill", "activity_log", ["skill"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_activity_created ON activity_log (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_activity_action_created ON activity_log (action, created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_activity_skill_created ON activity_log (skill, created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_activity_details_gin ON activity_log USING gin (details)")

    # ==================================================================
    # 5. social_posts (self-referential FK on post_id)
    # ==================================================================
    _safe_create_table(
        "social_posts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("platform", sa.String(50), server_default=sa.text("'moltbook'")),
        sa.Column("post_id", sa.String(100), unique=True, nullable=True),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("visibility", sa.String(50), server_default=sa.text("'public'")),
        sa.Column("reply_to", sa.String(100), nullable=True),
        sa.Column("url", sa.Text, nullable=True),
        sa.Column("posted_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.ForeignKeyConstraint(["reply_to"], ["social_posts.post_id"], name="fk_social_posts_reply_to", ondelete="SET NULL"),
    )
    _safe_create_index("idx_posts_platform", "social_posts", ["platform"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_posts_posted ON social_posts (posted_at DESC)")
    _safe_create_index("idx_posts_post_id", "social_posts", ["post_id"])

    # ==================================================================
    # 6. hourly_goals
    # ==================================================================
    _safe_create_table(
        "hourly_goals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hour_slot", sa.Integer, nullable=False),
        sa.Column("goal_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_hourly_status", "hourly_goals", ["status"])
    _safe_create_index("idx_hourly_hour_slot", "hourly_goals", ["hour_slot"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_hourly_created ON hourly_goals (created_at DESC)")

    # ==================================================================
    # 7. knowledge_entities
    # ==================================================================
    _safe_create_table(
        "knowledge_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("type", sa.Text, nullable=False),
        sa.Column("properties", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_kg_entity_name", "knowledge_entities", ["name"])
    _safe_create_index("idx_kg_entity_type", "knowledge_entities", ["type"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_kg_properties_gin ON knowledge_entities USING gin (properties)")

    # ==================================================================
    # 8. knowledge_relations (FK → knowledge_entities)
    # ==================================================================
    _safe_create_table(
        "knowledge_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("from_entity", UUID(as_uuid=True), nullable=False),
        sa.Column("to_entity", UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.Text, nullable=False),
        sa.Column("properties", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["from_entity"], ["knowledge_entities.id"], name="fk_kr_from_entity", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity"], ["knowledge_entities.id"], name="fk_kr_to_entity", ondelete="CASCADE"),
    )
    _safe_create_index("idx_kg_relation_from", "knowledge_relations", ["from_entity"])
    _safe_create_index("idx_kg_relation_to", "knowledge_relations", ["to_entity"])
    _safe_create_index("idx_kg_relation_type", "knowledge_relations", ["relation_type"])

    # ==================================================================
    # 9. skill_graph_entities
    # ==================================================================
    _safe_create_table(
        "skill_graph_entities",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("name", sa.String(500), nullable=False),
        sa.Column("type", sa.String(100), nullable=False),
        sa.Column("properties", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("name", "type", name="uq_sg_entity_name_type"),
    )
    _safe_create_index("idx_sg_entity_name", "skill_graph_entities", ["name"])
    _safe_create_index("idx_sg_entity_type", "skill_graph_entities", ["type"])

    # ==================================================================
    # 10. skill_graph_relations (FK → skill_graph_entities)
    # ==================================================================
    _safe_create_table(
        "skill_graph_relations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("from_entity", UUID(as_uuid=True), nullable=False),
        sa.Column("to_entity", UUID(as_uuid=True), nullable=False),
        sa.Column("relation_type", sa.String(100), nullable=False),
        sa.Column("properties", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["from_entity"], ["skill_graph_entities.id"], name="fk_sgr_from_entity", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_entity"], ["skill_graph_entities.id"], name="fk_sgr_to_entity", ondelete="CASCADE"),
    )
    _safe_create_index("idx_sg_relation_from", "skill_graph_relations", ["from_entity"])
    _safe_create_index("idx_sg_relation_to", "skill_graph_relations", ["to_entity"])
    _safe_create_index("idx_sg_relation_type", "skill_graph_relations", ["relation_type"])

    # ==================================================================
    # 11. knowledge_query_log
    # ==================================================================
    _safe_create_table(
        "knowledge_query_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("query_type", sa.String(50), nullable=False),
        sa.Column("params", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("result_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("tokens_saved", sa.Integer, nullable=True),
        sa.Column("used_result", sa.Boolean, server_default=sa.text("false")),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_kql_query_type", "knowledge_query_log", ["query_type"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_kql_created ON knowledge_query_log (created_at DESC)")
    _safe_create_index("idx_kql_source", "knowledge_query_log", ["source"])

    # ==================================================================
    # 12. performance_log
    # ==================================================================
    _safe_create_table(
        "performance_log",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("review_period", sa.String(20), nullable=False),
        sa.Column("successes", sa.Text, nullable=True),
        sa.Column("failures", sa.Text, nullable=True),
        sa.Column("improvements", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_perflog_created ON performance_log (created_at DESC)")

    # ==================================================================
    # 13. pending_complex_tasks
    # ==================================================================
    _safe_create_table(
        "pending_complex_tasks",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(50), unique=True, nullable=False),
        sa.Column("task_type", sa.String(50), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("agent_type", sa.String(50), nullable=False),
        sa.Column("priority", sa.String(20), server_default=sa.text("'medium'")),
        sa.Column("status", sa.String(20), server_default=sa.text("'pending'")),
        sa.Column("result", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    _safe_create_index("idx_pct_status", "pending_complex_tasks", ["status"])
    _safe_create_index("idx_pct_task_id", "pending_complex_tasks", ["task_id"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_pct_created ON pending_complex_tasks (created_at DESC)")

    # ==================================================================
    # 14. heartbeat_log
    # ==================================================================
    _safe_create_table(
        "heartbeat_log",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("beat_number", sa.Integer, nullable=False, server_default=sa.text("0")),
        sa.Column("job_name", sa.String(100), nullable=True),
        sa.Column("status", sa.String(50), server_default=sa.text("'healthy'")),
        sa.Column("details", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_heartbeat_created ON heartbeat_log (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_heartbeat_job_name ON heartbeat_log (job_name)")

    # ==================================================================
    # 15. scheduled_jobs
    # ==================================================================
    _safe_create_table(
        "scheduled_jobs",
        sa.Column("id", sa.String(50), primary_key=True),
        sa.Column("agent_id", sa.String(50), server_default=sa.text("'main'")),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("schedule_kind", sa.String(20), server_default=sa.text("'cron'")),
        sa.Column("schedule_expr", sa.String(50), nullable=False),
        sa.Column("session_target", sa.String(50), nullable=True),
        sa.Column("wake_mode", sa.String(50), nullable=True),
        sa.Column("payload_kind", sa.String(50), nullable=True),
        sa.Column("payload_text", sa.Text, nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_duration_ms", sa.Integer, nullable=True),
        sa.Column("run_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("fail_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("created_at_ms", sa.Integer, nullable=True),
        sa.Column("updated_at_ms", sa.Integer, nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_jobs_name", "scheduled_jobs", ["name"])
    _safe_create_index("idx_jobs_enabled", "scheduled_jobs", ["enabled"])
    _safe_create_index("idx_jobs_next_run", "scheduled_jobs", ["next_run_at"])

    # ==================================================================
    # 16. security_events
    # ==================================================================
    _safe_create_table(
        "security_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("threat_level", sa.String(20), nullable=False),
        sa.Column("threat_type", sa.String(100), nullable=False),
        sa.Column("threat_patterns", JSONB, server_default=sa.text("'[]'::jsonb")),
        sa.Column("input_preview", sa.Text, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("user_id", sa.String(100), nullable=True),
        sa.Column("blocked", sa.Boolean, server_default=sa.text("false")),
        sa.Column("details", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_security_threat_level", "security_events", ["threat_level"])
    _safe_create_index("idx_security_threat_type", "security_events", ["threat_type"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_security_created ON security_events (created_at DESC)")
    _safe_create_index("idx_security_blocked", "security_events", ["blocked"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_security_threat_created ON security_events (threat_level, created_at DESC)")

    # ==================================================================
    # 17. schedule_tick
    # ==================================================================
    _safe_create_table(
        "schedule_tick",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("last_tick", sa.DateTime(timezone=True), nullable=True),
        sa.Column("tick_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("heartbeat_interval", sa.Integer, server_default=sa.text("3600")),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("jobs_total", sa.Integer, server_default=sa.text("0")),
        sa.Column("jobs_successful", sa.Integer, server_default=sa.text("0")),
        sa.Column("jobs_failed", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_job_name", sa.String(255), nullable=True),
        sa.Column("last_job_status", sa.String(50), nullable=True),
        sa.Column("next_job_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ==================================================================
    # 18. agent_sessions
    # ==================================================================
    _safe_create_table(
        "agent_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("session_type", sa.String(50), server_default=sa.text("'interactive'")),
        sa.Column("started_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("messages_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("tokens_used", sa.Integer, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default=sa.text("0")),
        sa.Column("status", sa.String(50), server_default=sa.text("'active'")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
    )
    _safe_create_index("idx_agent_sessions_agent", "agent_sessions", ["agent_id"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_started ON agent_sessions (started_at DESC)")
    _safe_create_index("idx_agent_sessions_status", "agent_sessions", ["status"])
    _safe_create_index("idx_agent_sessions_type", "agent_sessions", ["session_type"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_agent_started ON agent_sessions (agent_id, started_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_metadata_gin ON agent_sessions USING gin (metadata)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_aria_sid ON agent_sessions ((metadata ->> 'aria_session_id'))")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_sessions_external_sid ON agent_sessions ((metadata ->> 'external_session_id'))")

    # ==================================================================
    # 19. session_messages (FK → agent_sessions)
    # ==================================================================
    _safe_create_table(
        "session_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("external_session_id", sa.String(120), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("source_channel", sa.String(50), nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], name="fk_sm_session", ondelete="SET NULL"),
        sa.UniqueConstraint("external_session_id", "role", "content_hash", name="uq_session_message_ext_role_hash"),
    )
    _safe_create_index("idx_session_messages_session", "session_messages", ["session_id"])
    _safe_create_index("idx_session_messages_external", "session_messages", ["external_session_id"])
    _safe_create_index("idx_session_messages_role", "session_messages", ["role"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_session_messages_created ON session_messages (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_session_messages_session_created ON session_messages (session_id, created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_session_messages_ext_created ON session_messages (external_session_id, created_at DESC)")

    # ==================================================================
    # 20. sentiment_events (FK → session_messages, agent_sessions)
    # ==================================================================
    _safe_create_table(
        "sentiment_events",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("message_id", UUID(as_uuid=True), nullable=False),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("external_session_id", sa.String(120), nullable=True),
        sa.Column("speaker", sa.String(20), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("sentiment_label", sa.String(20), nullable=False),
        sa.Column("primary_emotion", sa.String(50), nullable=True),
        sa.Column("valence", sa.Float, nullable=False),
        sa.Column("arousal", sa.Float, nullable=False),
        sa.Column("dominance", sa.Float, nullable=False),
        sa.Column("confidence", sa.Float, nullable=False),
        sa.Column("importance", sa.Float, server_default=sa.text("0.3")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["message_id"], ["session_messages.id"], name="fk_se_message", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], name="fk_se_session", ondelete="SET NULL"),
        sa.UniqueConstraint("message_id", name="uq_sentiment_event_message"),
    )
    _safe_create_index("idx_sentiment_events_message", "sentiment_events", ["message_id"])
    _safe_create_index("idx_sentiment_events_session", "sentiment_events", ["session_id"])
    _safe_create_index("idx_sentiment_events_external", "sentiment_events", ["external_session_id"])
    _safe_create_index("idx_sentiment_events_label", "sentiment_events", ["sentiment_label"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_sentiment_events_created ON sentiment_events (created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_sentiment_events_session_created ON sentiment_events (session_id, created_at DESC)")
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_sentiment_events_label_created ON sentiment_events (sentiment_label, created_at DESC)")
    _safe_create_index("idx_sentiment_events_speaker", "sentiment_events", ["speaker"])
    _safe_create_index("idx_sentiment_events_agent_id", "sentiment_events", ["agent_id"])

    # ==================================================================
    # 21. model_usage (FK → agent_sessions)
    # ==================================================================
    _safe_create_table(
        "model_usage",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("provider", sa.String(50), nullable=True),
        sa.Column("input_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("output_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("cost_usd", sa.Numeric(10, 6), server_default=sa.text("0")),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, server_default=sa.text("true")),
        sa.Column("error_message", sa.Text, nullable=True),
        sa.Column("session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["session_id"], ["agent_sessions.id"], name="fk_mu_session", ondelete="SET NULL"),
    )
    _safe_create_index("idx_model_usage_model", "model_usage", ["model"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_model_usage_created ON model_usage (created_at DESC)")
    _safe_create_index("idx_model_usage_session", "model_usage", ["session_id"])
    _safe_create_index("idx_model_usage_provider", "model_usage", ["provider"])
    _safe_create_index("idx_model_usage_success", "model_usage", ["success"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_model_usage_model_created ON model_usage (model, created_at DESC)")
    _safe_create_index("idx_model_usage_model_provider", "model_usage", ["model", "provider"])

    # ==================================================================
    # 22. rate_limits
    # ==================================================================
    _safe_create_table(
        "rate_limits",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("skill", sa.String(100), unique=True, nullable=False),
        sa.Column("last_action", sa.DateTime(timezone=True), nullable=True),
        sa.Column("action_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("window_start", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("last_post", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_rate_limits_skill", "rate_limits", ["skill"])

    # ==================================================================
    # 23. api_key_rotations
    # ==================================================================
    _safe_create_table(
        "api_key_rotations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("service", sa.String(100), nullable=False),
        sa.Column("rotated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("reason", sa.Text, nullable=True),
        sa.Column("rotated_by", sa.String(100), server_default=sa.text("'system'")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
    )
    _safe_create_index("idx_akr_service", "api_key_rotations", ["service"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_akr_rotated ON api_key_rotations (rotated_at DESC)")

    # ==================================================================
    # 24. agent_performance
    # ==================================================================
    _safe_create_table(
        "agent_performance",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("task_type", sa.String(100), nullable=False),
        sa.Column("success", sa.Boolean, nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("token_cost", sa.Numeric(10, 6), nullable=True),
        sa.Column("pheromone_score", sa.Numeric(5, 3), server_default=sa.text("0.500")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_agent_perf_agent", "agent_performance", ["agent_id"])
    _safe_create_index("idx_agent_perf_task", "agent_performance", ["task_type"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_agent_perf_created ON agent_performance (created_at DESC)")

    # ==================================================================
    # 25. working_memory
    # ==================================================================
    _safe_create_table(
        "working_memory",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("key", sa.String(200), nullable=False),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("importance", sa.Float, server_default=sa.text("0.5")),
        sa.Column("ttl_hours", sa.Integer, nullable=True),
        sa.Column("source", sa.String(100), nullable=True),
        sa.Column("checkpoint_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer, server_default=sa.text("0")),
    )
    _safe_create_index("idx_wm_category", "working_memory", ["category"])
    _safe_create_index("idx_wm_key", "working_memory", ["key"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_wm_importance ON working_memory (importance DESC)")
    _safe_create_index("idx_wm_checkpoint", "working_memory", ["checkpoint_id"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_wm_importance_created ON working_memory (importance DESC, created_at DESC)")
    _safe_execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_wm_category_key ON working_memory (category, key)")

    # ==================================================================
    # 26. skill_status
    # ==================================================================
    _safe_create_table(
        "skill_status",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("skill_name", sa.String(100), nullable=False, unique=True),
        sa.Column("canonical_name", sa.String(100), nullable=False),
        sa.Column("layer", sa.String(20), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'unavailable'")),
        sa.Column("last_health_check", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_execution", sa.DateTime(timezone=True), nullable=True),
        sa.Column("use_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("error_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("metadata", JSONB, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_skill_status_name", "skill_status", ["skill_name"])
    _safe_create_index("idx_skill_status_status", "skill_status", ["status"])
    _safe_create_index("idx_skill_status_layer", "skill_status", ["layer"])

    # ==================================================================
    # 27. semantic_memories (Vector(768) with JSONB fallback)
    # ==================================================================
    # Use raw DDL so we can attempt vector(768) first, then fall back to jsonb
    _safe_execute("""
        CREATE TABLE IF NOT EXISTS semantic_memories (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            content TEXT NOT NULL,
            summary TEXT,
            category VARCHAR(50) DEFAULT 'general',
            embedding vector(768) NOT NULL,
            metadata JSONB DEFAULT '{}'::jsonb,
            importance FLOAT DEFAULT 0.5,
            source VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            accessed_at TIMESTAMPTZ,
            access_count INTEGER DEFAULT 0
        )
    """)
    # Fallback if vector type not available — use JSONB
    _safe_execute("""
        CREATE TABLE IF NOT EXISTS semantic_memories (
            id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            content TEXT NOT NULL,
            summary TEXT,
            category VARCHAR(50) DEFAULT 'general',
            embedding JSONB NOT NULL,
            metadata JSONB DEFAULT '{}'::jsonb,
            importance FLOAT DEFAULT 0.5,
            source VARCHAR(100),
            created_at TIMESTAMPTZ DEFAULT NOW(),
            accessed_at TIMESTAMPTZ,
            access_count INTEGER DEFAULT 0
        )
    """)
    _safe_create_index("idx_semantic_category", "semantic_memories", ["category"])
    _safe_create_index("idx_semantic_importance", "semantic_memories", ["importance"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_semantic_created ON semantic_memories (created_at DESC)")
    _safe_create_index("idx_semantic_source", "semantic_memories", ["source"])

    # ==================================================================
    # 28. lessons_learned
    # ==================================================================
    _safe_create_table(
        "lessons_learned",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("error_pattern", sa.String(200), nullable=False),
        sa.Column("error_type", sa.String(100), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=True),
        sa.Column("context", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("resolution", sa.Text, nullable=False),
        sa.Column("resolution_code", sa.Text, nullable=True),
        sa.Column("occurrences", sa.Integer, server_default=sa.text("1")),
        sa.Column("last_occurred", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("effectiveness", sa.Float, server_default=sa.text("1.0")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.UniqueConstraint("error_pattern", name="uq_lesson_pattern"),
    )
    _safe_create_index("idx_lesson_pattern", "lessons_learned", ["error_pattern"])
    _safe_create_index("idx_lesson_type", "lessons_learned", ["error_type"])
    _safe_create_index("idx_lesson_skill", "lessons_learned", ["skill_name"])

    # ==================================================================
    # 29. improvement_proposals
    # ==================================================================
    _safe_create_table(
        "improvement_proposals",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("category", sa.String(50), nullable=True),
        sa.Column("risk_level", sa.String(20), server_default=sa.text("'low'")),
        sa.Column("file_path", sa.String(500), nullable=True),
        sa.Column("current_code", sa.Text, nullable=True),
        sa.Column("proposed_code", sa.Text, nullable=True),
        sa.Column("rationale", sa.Text, nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'proposed'")),
        sa.Column("reviewed_by", sa.String(100), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_proposal_status", "improvement_proposals", ["status"])
    _safe_create_index("idx_proposal_risk", "improvement_proposals", ["risk_level"])
    _safe_create_index("idx_proposal_category", "improvement_proposals", ["category"])

    # ==================================================================
    # 30. skill_invocations
    # ==================================================================
    _safe_create_table(
        "skill_invocations",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("skill_name", sa.String(100), nullable=False),
        sa.Column("tool_name", sa.String(100), nullable=False),
        sa.Column("duration_ms", sa.Integer, nullable=True),
        sa.Column("success", sa.Boolean, server_default=sa.text("true")),
        sa.Column("error_type", sa.String(100), nullable=True),
        sa.Column("tokens_used", sa.Integer, nullable=True),
        sa.Column("model_used", sa.String(100), nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_invocation_skill", "skill_invocations", ["skill_name"])
    _safe_execute("CREATE INDEX IF NOT EXISTS idx_invocation_created ON skill_invocations (created_at DESC)")
    _safe_create_index("idx_invocation_success", "skill_invocations", ["success"])
    _safe_create_index("idx_invocation_agent", "skill_invocations", ["agent_id"])

    # ==================================================================
    # 31. engine_chat_sessions
    # ==================================================================
    _safe_create_table(
        "engine_chat_sessions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_id", sa.String(100), nullable=False, server_default=sa.text("'main'")),
        sa.Column("session_type", sa.String(50), nullable=False, server_default=sa.text("'interactive'")),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("temperature", sa.Float, server_default=sa.text("0.7")),
        sa.Column("max_tokens", sa.Integer, server_default=sa.text("4096")),
        sa.Column("context_window", sa.Integer, server_default=sa.text("50")),
        sa.Column("status", sa.String(20), nullable=False, server_default=sa.text("'active'")),
        sa.Column("message_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_tokens", sa.Integer, server_default=sa.text("0")),
        sa.Column("total_cost", sa.Numeric(10, 6), server_default=sa.text("0")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
    )
    _safe_create_index("idx_ecs_agent", "engine_chat_sessions", ["agent_id"])
    _safe_create_index("idx_ecs_status", "engine_chat_sessions", ["status"])
    _safe_create_index("idx_ecs_created", "engine_chat_sessions", ["created_at"])

    # ==================================================================
    # 32. engine_chat_messages (FK → engine_chat_sessions)
    # ==================================================================
    _safe_create_table(
        "engine_chat_messages",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("session_id", UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("thinking", sa.Text, nullable=True),
        sa.Column("tool_calls", JSONB, nullable=True),
        sa.Column("tool_results", JSONB, nullable=True),
        sa.Column("model", sa.String(200), nullable=True),
        sa.Column("tokens_input", sa.Integer, nullable=True),
        sa.Column("tokens_output", sa.Integer, nullable=True),
        sa.Column("cost", sa.Numeric(10, 6), nullable=True),
        sa.Column("latency_ms", sa.Integer, nullable=True),
        sa.Column("agent_id", sa.String(100), nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["session_id"], ["engine_chat_sessions.id"], name="fk_ecm_session", ondelete="CASCADE"),
    )
    _safe_create_index("idx_ecm_session", "engine_chat_messages", ["session_id"])
    _safe_create_index("idx_ecm_role", "engine_chat_messages", ["role"])
    _safe_create_index("idx_ecm_created", "engine_chat_messages", ["created_at"])

    # ==================================================================
    # 33. engine_cron_jobs
    # ==================================================================
    _safe_create_table(
        "engine_cron_jobs",
        sa.Column("id", sa.String(100), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schedule", sa.String(100), nullable=False),
        sa.Column("agent_id", sa.String(100), server_default=sa.text("'main'")),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("payload_type", sa.String(50), server_default=sa.text("'prompt'")),
        sa.Column("payload", sa.Text, nullable=False),
        sa.Column("session_mode", sa.String(50), server_default=sa.text("'isolated'")),
        sa.Column("max_duration_seconds", sa.Integer, server_default=sa.text("300")),
        sa.Column("retry_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(20), nullable=True),
        sa.Column("last_duration_ms", sa.Integer, nullable=True),
        sa.Column("last_error", sa.Text, nullable=True),
        sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("run_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("success_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("fail_count", sa.Integer, server_default=sa.text("0")),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_ecj_enabled", "engine_cron_jobs", ["enabled"])
    _safe_create_index("idx_ecj_next_run", "engine_cron_jobs", ["next_run_at"])

    # ==================================================================
    # 34. engine_agent_state
    # ==================================================================
    _safe_create_table(
        "engine_agent_state",
        sa.Column("agent_id", sa.String(100), primary_key=True),
        sa.Column("display_name", sa.String(200), nullable=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("temperature", sa.Float, server_default=sa.text("0.7")),
        sa.Column("max_tokens", sa.Integer, server_default=sa.text("4096")),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("focus_type", sa.String(50), nullable=True),
        sa.Column("status", sa.String(20), server_default=sa.text("'idle'")),
        sa.Column("current_session_id", UUID(as_uuid=True), nullable=True),
        sa.Column("current_task", sa.Text, nullable=True),
        sa.Column("consecutive_failures", sa.Integer, server_default=sa.text("0")),
        sa.Column("pheromone_score", sa.Numeric(5, 3), server_default=sa.text("0.500")),
        sa.Column("last_active_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("metadata", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )

    # ==================================================================
    # 35. engine_config
    # ==================================================================
    _safe_create_table(
        "engine_config",
        sa.Column("key", sa.String(200), primary_key=True),
        sa.Column("value", JSONB, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
        sa.Column("updated_by", sa.String(100), server_default=sa.text("'system'")),
    )

    # ==================================================================
    # 36. engine_agent_tools
    # ==================================================================
    _safe_create_table(
        "engine_agent_tools",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("uuid_generate_v4()")),
        sa.Column("agent_id", sa.String(100), nullable=False),
        sa.Column("skill_name", sa.String(100), nullable=False),
        sa.Column("function_name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("parameters", JSONB, server_default=sa.text("'{}'::jsonb")),
        sa.Column("enabled", sa.Boolean, server_default=sa.text("true")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("NOW()")),
    )
    _safe_create_index("idx_eat_agent", "engine_agent_tools", ["agent_id"])


# ---------------------------------------------------------------------------
# downgrade — drop in reverse dependency order
# ---------------------------------------------------------------------------

def downgrade():
    # Dependents first, then parents
    tables = [
        # engine dependents
        "engine_agent_tools",
        "engine_config",
        "engine_agent_state",
        "engine_cron_jobs",
        "engine_chat_messages",   # FK → engine_chat_sessions
        "engine_chat_sessions",
        # skill invocations / proposals
        "skill_invocations",
        "improvement_proposals",
        "lessons_learned",
        "semantic_memories",
        "skill_status",
        "working_memory",
        "agent_performance",
        "api_key_rotations",
        "rate_limits",
        # session tree dependents first
        "sentiment_events",       # FK → session_messages, agent_sessions
        "model_usage",            # FK → agent_sessions
        "session_messages",       # FK → agent_sessions
        "agent_sessions",
        # scheduling / operations
        "schedule_tick",
        "security_events",
        "scheduled_jobs",
        "heartbeat_log",
        "pending_complex_tasks",
        "performance_log",
        "knowledge_query_log",
        # graph dependents first
        "skill_graph_relations",  # FK → skill_graph_entities
        "skill_graph_entities",
        "knowledge_relations",    # FK → knowledge_entities
        "knowledge_entities",
        # remaining core tables
        "hourly_goals",
        "social_posts",
        "activity_log",
        "goals",
        "thoughts",
        "memories",
    ]
    for table in tables:
        op.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
