"""
Structured agent trace logging for the demo workflow.

The trace is intentionally summary-oriented. It records what phase ran,
what tool or action was taken, what model/provider was configured, and what
data was persisted, without exposing raw chain-of-thought.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Optional

from app.core.db import create_audit_log, get_audit_logs
from app.core.llm import get_llm_provider_metadata
from app.core.redis_state import cache_get, cache_set

logger = logging.getLogger(__name__)

TRACE_LEVEL_DEBUG = "debug"
TRACE_LEVEL_INFO = "info"
TRACE_LEVEL_WARNING = "warning"
TRACE_LEVEL_ERROR = "error"

TRACE_STATUS_SUCCESS = "success"
TRACE_STATUS_IN_PROGRESS = "in_progress"
TRACE_STATUS_WARNING = "warning"
TRACE_STATUS_ERROR = "error"

_trace_buffer: dict[str, list[dict[str, Any]]] = {}


def _get_trace_key(vendor_id: str) -> str:
    return f"agent_trace:{vendor_id}"


def _truncate_text(value: str, limit: int = 240) -> str:
    value = value.strip()
    if len(value) <= limit:
        return value
    return f"{value[: limit - 3]}..."


def _sanitize(value: Any, *, depth: int = 0) -> Any:
    if value is None:
        return None
    if isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return _truncate_text(value, 320)
    if depth >= 2:
        return _truncate_text(str(value), 320)
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 8:
                sanitized["_truncated"] = True
                break
            sanitized[str(key)] = _sanitize(item, depth=depth + 1)
        return sanitized
    if isinstance(value, (list, tuple, set)):
        items = list(value)[:8]
        result = [_sanitize(item, depth=depth + 1) for item in items]
        if len(list(value)) > 8:
            result.append({"_truncated": True})
        return result
    return _truncate_text(str(value), 320)


def _summary_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return _truncate_text(value, 240)
    if isinstance(value, dict):
        interesting = []
        for key in (
            "summary",
            "status",
            "message",
            "overall_score",
            "overall_risk_score",
            "risk_level",
            "grade",
            "document_type",
            "count",
        ):
            if key in value and value[key] not in (None, "", [], {}):
                interesting.append(f"{key}={_sanitize(value[key])}")
        if interesting:
            return "; ".join(interesting)
    return _truncate_text(str(_sanitize(value)), 240)


def _entry_level(status: str) -> str:
    if status == TRACE_STATUS_ERROR:
        return TRACE_LEVEL_ERROR
    if status == TRACE_STATUS_WARNING:
        return TRACE_LEVEL_WARNING
    return TRACE_LEVEL_INFO


def _add_to_buffer(vendor_id: str, entry: dict[str, Any]) -> None:
    bucket = _trace_buffer.setdefault(vendor_id, [])
    bucket.append(entry)
    if len(bucket) > 200:
        _trace_buffer[vendor_id] = bucket[-200:]


def _persist_trace(vendor_id: str, entry: dict[str, Any]) -> None:
    try:
        existing = cache_get(_get_trace_key(vendor_id)) or []
        existing.append(entry)
        if len(existing) > 100:
            existing = existing[-100:]
        cache_set(_get_trace_key(vendor_id), existing, ttl=86400)
    except Exception as exc:
        logger.warning("Failed to cache trace for %s: %s", vendor_id, exc)


def record_trace(
    *,
    vendor_id: str,
    agent_name: str,
    step: str,
    status: str,
    message: str,
    phase: Optional[str] = None,
    action_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    input_summary: Any = None,
    output_summary: Any = None,
    db_write_summary: Any = None,
    error: Optional[str] = None,
    duration_ms: Optional[int] = None,
    trace_id: Optional[str] = None,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    fallback_used: Optional[bool] = None,
) -> str:
    trace_id = trace_id or f"{agent_name}_{step}_{int(time.time() * 1000)}"
    llm_meta = get_llm_provider_metadata(tooling=True)
    entry = {
        "trace_id": trace_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "vendor_id": vendor_id,
        "phase": phase or agent_name,
        "agent_name": agent_name,
        "step": step,
        "action_name": action_name or step,
        "event_type": step,
        "status": status,
        "level": _entry_level(status),
        "message": _truncate_text(message, 320),
        "thinking": None,
        "provider": provider or llm_meta.get("provider"),
        "model": model or llm_meta.get("model"),
        "fallback_used": fallback_used if fallback_used is not None else False,
        "fallback_available": llm_meta.get("fallback_configured", False),
        "tool_name": tool_name,
        "input_summary": _sanitize(input_summary),
        "output_summary": _sanitize(output_summary),
        "db_write_summary": _sanitize(db_write_summary),
        "duration_ms": duration_ms,
        "error": error,
        "tool_calls": (
            [
                {
                    "tool_name": tool_name,
                    "input": _sanitize(input_summary),
                    "output_status": status,
                    "duration_ms": duration_ms,
                    "output_preview": _summary_text(output_summary),
                }
            ]
            if tool_name
            else []
        ),
        "decisions": (
            [
                {
                    "decision": _truncate_text(message, 200),
                    "data": _sanitize(output_summary),
                }
            ]
            if step == "decision"
            else []
        ),
    }

    _add_to_buffer(vendor_id, entry)
    _persist_trace(vendor_id, entry)

    try:
        create_audit_log(
            vendor_id=vendor_id,
            agent_name=agent_name,
            action=f"trace:{step}",
            tool_name=tool_name,
            input_data={
                "phase": phase or agent_name,
                "input_summary": entry["input_summary"],
                "provider": entry["provider"],
                "model": entry["model"],
            },
            output_data={
                "message": entry["message"],
                "output_summary": entry["output_summary"],
                "db_write_summary": entry["db_write_summary"],
                "trace_id": trace_id,
            },
            status="error" if status == TRACE_STATUS_ERROR else "success",
            error_message=error,
            duration_ms=duration_ms,
        )
    except Exception as exc:
        logger.warning("Failed to persist audit trace for %s: %s", vendor_id, exc)

    return trace_id


def trace_agent_start(
    vendor_id: str,
    agent_name: str,
    input_data: dict[str, Any],
    trace_id: Optional[str] = None,
) -> str:
    return record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="start",
        action_name="agent_started",
        status=TRACE_STATUS_IN_PROGRESS,
        message=f"{agent_name} started with summarized input context.",
        input_summary=input_data,
        trace_id=trace_id,
    )


def trace_agent_thinking(
    vendor_id: str,
    agent_name: str,
    thinking: str,
    trace_id: Optional[str] = None,
    level: str = TRACE_LEVEL_DEBUG,
) -> None:
    record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="process_summary",
        status=TRACE_STATUS_IN_PROGRESS,
        message=thinking,
        trace_id=trace_id,
    )


def trace_tool_call(
    vendor_id: str,
    agent_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    tool_output_status: str = "success",
    tool_output: Optional[str] = None,
    duration_ms: Optional[int] = None,
    trace_id: Optional[str] = None,
) -> None:
    status = {
        "success": TRACE_STATUS_SUCCESS,
        "in_progress": TRACE_STATUS_IN_PROGRESS,
        "warning": TRACE_STATUS_WARNING,
        "error": TRACE_STATUS_ERROR,
    }.get(tool_output_status, TRACE_STATUS_SUCCESS)
    record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="tool_call",
        action_name="tool_called",
        status=status,
        message=f"{agent_name} used tool {tool_name} with status {tool_output_status}.",
        tool_name=tool_name,
        input_summary=tool_input,
        output_summary={"summary": tool_output} if tool_output else None,
        duration_ms=duration_ms,
        trace_id=trace_id,
        error=tool_output if status == TRACE_STATUS_ERROR else None,
    )


def trace_agent_decision(
    vendor_id: str,
    agent_name: str,
    decision: str,
    decision_data: Optional[dict[str, Any]] = None,
    trace_id: Optional[str] = None,
) -> None:
    record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="decision",
        status=TRACE_STATUS_SUCCESS,
        message=decision,
        output_summary=decision_data,
        trace_id=trace_id,
    )


def trace_agent_complete(
    vendor_id: str,
    agent_name: str,
    result: dict[str, Any],
    trace_id: Optional[str] = None,
) -> None:
    record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="complete",
        action_name="agent_completed",
        status=TRACE_STATUS_SUCCESS if result.get("status") not in {"error", "failed"} else TRACE_STATUS_ERROR,
        message=f"{agent_name} completed.",
        output_summary={
            "status": result.get("status"),
            "overall_score": result.get("overall_score"),
            "overall_risk_score": result.get("overall_risk_score"),
            "risk_level": result.get("risk_level"),
        },
        db_write_summary=result.get("db_write_summary"),
        trace_id=trace_id,
    )


def trace_agent_error(
    vendor_id: str,
    agent_name: str,
    error: str,
    error_type: Optional[str] = None,
    trace_id: Optional[str] = None,
) -> None:
    record_trace(
        vendor_id=vendor_id,
        agent_name=agent_name,
        phase=agent_name,
        step="error",
        action_name="agent_error",
        status=TRACE_STATUS_ERROR,
        message=f"{agent_name} failed.",
        output_summary={"error_type": error_type},
        error=error,
        trace_id=trace_id,
    )


def trace_workflow_phase(
    vendor_id: str,
    phase: str,
    message: str,
    progress_percentage: int = 0,
) -> None:
    record_trace(
        vendor_id=vendor_id,
        agent_name="workflow_orchestrator",
        phase=phase,
        step="phase_transition",
        action_name="phase_transition",
        status=TRACE_STATUS_IN_PROGRESS,
        message=message,
        output_summary={"progress_percentage": progress_percentage},
    )


def get_agent_traces(vendor_id: str) -> list[dict[str, Any]]:
    return _trace_buffer.get(vendor_id, [])


def _trace_from_audit_log(log: dict[str, Any]) -> dict[str, Any]:
    input_data = log.get("input_data", {}) or {}
    output_data = log.get("output_data", {}) or {}
    return {
        "trace_id": output_data.get("trace_id") or str(log.get("id") or ""),
        "timestamp": log.get("created_at"),
        "vendor_id": log.get("vendor_id"),
        "phase": input_data.get("phase") or log.get("agent_name"),
        "agent_name": log.get("agent_name"),
        "step": str(log.get("action", "")).replace("trace:", "") or "audit",
        "action_name": log.get("action"),
        "event_type": str(log.get("action", "")).replace("trace:", "") or "audit",
        "status": "error" if log.get("status") == "error" else "success",
        "level": TRACE_LEVEL_ERROR if log.get("status") == "error" else TRACE_LEVEL_INFO,
        "message": output_data.get("message")
        or f"{log.get('agent_name')} {log.get('action')}",
        "thinking": None,
        "provider": input_data.get("provider"),
        "model": input_data.get("model"),
        "fallback_used": False,
        "fallback_available": False,
        "tool_name": log.get("tool_name"),
        "input_summary": input_data.get("input_summary") or _sanitize(input_data),
        "output_summary": output_data.get("output_summary") or _sanitize(output_data),
        "db_write_summary": output_data.get("db_write_summary"),
        "duration_ms": log.get("duration_ms"),
        "error": log.get("error_message"),
        "tool_calls": (
            [
                {
                    "tool_name": log.get("tool_name"),
                    "input": input_data.get("input_summary") or _sanitize(input_data),
                    "output_status": log.get("status"),
                    "duration_ms": log.get("duration_ms"),
                    "output_preview": _summary_text(output_data),
                }
            ]
            if log.get("tool_name")
            else []
        ),
        "decisions": [],
    }


def get_persisted_traces(vendor_id: str) -> list[dict[str, Any]]:
    try:
        cached = cache_get(_get_trace_key(vendor_id)) or []
    except Exception:
        cached = []

    if cached:
        return cached

    try:
        logs = get_audit_logs(vendor_id)
    except Exception:
        return []
    return [_trace_from_audit_log(log) for log in logs]


def clear_trace_buffer(vendor_id: str) -> None:
    _trace_buffer.pop(vendor_id, None)


@contextmanager
def trace_tool_execution(
    vendor_id: str,
    agent_name: str,
    tool_name: str,
    tool_input: dict[str, Any],
    trace_id: Optional[str] = None,
):
    start_time = time.time()
    trace_tool_call(
        vendor_id,
        agent_name,
        tool_name,
        tool_input,
        tool_output_status="in_progress",
        trace_id=trace_id,
    )
    try:
        yield
        duration_ms = int((time.time() - start_time) * 1000)
        trace_tool_call(
            vendor_id,
            agent_name,
            tool_name,
            tool_input,
            tool_output_status="success",
            duration_ms=duration_ms,
            trace_id=trace_id,
        )
    except Exception as exc:
        duration_ms = int((time.time() - start_time) * 1000)
        trace_tool_call(
            vendor_id,
            agent_name,
            tool_name,
            tool_input,
            tool_output_status="error",
            tool_output=str(exc),
            duration_ms=duration_ms,
            trace_id=trace_id,
        )
        raise
