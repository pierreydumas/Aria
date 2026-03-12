# {{skill_name}}

> TODO: One-line summary of what this skill does.

## Purpose

TODO: 2-3 sentences explaining:
- What problem this skill solves
- Which external services it connects to (if any)
- Which agent types benefit most (e.g. "primarily for data-focused agents")

## Layer

**Layer {{layer}} — {{layer_name}}**

<!-- Layer reference:
  0 = Kernel (read-only security), 1 = API Client (DB gateway),
  2 = Core (runtime services), 3 = Domain (feature logic),
  4 = Orchestration (planning/scheduling) -->

## Tools

### {{skill_name}}__{{tool_1}}

TODO: Describe what this tool does and when to use it.

| Parameter | Type   | Required | Description          |
|-----------|--------|----------|----------------------|
| `param`   | string | yes      | TODO: describe param |

**Returns:** TODO: describe the return format.

**Example:**
```
Input:  {"param": "example_value"}
Output: {"result": "..."}
```

## Dependencies

- `api_client` (Layer 1) — for database access
<!-- List all skills this one depends on -->

## Configuration

| Env Variable        | Required | Description            |
|--------------------|----------|------------------------|
| `TEMPLATE_API_KEY` | yes      | API key for the service |

## Error Handling

| Error                    | Cause                        | Fix                        |
|--------------------------|------------------------------|----------------------------|
| `"API key not set"`      | Missing env var              | Set `TEMPLATE_API_KEY`     |
| `"Rate limited"`         | Too many requests            | Wait and retry             |

## Notes

- TODO: Any gotchas, limits, or important behavior to know about.
