import json
import os
import ssl
import urllib.request
import urllib.error
from pathlib import Path

BASE = os.getenv("ARIA_BASE_URL", "http://localhost:8000").rstrip("/")
API = BASE + "/api"


def resolve_key() -> str:
    key = (os.getenv("ARIA_API_KEY") or "").strip()
    if key:
        return key
    for candidate in (Path(".env"), Path("stacks/brain/.env")):
        if not candidate.exists():
            continue
        for line in candidate.read_text(errors="ignore").splitlines():
            if line.startswith("ARIA_API_KEY="):
                value = line.split("=", 1)[1].strip()
                value = value.strip("'").strip('"')
                if value:
                    return value
    return ""


def api_get(path: str, key: str) -> dict:
    headers = {"X-API-Key": key} if key else {}
    req = urllib.request.Request(API + path, headers=headers)
    ctx = ssl._create_unverified_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8", "ignore"))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return {"_http_404": True}
        raise


def main() -> int:
    key = resolve_key()
    if not key:
        print("WARN: ARIA_API_KEY not found; continuing without auth header")

    sessions = api_get("/engine/chat/sessions?page=1&page_size=30", key).get("items", [])
    rows = []

    for session in sessions:
        session_id = session["id"]
        tab_tokens = int(session.get("total_tokens") or 0)
        message_resp = api_get(f"/engine/chat/sessions/{session_id}/messages", key)
        if message_resp.get("_http_404"):
            rows.append(
                {
                    "id": session_id,
                    "session_type": session.get("session_type"),
                    "msg_tab": int(session.get("message_count") or 0),
                    "msg_real": None,
                    "tokens_tab": tab_tokens,
                    "tokens_sum": None,
                    "delta": None,
                    "note": "messages endpoint 404",
                }
            )
            continue

        messages = message_resp.get("messages", [])
        message_tokens_sum = 0
        for msg in messages:
            try:
                message_tokens_sum += int(msg.get("tokens_input") or 0) + int(msg.get("tokens_output") or 0)
            except (ValueError, TypeError):
                # Skip messages with invalid token counts
                continue

        rows.append(
            {
                "id": session_id,
                "session_type": session.get("session_type"),
                "msg_tab": int(session.get("message_count") or 0),
                "msg_real": len(messages),
                "tokens_tab": tab_tokens,
                "tokens_sum": message_tokens_sum,
                "delta": tab_tokens - message_tokens_sum,
            }
        )

    comparable = [r for r in rows if r.get("delta") is not None]
    non_comparable = [r for r in rows if r.get("delta") is None]
    mismatches = [r for r in comparable if r["delta"] != 0 or r["msg_tab"] != r["msg_real"]]

    print("base", BASE)
    print("checked", len(rows))
    print("comparable_rows", len(comparable))
    print("unavailable_rows", len(non_comparable))
    print("mismatch_rows", len(mismatches))
    for row in non_comparable[:20]:
        print(json.dumps(row, ensure_ascii=False))
    for row in mismatches[:20]:
        print(json.dumps(row, ensure_ascii=False))

    generic = api_get("/sessions?page=1&limit=30", key).get("items", [])
    tab_by_id = {r["id"]: r["tokens_tab"] for r in rows}
    generic_mismatch = 0
    for row in generic:
        sid = row.get("id")
        if sid in tab_by_id and int(row.get("tokens_used") or 0) != int(tab_by_id[sid]):
            generic_mismatch += 1

    print("generic_vs_engine_mismatch", generic_mismatch)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
