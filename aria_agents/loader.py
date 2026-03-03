# aria_agents/loader.py
"""
Agent configuration loader.

Loads agent definitions from AGENTS.md.
"""
import logging
import re
from pathlib import Path
from typing import Any

try:
    import yaml  # type: ignore
except Exception:  # pragma: no cover - optional dependency in some runtimes
    yaml = None

from aria_agents.base import AgentConfig, AgentRole
from aria_models.loader import load_catalog, get_primary_model_full

logger = logging.getLogger(__name__)

# Single source of truth: models.yaml routing.primary
_default_model = get_primary_model_full()


class AgentLoader:
    """
    Loads agent configurations from AGENTS.md files.
    
    Format:
        ## agent_id
        - model: qwen3-vl:8b
        - parent: aria
        - capabilities: [research, summarize]
        - skills: [ollama, browser]
    """
    
    @staticmethod
    def load_from_file(filepath: str) -> dict[str, AgentConfig]:
        """
        Load agent configs from a markdown file.
        
        Args:
            filepath: Path to AGENTS.md
            
        Returns:
            Dict of agent_id -> AgentConfig
        """
        path = Path(filepath)
        if not path.exists():
            return {}
        
        content = path.read_text(encoding="utf-8")
        return AgentLoader.parse_agents_md(content)
    
    @staticmethod
    def parse_agents_md(content: str) -> dict[str, AgentConfig]:
        """
        Parse AGENTS.md content into AgentConfig objects.
        
        Args:
            content: Markdown content
            
        Returns:
            Dict of agent_id -> AgentConfig
        """
        agents = {}
        
        # Split by h2 headers (## agent_id)
        sections = re.split(r'^## ', content, flags=re.MULTILINE)
        
        for section in sections[1:]:  # Skip content before first ##
            lines = section.strip().split('\n')
            if not lines:
                continue
            
            # First line is the agent ID
            agent_id = lines[0].strip().lower().replace(' ', '_')
            
            # Parse properties
            props: dict[str, Any] = {
                "id": agent_id,
                "name": lines[0].strip(),
            }
            
            for line in lines[1:]:
                line = line.strip()
                if line.startswith('- '):
                    # Parse "- key: value" format
                    match = re.match(r'-\s*(\w+):\s*(.+)', line)
                    if match:
                        key = match.group(1).lower()
                        value = match.group(2).strip()
                        
                        # Parse list values [a, b, c]
                        if value.startswith('[') and value.endswith(']'):
                            value = [v.strip() for v in value[1:-1].split(',')]
                        
                        props[key] = value

            # Prefer fenced YAML blocks when present (the current AGENTS.md format)
            yaml_match = re.search(r"```yaml\s*(.*?)\s*```", section, flags=re.DOTALL | re.IGNORECASE)
            if yaml_match:
                yaml_data = AgentLoader._safe_yaml_dict(yaml_match.group(1))
                for key, value in yaml_data.items():
                    props[str(key).lower()] = value

            # Ignore documentation-only sections that don't define an actual agent config
            config_keys = {
                "model", "skills", "capabilities", "role", "focus",
                "parent", "temperature", "max_tokens",
            }
            if not any(k in props for k in config_keys):
                continue
            
            # Canonical agent id: prefer explicit YAML id when provided
            explicit_id = str(props.get("id", "")).strip().lower().replace(" ", "_")
            if explicit_id:
                agent_id = explicit_id

            # Map role string to enum
            role_str = props.get("role")
            if not role_str:
                role_str = AgentLoader._role_from_focus(props.get("focus"))
            role_str = str(role_str or "coordinator").strip().lower()
            try:
                role = AgentRole(role_str)
            except ValueError:
                logger.warning(
                    "Unknown agent role '%s' for agent '%s', "
                    "falling back to COORDINATOR",
                    role_str, agent_id,
                )
                role = AgentRole.COORDINATOR
            
            # Create config
            skills = props.get("skills", [])
            capabilities = props.get("capabilities", [])
            if not isinstance(skills, list):
                skills = [str(skills)] if skills else []
            if not isinstance(capabilities, list):
                capabilities = [str(capabilities)] if capabilities else []

            # Parse mind_files list (explicit per-agent aria_mind file selection)
            mind_files_raw = props.get("mind_files", [])
            if isinstance(mind_files_raw, str):
                mind_files_raw = [f.strip() for f in mind_files_raw.split(",") if f.strip()]
            elif not isinstance(mind_files_raw, list):
                mind_files_raw = []
            mind_files = [str(f) for f in mind_files_raw]

            config = AgentConfig(
                id=agent_id,
                name=props.get("name", agent_id),
                role=role,
                model=props.get("model", _default_model),
                parent=props.get("parent"),
                capabilities=capabilities,
                skills=skills,
                temperature=float(props.get("temperature", 0.7)),
                max_tokens=int(props.get("max_tokens", 2048)),
                mind_files=mind_files,
            )
            
            agents[agent_id] = config
        
        return agents

    @staticmethod
    def _safe_yaml_dict(raw: str) -> dict[str, Any]:
        """Parse a YAML block to a dictionary with safe fallbacks."""
        if yaml is not None:
            try:
                parsed = yaml.safe_load(raw) or {}
                if isinstance(parsed, dict):
                    return parsed
                return {}
            except Exception as exc:
                logger.warning(f"Failed to parse agent YAML block with PyYAML: {exc}")

        # Fallback parser for simple key/value and [list, values] forms used in AGENTS.md
        data: dict[str, Any] = {}
        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped.startswith("#") or ":" not in stripped:
                continue
            key, value = stripped.split(":", 1)
            key = key.strip()
            value = value.strip()
            if not key:
                continue

            if value.startswith("[") and value.endswith("]"):
                items = [v.strip() for v in value[1:-1].split(",") if v.strip()]
                data[key] = items
                continue

            lowered = value.lower()
            if lowered in {"true", "false"}:
                data[key] = lowered == "true"
                continue
            if re.fullmatch(r"-?\d+", value):
                data[key] = int(value)
                continue
            if re.fullmatch(r"-?\d+\.\d+", value):
                data[key] = float(value)
                continue

            data[key] = value.strip("\"'")
        return data

    @staticmethod
    def _role_from_focus(focus: Any) -> str:
        """Map AGENTS.md focus values to AgentRole enum values."""
        focus_value = str(focus or "").strip().lower()
        focus_to_role = {
            "orchestrator": "coordinator",
            "coordinator": "coordinator",
            "devsecops": "devsecops",
            "data": "data",
            "trader": "trader",
            "creative": "creative",
            "social": "social",
            "journalist": "journalist",
            "memory": "memory",
            "conversational": "coordinator",
            "rpg_master": "rpg_master",
            "rpg": "rpg_master",
        }
        return focus_to_role.get(focus_value, "coordinator")

    @staticmethod
    def missing_expected_agents(
        agents: dict[str, AgentConfig],
        expected: list[str],
    ) -> list[str]:
        """Return expected agent IDs that are missing from loaded configs."""
        loaded = set(agents.keys())
        return [agent_id for agent_id in expected if agent_id not in loaded]
    
    @staticmethod
    def get_agent_hierarchy(agents: dict[str, AgentConfig]) -> dict[str, list[str]]:
        """
        Build parent -> children hierarchy.
        
        Args:
            agents: Dict of agent configs
            
        Returns:
            Dict mapping parent_id -> list of child_ids
        """
        hierarchy: dict[str, list[str]] = {}
        
        for agent_id, config in agents.items():
            if config.parent:
                if config.parent not in hierarchy:
                    hierarchy[config.parent] = []
                hierarchy[config.parent].append(agent_id)
        
        return hierarchy
