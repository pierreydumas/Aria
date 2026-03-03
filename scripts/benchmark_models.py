#!/usr/bin/env python3
"""
Benchmark local and remote models via the LiteLLM proxy.

TICKET-19 — Local Model Optimization
Measures latency and output token count for each model × task category.

Usage:
    python scripts/benchmark_models.py
    python scripts/benchmark_models.py --models qwen3-mlx trinity-free
    python scripts/benchmark_models.py --help
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

try:
    import httpx
except ImportError:
    print("ERROR: httpx is required.  pip install httpx")
    sys.exit(1)

# ── defaults ────────────────────────────────────────────────────────────────
LITELLM_URL = os.environ.get("LITELLM_URL", "http://localhost:18793")
try:
    import pathlib as _pl
    sys.path.insert(0, str(_pl.Path(__file__).resolve().parent.parent))
    from aria_models.loader import load_catalog as _lc
    _cat = _lc()
    DEFAULT_MODELS = [m.removeprefix("litellm/") for m in _cat.get("routing", {}).get("fallbacks", [])[:3]]
except Exception:
    DEFAULT_MODELS = []

# ── task categories (5 categories × 3 prompts each) ────────────────────────
TASK_PROMPTS: Dict[str, List[str]] = {
    "routing": [
        "Classify this request into one of: code, analysis, social, creative. Request: 'Write a Python function to sort a list'",
        "Given the user message 'How is Bitcoin doing today?', pick the best agent focus: orchestrator, devsecops, data, trader, creative, social, journalist.",
        "Route this task to the correct skill: 'Run the test suite and report failures'. Available skills: pytest_runner, brainstorm, social, market_data.",
    ],
    "code": [
        "Write a Python function that merges two sorted lists into one sorted list in O(n) time.",
        "Write a bash one-liner that finds all .py files modified in the last 24 hours and counts their total lines.",
        "Refactor this code to use async/await:\nimport requests\ndef fetch(url):\n    return requests.get(url).json()",
    ],
    "analysis": [
        "Summarise the key differences between transformer and SSM architectures in 3 bullet points.",
        "Given daily BTC prices [42000, 43500, 41000, 44200, 45000], calculate the 3-day moving average and identify the trend.",
        "Explain the trade-offs between 4-bit and 8-bit quantization for local LLM inference.",
    ],
    "social": [
        "Write a short, engaging tweet announcing that our AI agent now runs a local model on Apple Silicon.",
        "Draft a concise Moltbook post celebrating 100 days of uptime for the Aria project.",
        "Reply to this community message in a friendly, helpful tone: 'How do I set up the local model? The docs are confusing.'",
    ],
    "tooluse": [
        "You have access to tools: [web_search, calculator, code_executor]. Answer: 'What is 2^128 in decimal?'  Describe which tool you would call and with what arguments.",
        "Given tools [database_query, api_client, file_read], plan the steps to fetch the latest 10 log entries and summarise errors.",
        "You must call the 'schedule' tool to set a reminder. Generate the JSON function-call payload for: 'Remind me to check model benchmarks tomorrow at 9am'.",
    ],
}

TASK_CATEGORIES = list(TASK_PROMPTS.keys())


# ── result data ─────────────────────────────────────────────────────────────
@dataclass
class BenchmarkResult:
    model: str
    task: str
    prompt_index: int
    latency_s: float = 0.0
    output_tokens: int = 0
    error: Optional[str] = None


@dataclass
class ModelSummary:
    model: str
    results: List[BenchmarkResult] = field(default_factory=list)

    @property
    def avg_latency(self) -> float:
        ok = [r for r in self.results if r.error is None]
        return sum(r.latency_s for r in ok) / len(ok) if ok else 0.0

    @property
    def total_tokens(self) -> int:
        return sum(r.output_tokens for r in self.results)

    @property
    def error_count(self) -> int:
        return sum(1 for r in self.results if r.error is not None)


# ── benchmark logic ─────────────────────────────────────────────────────────
async def call_model(
    client: httpx.AsyncClient,
    model: str,
    prompt: str,
    timeout: float = 120.0,
) -> BenchmarkResult:
    """Send a single chat completion request and measure latency."""
    result = BenchmarkResult(model=model, task="", prompt_index=0)
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 512,
        "temperature": 0.3,
    }
    t0 = time.perf_counter()
    try:
        resp = await client.post(
            f"{LITELLM_URL}/v1/chat/completions",
            json=payload,
            timeout=timeout,
        )
        result.latency_s = time.perf_counter() - t0
        if resp.status_code != 200:
            result.error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            return result
        data = resp.json()
        usage = data.get("usage", {})
        result.output_tokens = usage.get("completion_tokens", 0)
    except httpx.TimeoutException:
        result.latency_s = time.perf_counter() - t0
        result.error = "TIMEOUT"
    except httpx.ConnectError:
        result.latency_s = time.perf_counter() - t0
        result.error = "CONNECTION_REFUSED"
    except Exception as exc:
        result.latency_s = time.perf_counter() - t0
        result.error = f"{type(exc).__name__}: {exc}"
    return result


async def benchmark_model(
    client: httpx.AsyncClient,
    model: str,
) -> ModelSummary:
    """Run all task prompts against one model."""
    summary = ModelSummary(model=model)
    for task, prompts in TASK_PROMPTS.items():
        for idx, prompt in enumerate(prompts):
            res = await call_model(client, model, prompt)
            res.task = task
            res.prompt_index = idx
            summary.results.append(res)
    return summary


async def run_benchmarks(models: List[str]) -> List[ModelSummary]:
    """Run benchmarks for all selected models."""
    summaries: List[ModelSummary] = []
    async with httpx.AsyncClient() as client:
        for model in models:
            print(f"  Benchmarking {model} …", flush=True)
            s = await benchmark_model(client, model)
            summaries.append(s)
            ok = len(s.results) - s.error_count
            print(f"    ✓ {ok}/{len(s.results)} prompts OK, avg {s.avg_latency:.2f}s")
    return summaries


# ── output ──────────────────────────────────────────────────────────────────
def format_markdown(summaries: List[ModelSummary]) -> str:
    """Render results as a Markdown table."""
    lines: List[str] = []
    lines.append("# Model Benchmark Results\n")
    lines.append(f"LiteLLM proxy: `{LITELLM_URL}`\n")

    # ── summary table ───────────────────────────────────────────────────
    lines.append("## Summary\n")
    lines.append("| Model | Avg Latency (s) | Total Tokens | Errors |")
    lines.append("|-------|----------------:|-------------:|-------:|")
    for s in summaries:
        lines.append(
            f"| {s.model} | {s.avg_latency:.2f} | {s.total_tokens} | {s.error_count} |"
        )
    lines.append("")

    # ── per-task breakdown ──────────────────────────────────────────────
    lines.append("## Per-Task Breakdown\n")
    lines.append("| Model | Task | Prompt# | Latency (s) | Tokens | Status |")
    lines.append("|-------|------|--------:|------------:|-------:|--------|")
    for s in summaries:
        for r in s.results:
            status = r.error if r.error else "OK"
            lines.append(
                f"| {r.model} | {r.task} | {r.prompt_index} | "
                f"{r.latency_s:.2f} | {r.output_tokens} | {status} |"
            )
    lines.append("")

    # ── per-category averages ───────────────────────────────────────────
    lines.append("## Category Averages\n")
    lines.append("| Model | Category | Avg Latency (s) | Avg Tokens |")
    lines.append("|-------|----------|-----------------:|-----------:|")
    for s in summaries:
        by_task: Dict[str, List[BenchmarkResult]] = {}
        for r in s.results:
            by_task.setdefault(r.task, []).append(r)
        for task, results in by_task.items():
            ok = [r for r in results if r.error is None]
            avg_lat = sum(r.latency_s for r in ok) / len(ok) if ok else 0.0
            avg_tok = sum(r.output_tokens for r in ok) / len(ok) if ok else 0.0
            lines.append(
                f"| {s.model} | {task} | {avg_lat:.2f} | {avg_tok:.0f} |"
            )
    lines.append("")
    return "\n".join(lines)


# ── CLI ─────────────────────────────────────────────────────────────────────
def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark LLM models via the LiteLLM proxy.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python benchmark_models.py\n"
            "  python benchmark_models.py --models qwen3-mlx trinity-free\n"
            "  LITELLM_URL=http://remote:4000 python benchmark_models.py\n"
        ),
    )
    parser.add_argument(
        "--models",
        nargs="+",
        default=DEFAULT_MODELS,
        help=f"Models to benchmark (default: {', '.join(DEFAULT_MODELS)})",
    )
    parser.add_argument(
        "--url",
        default=LITELLM_URL,
        help=f"LiteLLM proxy URL (default: {LITELLM_URL}, or set LITELLM_URL env var)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Write Markdown results to file (default: stdout)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> None:
    global LITELLM_URL
    args = parse_args(argv)
    LITELLM_URL = args.url

    print(f"Benchmarking {len(args.models)} model(s) against {LITELLM_URL}")
    print(f"Models: {', '.join(args.models)}")
    print(f"Tasks:  {', '.join(TASK_CATEGORIES)} ({sum(len(v) for v in TASK_PROMPTS.values())} prompts)\n")

    summaries = asyncio.run(run_benchmarks(args.models))
    md = format_markdown(summaries)

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(md)
        print(f"\nResults written to {args.output}")
    else:
        print("\n" + md)


if __name__ == "__main__":
    main()
