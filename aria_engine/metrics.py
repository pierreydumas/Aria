"""
Prometheus metrics for Aria Blue.

Exposes metrics on port 8081 via a dedicated HTTP server.
All counters, histograms, and gauges follow Prometheus naming conventions.

Usage:
    from aria_engine.metrics import METRICS, start_metrics_server

    # Start metrics server on port 8081
    await start_metrics_server(port=8081)

    # Record a request
    METRICS.request_duration.labels(method="chat", status="200").observe(0.15)
"""
import asyncio
import gc
import os
import time
from typing import Any

from prometheus_client import (
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    Info,
    Summary,
    generate_latest,
    start_http_server,
    REGISTRY,
)


# ---------------------------------------------------------------------------
# Custom registry (allows testing without global state pollution)
# ---------------------------------------------------------------------------

registry = REGISTRY


# ---------------------------------------------------------------------------
# Metric definitions
# ---------------------------------------------------------------------------

class AriaMetrics:
    """All Aria Blue metrics in one place."""

    def __init__(self, reg: CollectorRegistry = registry):
        # -- System info --
        self.build_info = Info(
            "aria_build",
            "Aria Blue build information",
            registry=reg,
        )

        # -- Request metrics --
        self.request_total = Counter(
            "aria_requests_total",
            "Total requests processed",
            ["method", "status"],
            registry=reg,
        )

        self.request_duration = Histogram(
            "aria_request_duration_seconds",
            "Request duration in seconds",
            ["method"],
            buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
            registry=reg,
        )

        self.request_in_progress = Gauge(
            "aria_requests_in_progress",
            "Number of requests currently being processed",
            ["method"],
            registry=reg,
        )

        # -- LLM metrics --
        self.llm_request_total = Counter(
            "aria_llm_requests_total",
            "Total LLM API calls",
            ["model", "status"],
            registry=reg,
        )

        self.llm_request_duration = Histogram(
            "aria_llm_request_duration_seconds",
            "LLM request duration (time to first token for streaming)",
            ["model"],
            buckets=[0.1, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0],
            registry=reg,
        )

        self.llm_tokens_input = Counter(
            "aria_llm_tokens_input_total",
            "Total input tokens sent to LLM",
            ["model"],
            registry=reg,
        )

        self.llm_tokens_output = Counter(
            "aria_llm_tokens_output_total",
            "Total output tokens received from LLM",
            ["model"],
            registry=reg,
        )

        self.llm_token_cost_estimate = Counter(
            "aria_llm_token_cost_estimate_total",
            "Estimated token cost in USD",
            ["model"],
            registry=reg,
        )

        self.llm_circuit_breaker_state = Gauge(
            "aria_llm_circuit_breaker_state",
            "Circuit breaker state (0=closed, 1=open, 2=half-open)",
            ["model"],
            registry=reg,
        )

        self.llm_thinking_duration = Histogram(
            "aria_llm_thinking_duration_seconds",
            "Duration of thinking/reasoning phase",
            ["model"],
            buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 30.0, 60.0, 120.0],
            registry=reg,
        )

        # -- LLM fallback metrics (ARIA-REV-117) --
        self.llm_fallback_total = Counter(
            "aria_llm_fallback_total",
            "Total LLM fallback events",
            ["primary_model", "fallback_model"],
            registry=reg,
        )

        # -- Agent metrics --
        self.agent_routing_total = Counter(
            "aria_agent_routing_total",
            "Total agent routing decisions",
            ["selected_agent"],
            registry=reg,
        )

        self.agent_routing_duration = Histogram(
            "aria_agent_routing_duration_seconds",
            "Time to make routing decision",
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5],
            registry=reg,
        )

        self.agent_pheromone_score = Gauge(
            "aria_agent_pheromone_score",
            "Current pheromone score for each agent",
            ["agent_id"],
            registry=reg,
        )

        self.agent_task_total = Counter(
            "aria_agent_tasks_total",
            "Total tasks executed by each agent",
            ["agent_id", "status"],
            registry=reg,
        )

        self.agent_active = Gauge(
            "aria_agents_active",
            "Number of active agents",
            registry=reg,
        )

        # -- Session metrics --
        self.sessions_active = Gauge(
            "aria_sessions_active",
            "Number of active sessions",
            registry=reg,
        )

        self.sessions_created_total = Counter(
            "aria_sessions_created_total",
            "Total sessions created",
            registry=reg,
        )

        self.sessions_messages_total = Counter(
            "aria_sessions_messages_total",
            "Total messages across all sessions",
            ["role"],
            registry=reg,
        )

        self.session_duration = Histogram(
            "aria_session_duration_seconds",
            "Session duration from creation to last message",
            buckets=[60, 300, 600, 1800, 3600, 7200, 86400],
            registry=reg,
        )

        # -- Scheduler metrics --
        self.scheduler_jobs_total = Gauge(
            "aria_scheduler_jobs_total",
            "Total registered scheduler jobs",
            ["status"],
            registry=reg,
        )

        self.scheduler_executions_total = Counter(
            "aria_scheduler_executions_total",
            "Total scheduler job executions",
            ["job_id", "status"],
            registry=reg,
        )

        self.scheduler_execution_duration = Histogram(
            "aria_scheduler_execution_duration_seconds",
            "Scheduler job execution duration",
            ["job_id"],
            buckets=[0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0, 300.0],
            registry=reg,
        )

        self.scheduler_last_run = Gauge(
            "aria_scheduler_last_run_timestamp",
            "Unix timestamp of last successful run for each job",
            ["job_id"],
            registry=reg,
        )

        self.scheduler_session_close_failures_total = Counter(
            "aria_scheduler_session_close_failures_total",
            "Total scheduler session close/cleanup failures",
            ["job_id", "phase"],
            registry=reg,
        )

        # -- Skill metrics --
        self.skill_execution_total = Counter(
            "aria_skill_executions_total",
            "Total skill executions",
            ["skill_name", "status"],
            registry=reg,
        )

        self.skill_execution_duration = Histogram(
            "aria_skill_execution_duration_seconds",
            "Skill execution duration",
            ["skill_name"],
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
            registry=reg,
        )

        # -- Database metrics --
        self.db_query_total = Counter(
            "aria_db_queries_total",
            "Total database queries",
            ["operation"],
            registry=reg,
        )

        self.db_query_duration = Histogram(
            "aria_db_query_duration_seconds",
            "Database query duration",
            ["operation"],
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0],
            registry=reg,
        )

        self.db_pool_size = Gauge(
            "aria_db_pool_size",
            "Current database connection pool size",
            registry=reg,
        )

        self.db_pool_available = Gauge(
            "aria_db_pool_available",
            "Available database connections",
            registry=reg,
        )

        # -- Error metrics --
        self.errors_total = Counter(
            "aria_errors_total",
            "Total errors by type",
            ["error_type", "component"],
            registry=reg,
        )

        # -- Memory metrics --
        self.memory_rss_bytes = Gauge(
            "aria_memory_rss_bytes",
            "Resident Set Size in bytes",
            registry=reg,
        )

        self.memory_gc_objects = Gauge(
            "aria_memory_gc_objects",
            "Number of objects tracked by GC",
            registry=reg,
        )


# Singleton
METRICS = AriaMetrics()


# ---------------------------------------------------------------------------
# Helper decorators
# ---------------------------------------------------------------------------

def track_request(method: str):
    """Decorator to track request metrics."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            METRICS.request_in_progress.labels(method=method).inc()
            start = time.monotonic()
            status = "200"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "500"
                METRICS.errors_total.labels(
                    error_type=type(e).__name__,
                    component=method,
                ).inc()
                raise
            finally:
                duration = time.monotonic() - start
                METRICS.request_total.labels(method=method, status=status).inc()
                METRICS.request_duration.labels(method=method).observe(duration)
                METRICS.request_in_progress.labels(method=method).dec()
        return wrapper
    return decorator


def track_llm(model: str):
    """Decorator to track LLM call metrics."""
    def decorator(func):
        async def wrapper(*args, **kwargs):
            start = time.monotonic()
            status = "success"
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                status = "error"
                METRICS.errors_total.labels(
                    error_type=type(e).__name__,
                    component="llm",
                ).inc()
                raise
            finally:
                duration = time.monotonic() - start
                METRICS.llm_request_total.labels(model=model, status=status).inc()
                METRICS.llm_request_duration.labels(model=model).observe(duration)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Metrics server
# ---------------------------------------------------------------------------

async def start_metrics_server(port: int = 8081) -> None:
    """Start the Prometheus metrics HTTP server on a dedicated port."""
    start_http_server(port, registry=registry)

    # Set build info
    METRICS.build_info.info({
        "version": os.getenv("ARIA_VERSION", "2.0.0"),
        "python": f"{os.sys.version_info.major}.{os.sys.version_info.minor}.{os.sys.version_info.micro}",
        "engine": "aria_engine",
    })


async def update_system_metrics() -> None:
    """Periodically update system-level metrics. Call every 30s."""
    try:
        import psutil
        proc = psutil.Process()
        METRICS.memory_rss_bytes.set(proc.memory_info().rss)
    except ImportError:
        pass

    METRICS.memory_gc_objects.set(len(gc.get_objects()))
