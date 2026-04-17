"""
LangGraph state machine — Phase 3 complete multi-agent orchestration.

**FIXED TOPOLOGY** (v2):
    START → intake_node
        → (parallel fan-out) security_node + compliance_node + financial_node
        → (fan-in) supervisor_aggregate_node
        → evidence_node                          ← MOVED: now runs AFTER reviews
        → risk_assessment_node
        → approval_orchestrator_node
        → supervisor_final_node
        → END

Key changes from v1:
  - Evidence coordinator now runs AFTER reviews (not before)
  - intake_node directly fans out to parallel review agents
  - shared_review_context added to GraphState for cross-agent visibility
  - Removed regex-based score extraction from security_node
  - Review agents now use deterministic scoring (Hybrid Pattern)
"""

import logging
from datetime import datetime, timezone
from typing import TypedDict, Annotated, Literal

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages
from langchain_core.messages import HumanMessage, AIMessage

from app.core.business_workflow import (
    build_vendor_metadata_update,
    derive_business_risk_tier,
)
from app.core.db import (
    update_vendor,
    create_audit_log,
    get_documents_for_vendor,
    get_vendor,
)
from app.core.agent_trace import trace_agent_decision, trace_workflow_phase
from app.core.redis_state import save_state, load_state
from app.core.events import publish_event
from app.agents.document_intake import run_intake_agent
from app.agents.security_review import run_security_agent
from app.agents.compliance_review import run_compliance_agent
from app.agents.financial_review import run_financial_agent
from app.agents.evidence_coordinator import run_evidence_coordinator
from app.agents.risk_assessment import run_risk_assessment_agent
from app.agents.approval_orchestrator import run_approval_orchestrator
from app.agents.supervisor import run_supervisor

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Graph State Definition
# ═══════════════════════════════════════════════════════════════════


class GraphState(TypedDict):
    """State shared across all nodes in the LangGraph."""

    vendor_id: str
    vendor_name: str
    vendor_type: str
    contract_value: float
    vendor_domain: str
    file_paths: list[str]
    current_phase: str
    messages: Annotated[list, add_messages]
    intake_result: dict
    security_result: dict
    compliance_result: dict
    financial_result: dict
    risk_tiering_result: dict
    evidence_result: dict
    risk_assessment_result: dict
    approval_result: dict
    supervisor_result: dict
    errors: list[str]
    final_report: dict
    retry_count: int
    # NEW: shared review context persisted in Redis for cross-agent visibility
    shared_review_context: dict


# ═══════════════════════════════════════════════════════════════════
# Node Functions
# ═══════════════════════════════════════════════════════════════════

def _update_state(vendor_id: str, overrides: dict, full_state: GraphState) -> None:
    current = load_state(vendor_id) or {}
    
    if full_state:
        if "file_paths" in full_state:
            current["file_paths"] = full_state["file_paths"]
        if "intake_result" in full_state:
            current["intake_result"] = full_state["intake_result"]
        if "errors" in full_state:
            current["errors"] = full_state["errors"]
        if "retry_count" in full_state:
            current["retry_count"] = full_state["retry_count"]
            
    current.update(overrides)
    save_state(vendor_id, current)


def intake_node(state: GraphState) -> GraphState:
    """Document Intake Agent node — processes vendor documents."""
    vendor_id = state["vendor_id"]
    file_paths = state.get("file_paths", [])

    logger.info(
        f"[intake_node] Processing {len(file_paths)} files for vendor {vendor_id}"
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "intake",
            "current_agent": "document_intake",
            "progress_percentage": 10,
        },
        state
    )
    trace_workflow_phase(vendor_id, "intake", "Document intake started.", 10)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="document_intake",
        action="agent_started",
    )

    result = run_intake_agent(vendor_id, file_paths)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="document_intake",
        action="agent_completed",
        output_data={"status": result.get("status")},
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "intake_complete",
            "progress_percentage": 15,
        },
        state
    )

    publish_event(
        vendor_id,
        "intake_complete",
        {
            "status": result.get("status"),
            "files_processed": result.get("files_processed", 0),
        },
    )

    
    retry_count = state.get("retry_count", 0)
    if result.get("status") == "error":
        retry_count += 1
        
    return {
        "intake_result": result,
        "current_phase": "intake_complete",
        "retry_count": retry_count,
        "messages": [
            AIMessage(
                content=f"[Document Intake] {result.get('status', 'unknown')}: "
                f"Processed {result.get('files_processed', 0)} documents."
            )
        ],
    }


def risk_tiering_node(state: GraphState) -> GraphState:
    """Compute the business-facing Tier 1-3 classification after document intake."""
    vendor_id = state["vendor_id"]

    logger.info(f"[risk_tiering_node] Determining initial risk tier for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "risk_tiering",
            "current_agent": "risk_tiering",
            "progress_percentage": 20,
        },
        state,
    )
    trace_workflow_phase(vendor_id, "risk_tiering", "Initial risk tiering started.", 20)

    try:
        vendor = get_vendor(vendor_id) or {}
    except Exception:
        vendor = {}
    vendor = {
        "vendor_type": state.get("vendor_type", ""),
        "contract_value": state.get("contract_value", 0.0),
        "metadata": {},
        **vendor,
    }
    try:
        documents = get_documents_for_vendor(vendor_id)
    except Exception:
        documents = []
    tier = derive_business_risk_tier(
        vendor_type=vendor.get("vendor_type", ""),
        contract_value=float(vendor.get("contract_value", 0) or 0),
        overall_score=None,
    )
    metadata = build_vendor_metadata_update(
        vendor,
        {
            "business_workflow": {
                "initial_risk_tier": {
                    **tier,
                    "document_count": len(documents),
                    "computed_at": datetime.now(timezone.utc).isoformat(),
                }
            }
        },
    )
    try:
        update_vendor(vendor_id, {"metadata": metadata})
    except Exception:
        logger.warning("Failed to persist initial risk tier metadata for vendor %s", vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="risk_tiering",
        action="initial_tier_assigned",
        output_data={
            "risk_tier": tier.get("label"),
            "document_count": len(documents),
            "rationale": tier.get("rationale"),
        },
    )
    trace_agent_decision(
        vendor_id,
        "risk_tiering",
        "Initial business risk tier determined from vendor profile and contract value.",
        {
            "risk_tier": tier.get("label"),
            "rationale": tier.get("rationale"),
            "document_count": len(documents),
        },
    )

    return {
        "risk_tiering_result": {"status": "success", **tier},
        "messages": [
            AIMessage(
                content=f"[Risk Tiering] {tier.get('label', 'Tier Pending')}: {tier.get('rationale', '')}"
            )
        ],
    }


def security_node(state: GraphState) -> GraphState:
    """Security Review Agent node — assesses vendor security posture.

    Uses the Hybrid Pattern: the agent gathers data via tools and produces
    narrative output.  Deterministic scoring is handled inside
    ``run_security_agent`` — no regex extraction here.
    """
    vendor_id = state["vendor_id"]

    logger.info(f"[security_node] Starting security review for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "security_review",
            "current_agent": "security_review",
            "progress_percentage": 25,
        },
        state
    )
    trace_workflow_phase(vendor_id, "security_review", "Security review started.", 25)

    create_audit_log(
        vendor_id=vendor_id, agent_name="security_review", action="agent_started"
    )

    result = run_security_agent(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="security_review",
        action="agent_completed",
        output_data={
            "status": result.get("status"),
            "overall_score": result.get("overall_score"),
            "grade": result.get("grade"),
        },
    )

    return {
        "security_result": result,
        "messages": [
            AIMessage(
                content=f"[Security Review] {result.get('status', 'unknown')}: "
                f"Score={result.get('overall_score', 'N/A')}, "
                f"Grade={result.get('grade', 'N/A')}."
            )
        ],
    }


def compliance_node(state: GraphState) -> GraphState:
    """Compliance Review Agent node — regulatory compliance assessment."""
    vendor_id = state["vendor_id"]

    logger.info(f"[compliance_node] Starting compliance review for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "compliance_review",
            "current_agent": "compliance_review",
        },
        state
    )
    trace_workflow_phase(vendor_id, "compliance_review", "Compliance review started.", 30)

    create_audit_log(
        vendor_id=vendor_id, agent_name="compliance_review", action="agent_started"
    )

    result = run_compliance_agent(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="compliance_review",
        action="agent_completed",
        output_data={
            "status": result.get("status"),
            "overall_score": result.get("overall_score"),
            "grade": result.get("grade"),
        },
    )

    publish_event(vendor_id, "compliance_complete", {"status": result.get("status")})

    return {
        "compliance_result": result,
        "messages": [
            AIMessage(
                content=f"[Compliance Review] {result.get('status', 'unknown')}: "
                f"Score={result.get('overall_score', 'N/A')}, "
                f"Grade={result.get('grade', 'N/A')}."
            )
        ],
    }


def financial_node(state: GraphState) -> GraphState:
    """Financial Review Agent node — financial risk assessment."""
    vendor_id = state["vendor_id"]

    logger.info(f"[financial_node] Starting financial review for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "financial_review",
            "current_agent": "financial_review",
        },
        state
    )
    trace_workflow_phase(vendor_id, "financial_review", "Financial review started.", 35)

    create_audit_log(
        vendor_id=vendor_id, agent_name="financial_review", action="agent_started"
    )

    result = run_financial_agent(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="financial_review",
        action="agent_completed",
        output_data={
            "status": result.get("status"),
            "overall_score": result.get("overall_score"),
            "grade": result.get("grade"),
        },
    )

    publish_event(vendor_id, "financial_complete", {"status": result.get("status")})

    return {
        "financial_result": result,
        "messages": [
            AIMessage(
                content=f"[Financial Review] {result.get('status', 'unknown')}: "
                f"Score={result.get('overall_score', 'N/A')}, "
                f"Grade={result.get('grade', 'N/A')}."
            )
        ],
    }


def supervisor_aggregate_node(state: GraphState) -> GraphState:
    """Supervisor aggregation node — gathers results from parallel reviews.

    Collects deterministic scores from all three review agents and
    persists a consolidated shared_review_context snapshot.
    """
    vendor_id = state["vendor_id"]

    logger.info(
        f"[supervisor_aggregate] Aggregating parallel review results for vendor {vendor_id}"
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "aggregating",
            "current_agent": "supervisor",
            "progress_percentage": 45,
        },
        state
    )
    trace_workflow_phase(vendor_id, "aggregating", "Aggregating parallel review results.", 45)

    create_audit_log(
        vendor_id=vendor_id, agent_name="supervisor", action="aggregate_results"
    )

    sec = state.get("security_result", {})
    comp = state.get("compliance_result", {})
    fin = state.get("financial_result", {})

    # Build the consolidated shared review context
    shared_review_context = {
        "security": {
            "score": sec.get("overall_score"),
            "grade": sec.get("grade"),
            "critical_flags": sec.get("critical_flags", []),
            "data_warnings": sec.get("data_warnings", []),
        },
        "compliance": {
            "score": comp.get("overall_score"),
            "grade": comp.get("grade"),
            "critical_flags": comp.get("critical_flags", []),
            "data_warnings": comp.get("data_warnings", []),
        },
        "financial": {
            "score": fin.get("overall_score"),
            "grade": fin.get("grade"),
            "critical_flags": fin.get("critical_flags", []),
            "data_warnings": fin.get("data_warnings", []),
        },
        "aggregated_at": datetime.now(timezone.utc).isoformat(),
    }

    # Persist shared context to Redis for downstream nodes
    try:
        save_state(f"shared_context:{vendor_id}", shared_review_context)
    except Exception as e:
        logger.warning("Failed to save shared review context: %s", e)

    summary = (
        f"Parallel reviews complete.\n"
        f"Security: {sec.get('status', 'unknown')} (score: {sec.get('overall_score', 'N/A')}, grade: {sec.get('grade', 'N/A')})\n"
        f"Compliance: {comp.get('status', 'unknown')} (score: {comp.get('overall_score', 'N/A')}, grade: {comp.get('grade', 'N/A')})\n"
        f"Financial: {fin.get('status', 'unknown')} (score: {fin.get('overall_score', 'N/A')}, grade: {fin.get('grade', 'N/A')})"
    )

    publish_event(vendor_id, "reviews_aggregated", {"progress_percentage": 45})
    trace_agent_decision(
        vendor_id,
        "supervisor",
        "Parallel review results aggregated into shared context.",
        shared_review_context,
    )

    return {
        "current_phase": "aggregated",
        "shared_review_context": shared_review_context,
        "messages": [AIMessage(content=f"[Supervisor] {summary}")],
    }


def evidence_node(state: GraphState) -> GraphState:
    """Evidence Coordinator Agent node — post-review gap analysis and collection.

    Runs AFTER supervisor_aggregate_node so it has access to all three
    review results, enabling a single consolidated evidence request email
    instead of multiple piecemeal requests.
    """
    vendor_id = state["vendor_id"]

    logger.info(
        f"[evidence_node] Starting evidence coordination for vendor {vendor_id}"
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "evidence_coordination",
            "current_agent": "evidence_coordinator",
            "progress_percentage": 55,
        },
        state
    )
    trace_workflow_phase(vendor_id, "evidence_coordination", "Evidence coordination started.", 55)

    create_audit_log(
        vendor_id=vendor_id, agent_name="evidence_coordinator", action="agent_started"
    )

    result = run_evidence_coordinator(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="evidence_coordinator",
        action="agent_completed",
        output_data={"status": result.get("status")},
    )

    publish_event(vendor_id, "evidence_complete", {"status": result.get("status")})

    return {
        "evidence_result": result,
        "current_phase": "evidence_complete",
        "messages": [
            AIMessage(
                content=f"[Evidence Coordinator] {result.get('status', 'unknown')}: Coordination complete."
            )
        ],
    }


def risk_assessment_node(state: GraphState) -> GraphState:
    """Risk Assessment Agent node — aggregates and scores all findings."""
    vendor_id = state["vendor_id"]

    logger.info(
        f"[risk_assessment_node] Starting risk assessment for vendor {vendor_id}"
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "risk_assessment",
            "current_agent": "risk_assessment",
            "progress_percentage": 70,
        },
        state
    )
    trace_workflow_phase(vendor_id, "risk_assessment", "Risk assessment started.", 70)

    create_audit_log(
        vendor_id=vendor_id, agent_name="risk_assessment", action="agent_started"
    )

    result = run_risk_assessment_agent(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="risk_assessment",
        action="agent_completed",
        output_data={"status": result.get("status")},
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "risk_assessment_complete",
            "progress_percentage": 75,
        },
        state
    )

    publish_event(
        vendor_id,
        "risk_assessment_complete",
        {
            "status": result.get("status"),
            "overall_risk_score": result.get("overall_risk_score"),
            "risk_level": result.get("risk_level"),
        },
    )

    return {
        "risk_assessment_result": result,
        "current_phase": "risk_assessment_complete",
        "messages": [
            AIMessage(
                content=f"[Risk Assessment] {result.get('status', 'unknown')}: Assessment complete."
            )
        ],
    }


def approval_orchestrator_node(state: GraphState) -> GraphState:
    """Approval Orchestrator Agent node — manages the approval workflow."""
    vendor_id = state["vendor_id"]

    logger.info(
        f"[approval_orchestrator_node] Starting approval workflow for vendor {vendor_id}"
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "approval",
            "current_agent": "approval_orchestrator",
            "progress_percentage": 85,
        },
        state
    )
    trace_workflow_phase(vendor_id, "approval", "Approval orchestration started.", 85)

    create_audit_log(
        vendor_id=vendor_id, agent_name="approval_orchestrator", action="agent_started"
    )

    result = run_approval_orchestrator(vendor_id)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="agent_completed",
        output_data={"status": result.get("status")},
    )

    _update_state(
        vendor_id,
        {
            "current_phase": "approval_complete",
            "progress_percentage": 92,
        },
        state
    )

    publish_event(
        vendor_id,
        "approval_orchestrated",
        {
            "status": result.get("status"),
            "approval_tier": result.get("approval_tier"),
            "current_status": result.get("current_status"),
        },
    )

    return {
        "approval_result": result,
        "current_phase": "approval_complete",
        "messages": [
            AIMessage(
                content=f"[Approval Orchestrator] {result.get('status', 'unknown')}: Workflow complete."
            )
        ],
    }


def erp_setup_node(state: GraphState) -> GraphState:
    """Record ERP setup as a post-approval operational step."""
    vendor_id = state["vendor_id"]

    logger.info(f"[erp_setup_node] Completing ERP setup for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "erp_setup",
            "current_agent": "operations",
            "progress_percentage": 94,
        },
        state,
    )
    trace_workflow_phase(vendor_id, "erp_setup", "ERP setup completed.", 94)
    create_audit_log(
        vendor_id=vendor_id,
        agent_name="operations",
        action="erp_setup_completed",
        output_data={"status": "completed"},
    )
    return {
        "messages": [AIMessage(content="[Operations] ERP setup completed.")],
    }


def activation_node(state: GraphState) -> GraphState:
    """Record vendor activation as a post-approval operational step."""
    vendor_id = state["vendor_id"]

    logger.info(f"[activation_node] Activating vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "activation",
            "current_agent": "operations",
            "progress_percentage": 97,
        },
        state,
    )
    trace_workflow_phase(vendor_id, "activation", "Vendor activation completed.", 97)
    create_audit_log(
        vendor_id=vendor_id,
        agent_name="operations",
        action="activation_completed",
        output_data={"status": "completed"},
    )
    return {
        "messages": [AIMessage(content="[Operations] Vendor activation completed.")],
    }


def annual_soc2_renewal_node(state: GraphState) -> GraphState:
    """Record annual SOC2 renewal scheduling after activation."""
    vendor_id = state["vendor_id"]

    logger.info(f"[annual_soc2_renewal_node] Scheduling SOC2 renewal for vendor {vendor_id}")

    _update_state(
        vendor_id,
        {
            "current_phase": "annual_soc2_renewal",
            "current_agent": "operations",
            "progress_percentage": 99,
        },
        state,
    )
    trace_workflow_phase(vendor_id, "annual_soc2_renewal", "Annual SOC2 renewal scheduled.", 99)
    create_audit_log(
        vendor_id=vendor_id,
        agent_name="operations",
        action="annual_soc2_renewal_scheduled",
        output_data={"status": "scheduled"},
    )
    return {
        "messages": [AIMessage(content="[Operations] Annual SOC2 renewal scheduled.")],
    }


def supervisor_final_node(state: GraphState) -> GraphState:
    """Supervisor final node — compiles all results and closes the workflow."""
    vendor_id = state["vendor_id"]

    logger.info(f"[supervisor_final] Compiling final results for vendor {vendor_id}")

    # Check for upstream errors first
    upstream_error = False
    if state.get("errors"):
        upstream_error = True
    elif state.get("intake_result", {}).get("status") == "error":
        upstream_error = True
    elif state.get("security_result", {}).get("status") == "error":
        upstream_error = True
    elif state.get("compliance_result", {}).get("status") == "error":
        upstream_error = True
    elif state.get("financial_result", {}).get("status") == "error":
        upstream_error = True

    _update_state(
        vendor_id,
        {
            "current_phase": "error" if upstream_error else "compiling",
            "current_agent": "supervisor",
            "progress_percentage": 95,
        },
        state
    )

    create_audit_log(
        vendor_id=vendor_id, agent_name="supervisor", action="compile_final"
    )
    trace_workflow_phase(
        vendor_id,
        "supervisor_final",
        "Compiling final supervisor packet and validating downstream artifacts.",
        95,
    )

    result = run_supervisor(vendor_id, has_error=upstream_error)

    downstream_artifacts_ready = bool(state.get("risk_assessment_result")) and bool(result.get("final_packet"))
    has_error = upstream_error or result.get("status") == "error" or not downstream_artifacts_ready
    final_phase = "error" if has_error else "done"
    approval_status = (state.get("approval_result") or {}).get("current_status")
    final_vendor_status = "error"
    if not has_error:
        if approval_status == "approved":
            final_vendor_status = "approved"
        elif approval_status == "rejected":
            final_vendor_status = "rejected"
        elif approval_status == "conditional":
            final_vendor_status = "conditional_approval"
        elif approval_status == "pending":
            final_vendor_status = "pending_approval"
        else:
            final_vendor_status = "review_completed"

    _update_state(
        vendor_id,
        {
            "current_phase": final_phase,
            "progress_percentage": 100 if not has_error else 90,
        },
        state
    )

    if has_error:
        update_vendor(vendor_id, {"status": "error"})
    else:
        update_vendor(vendor_id, {"status": final_vendor_status})

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="supervisor",
        action="agent_completed",
        output_data={"status": "error" if has_error else result.get("status")},
    )

    publish_event(
        vendor_id,
        "workflow_complete",
        {
            "status": "error" if has_error else result.get("status"),
            "approval_status": result.get("approval_status"),
        },
    )
    trace_agent_decision(
        vendor_id,
        "supervisor",
        "Final workflow status resolved.",
        {
            "has_error": has_error,
            "downstream_artifacts_ready": downstream_artifacts_ready,
            "vendor_status": final_vendor_status if not has_error else "error",
        },
    )

    return {
        "supervisor_result": result,
        "current_phase": final_phase,
        "final_report": result,
        "messages": [
            AIMessage(
                content=f"[Supervisor] Review complete. Status: {'error' if has_error else result.get('status', 'unknown')}"
            )
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# Routing Logic
# ═══════════════════════════════════════════════════════════════════


def route_after_intake(state: GraphState) -> list[str]:
    """After intake, determine initial risk tier before detailed reviews."""
    intake_result = state.get("intake_result", {})
    if intake_result.get("status") == "error":
        retry_count = state.get("retry_count", 0)
        from app.config import get_settings
        settings = get_settings()
        max_retries = settings.max_workflow_retries

        if retry_count < max_retries:
            logger.warning(f"Intake failed, attempting transient retry. Retry count: {retry_count + 1}/{max_retries}")
            return ["intake_node"]
        else:
            logger.warning("Intake failed and exhausted retries — routing to supervisor for error handling")
            return ["supervisor_final_node"]

    # ──────────────────────────────────────────────────────────────
    # FIX: Fan out directly to parallel review agents (NOT evidence)
    # ──────────────────────────────────────────────────────────────
    return ["risk_tiering_node"]


def route_after_approval(state: GraphState) -> Literal["erp_setup_node", "supervisor_final_node"]:
    approval_status = str((state.get("approval_result") or {}).get("current_status", "")).lower()
    if approval_status in {"approved", "conditional"}:
        return "erp_setup_node"
    return "supervisor_final_node"


# ═══════════════════════════════════════════════════════════════════
# Build the Graph
# ═══════════════════════════════════════════════════════════════════


def build_workflow_graph() -> StateGraph:
    """
    Build the complete LangGraph state machine for the vendor review workflow.

    **FIXED TOPOLOGY** (v2):
        START → intake_node
            → (parallel fan-out) security_node, compliance_node, financial_node
            → (fan-in) supervisor_aggregate_node
            → evidence_node                    ← runs AFTER reviews have completed
            → risk_assessment_node
            → approval_orchestrator_node
            → supervisor_final_node
            → END
    """
    workflow = StateGraph(GraphState)

    # Add all nodes
    workflow.add_node("intake_node", intake_node)
    workflow.add_node("risk_tiering_node", risk_tiering_node)
    workflow.add_node("security_node", security_node)
    workflow.add_node("compliance_node", compliance_node)
    workflow.add_node("financial_node", financial_node)
    workflow.add_node("supervisor_aggregate_node", supervisor_aggregate_node)
    workflow.add_node("evidence_node", evidence_node)
    workflow.add_node("risk_assessment_node", risk_assessment_node)
    workflow.add_node("approval_orchestrator_node", approval_orchestrator_node)
    workflow.add_node("erp_setup_node", erp_setup_node)
    workflow.add_node("activation_node", activation_node)
    workflow.add_node("annual_soc2_renewal_node", annual_soc2_renewal_node)
    workflow.add_node("supervisor_final_node", supervisor_final_node)

    # Entry point
    workflow.set_entry_point("intake_node")

    # ──────────────────────────────────────────────────────────────
    # FIXED: After intake → fan out DIRECTLY to parallel reviews
    # (was: intake → evidence → reviews  — WRONG)
    # ──────────────────────────────────────────────────────────────
    workflow.add_conditional_edges(
        "intake_node",
        route_after_intake,
        ["risk_tiering_node", "supervisor_final_node", "intake_node"],
    )

    workflow.add_edge("risk_tiering_node", "security_node")
    workflow.add_edge("risk_tiering_node", "compliance_node")
    workflow.add_edge("risk_tiering_node", "financial_node")

    # All three review nodes fan-in to the supervisor aggregate
    workflow.add_edge("security_node", "supervisor_aggregate_node")
    workflow.add_edge("compliance_node", "supervisor_aggregate_node")
    workflow.add_edge("financial_node", "supervisor_aggregate_node")

    # ──────────────────────────────────────────────────────────────
    # FIXED: Evidence coordinator runs AFTER aggregation
    # (was: evidence → reviews — WRONG)
    # ──────────────────────────────────────────────────────────────
    workflow.add_edge("supervisor_aggregate_node", "evidence_node")

    # After evidence → risk → approval → final → END
    workflow.add_edge("evidence_node", "risk_assessment_node")
    workflow.add_edge("risk_assessment_node", "approval_orchestrator_node")
    workflow.add_conditional_edges(
        "approval_orchestrator_node",
        route_after_approval,
        ["erp_setup_node", "supervisor_final_node"],
    )
    workflow.add_edge("erp_setup_node", "activation_node")
    workflow.add_edge("activation_node", "annual_soc2_renewal_node")
    workflow.add_edge("annual_soc2_renewal_node", "supervisor_final_node")
    workflow.add_edge("supervisor_final_node", END)

    return workflow


def get_compiled_graph():
    """Get the compiled workflow graph, ready for execution."""
    workflow = build_workflow_graph()
    return workflow.compile()


def run_full_workflow(
    vendor_id: str,
    vendor_name: str,
    vendor_type: str,
    contract_value: float,
    vendor_domain: str,
    file_paths: list[str],
) -> dict:
    """
    Execute the complete vendor review workflow.

    This is the main entry point for the entire multi-agent system.
    Phase 3: Includes all 8 agents — parallel Security/Compliance/Financial,
    Evidence Coordinator, Risk Assessment, and Approval Orchestrator.
    """
    logger.info(f"Starting full workflow for vendor {vendor_name} ({vendor_id})")

    graph = get_compiled_graph()

    initial_state: GraphState = {
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "vendor_type": vendor_type,
        "contract_value": contract_value,
        "vendor_domain": vendor_domain,
        "file_paths": file_paths,
        "current_phase": "init",
        "messages": [
            HumanMessage(content=f"Begin vendor onboarding review for {vendor_name}")
        ],
        "intake_result": {},
        "security_result": {},
        "compliance_result": {},
        "financial_result": {},
        "risk_tiering_result": {},
        "evidence_result": {},
        "risk_assessment_result": {},
        "approval_result": {},
        "supervisor_result": {},
        "errors": [],
        "final_report": {},
        "retry_count": 0,
        "shared_review_context": {},
    }

    try:
        final_state = graph.invoke(initial_state)

        return {
            "status": "success",
            "vendor_id": vendor_id,
            "current_phase": final_state.get("current_phase", "unknown"),
            "intake_result": final_state.get("intake_result", {}),
            "security_result": final_state.get("security_result", {}),
            "compliance_result": final_state.get("compliance_result", {}),
            "financial_result": final_state.get("financial_result", {}),
            "risk_tiering_result": final_state.get("risk_tiering_result", {}),
            "evidence_result": final_state.get("evidence_result", {}),
            "risk_assessment_result": final_state.get("risk_assessment_result", {}),
            "approval_result": final_state.get("approval_result", {}),
            "supervisor_result": final_state.get("supervisor_result", {}),
            "final_report": final_state.get("final_report", {}),
        }

    except Exception as e:
        logger.error(f"Workflow failed for vendor {vendor_id}: {e}")
        save_state(
            vendor_id,
            {
                "current_phase": "error",
                "errors": [str(e)],
            },
        )
        return {
            "status": "error",
            "vendor_id": vendor_id,
            "error": str(e),
        }
