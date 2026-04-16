"""
Supervisor Agent.

Phase 3 uses the supervisor as the final packet compiler instead of a task
delegator. Delegation happens in the LangGraph itself.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from app.core.db import create_audit_log, get_approval_request, get_vendor
from app.core.llm import get_tool_llm
from app.core.redis_state import save_state
from app.tools.supervisor_tools import SUPERVISOR_TOOLS, compile_approval_packet

logger = logging.getLogger(__name__)

SUPERVISOR_SYSTEM_PROMPT = """You are the OPUS supervisor.

Your job is to assemble the final approval packet from completed agent output,
highlight the current workflow status, and produce a concise executive summary
of the final packet.
"""


def create_supervisor_agent():
    """Create the supervisor ReAct agent."""
    return create_react_agent(get_tool_llm(), SUPERVISOR_TOOLS, prompt=SUPERVISOR_SYSTEM_PROMPT)


def _best_effort_summary(vendor_id: str, packet: dict) -> str:
    try:
        agent = create_supervisor_agent()
        response = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            f"Summarize the final approval packet for vendor {vendor_id}. "
                            f"Current vendor status: {packet.get('vendor', {}).get('status', 'unknown')}."
                        )
                    )
                ]
            }
        )
        messages = response.get("messages", [])
        if messages:
            return (getattr(messages[-1], "content", None) or str(messages[-1])).strip()
    except Exception as exc:
        logger.warning("Supervisor summary generation failed for %s: %s", vendor_id, exc)
    return ""


def run_supervisor(vendor_id: str) -> dict:
    """Compile the final approval packet for a vendor review."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        return {"status": "error", "vendor_id": vendor_id, "error": f"Vendor {vendor_id} not found"}

    save_state(
        vendor_id,
        {
            "current_phase": "supervisor_final",
            "current_agent": "supervisor",
            "progress_percentage": 98,
        },
    )

    create_audit_log(vendor_id=vendor_id, agent_name="supervisor", action="final_packet_started")

    try:
        packet_raw = compile_approval_packet.invoke({"vendor_id": vendor_id})
        packet_result = json.loads(packet_raw)
        packet = packet_result.get("approval_packet", {})

        approval = get_approval_request(vendor_id) or {}
        response = {
            "status": "success",
            "vendor_id": vendor_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "approval_status": approval.get("status"),
            "final_packet": packet,
        }

        summary = _best_effort_summary(vendor_id, packet)
        if summary:
            response["agent_response"] = summary

        save_state(
            vendor_id,
            {
                "current_phase": "done",
                "current_agent": "supervisor",
                "progress_percentage": 100,
            },
        )

        create_audit_log(
            vendor_id=vendor_id,
            agent_name="supervisor",
            action="final_packet_completed",
            output_data={
                "approval_status": approval.get("status"),
                "vendor_status": packet.get("vendor", {}).get("status"),
            },
        )
        return response
    except Exception as exc:
        logger.exception("Supervisor failed for vendor %s", vendor_id)
        save_state(
            vendor_id,
            {
                "current_phase": "error",
                "current_agent": "supervisor",
                "errors": [str(exc)],
            },
        )
        create_audit_log(
            vendor_id=vendor_id,
            agent_name="supervisor",
            action="final_packet_failed",
            status="error",
            error_message=str(exc),
        )
        return {"status": "error", "vendor_id": vendor_id, "error": str(exc)}
