# aria_skills/registry.py
"""
Skill registry for managing available skills.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

from aria_skills.base import BaseSkill, SkillConfig, SkillStatus

logger = logging.getLogger("aria.skills.registry")


class SkillRegistry:
    """
    Central registry for all available skills.
    
    Handles:
    - Loading skill configurations from TOOLS.md
    - Initializing skill instances
    - Providing access to skills by name
    - Health monitoring across all skills
    """
    
    # Map of skill names to their implementation classes
    _skill_classes: dict[str, type[BaseSkill]] = {}
    
    def __init__(self):
        self._skills: dict[str, BaseSkill] = {}
        self._configs: dict[str, SkillConfig] = {}
        self._aliases: dict[str, str] = {}
        # Backward-compatible alias for tests
        self._registered_classes = self._skill_classes
    
    @classmethod
    def register(cls, skill_class: type[BaseSkill]):
        """
        Register a skill class.
        
        Usage:
            @SkillRegistry.register
            class MySkill(BaseSkill):
                ...
        """
        # Create temporary instance to get name
        dummy_config = SkillConfig(name="dummy")
        instance = skill_class(dummy_config)
        cls._skill_classes[instance.name] = skill_class
        # Also register under canonical name for cross-system lookup
        canonical = f"aria-{instance.name.replace('_', '-')}"
        cls._skill_classes[canonical] = skill_class
        logger.debug(f"Registered skill class: {instance.name} (canonical: {canonical})")
        return skill_class
    
    async def load_from_config(self, config_path: str) -> int:
        """
        Load skill configurations from TOOLS.md file.
        
        Args:
            config_path: Path to TOOLS.md
            
        Returns:
            Number of skills loaded
        """
        path = Path(config_path)
        if not path.exists():
            logger.warning(f"Config file not found: {config_path}")
            return 0
        
        content = path.read_text()
        configs = self._parse_tools_md(content)
        
        loaded = 0
        for config in configs:
            self._configs[config.name] = config
            if config.enabled and config.name in self._skill_classes:
                skill_class = self._skill_classes[config.name]
                skill = skill_class(config)
                # Pass the live registry to PipelineSkill so it can
                # invoke other skills instead of using an empty registry.
                if config.name == "pipeline":
                    init_ok = await skill.initialize(registry=self)
                else:
                    init_ok = await skill.initialize()
                if init_ok:
                    self._skills[config.name] = skill
                    self._skills[skill.canonical_name] = skill  # canonical alias
                    loaded += 1
                    logger.info(f"Loaded skill: {config.name} (canonical: {skill.canonical_name})")
                else:
                    logger.warning(f"Failed to initialize skill: {config.name}")
        
        return loaded
    
    def _parse_tools_md(self, content: str) -> list[SkillConfig]:
        """
        Parse TOOLS.md to extract skill configurations.
        
        Looks for yaml code blocks after ### headers.
        """
        configs = []
        
        # Find all yaml/tool code blocks
        pattern = r"```(?:yaml|tool)\s*\n(.*?)```"
        matches = re.findall(pattern, content, re.DOTALL)
        
        for match in matches:
            try:
                # Simple YAML-like parsing (avoid full yaml dependency)
                config_dict = self._parse_simple_yaml(match)
                if "skill" in config_dict:
                    configs.append(SkillConfig.from_dict(config_dict))
            except Exception as e:
                logger.debug(f"Failed to parse config block: {e}")
        
        return configs
    
    def _parse_simple_yaml(self, content: str) -> dict:
        """
        Simple YAML-like parser for skill configs.
        Handles basic key: value pairs and nested config.
        """
        result = {}
        current_key = None
        current_indent = 0
        nested = {}
        
        for line in content.split("\n"):
            line = line.rstrip()
            if not line or line.startswith("#"):
                continue
            
            # Count indentation
            indent = len(line) - len(line.lstrip())
            line = line.strip()
            
            if ":" in line:
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                
                if indent == 0:
                    # Save any nested dict
                    if current_key and nested:
                        result[current_key] = nested
                        nested = {}
                    
                    if value:
                        # Handle env: prefix and booleans
                        if value.lower() == "true":
                            result[key] = True
                        elif value.lower() == "false":
                            result[key] = False
                        else:
                            result[key] = value
                    else:
                        current_key = key
                        current_indent = indent
                else:
                    # Nested value
                    if value:
                        if value.lower() == "true":
                            nested[key] = True
                        elif value.lower() == "false":
                            nested[key] = False
                        elif value.isdigit():
                            nested[key] = int(value)
                        else:
                            nested[key] = value
        
        # Save final nested dict
        if current_key and nested:
            result[current_key] = nested
        
        return result
    
    def get(self, name: str) -> BaseSkill | None:
        """Get a skill by name (supports both python name and canonical name)."""
        skill = self._skills.get(name)
        if skill is None:
            # Try normalizing from canonical to python name
            if name.startswith("aria-"):
                python_name = name[5:].replace("-", "_")
                skill = self._skills.get(python_name)
        return skill
    
    def list_available(self) -> list[str]:
        """List all available (loaded) skill names."""
        return list(self._skills.keys())

    def list(self) -> list[str]:
        """Backward-compatible list of loaded skills."""
        return self.list_available()
    
    def list_configured(self) -> list[str]:
        """List all configured skill names."""
        return list(self._configs.keys())

    async def load_from_manifests(self, skills_dir: str = "aria_skills") -> int:
        """
        Load skill configs from skill.json manifests (same source as ToolRegistry).

        Fallback when TOOLS.md has no parseable YAML blocks.
        """
        import json as _json

        base = Path(skills_dir)
        if not base.is_dir():
            logger.warning("Skills directory not found: %s", skills_dir)
            return 0

        loaded = 0
        for manifest in sorted(base.glob("*/skill.json")):
            try:
                data = _json.loads(manifest.read_text())
            except Exception as exc:
                logger.debug("Bad manifest %s: %s", manifest, exc)
                continue

            # Derive python name from directory (e.g. 'input_guard')
            skill_name = manifest.parent.name
            config = SkillConfig(name=skill_name, enabled=True)
            self._configs[skill_name] = config

            if skill_name in self._skill_classes:
                skill_class = self._skill_classes[skill_name]
                skill = skill_class(config)
                if skill_name == "pipeline":
                    init_ok = await skill.initialize(registry=self)
                else:
                    init_ok = await skill.initialize()
                if init_ok:
                    self._skills[skill_name] = skill
                    self._skills[skill.canonical_name] = skill
                    loaded += 1
                    logger.info("Loaded skill from manifest: %s", skill_name)
                else:
                    logger.warning("Failed to init skill from manifest: %s", skill_name)

        return loaded
    
    async def check_all_health(self) -> dict[str, SkillStatus]:
        """Run health checks on all loaded skills."""
        results = {}
        for name, skill in self._skills.items():
            try:
                results[name] = await skill.health_check()
            except Exception as e:
                logger.error(f"Health check failed for {name}: {e}")
                results[name] = SkillStatus.ERROR
        return results
    
    def get_all_metrics(self) -> dict[str, dict]:
        """Get metrics for all loaded skills."""
        return {
            name: skill.get_metrics()
            for name, skill in self._skills.items()
        }
