# Aria Model Catalog

Single source of truth for model definitions and routing.

> Last updated: 2026-03-10  
> User-facing routing guide: [MODELS.md](../MODELS.md)

- Catalog: `aria_models/models.yaml` (YAML, JSON-compatible)
- Loader: `aria_models/loader.py`
- Generated LiteLLM config: `stacks/brain/litellm-config.yaml`

## Active catalog

The repo keeps a small curated set of active models:

- `qwen3.5_mlx` — local MLX chat model
- `embedding` — local Ollama embedding model
- `trinity` — general free OpenRouter chat model
- `kimi` — paid Moonshot K2.5 long-context model

## Quick read (Python)

```python
from aria_models.loader import load_catalog

catalog = load_catalog()
models = catalog["models"].keys()
```

## Shape (derived views)

```yaml
schema_version: 5
routing:
  primary: litellm/kimi
criteria:
  tiers:
    local: [qwen3.5_mlx, embedding]
    free: [trinity]
    paid: [kimi]
tasks:
  primary: kimi
  embedding: embedding
```
