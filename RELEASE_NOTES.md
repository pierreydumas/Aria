# Release Notes — glden-v3

**Release tag:** `glden-v3`  
**Release date:** 2026-02-28  
**Base branch:** `main`  
**Release commit:** `c9edfa9a5ec20f008fb9ec998b0d0d7660909ee1`

## Summary
This release captures a stable production snapshot of Aria Blue with validated orchestration safeguards, improved sessions/token observability, resilient chat UX behavior, and a streamlined dashboard footer.

## Highlights

### 1) Sub-agent churn protection
- Added a cooldown breaker in `agent_manager` sub-agent communication paths to prevent repeated failure loops.
- Result: repeated failing calls are short-circuited during cooldown windows.

### 2) Chat stream recovery UX
- Improved chat UI handling for interrupted websocket streams.
- Result: controls recover correctly after backend restart/disconnect events.

### 3) Sessions token clarity
- Sessions recent table now splits token display into:
  - **Chat Tokens** (full session token total)
  - **Output Tokens** (assistant visible output token signal)
- Backend `/api/sessions` now provides explicit `chat_tokens` and `model_tokens` fields.

### 4) Footer polish
- Global footer simplified for professional presentation.
- Footer now links brand to: `https://datascience-adventure.xyz/`
- Footer copyright text standardized to:
  - `© 2026 Aria Blue. All rights reserved.`

## Verification done
- API + web services restarted and smoke checked.
- Live sessions page verified for new token column headers.
- Footer content and external link verified in served HTML.
- Branch/tag release hygiene completed:
  - Only `main` branch remains (local + remote)
  - Legacy tags removed
  - `glden-v3` tag pushed to origin

## Notes
- This release is intended as a stable baseline snapshot.
- If future patching is needed, branch from `main` and create a new tag rather than mutating `glden-v3`.
