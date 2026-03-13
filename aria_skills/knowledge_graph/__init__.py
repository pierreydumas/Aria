# aria_skills/knowledge_graph.py
"""
Knowledge graph skill.

Manages entities and relationships in Aria's knowledge base.
Persists via REST API (TICKET-12: eliminate in-memory stubs).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from aria_skills.api_client import get_api_client
from aria_skills.base import BaseSkill, SkillConfig, SkillResult, SkillStatus
from aria_skills.registry import SkillRegistry

from .cache import get_shared_cache


@SkillRegistry.register
class KnowledgeGraphSkill(BaseSkill):
    """
    Knowledge graph management.
    
    Stores entities and their relationships for reasoning.
    """
    
    def __init__(self, config: SkillConfig):
        super().__init__(config)
        self._entities: dict[str, dict] = {}  # fallback cache
        self._relations: list[dict] = []  # fallback cache
        self._api = None
        self._cache = get_shared_cache()
    
    @property
    def name(self) -> str:
        return "knowledge_graph"
    
    async def initialize(self) -> bool:
        """Initialize knowledge graph."""
        self._api = await get_api_client()
        self._status = SkillStatus.AVAILABLE
        self.logger.info("Knowledge graph initialized (API-backed, cache enabled)")
        return True
    
    async def close(self):
        """Cleanup (shared API client is managed by api_client module)."""
        self._api = None
    
    async def health_check(self) -> SkillStatus:
        """Check availability."""
        return self._status
    
    async def add_entity(
        self,
        name: str,
        entity_type: str,
        properties: dict | None = None,
    ) -> SkillResult:
        """Add an entity to the knowledge graph."""
        entity_id = f"{entity_type}:{name}".lower().replace(" ", "_")
        
        entity = {
            "id": entity_id,
            "name": name,
            "type": entity_type,
            "properties": properties or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            result = await self._api.post("/knowledge-graph/entities", data=entity)
            if not result:
                raise Exception(result.error)
            api_data = result.data
            saved = api_data if api_data else entity
            self._cache.invalidate(name)
            self._cache.put_entity(saved)
            return SkillResult.ok(saved)
        except Exception as e:
            self.logger.warning(f"API add_entity failed, using fallback: {e}")
            self._entities[entity_id] = entity
            return SkillResult.ok(entity)
    
    async def add_relation(
        self,
        from_entity: str,
        relation: str,
        to_entity: str,
        properties: dict | None = None,
    ) -> SkillResult:
        """Add a relationship between entities."""
        rel = {
            "from_entity": from_entity,
            "relation_type": relation,
            "to_entity": to_entity,
            "properties": properties or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        
        try:
            result = await self._api.post("/knowledge-graph/relations", data=rel)
            if not result:
                raise Exception(result.error)
            api_data = result.data
            self._cache.invalidate(from_entity)
            self._cache.invalidate(to_entity)
            return SkillResult.ok(api_data if api_data else rel)
        except Exception as e:
            detail = ""
            if hasattr(e, "response") and e.response is not None:
                try:
                    detail = f" — API response: {e.response.text[:500]}"
                except Exception:
                    pass
            self.logger.warning(f"API add_relation failed, using fallback: {e}{detail}")
            self._relations.append(rel)
            return SkillResult.ok(rel)
    
    async def get_entity(
        self,
        query: str | None = None,
        type: str | None = None,
        entity_id: str | None = None,
    ) -> SkillResult:
        """Search for and retrieve an entity by name/query, type, or ID."""
        lookup = entity_id or query
        if not lookup:
            return SkillResult.fail("Provide 'query' or 'entity_id'")

        # Check cache first
        if entity_id:
            cached = self._cache.get_entity(entity_id)
            if cached is not None:
                return SkillResult.ok({"entity": cached, "relations": [], "_cached": True})
        if query and type:
            cached = self._cache.get_entity_by_name(query, type)
            if cached is not None:
                return SkillResult.ok({"entity": cached, "relations": [], "_cached": True})

        try:
            params: dict[str, Any] = {}
            if type:
                params["type"] = type
            result = await self._api.get("/knowledge-graph/entities", params=params)
            if not result:
                raise Exception(result.error)
            data = result.data
            entities = data.get("entities", data if isinstance(data, list) else [])
            # Filter by name match
            matches = [e for e in entities if lookup.lower() in e.get("name", "").lower()]
            if matches:
                self._cache.put_entity(matches[0])
                return SkillResult.ok({"entity": matches[0], "relations": []})
            return SkillResult.fail(f"Entity not found: {lookup}")
        except Exception as e:
            self.logger.warning(f"API get_entity failed, using fallback: {e}")
            lookup_key = lookup.lower().replace(" ", "_")
            entity_keys = [k for k in self._entities if lookup_key in k]
            if not entity_keys:
                return SkillResult.fail(f"Entity not found: {lookup}")
            entity = self._entities[entity_keys[0]]
            relations = [
                r for r in self._relations
                if r["from_entity"] == entity_keys[0] or r["to_entity"] == entity_keys[0]
            ]
            return SkillResult.ok({"entity": entity, "relations": relations})
    
    async def query(
        self,
        entity_name: str | None = None,
        depth: int = 1,
        entity_type: str | None = None,
        relation: str | None = None,
    ) -> SkillResult:
        """Query the knowledge graph. Find entities related to a given entity.
        
        When entity_name + depth are given, performs a BFS traversal.
        When only entity_type/relation are given, lists matching entities.
        """
        # --- Check traversal cache ---
        if entity_name:
            cached = self._cache.get_traversal(entity_name, depth, relation, entity_type)
            if cached is not None:
                cached["_cached"] = True
                return SkillResult.ok(cached)

        # --- Path A: Traverse from a named entity ---
        if entity_name:
            try:
                params: dict[str, Any] = {
                    "start": entity_name,
                    "max_depth": depth,
                    "direction": "both",
                }
                if relation:
                    params["relation_type"] = relation
                resp = await self._api.get("/knowledge-graph/kg-traverse", params=params)
                if not resp:
                    raise Exception(resp.error)
                data = resp.data
                # If traverse found the entity, return subgraph
                if not data.get("error"):
                    result_data = {
                        "entities": data.get("nodes", []),
                        "relations": data.get("edges", []),
                        "total_entities": data.get("total_nodes", 0),
                        "total_relations": data.get("total_edges", 0),
                    }
                    self._cache.put_traversal(entity_name, depth, result_data, relation, entity_type)
                    return SkillResult.ok(result_data)
                # If entity not found via traverse, fall through to search
            except Exception as e:
                self.logger.warning(f"API kg-traverse failed: {e}")

            # Fallback: search by name
            try:
                params = {"q": entity_name, "limit": 50}
                if entity_type:
                    params["entity_type"] = entity_type
                resp = await self._api.get("/knowledge-graph/kg-search", params=params)
                if not resp:
                    raise Exception(resp.error)
                data = resp.data
                entities = data.get("results", [])
                return SkillResult.ok({
                    "entities": entities,
                    "relations": [],
                    "total_entities": len(entities),
                    "total_relations": 0,
                })
            except Exception as e:
                self.logger.warning(f"API kg-search failed: {e}")

        # --- Path B: List entities by type/relation ---
        try:
            params = {}
            if entity_type:
                params["type"] = entity_type
            resp = await self._api.get("/knowledge-graph/entities", params=params)
            if not resp:
                raise Exception(resp.error)
            api_data = resp.data
            entities = api_data if isinstance(api_data, list) else api_data.get("entities", [])
            if entity_name:
                entities = [
                    e for e in entities
                    if entity_name.lower() in e.get("name", "").lower()
                ]
            return SkillResult.ok({
                "entities": entities,
                "relations": [],
                "total_entities": len(entities),
                "total_relations": 0,
            })
        except Exception as e:
            self.logger.warning(f"API query failed, using fallback: {e}")
            entities = list(self._entities.values())
            if entity_type:
                entities = [ent for ent in entities if ent["type"] == entity_type]
            if entity_name:
                entities = [
                    ent for ent in entities
                    if entity_name.lower() in ent.get("name", "").lower()
                ]
            relations = self._relations
            if relation:
                relations = [r for r in relations if r["relation_type"] == relation]
            return SkillResult.ok({
                "entities": entities,
                "relations": relations,
                "total_entities": len(entities),
                "total_relations": len(relations),
            })

    async def cache_stats(self) -> SkillResult:
        """Return KG cache hit/miss statistics."""
        return SkillResult.ok(self._cache.stats)
