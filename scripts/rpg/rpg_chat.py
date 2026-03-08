#!/usr/bin/env python3
"""Send messages to specific RPG agents via chat sessions with tool execution."""
from __future__ import annotations
import os
import httpx
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("ARIA_BASE_URL", "http://localhost:8000").rstrip("/")
OUTDIR = REPO_ROOT / "aria_memories" / "rpg" / "sessions"


def create_session(agent_id: str, title: str) -> str:
    """Create a new chat session for a specific agent."""
    r = httpx.post(
        f"{BASE}/api/engine/chat/sessions",
        json={"agent_id": agent_id, "title": title},
        verify=False, timeout=15,
    )
    r.raise_for_status()
    d = r.json()
    sid = d.get("id") or d.get("session_id")
    print(f"Created session {sid} for agent={agent_id}")
    return sid


def send_message(session_id: str, message: str, agent_id: str = None) -> dict:
    """Send a message and get the response (with tool execution)."""
    payload = {"content": message, "enable_tools": True}
    r = httpx.post(
        f"{BASE}/api/engine/chat/sessions/{session_id}/messages",
        json=payload,
        verify=False, timeout=180,
    )
    if r.status_code != 200:
        print(f"Error {r.status_code}: {r.text[:500]}")
    r.raise_for_status()
    return r.json()


def extract_tool_calls(response: dict) -> list:
    """Extract tool calls from a response."""
    calls = []
    tc = response.get("tool_calls") or []
    for t in tc:
        if isinstance(t, dict):
            fn = t.get("function", {})
            calls.append({
                "name": fn.get("name", "?"),
                "args": fn.get("arguments", ""),
            })
    return calls


def print_response(resp: dict, label: str = ""):
    """Print a formatted response."""
    content = resp.get("content", resp.get("message", ""))
    tools = extract_tool_calls(resp)
    model = resp.get("model", "?")

    if label:
        print(f"\n{'='*60}")
        print(f"  {label}")
        print(f"{'='*60}")
    print(f"Model: {model}")
    if tools:
        print(f"Tool calls: {len(tools)}")
        for tc in tools:
            print(f"  -> {tc['name']}")
    preview = content[:1500] if content else "(no content)"
    print(preview)


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "setup"

    if mode == "setup":
        # Create campaign via rpg_master with tool execution
        sid = create_session("rpg_master", "Shadows of Absalom - Campaign Setup")
        print(f"\nSession: {sid}")

        # Message 1: Create campaign
        print("\n--- Creating campaign ---")
        r1 = send_message(sid, (
            "You are the Dungeon Master for a Pathfinder 2e campaign. "
            "Create a new campaign using the rpg_campaign tools: "
            "campaign_id 'shadows_of_absalom', title 'Shadows of Absalom', "
            "setting 'Golarion', starting_level 1. "
            "Then add two characters to the party: "
            "claude_thorin_ashveil.yaml and aria_seraphina_lv1.yaml. "
            "Then start session 1."
        ))
        print_response(r1, "Campaign Setup")

        # Save
        out = OUTDIR / "rpg_master_setup.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(r1, indent=2, ensure_ascii=False))
        print(f"\nSaved to {out}")

        # Save session ID
        (OUTDIR / "rpg_master_session_id.txt").write_text(sid)

        # Message 2: Store entities in knowledge graph
        print("\n--- Knowledge Graph ---")
        r2 = send_message(sid, (
            "Now store the key campaign entities in the knowledge graph: "
            "1. Add entity 'Shadows of Absalom' type 'campaign' "
            "2. Add entity 'Precipice Quarter' type 'location' "
            "3. Add entity 'Thorin Ashveil' type 'player_character' "
            "4. Add entity 'Seraphina Dawnblade' type 'player_character' "
            "5. Add entity 'Sergeant Varen' type 'npc' "
            "6. Add relations between them."
        ))
        print_response(r2, "Knowledge Graph")
        (OUTDIR / "rpg_master_kg.json").write_text(json.dumps(r2, indent=2, ensure_ascii=False))

    elif mode == "dice":
        # Test dice rolling
        sid_file = OUTDIR / "rpg_master_session_id.txt"
        if not sid_file.exists():
            print("Run 'setup' first")
            sys.exit(1)
        sid = sid_file.read_text().strip()

        print("\n--- Testing Dice Rolls ---")
        r = send_message(sid, (
            "Roll initiative for a combat encounter! "
            "Use rpg_pathfinder tools to roll: "
            "1. Thorin Ashveil initiative (d20+4 Perception) "
            "2. Seraphina Dawnblade initiative (d20+3 Perception) "
            "3. Two Goblin Warriors initiative (d20+2 each) "
            "Report the initiative order."
        ))
        print_response(r, "Initiative Rolls")
        (OUTDIR / "rpg_master_dice.json").write_text(json.dumps(r, indent=2, ensure_ascii=False))

    else:
        print(f"Usage: {sys.argv[0]} [setup|dice]")
