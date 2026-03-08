#!/usr/bin/env python3
"""Launch RPG roundtable sessions with ARIA's multi-agent system."""
from __future__ import annotations
import os
import httpx
import json
import sys
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
BASE_URL = os.environ.get("ARIA_BASE_URL", "http://localhost:8000").rstrip("/")
SESSIONS_DIR = REPO_ROOT / "aria_memories" / "rpg" / "sessions"


def launch_roundtable(topic: str, agent_ids: list[str], rounds: int = 3,
                      synthesizer_id: str = "rpg_master",
                      agent_timeout: int = 120, total_timeout: int = 600,
                      save_as: Optional[str] = None):
    """POST a roundtable and return the response."""
    payload = {
        "topic": topic,
        "agent_ids": agent_ids,
        "rounds": rounds,
        "synthesizer_id": synthesizer_id,
        "agent_timeout": agent_timeout,
        "total_timeout": total_timeout,
    }
    print(f"Launching roundtable with agents: {agent_ids}")
    print(f"Rounds: {rounds}, Timeout: {total_timeout}s")
    print(f"Topic: {topic[:120]}...")
    print("---")

    resp = httpx.post(
        f"{BASE_URL}/api/engine/roundtable/async",
        json=payload,
        verify=False,
        timeout=30,
    )
    print(f"Status: {resp.status_code}")
    print(f"Content-Type: {resp.headers.get('content-type', 'none')}")
    print(f"Response length: {len(resp.content)} bytes")

    if resp.status_code >= 400 or not resp.content:
        print(f"Raw response: {resp.text[:1000]}")
        return {"error": resp.text, "status_code": resp.status_code}

    init_data = resp.json()
    tracking_key = init_data.get("session_id", "")
    print(f"Roundtable launched! Tracking key: {tracking_key}")
    print(f"Initial: {json.dumps(init_data, indent=2)}")

    # Poll for completion
    import time
    max_wait = total_timeout + 60
    start = time.time()
    while time.time() - start < max_wait:
        time.sleep(15)
        elapsed = int(time.time() - start)
        status_resp = httpx.get(
            f"{BASE_URL}/api/engine/roundtable/status/{tracking_key}",
            verify=False, timeout=10,
        )
        if status_resp.status_code == 404:
            print(f"  [{elapsed}s] Status: not found yet, waiting...")
            continue
        status_data = status_resp.json()
        st = status_data.get("status", "unknown")
        print(f"  [{elapsed}s] Status: {st}")

        if st == "completed":
            session_id = status_data.get("session_id", tracking_key)
            # Fetch full roundtable result
            detail_resp = httpx.get(
                f"{BASE_URL}/api/engine/roundtable/{session_id}",
                verify=False, timeout=30,
            )
            if detail_resp.status_code == 200:
                data = detail_resp.json()
            else:
                data = status_data
            break
        elif st == "failed":
            print(f"  FAILED: {status_data.get('error', 'unknown')}")
            data = status_data
            break
    else:
        print("  TIMEOUT waiting for roundtable completion")
        data = {"error": "timeout", "tracking_key": tracking_key}

    if save_as:
        out = SESSIONS_DIR / save_as
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        print(f"Saved to {out}")

    return data


def print_roundtable_summary(data: dict):
    """Print a summary of roundtable results."""
    if "detail" in data:
        print(f"ERROR: {data['detail']}")
        return

    roundtable_id = data.get("roundtable_id", "?")
    status = data.get("status", "?")
    participants = data.get("participants", [])
    rounds = data.get("rounds", [])
    synthesis = data.get("synthesis", "")
    tool_calls = data.get("tool_calls_summary", [])

    print(f"\nRoundtable: {roundtable_id}")
    print(f"Status: {status}")
    print(f"Participants: {participants}")
    print(f"Rounds: {len(rounds)}")

    for i, rnd in enumerate(rounds):
        print(f"\n--- Round {i+1} ---")
        if isinstance(rnd, dict):
            for agent_id, response in rnd.items():
                if isinstance(response, str):
                    text = response
                elif isinstance(response, dict):
                    text = response.get("content", response.get("message", str(response)))
                else:
                    text = str(response)
                preview = text[:300].replace("\n", " ")
                print(f"  [{agent_id}]: {preview}...")
        elif isinstance(rnd, list):
            for entry in rnd:
                if isinstance(entry, dict):
                    agent = entry.get("agent_id", "?")
                    content = entry.get("content", entry.get("message", ""))
                    preview = content[:300].replace("\n", " ")
                    print(f"  [{agent}]: {preview}...")

    if synthesis:
        preview = synthesis[:500] if isinstance(synthesis, str) else json.dumps(synthesis)[:500]
        print(f"\n=== SYNTHESIS (rpg_master) ===\n{preview}")

    if tool_calls:
        print(f"\n=== TOOL CALLS ===")
        for tc in tool_calls[:20]:
            print(f"  {tc}")


# --- Campaign Setup Roundtable ---
CAMPAIGN_SETUP_TOPIC = """BEGIN NEW CAMPAIGN: Shadows of Absalom - Pathfinder 2e

You are starting a new Pathfinder 2e campaign called Shadows of Absalom set in Golarion.

IMPORTANT INSTRUCTIONS FOR EACH AGENT:

rpg_master (Dungeon Master):
1. Use rpg_campaign__create_campaign tool: campaign_id=shadows_of_absalom, title=Shadows of Absalom, setting=Golarion, starting_level=1
2. Use rpg_campaign__add_to_party for: claude_thorin_ashveil.yaml and aria_seraphina_lv1.yaml
3. Use rpg_campaign__start_session to begin session 1
4. Describe the opening scene: the party arrives at the Precipice Quarter of Absalom at dusk
5. Use rpg_pathfinder__roll for any dice rolls needed
6. Use knowledge_graph__add_entity to store key NPCs and locations

rpg_npc (NPC Controller):
- Play a nervous city guard named Sergeant Varen who warns the party about recent disappearances in the Precipice Quarter
- Use knowledge_graph__add_entity to register your NPC (name=Sergeant Varen, entity_type=npc)
- Respond to Thorin asking about the disappearances with details: 7 people missing over 3 weeks, all from near the old Azlanti ruins

rpg_paladin (Seraphina Dawnblade, Half-Elf Champion Lv1):
- React to the scene, show concern for the missing people
- Offer to help investigate as a servant of Sarenrae
- Ask Thorin what he thinks about the situation

PLAYER INPUT (Thorin Ashveil, Dwarf Fighter Lv1, played by Claude):
I grip my warhammer tightly and look around the crumbling buildings of the Precipice Quarter. Something feels wrong in the air. I turn to the guard and ask: Tell me more about these disappearances. How many and since when?

Use rpg_pathfinder and rpg_campaign tools for ALL dice rolls, checks, and state tracking. Store entities in knowledge_graph."""


if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "setup"

    if mode == "setup":
        data = launch_roundtable(
            topic=CAMPAIGN_SETUP_TOPIC,
            agent_ids=["rpg_master", "rpg_npc", "rpg_paladin"],
            rounds=3,
            synthesizer_id="rpg_master",
            agent_timeout=120,
            total_timeout=600,
            save_as="roundtable1_setup.json",
        )
        print_roundtable_summary(data)

    elif mode == "custom":
        topic = sys.argv[2] if len(sys.argv) > 2 else "Continue the campaign"
        agents = sys.argv[3].split(",") if len(sys.argv) > 3 else ["rpg_master", "rpg_npc", "rpg_paladin"]
        data = launch_roundtable(
            topic=topic,
            agent_ids=agents,
            rounds=3,
            synthesizer_id="rpg_master",
            save_as="roundtable_custom.json",
        )
        print_roundtable_summary(data)

    else:
        print(f"Usage: {sys.argv[0]} [setup|custom] [topic] [agent1,agent2,...]")
