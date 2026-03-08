# Aria Engine Benchmarks

**Python:** 3.13  
**JIT:** Disabled  
**Date:** 2026-02-19 00:32:00  
**Iterations:** 100  
**Hardware:** Mac Mini M-series Apple Silicon (record hardware model here for regression tracking)  
**Baseline:** Values below are point-in-time snapshots; re-run with `pytest --benchmark-only` to compare.

## Results

| Benchmark | Mean (ms) | Median (ms) | P95 (ms) | P99 (ms) | Std (ms) |
|-----------|-----------|-------------|----------|----------|----------|
| bench_toml_parsing | 0.888 | 0.886 | 0.906 | 0.935 | 0.011 |
| bench_context_assembly | 0.144 | 0.142 | 0.152 | 0.216 | 0.008 |
| bench_pheromone_scoring | 0.006 | 0.006 | 0.006 | 0.006 | 0.000 |
| bench_json_serialization | 0.526 | 0.521 | 0.547 | 0.611 | 0.015 |
| bench_async_context_switch | 0.000 | 0.001 | 0.001 | 0.001 | 0.000 |
| bench_semaphore_acquire | 0.002 | 0.002 | 0.002 | 0.006 | 0.001 |

## Notes

- JIT (Disabled): Set via `PYTHON_JIT=0`
- All times in milliseconds
- Warmup iterations excluded from measurement
- Run both JIT=0 and JIT=1 and compare results