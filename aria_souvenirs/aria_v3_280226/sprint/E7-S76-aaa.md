# E7-S76 — engine_focus.html: Focus Profile Management UI
**Epic:** E7 — Focus System v2 | **Priority:** P2 | **Points:** 3 | **Phase:** 4  
**Status:** NOT STARTED | **Depends on:** E7-S71 (engine_focus.py CRUD API live)  
**Familiar Value:** The focus system is operational after S70–S74 but invisible. This page is Shiva's control plane: see all 8 profiles at a glance, toggle levels, edit prompt addons, and adjust token budgets — without writing a single line of JSON. Over years of use, adjusting Aria's personalities without code deploys is the difference between a living familiar and a static configuration.

---

## Problem

`aria_engine.focus_profiles` table is live (S-70). CRUD API is registered at `/api/engine/focus` (S-71). But there is **no management page** — the only way to view or edit focus profiles is via raw `curl` calls. Specifically:

- No visual representation of delegation levels (L1/L2/L3)
- No way to see `token_budget_hint` as a visual budget bar
- No in-browser editing of `system_prompt_addon` (the most important field)
- The existing `engine_agents_mgmt.html` focus dropdown is still static HTML

---

## Fix

### Create `src/web/templates/engine_focus.html`

**Verify template directory location:**
```bash
ls src/web/templates/*.html | head -5
```
Use the actual path. If templates are elsewhere (e.g. `src/api/templates/`), adjust accordingly.

**Full file:**

```html
{% extends "base.html" %}
{% block title %}Focus Profiles — Aria Engine{% endblock %}

{% block head %}
<style>
  .focus-card {
    background: #fff; border: 1px solid #dee2e6; border-radius: 10px;
    padding: 16px; margin-bottom: 14px; transition: box-shadow 0.15s;
  }
  .focus-card:hover { box-shadow: 0 2px 10px rgba(0,0,0,0.08); }
  .focus-card.disabled-card { opacity: 0.55; }
  .badge-l1 { background: #8b5cf6; }
  .badge-l2 { background: #0d6efd; }
  .badge-l3 { background: #6c757d; }
  .level-badge {
    display: inline-block; font-size: 0.7rem; font-weight: 700;
    padding: 2px 8px; border-radius: 20px; color: #fff; letter-spacing: 0.5px;
  }
  .budget-bar-wrap { background: #e9ecef; border-radius: 4px; height: 6px; margin-top: 4px; }
  .budget-bar { height: 6px; border-radius: 4px; background: linear-gradient(to right, #28a745, #ffc107, #dc3545); }
  .keyword-chip {
    display: inline-block; background: #e9f2ff; color: #0d6efd;
    border-radius: 20px; padding: 1px 9px; font-size: 0.75rem; margin: 2px;
  }
  .addon-preview {
    font-family: monospace; font-size: 0.8rem; background: #f8f9fa;
    border: 1px solid #dee2e6; border-radius: 6px; padding: 8px 12px;
    max-height: 60px; overflow: hidden; white-space: pre-wrap;
    cursor: pointer; color: #495057;
  }
</style>
{% endblock %}

{% block content %}
<div class="container-fluid py-3">
  <div class="d-flex justify-content-between align-items-center mb-3">
    <div>
      <h4 class="mb-0">🎭 Focus Profiles</h4>
      <small class="text-muted">
        <span id="totalCount">0</span> profiles |
        <span id="enabledCount">0</span> enabled
      </small>
    </div>
    <div class="d-flex gap-2">
      <button class="btn btn-sm btn-outline-secondary" onclick="loadProfiles()">🔄 Refresh</button>
      <button class="btn btn-sm btn-success" onclick="openNew()">+ New Profile</button>
      <button class="btn btn-sm btn-outline-primary" onclick="seedProfiles()">🌱 Seed Defaults</button>
    </div>
  </div>
  <div id="profileGrid" class="row g-3">
    <div class="col-12 text-muted p-3">Loading...</div>
  </div>
</div>

<!-- Edit Modal -->
<div class="modal fade" id="editModal" tabindex="-1">
<div class="modal-dialog modal-lg modal-dialog-scrollable">
<div class="modal-content">
  <div class="modal-header">
    <h5 class="modal-title" id="editModalTitle">Focus Profile</h5>
    <button type="button" class="btn-close" data-bs-dismiss="modal"></button>
  </div>
  <div class="modal-body">
  <form id="editForm">
    <input type="hidden" id="fld_mode"><!-- "new" or "edit" -->
    <div class="row g-3">
      <div class="col-md-5">
        <label class="form-label fw-semibold">Focus ID <span class="text-danger">*</span></label>
        <input type="text" class="form-control form-control-sm" id="fld_focus_id" placeholder="e.g. devsecops">
      </div>
      <div class="col-md-5">
        <label class="form-label fw-semibold">Display Name</label>
        <input type="text" class="form-control form-control-sm" id="fld_display_name">
      </div>
      <div class="col-md-2">
        <label class="form-label fw-semibold">Emoji</label>
        <input type="text" class="form-control form-control-sm" id="fld_emoji" value="🎯">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Delegation Level</label>
        <select class="form-select form-select-sm" id="fld_delegation_level">
          <option value="1">L1 — Orchestrator</option>
          <option value="2" selected>L2 — Specialist</option>
          <option value="3">L3 — Ephemeral</option>
        </select>
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Token Budget</label>
        <input type="number" class="form-control form-control-sm" id="fld_token_budget_hint"
               min="100" max="8000" step="100" value="2000">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Temp Delta</label>
        <input type="number" class="form-control form-control-sm" id="fld_temperature_delta"
               min="-0.5" max="0.5" step="0.05" value="0">
        <div class="form-text">Additive to agent base temp (clamped 0–1)</div>
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Tone</label>
        <input type="text" class="form-control form-control-sm" id="fld_tone" placeholder="precise">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Style</label>
        <input type="text" class="form-control form-control-sm" id="fld_style" placeholder="directive">
      </div>
      <div class="col-md-4">
        <label class="form-label fw-semibold">Model Override</label>
        <input type="text" class="form-control form-control-sm" id="fld_model_override"
               placeholder="(slug from models.yaml or blank)">
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold">Expertise Keywords <span class="text-muted">(comma-separated)</span></label>
        <input type="text" class="form-control form-control-sm" id="fld_keywords"
               placeholder="deploy, docker, security, ci, cd">
        <div class="form-text">Used for DB-driven routing (S-72). Each term becomes a regex fragment.</div>
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold">Auto Skills <span class="text-muted">(comma-separated skill IDs)</span></label>
        <input type="text" class="form-control form-control-sm" id="fld_auto_skills"
               placeholder="ci_cd, database, pytest_runner">
      </div>
      <div class="col-12">
        <label class="form-label fw-semibold">System Prompt Addon</label>
        <textarea class="form-control form-control-sm font-monospace"
                  id="fld_system_prompt_addon" rows="5"
                  placeholder="Appended to agent system_prompt when this focus is active. Additive only — never replaces."></textarea>
      </div>
      <div class="col-12">
        <div class="form-check">
          <input class="form-check-input" type="checkbox" id="fld_enabled" checked>
          <label class="form-check-label" for="fld_enabled">Enabled</label>
        </div>
      </div>
    </div>
  </form>
  </div>
  <div class="modal-footer">
    <button class="btn btn-sm btn-outline-danger" id="btnDelete" onclick="deleteProfile()" style="display:none">🗑 Delete</button>
    <button class="btn btn-sm btn-secondary" data-bs-dismiss="modal">Cancel</button>
    <button class="btn btn-sm btn-primary" onclick="saveProfile()">💾 Save</button>
  </div>
</div></div></div>

<script>
const API = '/api/engine/focus';
const KEY = document.cookie.match(/aria_api_key=([^;]+)/)?.[1] || '';
const H = {'Content-Type':'application/json', 'Authorization':'Bearer ' + KEY};
const LEVEL_BADGE = {1:'<span class="level-badge badge-l1">L1</span>',
                     2:'<span class="level-badge badge-l2">L2</span>',
                     3:'<span class="level-badge badge-l3">L3</span>'};
const MAX_BUDGET = 4096;

async function loadProfiles() {
  const r = document.getElementById('profileGrid');
  r.innerHTML = '<div class="col-12 text-muted">Loading...</div>';
  const res = await fetch(API, {headers:H});
  const profiles = await res.json();
  document.getElementById('totalCount').textContent = profiles.length;
  document.getElementById('enabledCount').textContent = profiles.filter(p=>p.enabled).length;
  if (!profiles.length) { r.innerHTML = '<div class="col-12 text-muted p-3">No profiles. Click Seed Defaults.</div>'; return; }
  r.innerHTML = profiles.map(p => {
    const pct = Math.round((p.token_budget_hint / MAX_BUDGET) * 100);
    const kws = (p.expertise_keywords||[]).slice(0,6).map(k=>`<span class="keyword-chip">${k}</span>`).join('');
    return `
    <div class="col-md-6 col-xl-4">
      <div class="focus-card ${p.enabled?'':'disabled-card'}" onclick="openEdit('${p.focus_id}')">
        <div class="d-flex justify-content-between align-items-start mb-1">
          <div>
            <span style="font-size:1.3rem">${p.emoji||'🎯'}</span>
            <strong class="ms-1">${p.display_name}</strong>
            ${LEVEL_BADGE[p.delegation_level]||''}
            ${p.enabled?'':'<span class="badge bg-secondary ms-1">disabled</span>'}
          </div>
          <small class="text-muted">${p.focus_id}</small>
        </div>
        <div class="text-muted" style="font-size:0.8rem">${p.description||''}</div>
        <div class="mt-2">
          <small class="text-muted">Budget: <strong>${p.token_budget_hint}</strong> tok</small>
          <div class="budget-bar-wrap"><div class="budget-bar" style="width:${pct}%"></div></div>
        </div>
        <div class="mt-1">${kws}</div>
        ${p.system_prompt_addon ? `<div class="addon-preview mt-2">${p.system_prompt_addon.substring(0,200)}</div>` : ''}
      </div>
    </div>`;
  }).join('');
}

function openNew() {
  document.getElementById('fld_mode').value = 'new';
  document.getElementById('editModalTitle').textContent = 'New Focus Profile';
  document.getElementById('editForm').reset();
  document.getElementById('fld_emoji').value = '🎯';
  document.getElementById('fld_delegation_level').value = '2';
  document.getElementById('fld_token_budget_hint').value = '2000';
  document.getElementById('fld_temperature_delta').value = '0';
  document.getElementById('btnDelete').style.display = 'none';
  new bootstrap.Modal(document.getElementById('editModal')).show();
}

async function openEdit(focus_id) {
  const res = await fetch(`${API}/${focus_id}`, {headers:H});
  const p = await res.json();
  document.getElementById('fld_mode').value = 'edit';
  document.getElementById('editModalTitle').textContent = `Edit — ${p.display_name}`;
  document.getElementById('fld_focus_id').value = p.focus_id;
  document.getElementById('fld_focus_id').disabled = true;
  document.getElementById('fld_display_name').value = p.display_name||'';
  document.getElementById('fld_emoji').value = p.emoji||'🎯';
  document.getElementById('fld_delegation_level').value = p.delegation_level||2;
  document.getElementById('fld_token_budget_hint').value = p.token_budget_hint||2000;
  document.getElementById('fld_temperature_delta').value = p.temperature_delta||0;
  document.getElementById('fld_tone').value = p.tone||'';
  document.getElementById('fld_style').value = p.style||'';
  document.getElementById('fld_model_override').value = p.model_override||'';
  document.getElementById('fld_keywords').value = (p.expertise_keywords||[]).join(', ');
  document.getElementById('fld_auto_skills').value = (p.auto_skills||[]).join(', ');
  document.getElementById('fld_system_prompt_addon').value = p.system_prompt_addon||'';
  document.getElementById('fld_enabled').checked = p.enabled;
  document.getElementById('btnDelete').style.display = '';
  new bootstrap.Modal(document.getElementById('editModal')).show();
}

async function saveProfile() {
  const mode = document.getElementById('fld_mode').value;
  const focus_id = document.getElementById('fld_focus_id').value.trim();
  if (!focus_id) { alert('Focus ID is required'); return; }
  const body = {
    focus_id,
    display_name: document.getElementById('fld_display_name').value,
    emoji: document.getElementById('fld_emoji').value||'🎯',
    delegation_level: parseInt(document.getElementById('fld_delegation_level').value),
    token_budget_hint: parseInt(document.getElementById('fld_token_budget_hint').value),
    temperature_delta: parseFloat(document.getElementById('fld_temperature_delta').value),
    tone: document.getElementById('fld_tone').value,
    style: document.getElementById('fld_style').value,
    model_override: document.getElementById('fld_model_override').value||null,
    expertise_keywords: document.getElementById('fld_keywords').value
      .split(',').map(k=>k.trim()).filter(Boolean),
    auto_skills: document.getElementById('fld_auto_skills').value
      .split(',').map(s=>s.trim()).filter(Boolean),
    system_prompt_addon: document.getElementById('fld_system_prompt_addon').value||null,
    enabled: document.getElementById('fld_enabled').checked,
  };
  const url = mode === 'new' ? API : `${API}/${focus_id}`;
  const method = mode === 'new' ? 'POST' : 'PUT';
  const res = await fetch(url, {method, headers:H, body: JSON.stringify(body)});
  if (res.ok) {
    bootstrap.Modal.getInstance(document.getElementById('editModal')).hide();
    loadProfiles();
  } else {
    const err = await res.json().catch(()=>({detail:'Unknown error'}));
    alert('Save failed: ' + (err.detail||JSON.stringify(err)));
  }
}

async function deleteProfile() {
  const focus_id = document.getElementById('fld_focus_id').value;
  if (!confirm(`Delete focus profile "${focus_id}"?`)) return;
  await fetch(`${API}/${focus_id}`, {method:'DELETE', headers:H});
  bootstrap.Modal.getInstance(document.getElementById('editModal')).hide();
  loadProfiles();
}

async function seedProfiles() {
  const res = await fetch(`${API}/seed`, {method:'POST', headers:H});
  const d = await res.json();
  alert(`Seeded: ${d.inserted} new profiles (${d.total} total)`);
  loadProfiles();
}

document.addEventListener('DOMContentLoaded', loadProfiles);
</script>
{% endblock %}
```

### Wire into navigation

**Find:** The engine management nav template (likely `src/web/templates/base.html` or `engine_nav.html`).

**Add link:**
```html
<li class="nav-item">
  <a class="nav-link" href="/engine/focus">🎭 Focus Profiles</a>
</li>
```

**Find:** The route in the web server that serves engine management pages (likely in `src/api/main.py` or a static file router).

**Add route:**
```python
@app.get("/engine/focus", include_in_schema=False)
async def engine_focus_page(request: Request):
    return templates.TemplateResponse("engine_focus.html", {"request": request})
```

---

## Constraints

| # | Constraint | Status | Notes |
|---|-----------|:------:|-------|
| 1 | API key from cookie | ✅ | JS reads `aria_api_key` cookie — same pattern as other engine pages |
| 2 | Additive prompt display | ✅ | UI shows "Appended to agent system_prompt — never replaces" in form text |
| 3 | Model override is slug only | ✅ | Placeholder says "slug from models.yaml" — no URL input |
| 4 | No soul file modification | ✅ | This is a UI file only |
| 5 | Bootstrap pattern consistent | ✅ | Uses existing Bootstrap + bootstrap.Modal from base.html |

---

## Dependencies

- **E7-S71 must complete first** — `/api/engine/focus` CRUD + seed endpoints must be live

---

## Verification

```bash
# 1. Template file exists
test -f src/web/templates/engine_focus.html && echo "EXISTS" || echo "MISSING"
# EXPECTED: EXISTS

# 2. Page loads (HTTP 200)
curl -s -o /dev/null -w "%{http_code}" \
  http://localhost/engine/focus \
  -H "Authorization: Bearer $ARIA_API_KEY"
# EXPECTED: 200

# 3. Page includes key elements
curl -s http://localhost/engine/focus | grep -c "focus-card\|level-badge\|budget-bar\|editModal"
# EXPECTED: >= 4

# 4. Page shows loaded profiles (JS must be able to call API)
# Manual test: open http://localhost/engine/focus in browser
# Expected: 8 profile cards visible with budget bars and keyword chips
```

---

## Prompt for Agent

You are executing ticket **E7-S76** for the Aria project.

**Pre-check — confirm S71 is done:**
```bash
curl -s http://localhost/api/engine/focus -H "Authorization: Bearer $ARIA_API_KEY" | python3 -c "import sys,json;d=json.load(sys.stdin);print(len(d),'profiles')"
# Expected: 8 profiles
```

**Constraint:** Frontend only — no backend code changes except adding the page route. Do not modify `aria_mind/soul/`. API key is read from the `aria_api_key` cookie — do not hardcode values.

**Files to read first:**
1. Any existing engine management HTML template (e.g. `engine_cron.html` or `engine_sessions.html`) — to match the nav and JS style
2. The route file that serves HTML pages — to find where to add the `/engine/focus` GET route
3. `src/web/templates/base.html` or equivalent — to find nav location

**Steps:**
1. Create `src/web/templates/engine_focus.html` with full file content above.
2. Add GET route for `/engine/focus` page.
3. Add nav link to the engine nav section.
4. Run verification 1–3.
5. Manual browser test: Open page, verify 8 profile cards load.
6. Report: "S-76 DONE — engine_focus.html created, page renders, 8 profiles show."
