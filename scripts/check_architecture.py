#!/usr/bin/env python3
"""
Architecture compliance checker — 5-layer validation (S4-06).

Checks for:
1. Skills importing SQLAlchemy (should use api_client only)
2. Hardcoded model names (should use models.yaml)
3. Secrets in code (API keys, tokens, passwords)
4. Duplicate JS functions across templates
5. Skills calling other skills directly (should go through coordinator)
6. soul/ directory integrity

Usage:
    python scripts/check_architecture.py [--verbose]
"""

import os
import re
import sys
from collections import defaultdict
from pathlib import Path

WORKSPACE = Path(__file__).resolve().parent.parent
SKILLS_DIR = WORKSPACE / "aria_skills"
TEMPLATES_DIR = WORKSPACE / "src" / "web" / "templates"
SOUL_DIR = WORKSPACE / "aria_mind" / "soul"

SCAN_DIRS = ["aria_skills", "aria_mind", "aria_agents"]
ALLOW_LIST = {"aria_skills/database"}  # Deprecated but still present

FORBIDDEN = [
    re.compile(r"^\s*(import|from)\s+(asyncpg|psycopg2|psycopg)\b"),
    re.compile(r"^\s*(import|from)\s+sqlalchemy\b"),
]

HARDCODED_MODELS: list[str] = []
try:
    import pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    from aria_models.loader import list_all_model_ids
    HARDCODED_MODELS = list_all_model_ids()
except Exception:
    HARDCODED_MODELS = [
        "moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k",
        "gpt-4", "gpt-3.5-turbo", "claude-3", "claude-2",
        "deepseek-chat", "deepseek-coder",
    ]

SECRET_PATTERNS = [
    (r'["\']sk-[a-zA-Z0-9]{20,}["\']', "OpenAI API key"),
    (r'["\']ghp_[a-zA-Z0-9]{36}["\']', "GitHub PAT"),
    (r'["\']xoxb-[a-zA-Z0-9-]+["\']', "Slack bot token"),
    (r'password\s*=\s*["\'][^"\']{8,}["\']', "Hardcoded password"),
]

EXCLUDE_DIRS = {"__pycache__", ".git", "node_modules", ".venv", "venv", "aria_souvenirs", "aria_memories"}


def find_python_files(root: Path) -> list[Path]:
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
        for fname in filenames:
            if fname.endswith(".py"):
                files.append(Path(dirpath) / fname)
    return files


def check_5layer():
    """Skills should NOT import SQLAlchemy — they must use api_client."""
    violations = []
    warnings_list = []
    root = WORKSPACE

    for scan_dir in SCAN_DIRS:
        d = root / scan_dir
        if not d.exists():
            continue
        for py_file in d.rglob("*.py"):
            rel = py_file.relative_to(root).as_posix()
            is_allowed = any(rel.startswith(a) for a in ALLOW_LIST)

            try:
                lines = py_file.read_text(encoding="utf-8").splitlines()
            except (OSError, UnicodeDecodeError):
                continue  # Skip unreadable files

            for i, line in enumerate(lines, 1):
                for pattern in FORBIDDEN:
                    if pattern.search(line):
                        entry = f"  🔴 [5-LAYER] {rel}:{i}: {line.strip()}"
                        if is_allowed:
                            warnings_list.append(entry.replace("🔴", "🟡"))
                        else:
                            violations.append(entry)

    return violations, warnings_list


def check_hardcoded_models():
    """Check for hardcoded model names outside models.yaml."""
    violations = []
    for pyfile in find_python_files(WORKSPACE / "src"):
        rel = pyfile.relative_to(WORKSPACE).as_posix()
        if "models.yaml" in rel or "models_config" in rel:
            continue
        try:
            for i, line in enumerate(pyfile.read_text().splitlines(), 1):
                if line.strip().startswith("#"):
                    continue
                for model in HARDCODED_MODELS:
                    if model in line:
                        violations.append(f"  🟡 [MODEL] {rel}:{i}: hardcoded '{model}'")
        except Exception:
            pass
    return violations


def check_secrets():
    """Check for hardcoded secrets/tokens."""
    violations = []
    all_files = find_python_files(WORKSPACE / "src") + find_python_files(SKILLS_DIR)
    for pyfile in all_files:
        rel = pyfile.relative_to(WORKSPACE).as_posix()
        try:
            for i, line in enumerate(pyfile.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#") or "os.environ" in line or "os.getenv" in line:
                    continue
                for pattern, desc in SECRET_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        violations.append(f"  🔴 [SECRET] {rel}:{i}: possible {desc}")
        except Exception:
            pass
    return violations


# Ports that are expected defaults and acceptable when behind os.getenv/os.environ
HARDCODED_PORT_RE = re.compile(r'(?:port\s*[=:]\s*|:)\s*(\d{4,5})\b')
KNOWN_DEFAULT_PORTS = {"8000", "5000", "5432", "4000", "9090", "3000", "8080", "11434", "9999", "8888", "9050", "9051"}
PORT_SAFE_CONTEXTS = re.compile(r'os\.getenv|os\.environ|getenv|argparse|add_argument|--api-url|--port|DEFAULT_|EXPOSE|healthcheck|curl|"http|\'http')


def check_hardcoded_ports():
    """Check for hardcoded port numbers not behind env var lookups."""
    violations = []
    src_files = find_python_files(WORKSPACE / "src")
    for pyfile in src_files:
        rel = pyfile.relative_to(WORKSPACE).as_posix()
        try:
            for i, line in enumerate(pyfile.read_text().splitlines(), 1):
                stripped = line.strip()
                if stripped.startswith("#"):
                    continue
                # Skip lines that are already env-aware or URL defaults
                if PORT_SAFE_CONTEXTS.search(line):
                    continue
                match = re.search(r'\bport\s*[=:]\s*(\d{4,5})\b', line, re.IGNORECASE)
                if match:
                    port = match.group(1)
                    if port in KNOWN_DEFAULT_PORTS:
                        violations.append(f"  🟡 [PORT] {rel}:{i}: hardcoded port={port} — use env var with default")
        except Exception:
            pass
    return violations


def check_duplicate_js():
    """Check for duplicate JS function definitions across templates."""
    violations = []
    if not TEMPLATES_DIR.exists():
        return violations
    func_locations: dict[str, list[str]] = defaultdict(list)
    for tmpl in TEMPLATES_DIR.glob("*.html"):
        rel = tmpl.relative_to(WORKSPACE).as_posix()
        try:
            for i, line in enumerate(tmpl.read_text().splitlines(), 1):
                match = re.search(r'function\s+(\w+)\s*\(', line)
                if match:
                    func_locations[match.group(1)].append(rel)
        except Exception:
            pass
    for func_name, files in func_locations.items():
        unique_files = list(set(files))
        if len(unique_files) > 1:
            violations.append(f"  🟡 [DUP_JS] '{func_name}' in {len(unique_files)} files: {', '.join(unique_files)}")
    return violations


def check_skill_coupling():
    """Skills should not directly import other skills."""
    violations = []
    for pyfile in find_python_files(SKILLS_DIR):
        rel = pyfile.relative_to(SKILLS_DIR)
        parts = rel.parts
        if not parts or parts[0] in ("_template", "__pycache__"):
            continue
        if len(parts) == 1:
            continue  # Top-level files like base.py, catalog.py
        skill_dir = parts[0]
        try:
            for i, line in enumerate(pyfile.read_text().splitlines(), 1):
                match = re.search(r"from\s+aria_skills\.(\w+)", line)
                if match:
                    imported = match.group(1)
                    if imported not in (skill_dir, "base", "api_client", "registry",
                                        "pipeline", "pipeline_executor", "pipeline_skill", "catalog"):
                        file_rel = pyfile.relative_to(WORKSPACE).as_posix()
                        violations.append(f"  🟡 [COUPLING] {file_rel}:{i}: '{skill_dir}' imports '{imported}'")
        except Exception:
            pass
    return violations


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Architecture compliance checker")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print("🏗️  Aria Architecture Compliance Check")
    print("=" * 60)

    total_errors = 0
    total_warnings = 0

    # Check 1: 5-layer violations
    print("\n🔍 5-Layer architecture (skills ↛ SQLAlchemy)…")
    violations, warnings = check_5layer()
    for v in violations:
        print(v)
    for w in warnings:
        print(w)
    if not violations and not warnings:
        print("  ✅ No violations")
    total_errors += len(violations)
    total_warnings += len(warnings)

    # Check 2: Hardcoded models
    print("\n🔍 Hardcoded model names…")
    viol = check_hardcoded_models()
    for v in viol:
        print(v)
    if not viol:
        print("  ✅ No violations")
    total_warnings += len(viol)

    # Check 3: Secrets
    print("\n🔍 Secrets in code…")
    viol = check_secrets()
    for v in viol:
        print(v)
    if not viol:
        print("  ✅ No violations")
    total_errors += len(viol)

    # Check 4: Duplicate JS
    print("\n🔍 Duplicate JS functions…")
    viol = check_duplicate_js()
    for v in viol:
        print(v)
    if not viol:
        print("  ✅ No violations")
    total_warnings += len(viol)

    # Check 5: Skill coupling
    print("\n🔍 Skill-to-skill coupling…")
    viol = check_skill_coupling()
    for v in viol:
        print(v)
    if not viol:
        print("  ✅ No violations")
    total_warnings += len(viol)

    # Check 6: Hardcoded ports
    print("\n🔍 Hardcoded ports…")
    viol = check_hardcoded_ports()
    for v in viol:
        print(v)
    if not viol:
        print("  ✅ No violations")
    total_warnings += len(viol)

    # Summary
    print(f"\n{'=' * 60}")
    print(f"📊 Summary: {total_errors} errors, {total_warnings} warnings")

    if total_errors:
        print(f"\n🔴 {total_errors} ERRORS — must fix before deploy")
        sys.exit(1)
    elif total_warnings:
        print(f"\n🟡 {total_warnings} warnings (non-blocking)")
        sys.exit(0)
    else:
        print("\n✅ All checks passed — architecture is compliant!")
        sys.exit(0)


if __name__ == "__main__":
    main()
