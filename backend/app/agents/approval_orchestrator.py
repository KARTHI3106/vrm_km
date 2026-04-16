"""
Approval Orchestrator Agent.

Sets up the approval workflow deterministically and finalizes immediately only
for auto-approval flows. Human approvers can continue the workflow via API.
"""
from __future__ import annotations

import logging

from langgraph.prebuilt import create_react_agent

from app.config import get_settings
from app.core.db import (
    create_audit_log, 
    get_approval_request, 
    get_risk_assessment, 
    get_vendor, 
    get_approval_decisions
)
from app.core.llm import get_tool_llm
from app.tools.approval_tools import (
    APPROVAL_TOOLS,
    orchestrate_approval_setup,
    record_approval_decision_data,
    sync_approval_completion,
)

logger = logging.getLogger(__name__)

APPROVAL_SYSTEM_PROMPT = """You are the Approval Orchestrator Agent for Vendorsols.

Use the approval workflow tools to route the vendor to the correct approvers,
track the approval state, and finalize the vendor record once the workflow is
complete.
"""


def create_approval_orchestrator_agent():
    """Create the ReAct approval orchestrator agent (used by approval tools)."""
    return create_react_agent(get_tool_llm(), APPROVAL_TOOLS, prompt=APPROVAL_SYSTEM_PROMPT)


def _best_effort_trace(vendor_id: str, status: dict) -> str:
    """Generate a lightweight approval trace summary without an LLM call."""
    tier = status.get('approval_tier', 'unknown')
    current = status.get('current_status', status.get('status', 'pending'))
    approval_id = status.get('approval_id', 'N/A')
    return (
        f"Approval orchestration complete for vendor {vendor_id}. "
        f"Tier: {tier}. Status: {current}. Approval ID: {approval_id}."
    )


def _simulate_if_enabled(vendor_id: str, risk_score: float) -> None:
    settings = get_settings()
    if not settings.auto_simulate_approvals:
        return

    approval = get_approval_request(vendor_id)
    if not approval:
        return

    approvers = approval.get("required_approvers", [])
    if not approvers:
        sync_approval_completion(vendor_id)
        return
        
    # Idempotency check: don't auto-simulate if decisions already exist
    existing_decisions = get_approval_decisions(approval["id"])
    if existing_decisions:
        logger.info(f"Skipping auto-simulation for {vendor_id}: decisions already exist.")
        return

    # Use thresholds from settings or defaults
    high_threshold = getattr(settings, 'risk_threshold_high', 80)
    med_threshold = getattr(settings, 'risk_threshold_medium', 60)
    low_threshold = getattr(settings, 'risk_threshold_low', 40)

    if risk_score >= high_threshold:
        decision = "approve"
        conditions: list[str] = []
    elif risk_score >= med_threshold:
        decision = "request_changes"
        conditions = ["Quarterly review required for the first year."]
    elif risk_score >= low_threshold:
        decision = "request_changes"
        conditions = ["Remediation plan due within 30 days."]
    else:
        decision = "reject"
        conditions = ["Re-evaluate after material remediation."]

    for approver in approvers:
        record_approval_decision_data(
            vendor_id=vendor_id,
            approval_id=approval["id"],
            approver_name=approver.get("name") or approver.get("role", "Approver"),
            approver_role=approver.get("role", "approver"),
            decision=decision,
            comments="Auto-simulated approval for development workflow.",
            conditions=conditions,
        )

    sync_approval_completion(vendor_id)


def run_approval_orchestrator(vendor_id: str) -> dict:
    """Create approval workflow state and notify approvers."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        return {"status": "error", "vendor_id": vendor_id, "error": f"Vendor {vendor_id} not found"}

    risk = get_risk_assessment(vendor_id) or {}
    if not risk:
        return {
            "status": "error",
            "vendor_id": vendor_id,
            "error": "Risk assessment must complete before approval orchestration.",
        }

    create_audit_log(vendor_id=vendor_id, agent_name="approval_orchestrator", action="orchestration_started")

    try:
        status = orchestrate_approval_setup(vendor_id)
        _simulate_if_enabled(vendor_id, float(risk.get("overall_risk_score", 0) or 0))

        approval = get_approval_request(vendor_id) or {}
        result = {
            "status": "success",
            "vendor_id": vendor_id,
            "approval_id": approval.get("id"),
            "approval_tier": risk.get("approval_tier"),
            "current_status": approval.get("status", "pending"),
            "workflow": status.get("workflow", {}),
        }

        trace = _best_effort_trace(vendor_id, result)
        if trace:
            result["agent_response"] = trace

        create_audit_log(
            vendor_id=vendor_id,
            agent_name="approval_orchestrator",
            action="orchestration_completed",
            output_data={
                "approval_id": approval.get("id"),
                "approval_tier": risk.get("approval_tier"),
                "status": approval.get("status", "pending"),
            },
        )
        return result
    except Exception as exc:
        logger.exception("Approval Orchestrator failed for vendor %s", vendor_id)
        create_audit_log(
            vendor_id=vendor_id,
            agent_name="approval_orchestrator",
            action="orchestration_failed",
            status="error",
            error_message=str(exc),
        )
        return {"status": "error", "vendor_id": vendor_id, "error": str(exc)}
