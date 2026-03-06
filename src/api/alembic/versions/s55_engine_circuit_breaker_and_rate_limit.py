"""s55 — engine resilience: circuit_breaker_state + rate_limit_windows tables

Revision ID: s55_engine_circuit_breaker_and_rate_limit
Revises: s54_client_message_id_column
Create Date: 2026-03-06

Adds two new tables to the ``aria_engine`` schema for cross-restart persistence
of in-process resilience state.  No Redis dependency — everything lives in the
existing PostgreSQL warehouse via SQLAlchemy ORM.

Tables created:
  aria_engine.circuit_breaker_state  — persists CircuitBreaker failure counters
  aria_engine.rate_limit_windows     — persists SlidingWindow event timestamps

Both are written from Python via ``INSERT … ON CONFLICT DO UPDATE`` (upsert),
so callers never need raw SQL.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB, UUID

revision = "s55_engine_circuit_breaker_and_rate_limit"
down_revision = "s54_client_message_id_column"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── aria_engine.circuit_breaker_state ────────────────────────────────────
    op.create_table(
        "circuit_breaker_state",
        sa.Column("name", sa.String(100), primary_key=True,
                  comment="Breaker identity key, e.g. 'llm' or 'skill:api_client'"),
        sa.Column("failures", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("opened_at", sa.DateTime(timezone=True), nullable=True,
                  comment="UTC instant when breaker was opened; NULL when closed"),
        sa.Column("state", sa.String(20), server_default=sa.text("'closed'"), nullable=False,
                  comment="closed | open | half-open"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        schema="aria_engine",
    )
    op.create_index(
        "idx_ecb_state",
        "circuit_breaker_state",
        ["state"],
        schema="aria_engine",
    )
    op.create_index(
        "idx_ecb_updated",
        "circuit_breaker_state",
        [sa.text("updated_at DESC")],
        schema="aria_engine",
    )

    # ── aria_engine.rate_limit_windows ───────────────────────────────────────
    op.create_table(
        "rate_limit_windows",
        sa.Column("id", UUID(as_uuid=True), primary_key=True,
                  server_default=sa.text("uuid_generate_v4()")),
        sa.Column("window_key", sa.String(200), nullable=False,
                  comment="session UUID string or agent_id"),
        sa.Column("window_type", sa.String(10), nullable=False,
                  comment="'session' or 'agent'"),
        sa.Column("events", JSONB, server_default=sa.text("'[]'::jsonb"), nullable=False,
                  comment="ISO-8601 UTC timestamps of events in the last hour"),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
        sa.UniqueConstraint("window_key", "window_type", name="uq_rlw_key_type"),
        schema="aria_engine",
    )
    op.create_index(
        "idx_rlw_key_type",
        "rate_limit_windows",
        ["window_key", "window_type"],
        schema="aria_engine",
    )
    op.create_index(
        "idx_rlw_updated",
        "rate_limit_windows",
        [sa.text("updated_at DESC")],
        schema="aria_engine",
    )


def downgrade() -> None:
    op.drop_table("rate_limit_windows", schema="aria_engine")
    op.drop_table("circuit_breaker_state", schema="aria_engine")
