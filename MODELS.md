# Aria Blue ⚡️ — Model Routing

## Strategy

Aria uses a **local-first** LLM strategy: prefer on-device inference (Apple Silicon Metal GPU), fall back to free cloud models, use paid models only as a last resort.

All routing goes through [LiteLLM](https://github.com/BerriAI/litellm) with automatic failover and spend tracking.

---

## Tier Priority

| Tier | Strategy | Cost |
|------|----------|------|
| **Local** | MLX on Apple Silicon (Metal GPU) | Free — ~25-35 tok/s |
| **Free** | OpenRouter free-tier models | Free — rate-limited |
| **Paid** | Cloud APIs (last resort) | Per-token billing |

The routing priority, fallback chain, and all model definitions are in a single source of truth:

**→ [`aria_models/models.yaml`](aria_models/models.yaml)**

This file defines every model alias, provider, tier, context window, and pricing. Nothing else should duplicate this information.

---

## How It Works

```
Aria (or Agent)
     │
     ▼
LiteLLM Router (:18793)
     │
     ├─► Local: MLX Server (host:8080, Metal GPU)
     ├─► Free:  OpenRouter (multiple models)
     └─► Paid:  Cloud APIs (fallback only)
```

- LiteLLM receives a model alias (e.g., `litellm/qwen3-mlx`)
- Routes to the correct provider based on `models.yaml` configuration
- Automatic failover follows the `routing.fallbacks` chain
- All usage is tracked for cost monitoring

---

## Focus-to-Model Mapping

Each focus persona has a model hint for optimal routing. These mappings are defined in `aria_mind/soul/focus.py` with the canonical model names from `models.yaml`.

---

## Configuration

- Model catalog and routing: [`aria_models/models.yaml`](aria_models/models.yaml)
- Model loader: [`aria_models/loader.py`](aria_models/loader.py)
- LiteLLM proxy config: [`stacks/brain/litellm-config.yaml`](stacks/brain/litellm-config.yaml)
- Model documentation: [`aria_models/README.md`](aria_models/README.md)

To regenerate LiteLLM config from models.yaml:

```bash
python scripts/generate_litellm_config.py
```

To benchmark local models:

```bash
python tests/load/benchmark_models.py
```

---

## Related

- [ARCHITECTURE.md](ARCHITECTURE.md) — System design overview
- [DEPLOYMENT.md](DEPLOYMENT.md) — How to set up MLX server and configure API keys
