# Aria Model Catalog

Single source of truth for model definitions and routing.

> **User-facing routing guide:** [MODELS.md](../MODELS.md) — tier strategy,
> LiteLLM topology, focus-to-model mapping, and benchmark scripts.

- Catalog: `aria_models/models.yaml` (YAML, JSON-compatible)
- Loader: `aria_models/loader.py`
- LiteLLM routing config remains in `stacks/brain/litellm-config.yaml` (keep aligned)

## Quick read (Python)

```python
import json
from pathlib import Path

catalog = json.loads(Path("aria_models/models.yaml").read_text())
models = catalog["models"].keys()
```

## Structure (example)

```yaml
schema_version: 1
routing:
  primary: litellm/qwen3-mlx
  fallbacks:
    - litellm/trinity-free
criteria:
  tiers:
    local: [qwen3-mlx]
    free: [trinity-free, chimera-free]
    paid: [kimi]
```
