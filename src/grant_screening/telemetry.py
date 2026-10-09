"""Phase 8: OpenTelemetry -> Application Insights.

  * one root span per proposal ("screen <application_id>")
  * one child span per pipeline stage (A, B, C+D1, D2, E, F1+F2, F3, G1)
  * Agent Framework adds its own spans for chat calls, agent runs and tool calls
    (gen_ai semantic conventions: model, token counts, tool names)

Prompt and response CONTENT is not recorded (enable_sensitive_data=False): the
application text is personal data even after pseudonymisation. Counts, ids,
statuses and durations are enough to debug cost and latency.

Ingestion uses Entra ID (DefaultAzureCredential + Monitoring Metrics Publisher);
local auth is disabled on the Application Insights resource.
"""
from __future__ import annotations

import functools
import os
from contextlib import contextmanager

from opentelemetry import trace

_TRACER = trace.get_tracer("grant_screening")
_ENABLED = False


def setup(service_name: str = "grant-screening") -> bool:
    """Call once from an entry point. No-op without a connection string."""
    global _ENABLED
    conn = os.environ.get("APPLICATIONINSIGHTS_CONNECTION_STRING")
    if _ENABLED or not conn:
        return _ENABLED
    from azure.monitor.opentelemetry import configure_azure_monitor
    from agent_framework.observability import enable_instrumentation

    from grant_screening.azure_clients import credential

    os.environ.setdefault("OTEL_SERVICE_NAME", service_name)
    configure_azure_monitor(connection_string=conn, credential=credential())
    enable_instrumentation(enable_sensitive_data=False)
    _ENABLED = True
    return True


def flush() -> None:
    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()


@contextmanager
def span(name: str, **attributes):
    with _TRACER.start_as_current_span(name) as s:
        for k, v in attributes.items():
            if v is not None:
                s.set_attribute(k, v)
        yield s


def traced_stage(stage: str):
    """Decorator for stage functions taking a case dict as first argument."""
    def deco(fn):
        @functools.wraps(fn)
        def wrapper(case, *args, **kwargs):
            import time

            with span(f"stage {stage}", **{"grant.application_id": case.get("application_id"),
                                           "grant.stage": stage}) as s:
                before = len(case["ledger"].entries) if "ledger" in case else 0
                t0 = time.perf_counter()
                out = fn(case, *args, **kwargs)
                timing = {"ms": int((time.perf_counter() - t0) * 1000), "llm_calls": 0, "tokens": 0}
                if "ledger" in case:
                    new = case["ledger"].entries[before:]
                    timing["llm_calls"] = sum(1 for u in new if not u.cached)
                    timing["cached_calls"] = sum(1 for u in new if u.cached)
                    timing["tokens"] = sum(u.input_tokens + u.output_tokens for u in new)
                    s.set_attribute("grant.llm_calls", len(new))
                    s.set_attribute("grant.input_tokens", sum(u.input_tokens for u in new))
                    s.set_attribute("grant.output_tokens", sum(u.output_tokens for u in new))
                    s.set_attribute("grant.cache_hits", sum(1 for u in new if u.cached))
                if case.get("decision"):
                    s.set_attribute("grant.decision", case["decision"]["decision"])
                case.setdefault("timings", {})[stage] = timing  # shown as the timeline in the UI
                return out
        return wrapper
    return deco
