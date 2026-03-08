#!/usr/bin/env python3
"""RPG Session Driver — Send messages to ARIA for Pathfinder 2e campaign."""
import json
import os
import sys
from pathlib import Path

# Ensure we use the right python
try:
    import httpx
except ImportError:
    os.system("pip install httpx")
    import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = REPO_ROOT / "aria_memories" / "rpg" / "sessions"
API = os.environ.get("ARIA_API_BASE_URL", "http://localhost:8000/api").rstrip("/")
TIMEOUT = 600
SESSION_FILE = SESSIONS_DIR / "active_session_id.txt"


def get_client():
    return httpx.Client(base_url=API, timeout=TIMEOUT)


def create_session(client):
    resp = client.post("/engine/chat/sessions", json={
        "agent_id": "aria",
        "session_type": "interactive",
        "metadata": {"mode": "rpg", "role": "rpg_master"}
    })
    resp.raise_for_status()
    data = resp.json()
    session_id = data["id"]
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSION_FILE, "w", encoding="utf-8") as f:
        f.write(session_id)
    print(f"[NEW SESSION] {session_id}")
    return session_id


def load_session():
    if os.path.exists(SESSION_FILE):
        with open(SESSION_FILE, encoding="utf-8") as f:
            return f.read().strip()
    return None


def check_session(client, session_id):
    """Check if session is still active."""
    try:
        resp = client.get(f"/engine/chat/sessions/{session_id}")
        if resp.status_code == 200:
            data = resp.json()
            return data.get("status") == "active"
    except Exception:
        pass
    return False


def send(client, session_id, content, msg_num=0):
    """Send a message and save the response."""
    print(f"\n{'='*80}")
    print(f"[MSG {msg_num}] Sending to {session_id[:12]}...")
    print(f"{'='*80}")
    
    resp = client.post(f"/engine/chat/sessions/{session_id}/messages", json={
        "content": content,
        "enable_thinking": False,
        "enable_tools": True,
    })
    resp.raise_for_status()
    data = resp.json()
    
    # Save response
    path = SESSIONS_DIR / f"session1_msg{msg_num}_response.json"
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    content_text = data.get("content", "") or ""
    tools = data.get("tool_calls") or []
    results = data.get("tool_results") or []
    
    print(f"\n[ARIA DM] ({len(content_text)} chars, {len(tools)} tool calls)")
    print(content_text[:5000])
    
    if tools:
        print(f"\n[TOOLS]")
        for t in tools[:8]:
            name = t.get("function", {}).get("name", "?")
            print(f"  - {name}")
    if results:
        for r in results[:8]:
            ok = "OK" if r.get("success") else "FAIL"
            print(f"  [{ok}] {r.get('name', '?')}")
    
    return data, path


def main():
    client = get_client()
    
    # Get or create session
    session_id = load_session()
    if session_id and check_session(client, session_id):
        print(f"[RESUME] Session {session_id}")
    else:
        print("[INFO] Creating new session...")
        session_id = create_session(client)
    
    # Read message from argv or stdin
    if len(sys.argv) > 1:
        msg_file = sys.argv[1]
        msg_num = int(sys.argv[2]) if len(sys.argv) > 2 else 0
        with open(msg_file, encoding="utf-8") as f:
            content = f.read()
    else:
        print("Usage: python scripts/rpg/rpg_send.py <message_file> [msg_num]")
        print("  Or pipe: echo 'message' | python scripts/rpg/rpg_send.py - [msg_num]")
        sys.exit(1)
    
    if msg_file == "-":
        content = sys.stdin.read()
    
    result, saved_path = send(client, session_id, content, msg_num)
    print(f"\n[SAVED] {saved_path}")


if __name__ == "__main__":
    main()
