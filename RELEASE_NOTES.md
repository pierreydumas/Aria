# Release Notes — golden-v3

**Release tag:** `golden-v3`  
**Release date:** 2026-02-28  
**Base branch:** `main`  
**Release commit:** `17a76920a428fc75934f1f6eda19ee7549928d69`

## Summary
This release captures a stable production snapshot with heartbeat-contract hardening, clone-safe runtime behavior, and live cron prompt sync verification.

## Highlights

### 1) Work-cycle contract path hardening
- Updated cron job contracts to explicitly read `aria_memories/HEARTBEAT.md` via artifact path, with fallback to `/HEARTBEAT.md`.
- Applied to `work_cycle`, `six_hour_review`, `morning_checkin`, and `daily_reflection`.

### 2) Clone-safe heartbeat availability
- Added API startup self-heal in `src/api/main.py` to auto-seed `aria_memories/HEARTBEAT.md` from canonical heartbeat source when missing.
- Ensures fresh `git clone` environments work even though `aria_memories/` is gitignored.

### 3) Runtime + DB sync validation
- Synced cron YAML to DB with `POST /api/jobs/sync`.
- Verified live payload marker includes `aria_memories/HEARTBEAT.md`.
- Manually triggered `work_cycle` and confirmed injected contract text uses the new path and no legacy phrase.

### 4) Operational readiness checks
- Restarted `aria-api`, `aria-engine`, and `aria-brain` and confirmed healthy state.
- Confirmed artifact endpoint for heartbeat returns HTTP 200.

## Verification done
- `POST /api/jobs/sync` returned updated/unchanged sync status from `cron_jobs.yaml`.
- `GET /api/jobs/live` contained updated contract marker.
- `GET /api/artifacts/memory/HEARTBEAT.md` returned 200.
- Startup self-heal test passed: deleting `aria_memories/HEARTBEAT.md` then restarting API recreated the file.
- `golden-v3` reviewed and updated to release commit above.

## Notes
- This release is intended as a stable baseline snapshot.
- `aria_memories/` remains excluded from git by design; heartbeat runtime copy is now ensured at startup.
