#!/usr/bin/env python3
"""Check RPG tool registration and agent configs."""
import httpx
import json

API = "http://localhost:8000/api"
client = httpx.Client(base_url=API, timeout=30)

print("=== AGENTS AND SKILLS ===")
try:
    resp = client.get("/engine/agents")
    agents = resp.json()
    items = agents.get("items", agents if isinstance(agents, list) else [])
    for a in items:
        aid = a.get("agent_id", "?")
        skills = a.get("skills", [])
        enabled = a.get("enabled", "?")
        print(f"  Agent: {aid} | enabled={enabled} | skills={skills}")
except Exception as e:
    print(f"  Error fetching agents: {e}")

print()
print("=== REGISTERED TOOLS ===")
try:
    resp2 = client.get("/engine/tools")
    tools = resp2.json()
    if isinstance(tools, list):
        print(f"  Total tools: {len(tools)}")
        rpg_tools = [t for t in tools if "rpg" in (t.get("name", "") + t.get("skill", "")).lower()]
        print(f"  RPG tools: {len(rpg_tools)}")
        for t in rpg_tools[:20]:
            print(f"    {t['name']} (skill={t.get('skill','?')})")
        
        # Also check knowledge_graph tools
        kg_tools = [t for t in tools if "knowledge" in (t.get("name", "") + t.get("skill", "")).lower()]
        print(f"  Knowledge graph tools: {len(kg_tools)}")
        for t in kg_tools[:10]:
            print(f"    {t['name']} (skill={t.get('skill','?')})")
    elif isinstance(tools, dict):
        print(f"  Response keys: {list(tools.keys())}")
        if "items" in tools:
            items = tools["items"]
            print(f"  Total tools: {len(items)}")
            rpg_tools = [t for t in items if "rpg" in str(t).lower()]
            print(f"  RPG tools: {len(rpg_tools)}")
            for t in rpg_tools[:20]:
                print(f"    {t}")
        else:
            print(f"  Full response: {json.dumps(tools, indent=2)[:500]}")
except Exception as e:
    print(f"  Error fetching tools: {e}")

print()
print("=== ROUNDTABLES ===")
try:
    resp3 = client.get("/engine/roundtable")
    rt = resp3.json()
    print(f"  Response: {json.dumps(rt, indent=2)[:500]}")
except Exception as e:
    print(f"  Error: {e}")
