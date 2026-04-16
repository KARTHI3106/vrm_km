"""
Risk Assessment Agent.

The ReAct agent definition is preserved, but the execution path is backed by
deterministic scoring/persistence so Phase 3 works even without a live LLM.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from app.core.db import (
    create_audit_log,
    create_risk_assessment,
    get_vendor,
    update_risk_assessment,
)
from app.core.llm import get_tool_llm
from app.tools.risk_tools import RISK_TOOLS, build_risk_assessment_result

logger = logging.getLogger(__name__)

RISK_SYSTEM_PROMPT = """You are the Risk Assessment Agent for OPUS.

Use the available tools to aggregate completed domain reviews, calculate the
overall risk score, identify blockers or conditional requirements, and produce
an executive-ready recommendation.
"""


def create_risk_assessment_agent():
    """Create the ReAct risk assessment agent."""
    return create_react_agent(get_tool_llm(), RISK_TOOLS, prompt=RISK_SYSTEM_PROMPT)


def _best_effort_trace(vendor_id: str, result: dict) -> str:
    try:
        agent = create_risk_assessment_agent()
        response = agent.invoke(
            {
                "messages": [
                    HumanMessage(
                        content=(
                            f"Summarize the completed risk assessment for vendor {vendor_id}. "
                            f"Overall score: {result['overall_risk_score']}/100. "
                            f"Risk level: {result['risk_level']}. "
                            f"Blockers: {len(result['critical_blockers'])}. "
                            f"Conditional items: {len(result['conditional_items'])}."
                        )
                    )
                ]
            }
        )
        messages = response.get("messages", [])
        if messages:
            last_message = messages[-1]
            content = getattr(last_message, "content", None) or str(last_message)
            return content.strip()
    except Exception as exc:
        logger.warning("Risk assessment trace generation failed for %s: %s", vendor_id, exc)
    return ""


def run_risk_assessment_agent(vendor_id: str) -> dict:
    """Run the risk assessment workflow and persist the result."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        return {"status": "error", "vendor_id": vendor_id, "error": f"Vendor {vendor_id} not found"}

    started_at = datetime.now(timezone.utc).isoformat()
    assessment = create_risk_assessment(
        {
            "vendor_id": vendor_id,
            "status": "in_progress",
            "started_at": started_at,
        }
    )
    assessment_id = assessment.get("id")

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="risk_assessment",
        action="assessment_started",
        output_data={"assessment_id": assessment_id},
    )

    try:
        result = build_risk_assessment_result(vendor_id)
        result["status"] = "completed"
        result["completed_at"] = datetime.now(timezone.utc).isoformat()
        trace = _best_effort_trace(vendor_id, result)
        if trace:
            result["agent_response"] = trace

        if assessment_id:
            update_risk_assessment(
                assessment_id,
                {
                    **result,
                    "status": "completed",
                    "completed_at": result["completed_at"],
                },
            )

        create_audit_log(
            vendor_id=vendor_id,
            agent_name="risk_assessment",
            action="assessment_completed",
            output_data={
                "assessment_id": assessment_id,
                "overall_risk_score": result["overall_risk_score"],
                "risk_level": result["risk_level"],
                "approval_tier": result["approval_tier"],
            },
        )

        return {
            "status": "success",
            "vendor_id": vendor_id,
            "assessment_id": assessment_id,
            **result,
        }
    except Exception as exc:
        logger.exception("Risk Assessment Agent failed for vendor %s", vendor_id)
        if assessment_id:
            update_risk_assessment(
                assessment_id,
                {
                    "status": "error",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        create_audit_log(
            vendor_id=vendor_id,
            agent_name="risk_assessment",
            action="assessment_failed",
            status="error",
            error_message=str(exc),
        )
        return {
            "status": "error",
            "vendor_id": vendor_id,
            "assessment_id": assessment_id,
            "error": str(exc),
        }
