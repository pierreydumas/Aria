# Aria Complete Development Reference

> **Version 3.0** | Last Updated: February 3, 2026 | **Last verified against codebase: 2026-03-07**  
> ⚠️ Review quarterly — skill count, agent list, and Docker service list change frequently.  
> Master reference for Aria's architecture, skills, agents, and deployment.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Focus System (7 Personas)](#2-focus-system-7-personas)
3. [Skills Reference](#3-skills-reference)
4. [Creating New Skills](#4-creating-new-skills)
5. [Agent Architecture](#5-agent-architecture)
6. [Mind Architecture](#6-mind-architecture)
7. [Docker Infrastructure](#7-docker-infrastructure)
8. [LLM Models](#8-llm-models)
9. [Database Schema](#9-database-schema)
10. [Deployment Guide](#10-deployment-guide)

---

## 1. System Overview

Aria is a **distributed cognitive architecture** with a **Focus-based persona system**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                          AriaMind                                    │
│  ┌─────────────────────────────────────────────────────────────────┐│
│  │                    Soul (Core Identity)                          ││
│  │  ┌──────────┐  ┌────────┐  ┌──────────┐  ┌────────────────────┐││
│  │  │ Identity │  │ Values │  │Boundaries│  │  Focus (Persona)   │││
│  │  │ (immut.) │  │(immut.)│  │ (immut.) │  │ 🎯🔒📊📈🎨🌐📰   │││
│  │  └──────────┘  └────────┘  └──────────┘  └────────────────────┘││
│  └─────────────────────────────────────────────────────────────────┘│
│  ┌─────────────┐  ┌─────────────┐  ┌────────────┐                   │
│  │  Cognition  │  │   Memory    │  │  Heartbeat │                   │
│  │ (Processing)│  │(Short/Long) │  │ (Schedule) │                   │
│  └──────┬──────┘  └──────┬──────┘  └──────┬─────┘                   │
│         └────────────────┼────────────────┘                          │
│                          ▼                                           │
│  ┌──────────────────────────────────────────────────────────────┐   │
│  │               AgentCoordinator (Focus-mapped)                 │   │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐     │   │
│  │  │   aria   │  │  devops  │  │ analyst  │  │ creator  │     │   │
│  │  │ 🎯 Orch. │  │ 🔒 Sec.  │  │ 📊 Data  │  │ 🌐 Social│     │   │
│  │  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘     │   │
│  │       └─────────────┴─────────────┴─────────────┘             │   │
│  └──────────────────────────────────────────────────────────────┘   │
│                             │                                        │
│  ┌──────────────────────────┼───────────────────────────────────┐   │
│  │                  SkillRegistry (35+ Skills)                    │   │
│  │  ┌──────┐  ┌────────┐  ┌────────┐  ┌───────┐  ┌──────────┐  │   │
│  │  │ llm  │  │database│  │security│  │market │  │brainstorm│  │   │
│  │  └──────┘  └────────┘  └────────┘  └───────┘  └──────────┘  │   │
│  └──────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### Component Locations

| Component | Location | Purpose |
|-----------|----------|---------|
| **AriaMind** | `aria_mind/` | Main cognitive container |
| **Soul** | `aria_mind/soul/` | Identity, values, boundaries, focus |
| **Focus** | `aria_mind/soul/focus.py` | Specialized persona overlays |
| **Cognition** | `aria_mind/cognition.py` | Request processing, reasoning |
| **Memory** | `aria_mind/memory.py` | Short-term and long-term storage |
| **Heartbeat** | `aria_mind/heartbeat.py` | Health monitoring, scheduling |
| **AgentCoordinator** | `aria_agents/coordinator.py` | Multi-agent orchestration |
| **Skills** | `aria_skills/<skill>/` | Tool implementations + manifests (35+ skills) |
| **Entrypoint** | `stacks/brain/entrypoint.sh` | Dynamic skill runner + symlink generation |

---

## 2. Focus System (7 Personas)

Aria has 7 specialized **focuses** (personas) that enhance her core identity:

### Focus Reference Table

| Focus | Emoji | Vibe | Primary Model | Skills |
|-------|-------|------|---------------|--------|
| **Orchestrator** | 🎯 | Meta-cognitive, strategic | `qwen3-mlx` | goals, schedule, health |
| **DevSecOps** | 🔒 | Security-paranoid, precise | `qwen3-coder-free` | security_scan, ci_cd, pytest_runner, database |
| **Data Architect** | 📊 | Analytical, metrics-driven | `chimera-free` | data_pipeline, experiment, knowledge_graph, performance |
| **Crypto Trader** | 📈 | Risk-aware, disciplined | `deepseek-free` | market_data, portfolio, database, schedule |
| **Creative** | 🎨 | Exploratory, playful | `trinity-free` | brainstorm, llm, moltbook |
| **Social Architect** | 🌐 | Community-building | `trinity-free` | community, moltbook, social, schedule |
| **Journalist** | 📰 | Investigative, thorough | `qwen3-next-free` | research, fact_check, knowledge_graph, social |

### Focus Rules

1. **Additive**: Focuses ADD traits, never REPLACE core identity
2. **Default**: Orchestrator 🎯 is the default focus
3. **Immutable Core**: Values and boundaries never change with focus
4. **Auto-Selection**: Focus selected based on task keywords

### Focus → Agent Mapping

| Focus | Agent | Handles |
|-------|-------|---------|
| Orchestrator | aria | Coordination, delegation |
| DevSecOps | devops | Code, security, tests |
| Data + Trader | analyst | Analysis, metrics, trading |
| Creative + Social + Journalist | creator | Content, community |

### Using Focus in Code

```python
from aria_mind.soul import Soul, FocusType

soul = Soul()
await soul.load()

# Set focus explicitly
soul.set_focus(FocusType.DEVSECOPS)

# Auto-select based on keywords
focus_type = soul.focus.get_focus_for_task(["code", "security", "test"])
soul.set_focus(focus_type)

# Get current focus info
print(soul.active_focus.name)   # "DevSecOps"
print(soul.active_focus.emoji)  # "🔒"
print(soul.active_focus.skills) # ["security_scan", "ci_cd", ...]
```

---

## 3. Skills Reference

### Complete Skill Registry (35+ Skills)

#### Core Skills (v1.0)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `database` | `aria_skills.database` | `DatabaseSkill` | PostgreSQL queries |
| `moltbook` | `aria_skills.moltbook` | `MoltbookSkill` | Social platform posting |
| `health` | `aria_skills.health` | `HealthSkill` | System monitoring |
| `llm` | `aria_skills.llm` | `LLMSkill` | Local LLM calls |
| `knowledge_graph` | `aria_skills.knowledge_graph` | `KnowledgeGraphSkill` | Entity relationships |
| `goals` | `aria_skills.goals` | `GoalSkill` | Task scheduling |
| `pytest` | `aria_skills.pytest_runner` | `PytestSkill` | Test execution |
| `model_switcher` | `aria_skills.model_switcher` | `ModelSwitcherSkill` | LLM model selection |

#### Social & Communication Skills (v1.1)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `performance` | `aria_skills.performance` | `PerformanceSkill` | Metrics, analytics |
| `social` | `aria_skills.social` | `SocialSkill` | Telegram, Discord |
| `hourly_goals` | `aria_skills.hourly_goals` | `HourlyGoalSkill` | Short-term goals |
| `litellm` | `aria_skills.litellm` | `LiteLLMSkill` | LiteLLM management |
| `schedule` | `aria_skills.schedule` | `ScheduleSkill` | Job scheduling |

#### DevSecOps Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `security_scan` | `aria_skills.security_scan` | `SecurityScanSkill` | Vulnerability scanning, SAST, secret detection |
| `ci_cd` | `aria_skills.ci_cd` | `CICDSkill` | GitHub Actions, Dockerfile generation |

#### Data & ML Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `data_pipeline` | `aria_skills.data_pipeline` | `DataPipelineSkill` | ETL, validation, schema inference |
| `experiment` | `aria_skills.experiment` | `ExperimentSkill` | ML experiment tracking, model registry |

#### Crypto Trading Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `market_data` | `aria_skills.market_data` | `MarketDataSkill` | Price feeds, technical indicators |
| `portfolio` | `aria_skills.portfolio` | `PortfolioSkill` | Position tracking, P&L, risk metrics |

#### Creative Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `brainstorm` | `aria_skills.brainstorm` | `BrainstormSkill` | Ideation (SCAMPER, Six Hats, Mind Maps) |

#### Journalist Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `research` | `aria_skills.research` | `ResearchSkill` | Source collection, credibility scoring |
| `fact_check` | `aria_skills.fact_check` | `FactCheckSkill` | Claim extraction, verdicts |

#### Community Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `community` | `aria_skills.community` | `CommunitySkill` | Community health, engagement metrics |

#### API Client Skills (v1.2)

| Skill | Module | Class | Purpose |
|-------|--------|-------|---------|
| `api_client` | `aria_skills.api_client` | `AriaAPIClient` | Centralized HTTP client for aria-api |

### Skill-to-Focus Matrix

| Skill | 🎯 | 🔒 | 📊 | 📈 | 🎨 | 🌐 | 📰 |
|-------|----|----|----|----|----|----|-----|
| `goals` | ✅ | - | - | - | - | - | - |
| `schedule` | ✅ | - | - | ✅ | - | ✅ | - |
| `health` | ✅ | ✅ | - | - | - | - | - |
| `database` | - | ✅ | ✅ | ✅ | - | - | - |
| `pytest_runner` | - | ✅ | - | - | - | - | - |
| `security_scan` | - | ✅ | - | - | - | - | - |
| `ci_cd` | - | ✅ | - | - | - | - | - |
| `knowledge_graph` | - | - | ✅ | - | - | - | ✅ |
| `performance` | - | - | ✅ | - | - | - | - |
| `data_pipeline` | - | - | ✅ | - | - | - | - |
| `experiment` | - | - | ✅ | - | - | - | - |
| `market_data` | - | - | - | ✅ | - | - | - |
| `portfolio` | - | - | - | ✅ | - | - | - |
| `moltbook` | - | - | - | - | ✅ | ✅ | ✅ |
| `social` | - | - | - | - | ✅ | ✅ | - |
| `brainstorm` | - | - | - | - | ✅ | - | - |
| `community` | - | - | - | - | - | ✅ | - |
| `research` | - | - | - | - | - | - | ✅ |
| `fact_check` | - | - | - | - | - | - | ✅ |
| `llm` | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |

---

## 4. Creating New Skills

### File Structure (Consolidated v2.0)

Each skill is a **subdirectory** containing code, manifest, and docs together:

```
aria_skills/
├── base.py               # BaseSkill, SkillConfig, SkillResult
├── registry.py           # SkillRegistry
├── __init__.py           # Package exports
└── my_skill/             # One directory per skill
    ├── __init__.py       # Python implementation
    ├── skill.json        # Skill manifest
    └── SKILL.md          # Documentation (optional)
```

> **Note**: The entrypoint automatically creates symlinks from `/app/skills/aria-<skill>/` to each `skill.json` at container startup.

### Step 1: Create Python Skill

```python
# aria_skills/my_skill/__init__.py

"""
My Skill - Description of what this skill does.

Config:
    api_url: Base API URL
    api_key: API key (use env:MY_API_KEY)
"""

from typing import Any, Dict, Optional
import httpx

from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry


@SkillRegistry.register
class MySkill(BaseSkill):
    """Skill for [purpose]."""
    """Skill for [purpose]."""
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._api_url = config.config.get("api_url", "http://localhost:8000")
        self._token: Optional[str] = None
    
    @property
    def name(self) -> str:
        return "my_skill"
    
    async def initialize(self) -> bool:
        self._token = self._get_env_value("api_key")
        if not self._token:
            self._status = SkillStatus.UNAVAILABLE
            return False
        self._status = SkillStatus.AVAILABLE
        return True
    
    async def health_check(self) -> SkillStatus:
        try:
            async with httpx.AsyncClient() as client:
                r = await client.get(f"{self._api_url}/health", timeout=10)
                self._status = SkillStatus.AVAILABLE if r.status_code == 200 else SkillStatus.ERROR
        except Exception:
            self._status = SkillStatus.ERROR
        return self._status
    
    async def my_action(self, input_data: str) -> SkillResult:
        """Main action method."""
        if not self.is_available:
            return SkillResult.fail("Skill not available")
        
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{self._api_url}/action",
                    json={"input": input_data},
                    headers={"Authorization": f"Bearer {self._token}"},
                )
                response.raise_for_status()
                return SkillResult.ok(response.json())
        except Exception as e:
            return SkillResult.fail(str(e))
```

### Step 2: Register in __init__.py

```python
# aria_skills/__init__.py

from aria_skills.my_skill import MySkill  # Import from subdirectory

__all__ = [
    # ... existing
    "MySkill",
]
```

### Step 3: Add to SKILL_REGISTRY (entrypoint.sh)

The skill runner at `stacks/brain/entrypoint.sh` has a `SKILL_REGISTRY` dict. Add your skill:

```python
SKILL_REGISTRY = {
    # ... existing skills ...
    
    'my_skill': ('aria_skills.my_skill', 'MySkill', lambda: {
        'api_url': os.environ.get('MY_SKILL_URL', 'http://localhost:8000'),
        'api_key': os.environ.get('MY_SKILL_API_KEY')
    }),
}
```

### Step 4: Create Skill Manifest

```json
// aria_skills/my_skill/skill.json
{
  "name": "aria-my-skill",
  "version": "1.0.0",
  "description": "Description of what this skill does.",
  "author": "Aria Team",
  "tools": [
    {
      "name": "my_action",
      "description": "Perform the main action. Use when you need to [purpose].",
      "parameters": {
        "type": "object",
        "properties": {
          "input_data": {
            "type": "string",
            "description": "The input to process"
          }
        },
        "required": ["input_data"]
      }
    }
  ],
    "run": "python3 skills/run_skill.py my_skill {{tool}} '{{args_json}}'"
}
```

### Step 5: Create SKILL.md (Optional)

Create `aria_skills/my_skill/SKILL.md`:

```markdown
---
name: aria-my-skill
description: Brief description
metadata: {"aria": {"emoji": "🔧", "requires": {"env": ["MY_SKILL_API_KEY"]}}}
---

# My Skill 🔧

## Usage

\`\`\`bash
exec python3 skills/run_skill.py my_skill my_action '{"input_data": "example"}'
\`\`\`

## Functions

### my_action
Perform the main action.

**Parameters:**
- `input_data` (required): The input to process

## Configuration

Environment variables:
- `MY_SKILL_API_KEY`: API authentication key
```

### Step 6: Add to skills.entries in Entrypoint

In `stacks/brain/entrypoint.sh`, add to the `skills.entries` section:

```json
"aria-my-skill": { "enabled": true }
```

> **Note**: Symlinks are created automatically by the entrypoint script for any `skill.json` found in `aria_skills/*/`.

### Step 7: Add to TOOLS.md

```yaml
my_skill:
  enabled: true
  api_url: http://localhost:8000
  api_key: env:MY_SKILL_API_KEY
```

---

## 5. Agent Architecture

### Agent Types

| Agent | Role | Focus | Skills |
|-------|------|-------|--------|
| `aria` | Coordinator | Orchestrator | api_client, knowledge_graph, goals, brainstorm, health |
| `devops` | Coder | DevSecOps | ci_cd, api_client, health, security_scan, pytest_runner |
| `analyst` | Researcher | Data/Trader | api_client, knowledge_graph, brainstorm, market_data |
| `creator` | Social | Creative | moltbook, brainstorm, community, research |
| `memory` | Memory | Support | api_client, knowledge_graph, conversation_summary |
| `aria_talk` | Conversational | Chat/Social | moltbook, conversation_summary, community, api_client |

### AgentConfig Structure

```python
@dataclass
class AgentConfig:
    agent_id: str              # Unique identifier
    name: str                  # Display name
    role: AgentRole            # COORDINATOR, RESEARCHER, SOCIAL, CODER, MEMORY
    model: str                 # LLM model name
    parent: Optional[str]      # Parent agent ID
    capabilities: List[str]    # What the agent can do
    skills: List[str]          # Allowed skill names
    temperature: float = 0.7
    max_tokens: int = 2048
```

### Agent Communication

```python
# Get agent from coordinator
agent = coordinator.get_agent("devops")

# Process message through agent
result = await agent.process("Scan this code for vulnerabilities")

# Broadcast to all agents
responses = await coordinator.broadcast("Status check")
```

---

## 6. Mind Architecture

### Soul System (Immutable)

```python
class Soul:
    identity: Identity      # Name, creature, vibe, colors
    values: Values          # Core principles (never compromise)
    boundaries: Boundaries  # Will do / Will not do
    focus: FocusManager     # Current persona overlay
```

### Memory System

| Tier | Storage | Persistence | Capacity |
|------|---------|-------------|----------|
| **Short-term** | In-memory | Session only | 100 entries |
| **Long-term** | PostgreSQL | Permanent | Unlimited |

### Cognition Flow

```
User Input → Boundary Check → Memory Store → Agent Delegation → Skill Execution → Response
```

### Scheduled Tasks

| Job | Schedule | Purpose |
|-----|----------|---------|
| `work_cycle` | Every 5 min | Goal progress |
| `hourly_goal_check` | Every hour | Complete/create hourly goals |
| `six_hour_review` | Every 6 hours | Priority adjustment |
| `moltbook_post` | Every 6 hours | Social presence |
| `daily_reflection` | 11 PM | Daily summary |
| `morning_checkin` | 8 AM | Daily priorities |
| `weekly_summary` | Sunday 6 PM | Weekly report |

---

## 7. Docker Infrastructure

### Container Map

| Container | Port | Purpose | Internal URL |
|-----------|------|---------|--------------|
| `aria-engine` | 8100 | Aria Engine | - |
| `litellm` | 18793→4000 | Model routing | `http://litellm:4000` |
| `aria-db` | 18780→5432 | PostgreSQL | `postgresql://aria-db:5432` |
| `mlx-server` | 8080 | Local Qwen3 | `http://host.docker.internal:8080` |
| `aria-api` | 18791→8000 | FastAPI | `http://aria-api:8000` |
| `aria-web` | 18790 | Web UI | - |

### Network Topology

```
┌─────────────────────────────────────────────────────────────────┐
│                    Docker Network (aria-net)                     │
│                                                                  │
│  ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────┐  │
│  │ aria-engine │───▶│ litellm  │───▶│mlx-server│    │ aria-web │  │
│  │  :8100  │    │  :4000   │    │  :8080   │    │  :18790  │  │
│  └─────┬────┘    └──────────┘    └──────────┘    └──────────┘  │
│        │                                                         │
│        │         ┌──────────┐    ┌──────────┐                   │
│        └────────▶│ aria-db  │◀───│ aria-api │                   │
│                  │  :5432   │    │  :8000   │                   │
│                  └──────────┘    └──────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

### Volume Mounts (aria-engine)

```yaml
volumes:
  - ../../aria_mind:/app
  - ../../aria_skills:/app/skills/aria_skills:ro
  - ../../aria_agents:/app/skills/aria_agents:ro
  - ./entrypoint.sh:/entrypoint.sh:ro
```

> **Note**: Skill manifests are symlinked at startup from `aria_skills/*/skill.json` to `/app/skills/aria-*/skill.json`.

### Entrypoint Sequence

`stacks/brain/entrypoint.sh` runs when aria-engine starts:

1. Install apt dependencies (curl, jq, python3)
2. Install dependencies if not present
3. **Create skill manifest symlinks** from `aria_skills/*/skill.json` to `/app/skills/aria-*/`
4. pip install Python dependencies
5. **Generate `run_skill.py`** with SKILL_REGISTRY (35+ skills)
6. Read BOOTSTRAP.md for system prompt
7. **Generate `aria-engine.json`** with all skill entries enabled
8. Prepare awakening (first boot detection)
9. Start Aria Engine on port 8100

---

## 8. LLM Models

### Model Priority: Local → Free Cloud → Paid

**Source of truth**: [aria_models/models.yaml](aria_models/models.yaml). The tables below are examples only and may drift.

| Model | Provider | Context | Cost | Best For |
|-------|----------|---------|------|----------|
| `qwen3-mlx` | Local MLX | 32K | FREE | **PRIMARY** - Fast, private |
| `trinity-free` | OpenRouter | 128K | FREE | Creative, agentic |
| `qwen3-coder-free` | OpenRouter | 262K | FREE | Code generation |
| `chimera-free` | OpenRouter | 164K | FREE | Reasoning (fast) |
| `qwen3-next-free` | OpenRouter | 262K | FREE | RAG, long context |
| `glm-free` | OpenRouter | 131K | FREE | Agent-focused |
| `deepseek-free` | OpenRouter | 164K | FREE | Deep reasoning |
| `nemotron-free` | OpenRouter | 256K | FREE | Long context |
| `gpt-oss-free` | OpenRouter | 131K | FREE | Function calling |
| `kimi` | Moonshot | 256K | 💰 PAID | Last resort only |

### Model Selection by Focus

| Focus | Primary | Fallback |
|-------|---------|----------|
| 🎯 Orchestrator | `qwen3-mlx` | `trinity-free` |
| 🔒 DevSecOps | `qwen3-coder-free` | `gpt-oss-free` |
| 📊 Data Architect | `chimera-free` | `deepseek-free` |
| 📈 Crypto Trader | `deepseek-free` | `chimera-free` |
| 🎨 Creative | `trinity-free` | `qwen3-next-free` |
| 🌐 Social | `trinity-free` | `qwen3-mlx` |
| 📰 Journalist | `qwen3-next-free` | `chimera-free` |

### Model Switching

```bash
# Via skill
exec python3 skills/run_skill.py model_switcher switch_model '{"model": "chimera-free"}'

# Check current model
exec python3 skills/run_skill.py model_switcher get_current_model '{}'
```

---

## 9. Database Schema

### Core Tables

```sql
-- Goals
CREATE TABLE goals (
    id SERIAL PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT,
    priority INTEGER DEFAULT 3,
    status TEXT DEFAULT 'active',
    progress INTEGER DEFAULT 0,
    target_date TIMESTAMP,
    parent_goal_id INTEGER REFERENCES goals(id),
    created_at TIMESTAMP DEFAULT NOW()
);

-- Hourly Goals
CREATE TABLE hourly_goals (
    id SERIAL PRIMARY KEY,
    hour_start TIMESTAMP NOT NULL,
    goal_type TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'pending',
    result TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Activity Log
CREATE TABLE activity_log (
    id SERIAL PRIMARY KEY,
    action TEXT NOT NULL,
    details JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Thoughts
CREATE TABLE thoughts (
    id SERIAL PRIMARY KEY,
    content TEXT NOT NULL,
    category TEXT DEFAULT 'reflection',
    created_at TIMESTAMP DEFAULT NOW()
);

-- Social Posts
CREATE TABLE social_posts (
    id SERIAL PRIMARY KEY,
    platform TEXT NOT NULL,
    post_id TEXT,
    content TEXT,
    url TEXT,
    created_at TIMESTAMP DEFAULT NOW()
);

-- Knowledge Graph
CREATE TABLE kg_entities (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    entity_type TEXT,
    properties JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE TABLE kg_relationships (
    id SERIAL PRIMARY KEY,
    source_id INTEGER REFERENCES kg_entities(id),
    target_id INTEGER REFERENCES kg_entities(id),
    relation_type TEXT NOT NULL,
    properties JSONB,
    created_at TIMESTAMP DEFAULT NOW()
);
```

---

## 10. Deployment Guide

### Local Development

```bash
# Clone repo
git clone https://github.com/Najia-afk/Aria_moltbot.git
cd Aria_moltbot

# Create .env
cp stacks/brain/.env.example stacks/brain/.env
# Edit .env with your keys

# Deploy
cd stacks/brain
docker compose up -d
```

### Production Deployment

```bash
# SSH to server
ssh -i najia_mac_key najia@$MAC_HOST

# Deploy
cd ~/aria-blue/stacks/brain
git pull origin main
docker compose down
docker compose up -d --build

# Verify
docker compose logs -f aria-engine
```

### Testing a Skill

```bash
# From inside aria-engine container or via exec
python3 skills/run_skill.py <skill> <function> '<args_json>'

# Examples:
python3 skills/run_skill.py api_client get_goals '{"status": "active", "limit": 5}'
python3 skills/run_skill.py security_scan scan_directory '{"directory": "/workspace", "extensions": [".py"]}'
python3 skills/run_skill.py market_data get_price '{"symbol": "BTC"}'
python3 skills/run_skill.py --auto-task "summarize active goals and risks" --route-limit 2 --route-no-info
```

### Checklist for New Skills

- [ ] Create directory `aria_skills/my_skill/`
- [ ] Create `aria_skills/my_skill/__init__.py` (Python implementation)
- [ ] Create `aria_skills/my_skill/skill.json` (Skill manifest)
- [ ] Create `aria_skills/my_skill/SKILL.md` (documentation, optional)
- [ ] Add import to `aria_skills/__init__.py`
- [ ] Add to SKILL_REGISTRY in `entrypoint.sh`
- [ ] Add to skills.entries in `entrypoint.sh`
- [ ] Add config to `aria_mind/TOOLS.md`
- [ ] Update Focus skills list in `aria_mind/soul/focus.py` (if focus-specific)
- [ ] Write tests in `tests/test_my_skill.py`
- [ ] Commit and push
- [ ] Deploy with `docker compose up -d`

---

## Quick Reference

### Skill Invocation Pattern

```bash
python3 skills/run_skill.py <skill_name> <function> '<json_args>'
```

### Available Skills

Use live catalog output as source of truth:

```bash
python -m aria_mind --list-skills
```

Legacy compatibility skills may still exist, but API-client-first flow is preferred.

```
api_client, goals, health, hourly_goals, knowledge_graph, litellm,
llm, market_data, moltbook, performance, portfolio,
pytest_runner, research, schedule, security_scan, session_manager,
social, sprint_manager, telegram, working_memory
```

### Focus Keywords

| Focus | Trigger Keywords |
|-------|------------------|
| 🔒 DevSecOps | security, code, test, pipeline, docker, vulnerability |
| 📊 Data | data, analysis, metrics, experiment, ml, etl |
| 📈 Trader | crypto, trade, market, portfolio, bitcoin, price |
| 🎨 Creative | create, idea, brainstorm, design, story |
| 🌐 Social | community, post, engage, social, moltbook |
| 📰 Journalist | research, fact, news, source, investigate |

---

> **Remember**: Skills are Aria's hands. Each skill should do one thing well, be reliable, and be well-documented. Focus personas enhance capabilities without changing core identity.
