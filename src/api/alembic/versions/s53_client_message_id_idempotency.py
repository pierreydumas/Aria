"""s53 — enforce user-turn idempotency by client_message_id

Revision ID: s53_client_message_id_idempotency
Revises: s52_pg17_pgvector_hnsw
Create Date: 2026-03-03

Adds a partial unique index for user messages based on:
  (session_id, metadata->>'client_message_id')

This keeps schema compatible while enabling deterministic retry dedup in
streaming with `client_message_id` keys.
"""

from alembic import op

revision = "s53_client_message_id_idempotency"
down_revision = "s52_pg17_pgvector_hnsw"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ecm_session_client_message_id_user "
        "ON aria_engine.chat_messages "
        "(session_id, (metadata->>'client_message_id')) "
        "WHERE role = 'user' "
        "AND metadata ? 'client_message_id' "
        "AND coalesce(metadata->>'client_message_id', '') <> ''"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS aria_engine.uq_ecm_session_client_message_id_user")
