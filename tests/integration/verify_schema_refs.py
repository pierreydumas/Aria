#!/usr/bin/env python3
"""
verify_schema_refs.py — Cross-reference ORM models with SQL init scripts (S-14).

Checks that every table/column defined in SQLAlchemy models has a matching
definition in the init SQL scripts, and vice-versa.

Usage:
    python tests/integration/verify_schema_refs.py
    python tests/integration/verify_schema_refs.py --verbose
"""

import argparse
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# ── Paths ────────────────────────────────────────────────────────────────────
MODELS_PY = ROOT / "src" / "api" / "db" / "models.py"
SQL_DIR = ROOT / "stacks" / "brain" / "init-scripts"

# ── Patterns ─────────────────────────────────────────────────────────────────
# ORM: __tablename__ = "foo"  and  __table_args__ = {"schema": "bar"}
RE_TABLE = re.compile(
    r'__tablename__\s*=\s*["\'](\w+)["\']', re.MULTILINE
)
RE_SCHEMA = re.compile(
    r'"schema"\s*:\s*["\'](\w+)["\']', re.MULTILINE
)
RE_COLUMN = re.compile(
    r'^\s+(\w+):\s*Mapped\[', re.MULTILINE
)

# SQL: CREATE TABLE schema.table (  ...  column_name type ...
RE_SQL_TABLE = re.compile(
    r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'(?:(\w+)\.)?(\w+)\s*\(',
    re.IGNORECASE | re.MULTILINE,
)
RE_SQL_COL = re.compile(
    r'^\s+(\w+)\s+(?:UUID|TEXT|VARCHAR|INTEGER|INT|BIGINT|BOOLEAN|FLOAT|'
    r'NUMERIC|TIMESTAMP|JSONB|SERIAL|DOUBLE|REAL|vector)',
    re.IGNORECASE | re.MULTILINE,
)


def parse_orm_models(path: Path) -> dict[str, dict]:
    """Return {schema.table: {columns: set, line: int}}."""
    text = path.read_text(encoding="utf-8")
    # Split by class definitions
    classes = re.split(r'^class \w+\(Base\):', text, flags=re.MULTILINE)
    results: dict[str, dict] = {}
    for block in classes[1:]:
        tbl_m = RE_TABLE.search(block)
        if not tbl_m:
            continue
        table_name = tbl_m.group(1)
        schema_m = RE_SCHEMA.search(block)
        schema = schema_m.group(1) if schema_m else "public"
        key = f"{schema}.{table_name}"
        cols = set()
        for col_m in RE_COLUMN.finditer(block):
            col_name = col_m.group(1)
            if col_name.startswith("_") or col_name in ("metadata",):
                continue
            cols.add(col_name)
        results[key] = {"columns": cols}
    return results


def parse_sql_scripts(sql_dir: Path) -> dict[str, dict]:
    """Return {schema.table: {columns: set, file: str}}."""
    results: dict[str, dict] = {}
    for sql_file in sorted(sql_dir.glob("*.sql")):
        text = sql_file.read_text(encoding="utf-8", errors="replace")
        # Find CREATE TABLE blocks
        for m in RE_SQL_TABLE.finditer(text):
            schema = m.group(1) or "public"
            table = m.group(2)
            key = f"{schema}.{table}"
            # Extract column block (from opening paren to closing)
            start = m.end()
            depth = 1
            pos = start
            while pos < len(text) and depth > 0:
                if text[pos] == "(":
                    depth += 1
                elif text[pos] == ")":
                    depth -= 1
                pos += 1
            block = text[start:pos]
            cols = set()
            for col_m in RE_SQL_COL.finditer(block):
                col_name = col_m.group(1).lower()
                if col_name in ("primary", "unique", "constraint", "foreign", "check", "create", "index"):
                    continue
                cols.add(col_name)
            results[key] = {"columns": cols, "file": sql_file.name}
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ORM ↔ SQL schema alignment")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if not MODELS_PY.exists():
        print(f"ERROR: models.py not found at {MODELS_PY}")
        return 1
    if not SQL_DIR.exists():
        print(f"ERROR: SQL dir not found at {SQL_DIR}")
        return 1

    orm = parse_orm_models(MODELS_PY)
    sql = parse_sql_scripts(SQL_DIR)

    issues: list[str] = []
    warnings: list[str] = []

    # 1. Tables in ORM but not in SQL
    for key in sorted(orm):
        if key not in sql:
            warnings.append(f"  ORM-only table (no SQL init): {key}")

    # 2. Tables in SQL but not in ORM
    for key in sorted(sql):
        if key not in orm:
            if args.verbose:
                warnings.append(f"  SQL-only table (no ORM model): {key}  [{sql[key]['file']}]")

    # 3. Column mismatches for shared tables
    shared = sorted(set(orm) & set(sql))
    for key in shared:
        orm_cols = orm[key]["columns"]
        sql_cols = sql[key]["columns"]
        orm_only = orm_cols - sql_cols
        sql_only = sql_cols - orm_cols
        if orm_only:
            issues.append(f"  {key}: ORM columns missing from SQL: {', '.join(sorted(orm_only))}")
        if sql_only and args.verbose:
            warnings.append(f"  {key}: SQL columns missing from ORM: {', '.join(sorted(sql_only))}")

    # ── Report ───────────────────────────────────────────────────────────────
    print(f"Schema Verification Report")
    print(f"{'='*60}")
    print(f"  ORM models: {len(orm)} tables")
    print(f"  SQL scripts: {len(sql)} tables")
    print(f"  Shared tables: {len(shared)}")
    print()

    if issues:
        print(f"ISSUES ({len(issues)}):")
        for i in issues:
            print(i)
        print()

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings:
            print(w)
        print()

    if not issues and not warnings:
        print("✓ All schema references aligned.")

    if args.verbose:
        print(f"\nORM tables: {', '.join(sorted(orm))}")
        print(f"SQL tables: {', '.join(sorted(sql))}")

    return 1 if issues else 0


if __name__ == "__main__":
    sys.exit(main())
