"""
Unit test conftest — stubs the ``db`` namespace so engine modules
can be imported without a live PostgreSQL / Docker environment.
"""
from __future__ import annotations

import sys
from unittest.mock import MagicMock

# Stub db package before any module under test is imported.
# This lets aria_engine.context_manager / session_protection etc.
# be imported in a pure-Python unit-test context.
if "db" not in sys.modules:
    _db_stub = MagicMock()
    _db_stub.models = MagicMock()
    sys.modules["db"] = _db_stub
    sys.modules["db.models"] = _db_stub.models

# Stub sqlalchemy async components (used in session_protection constructor)
if "sqlalchemy.ext.asyncio" not in sys.modules:
    _sa_async = MagicMock()
    sys.modules.setdefault("sqlalchemy.ext.asyncio", _sa_async)
