"""
Database engine & async session factory.

Driver: psycopg 3 (postgresql+psycopg)
ORM:    SQLAlchemy 2.0 async
"""

import logging
import os
import re
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateIndex, CreateTable

from config import DATABASE_URL
from .models import Base

logger = logging.getLogger("aria.db")


# ── URL helpers ──────────────────────────────────────────────────────────────

def _as_psycopg_url(url: str) -> str:
    """Convert any PostgreSQL URL to the runtime async dialect.

    Windows: asyncpg (psycopg async has Proactor loop limitations)
    Others:  psycopg
    """
    target_prefix = (
        "postgresql+asyncpg://"
        if os.name == "nt"
        else "postgresql+psycopg://"
    )
    for prefix in (
        "postgresql+psycopg://",
        "postgresql+asyncpg://",
        "postgresql://",
    ):
        if url.startswith(prefix):
            return url.replace(prefix, target_prefix, 1)
    return url


def _litellm_url_from(url: str) -> str:
    """Derive LiteLLM connection URL from the main DATABASE_URL.

    Same host/credentials/database, but with search_path set to the
    ``litellm`` schema so LiteLLM tables are transparently isolated.
    """
    # Strip any existing query params, then add search_path
    base = url.split("?")[0]
    return f"{base}?options=-csearch_path%3Dlitellm"


# ── Engine + session factory ─────────────────────────────────────────────────

async_engine = create_async_engine(
    _as_psycopg_url(DATABASE_URL),
    pool_size=10,
    max_overflow=20,
    pool_timeout=30,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ── LiteLLM database (separate DB, same PG instance) ────────────────────────

litellm_engine = create_async_engine(
    _as_psycopg_url(_litellm_url_from(DATABASE_URL)),
    pool_size=3,
    max_overflow=5,
    pool_timeout=15,
    pool_recycle=3600,
    pool_pre_ping=True,
    echo=False,
)

LiteLLMSessionLocal = async_sessionmaker(
    litellm_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

# ── Validation helpers ───────────────────────────────────────────────────────

_VALID_TABLE_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def _validate_table_name(name: str) -> str:
    """Return *name* unchanged if it is a safe SQL identifier, else raise ValueError.

    Only lowercase letters, digits, and underscores are allowed (no schema
    prefix, no quotes).  This is defense-in-depth against SQL injection when
    table names are interpolated into raw SQL (e.g. ANALYZE).
    """
    if not _VALID_TABLE_RE.match(name):
        raise ValueError(f"Invalid table name: {name!r}")
    return name


# ── Schema bootstrapping ────────────────────────────────────────────────────

async def _run_isolated(conn, label: str, sql):
    """Execute a DDL statement inside a SAVEPOINT so failures don't poison
    the outer transaction.  Returns True on success, False on error."""
    sp_name = f"sp_{label.replace('.', '_').replace('-', '_')[:50]}"
    try:
        await conn.execute(text(f"SAVEPOINT {sp_name}"))
        if isinstance(sql, str):
            await conn.execute(text(sql))
        else:
            await conn.execute(sql)
        await conn.execute(text(f"RELEASE SAVEPOINT {sp_name}"))
        return True
    except Exception as e:
        await conn.execute(text(f"ROLLBACK TO SAVEPOINT {sp_name}"))
        logger.warning("[%s] %s", label, e)
        return False


async def ensure_schema() -> None:
    """Create all tables and indexes if they don't exist.

    Installs required extensions (uuid-ossp, pg_trgm, pgvector) first,
    then creates each table individually.

    Every DDL runs inside a SAVEPOINT so one failure doesn't cascade and
    poison the whole transaction (fixes InFailedSqlTransaction cascade).
    """
    async with async_engine.begin() as conn:
        # Create named schemas — nothing in public
        for schema_name in ("aria_data", "aria_engine", "litellm"):
            await _run_isolated(conn, f"schema_{schema_name}",
                                f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

        # Extensions — pgvector MUST be installed before SemanticMemory table
        for ext in ("uuid-ossp", "pg_trgm", "vector"):
            ok = await _run_isolated(conn, f"ext_{ext}",
                                     f'CREATE EXTENSION IF NOT EXISTS "{ext}"')
            if ok:
                logger.info("Extension '%s' ensured", ext)

        # Tables — create each individually with SAVEPOINT isolation
        created = []
        failed = []
        for table in Base.metadata.sorted_tables:
            ok = await _run_isolated(
                conn, f"table_{table.name}",
                CreateTable(table, if_not_exists=True),
            )
            (created if ok else failed).append(table.name)

        # ── Column migrations (add columns to existing tables) ─────────
        _column_migrations = [
            # (table, column, type_sql, default)
            ("aria_data.sentiment_events", "speaker", "VARCHAR(20)", None),
            ("aria_data.sentiment_events", "agent_id", "VARCHAR(100)", None),
            # Agent state new columns for agent management
            ("aria_engine.agent_state", "agent_type", "VARCHAR(30)", "'agent'"),
            ("aria_engine.agent_state", "parent_agent_id", "VARCHAR(100)", None),
            ("aria_engine.agent_state", "fallback_model", "VARCHAR(200)", None),
            ("aria_engine.agent_state", "enabled", "BOOLEAN", "true"),
            ("aria_engine.agent_state", "skills", "JSONB", "'[]'::jsonb"),
            ("aria_engine.agent_state", "capabilities", "JSONB", "'[]'::jsonb"),
            ("aria_engine.agent_state", "timeout_seconds", "INTEGER", "600"),
            ("aria_engine.agent_state", "rate_limit", "JSONB", "'{}'::jsonb"),
            # skill_invocations — track which agent invoked a skill
            ("aria_data.skill_invocations", "agent_id", "VARCHAR(100)", None),
        ]
        for tbl, col, col_type, default in _column_migrations:
            ddl = f"ALTER TABLE {tbl} ADD COLUMN IF NOT EXISTS {col} {col_type}"
            if default is not None:
                ddl += f" DEFAULT {default}"
            ok = await _run_isolated(conn, f"col_{tbl}_{col}", ddl)
            if ok:
                logger.info("Column '%s.%s' ensured", tbl, col)

        # Indexes — same per-index error isolation
        for table in Base.metadata.sorted_tables:
            for index in table.indexes:
                await _run_isolated(
                    conn, f"idx_{index.name}",
                    CreateIndex(index, if_not_exists=True),
                )

        # HNSW vector indexes (pgvector 0.5+) — not in ORM metadata, added manually
        # vector_cosine_ops matches the cosine_distance() calls in memories.py
        await _run_isolated(
            conn, "hnsw_semantic_embedding",
            "CREATE INDEX IF NOT EXISTS idx_semantic_embedding_hnsw "
            "ON aria_data.semantic_memories USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64)",
        )
        await _run_isolated(
            conn, "hnsw_session_messages_embedding",
            "CREATE INDEX IF NOT EXISTS idx_session_messages_embedding_hnsw "
            "ON aria_engine.chat_messages USING hnsw (embedding vector_cosine_ops) "
            "WITH (m = 16, ef_construction = 64) "
            "WHERE embedding IS NOT NULL",
        )

        if failed:
            logger.warning("Schema bootstrap: %d tables created, %d failed: %s",
                           len(created), len(failed), failed)
        else:
            logger.info("Schema bootstrap: all %d tables ensured", len(created))


async def check_database_health() -> dict:
    """Return database health info: existing tables, missing tables, extensions."""
    expected_tables = {t.name for t in Base.metadata.sorted_tables}
    async with async_engine.connect() as conn:
        # Existing tables across both schemas
        result = await conn.execute(text(
            "SELECT tablename FROM pg_catalog.pg_tables "
            "WHERE schemaname IN ('aria_data', 'aria_engine')"
        ))
        existing_tables = {row[0] for row in result.all()}

        # Extensions
        result = await conn.execute(text(
            "SELECT extname FROM pg_extension"
        ))
        extensions = [row[0] for row in result.all()]

        missing = expected_tables - existing_tables
        table_status = {t: t in existing_tables for t in sorted(expected_tables)}

        return {
            "status": "ok" if not missing else "degraded",
            "tables": table_status,
            "missing": sorted(missing),
            "existing_count": len(existing_tables & expected_tables),
            "expected_count": len(expected_tables),
            "pgvector_installed": "vector" in extensions,
            "extensions": extensions,
        }
