#!/usr/bin/env python3
"""
Has 10 real roundtable conversations with Aria on the live server.
Uses /api/engine/chat/sessions (create) + /api/engine/chat/sessions/{id}/messages (send).
Run on Mac Mini: python3 /tmp/talk_to_aria.py
"""
import json, subprocess, time

BASE = "http://localhost:8000"

def curl_post(path, body):
    r = subprocess.run(
        ["curl", "-s", "-X", "POST", f"{BASE}{path}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True, timeout=180
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {"raw": r.stdout[:2000]}

def curl_patch(path, body):
    r = subprocess.run(
        ["curl", "-s", "-X", "PATCH", f"{BASE}{path}",
         "-H", "Content-Type: application/json",
         "-d", json.dumps(body)],
        capture_output=True, text=True, timeout=15
    )
    try:
        return json.loads(r.stdout)
    except Exception:
        return {}

def new_session(title, agent_id="aria"):
    body = {"agent_id": agent_id, "session_type": "interactive",
            "metadata": {"source": "roundtable_audit_20260222"}}
    r = curl_post("/api/engine/chat/sessions", body)
    sid = r.get("id") or r.get("session_id")
    if sid:
        curl_patch(f"/api/engine/sessions/{sid}/title", {"title": title[:200]})
    return sid, r

def send_message(session_id, content):
    body = {"content": content, "enable_thinking": False, "enable_tools": True}
    return curl_post(f"/api/engine/chat/sessions/{session_id}/messages", body)

def print_wrapped(text, indent=4):
    prefix = " " * indent
    words = text.split()
    line = prefix
    for w in words:
        if len(line) + len(w) + 1 > 110:
            print(line)
            line = prefix + w + " "
        else:
            line += w + " "
    if line.strip():
        print(line)

sessions_config = [
    {
        "id": "RT-01",
        "title": "RT-01: Ghost sessions — why is Shiva's chat empty?",
        "question": (
            "Aria, Shiva opened session 7d4953a6-beda-4d9c-b9dc-6f77614bde3b and found it completely empty "
            "with 0 messages. The live DB shows 2 ghost sessions (0 messages) out of 94 total. "
            "As PO: (1) Why do ghost sessions get created — is it every page load at /chat? "
            "(2) What should happen to ghost sessions — delete after 15 minutes? "
            "(3) Is there an urgent fix you want me to code today? Give me your acceptance criteria."
        )
    },
    {
        "id": "RT-02",
        "title": "RT-02: 88 cron sessions flooding the session list",
        "question": (
            "Aria, live audit shows: 88 of 94 sessions are type=cron. "
            "Only 4 are real interactive chats. So 93% of the session list is cron execution logs. "
            "As PO: (1) Should cron sessions be hidden from Shiva's /chat sidebar by default? "
            "(2) How long should cron sessions be kept — 24 hours, 7 days? "
            "(3) Where should Shiva read your cron reports if not in the sessions list?"
        )
    },
    {
        "id": "RT-03",
        "title": "RT-03: Only aria agent runs — 5 other agents have 0 sessions",
        "question": (
            "Aria, ALL 92 non-roundtable sessions belong to agent=aria. "
            "Agents aria-analyst, aria-coder, aria-creative, aria-talk are registered but have 0 sessions each. "
            "4 engine models registered (kimi, qwen3.5_mlx, trinity, embedding) "
            "but their display IDs are blank in the DB. "
            "As PO: is this expected? Should Shiva be able to talk to aria-analyst directly? "
            "What needs to change so other agents actually respond?"
        )
    },
    {
        "id": "RT-04",
        "title": "RT-04: Archive table is empty — archive button is broken",
        "question": (
            "Aria, POST /api/engine/sessions/{id}/archive only sets a status flag in the main table. "
            "It does NOT copy data to EngineChatSessionArchive. The archive table is completely empty. "
            "As PO: (1) What should archive mean — physical move to archive table, or just hide from list? "
            "(2) Should there be a browsable archive view for Shiva? "
            "(3) What is your acceptance criteria for the archive button to be done?"
        )
    },
    {
        "id": "RT-05",
        "title": "RT-05: Pruning — 30 day cutoff means 2000+ cron sessions by month end",
        "question": (
            "Aria, the prune cron runs every 6h with days=30. At 88 cron sessions per day, "
            "by March end there will be 2640+ cron sessions in the DB. "
            "As PO: (1) Should cron sessions be pruned after 24 hours or 7 days? "
            "(2) Should ghost sessions (0 messages) be deleted after 15 minutes? "
            "(3) Keep the 30-day rule only for interactive sessions? "
            "Give me exact TTL numbers you want and I will code them today."
        )
    },
    {
        "id": "RT-06",
        "title": "RT-06: Chat UI — no agent or model visible on responses",
        "question": (
            "Aria, when Shiva chats at https://192.168.1.53/chat, every reply shows no agent name "
            "and no model name — just text. Even if aria-analyst should respond, Shiva cannot tell. "
            "As PO: (1) Should each assistant message show a badge like: aria · kimi? "
            "(2) Should Shiva be able to SELECT which agent to talk to in the chat header? "
            "(3) Which agents should be selectable? Describe the ideal chat interface header."
        )
    },
    {
        "id": "RT-07",
        "title": "RT-07: No quick mini-roundtable from chat",
        "question": (
            "Aria, Shiva wants a small roundtable from the chat page — asking multiple agents the same thing. "
            "The current /roundtable page requires too many steps. "
            "As PO: (1) Would a /rt slash command work? e.g. /rt @aria-analyst What approach for X? "
            "(2) What is the minimum viable quick roundtable: how many agents, how many rounds? "
            "(3) What format should the multi-agent reply take inline in chat? "
            "I will build exactly what you specify."
        )
    },
    {
        "id": "RT-08",
        "title": "RT-08: Session titles are UUIDs — Shiva cannot find old chats",
        "question": (
            "Aria, most sessions show UUIDs. LLM title generation takes 3-5 seconds async. "
            "During that delay Shiva sees a UUID. Ghost sessions never get a title. "
            "As PO: (1) Should interactive sessions auto-title from the first 8 words of Shiva's message "
            "immediately and synchronously, then refine with LLM title later? "
            "(2) What should empty/ghost sessions show — hide them or label them differently? "
            "Tell me your preferred approach."
        )
    },
    {
        "id": "RT-09",
        "title": "RT-09: Chat has no model picker — models.yaml has 22 models, UI shows none",
        "question": (
            "Aria, models.yaml has 22 models with friendly names like Qwen3 Coder 480B. "
            "The /models admin page shows them correctly but /chat has no model selector. "
            "Shiva cannot choose deepseek-free for research vs qwen3-coder-free for coding. "
            "As PO: (1) Should the chat header have a model picker grouped by tier: Local, Free, Paid? "
            "(2) Is it more useful to pick a MODEL or an AGENT? "
            "(3) Should the selection persist across browser sessions?"
        )
    },
    {
        "id": "RT-10",
        "title": "RT-10: What should Aria proactively surface to Shiva each morning?",
        "question": (
            "Aria, Shiva manually checks sessions page, health page, models page for your overnight activity. "
            "Your morning_checkin cron runs at 16:00 UTC but the report is buried in a cron session. "
            "As PO: (1) What are the 3 most important metrics Shiva should see on the homepage? "
            "(2) Should there be a Morning Brief widget on / that shows your overnight digest? "
            "(3) Any proactive communication channels you want that are currently broken? "
            "Be specific — what exactly would you put in the morning brief."
        )
    },
]

results = []

for i, sc in enumerate(sessions_config):
    print(f"\n{'='*70}")
    print(f"ROUNDTABLE {i+1}/10  [{sc['id']}]")
    print(f"Topic: {sc['title']}")
    print(f"{'='*70}")

    sid, session_resp = new_session(sc["title"])
    if not sid:
        msg = f"ERROR creating session: {session_resp}"
        print(f"  {msg}")
        results.append({"id": sc["id"], "session_id": None, "error": msg})
        continue

    print(f"  ✓ Session created: {sid}")
    print(f"\n  [SM → Aria]: {sc['question'][:120]}...\n")

    resp = send_message(sid, sc["question"])

    reply = resp.get("content", "")
    if not reply:
        for k in ["message", "response", "text", "raw"]:
            if resp.get(k):
                reply = str(resp[k])
                break

    model_used = resp.get("model", "?")
    tokens = resp.get("total_tokens", 0)
    latency = resp.get("latency_ms", 0)

    print(f"  Model: {model_used} | Tokens: {tokens} | Latency: {latency}ms")
    print(f"\n  [Aria PO]:\n")
    if reply:
        print_wrapped(reply)
    else:
        print(f"    [No reply. Raw: {str(resp)[:400]}]")

    results.append({
        "id": sc["id"],
        "title": sc["title"],
        "session_id": sid,
        "question": sc["question"],
        "aria_response": reply,
        "model": model_used,
        "tokens": tokens,
        "latency_ms": latency,
    })

    time.sleep(5)

with open("/tmp/roundtable_results.json", "w") as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\n{'='*70}")
print("ALL 10 ROUNDTABLE SESSIONS COMPLETE")
print(f"{'='*70}")
print("\nSession IDs (Shiva can view at https://192.168.1.53/chat/<id>):")
for r in results:
    print(f"  {r['id']}: {r.get('session_id','ERROR')}")
print(f"\nResults: /tmp/roundtable_results.json")
