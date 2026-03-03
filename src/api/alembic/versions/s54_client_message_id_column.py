"""s54 — add concrete client_message_id column for chat_messages idempotency

Revision ID: s54_client_message_id_column
Revises: s53_client_message_id_idempotency
Create Date: 2026-03-03

Adds `client_message_id` VARCHAR(128) to working/archive chat message tables,
backfills from metadata JSON, and moves unique idempotency index to the column.
"""

from alembic import op

revision = "s54_client_message_id_column"
down_revision = "s53_client_message_id_idempotency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE aria_engine.chat_messages "
        "ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(128)"
    )
    op.execute(
        "ALTER TABLE aria_engine.chat_messages_archive "
        "ADD COLUMN IF NOT EXISTS client_message_id VARCHAR(128)"
    )

    op.execute(
        "UPDATE aria_engine.chat_messages "
        "SET client_message_id = NULLIF(metadata->>'client_message_id', '') "
        "WHERE client_message_id IS NULL "
        "AND metadata ? 'client_message_id'"
    )
    op.execute(
        "UPDATE aria_engine.chat_messages_archive "
        "SET client_message_id = NULLIF(metadata->>'client_message_id', '') "
        "WHERE client_message_id IS NULL "
        "AND metadata ? 'client_message_id'"
    )

    op.execute("DROP INDEX IF EXISTS aria_engine.uq_ecm_session_client_message_id_user")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ecm_session_client_message_id_user "
        "ON aria_engine.chat_messages (session_id, client_message_id) "
        "WHERE role = 'user' "
        "AND client_message_id IS NOT NULL "
        "AND client_message_id <> ''"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_ecm_client_message_id "
        "ON aria_engine.chat_messages (client_message_id)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS aria_engine.idx_ecm_client_message_id")
    op.execute("DROP INDEX IF EXISTS aria_engine.uq_ecm_session_client_message_id_user")
    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS uq_ecm_session_client_message_id_user "
        "ON aria_engine.chat_messages "
        "(session_id, (metadata->>'client_message_id')) "
        "WHERE role = 'user' "
        "AND metadata ? 'client_message_id' "
        "AND coalesce(metadata->>'client_message_id', '') <> ''"
    )
    op.execute(
        "ALTER TABLE aria_engine.chat_messages_archive "
        "DROP COLUMN IF EXISTS client_message_id"
    )
    op.execute(
        "ALTER TABLE aria_engine.chat_messages "
        "DROP COLUMN IF EXISTS client_message_id"
    )
