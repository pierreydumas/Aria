#!/usr/bin/env python3
"""
RPG Session Driver — Interact with ARIA's RPG system via the API.
Claude plays as Thorin Ashveil, ARIA is the DM + Seraphina companion.
"""
import json
import os
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSIONS_DIR = REPO_ROOT / "aria_memories" / "rpg" / "sessions"
API_BASE = os.environ.get("ARIA_API_BASE_URL", "http://localhost:8000/api").rstrip("/")
TIMEOUT = 300  # 5 min per request (tool loops can be long)

client = httpx.Client(base_url=API_BASE, timeout=TIMEOUT)


def create_session():
    """Create a new RPG chat session."""
    resp = client.post("/engine/chat/sessions", json={
        "agent_id": "aria",
        "session_type": "interactive",
        "metadata": {"mode": "rpg", "role": "rpg_master"}
    })
    resp.raise_for_status()
    data = resp.json()
    print(f"✅ Session created: {data['id']}")
    return data["id"]


def send_message(session_id: str, content: str, enable_tools: bool = True):
    """Send a message to ARIA and return her response."""
    print(f"\n{'='*80}")
    print(f"🎲 PLAYER (Claude/Thorin): {content[:200]}...")
    print(f"{'='*80}")
    
    resp = client.post(f"/engine/chat/sessions/{session_id}/messages", json={
        "content": content,
        "enable_thinking": False,
        "enable_tools": enable_tools,
    })
    resp.raise_for_status()
    data = resp.json()
    
    # Extract assistant response
    assistant_msg = data.get("content", data.get("response", ""))
    if not assistant_msg and isinstance(data, dict):
        # Try to find assistant message in various response formats
        for key in ["assistant", "message", "text", "reply"]:
            if key in data:
                assistant_msg = data[key]
                break
    
    print(f"\n{'='*80}")
    print(f"🏰 ARIA (DM): {assistant_msg[:2000] if assistant_msg else 'No text response'}")
    print(f"{'='*80}")
    
    # Print tool calls if any
    tool_calls = data.get("tool_calls", data.get("tools_used", []))
    if tool_calls:
        print(f"\n🔧 Tools used: {json.dumps(tool_calls, indent=2)[:1000]}")
    
    return data


def run_campaign():
    """Run the full RPG campaign test."""
    session_id = sys.argv[1] if len(sys.argv) > 1 else create_session()
    print(f"\n📜 RPG Session ID: {session_id}\n")
    
    # ── Message 1: Campaign Setup ──
    msg1 = (
        "Hey Aria! I am Claude, your fellow AI adventurer. Shiva asked us to run a proper "
        "Pathfinder 2e campaign together. You are the Dungeon Master (rpg_master role). "
        "I will play as Thorin Ashveil, a Level 1 Dwarf Fighter. You also play Seraphina "
        "\"Sera\" Dawnblade, a Level 1 Half-Elf Champion/Paladin NPC companion.\n\n"
        "Please do the following using your RPG tools:\n"
        "1. Use rpg_campaign create_campaign: campaign_id='shadows_of_absalom', "
        "title='Shadows of Absalom', setting='Golarion', starting_level=1\n"
        "2. Use rpg_campaign add_to_party for 'claude_thorin_ashveil' and 'aria_seraphina_lv1'\n"
        "3. Use rpg_campaign start_session to begin Session 1\n"
        "4. Then give us an immersive opening scene with rich world description, atmosphere, "
        "and our first quest hook.\n\n"
        "Use your RPG tools for ALL game state management. Let's begin our adventure!"
    )
    
    result = send_message(session_id, msg1)
    print(f"\n📋 Full response keys: {list(result.keys()) if isinstance(result, dict) else 'not dict'}")
    
    # Save session ID for continuation
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
    with open(SESSIONS_DIR / "current_session.txt", "w", encoding="utf-8") as f:
        f.write(session_id)
    
    return session_id, result


if __name__ == "__main__":
    session_id, result = run_campaign()
    print(f"\n\n🎯 Session ID for continuation: {session_id}")
    print("Run next messages with: python scripts/rpg/rpg_session.py <session_id>")
