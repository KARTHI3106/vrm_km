"""
Business workflow helpers for the judge-demo vendor onboarding flow.

This module models the exact stage sequence shown in the product brief while
allowing the existing agent graph to keep its internal implementation details.
"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from typing import Any

WORKFLOW_STAGES: list[dict[str, Any]] = [
    {
        "key": "internal_request",
        "label": "Internal Request",
        "description": "Business stakeholder submits the vendor onboarding request.",
        "progress": 5,
    },
    {
        "key": "vendor_registration",
        "label": "Vendor Registration Form",
        "description": "Vendor record and registration context are created.",
        "progress": 10,
    },
    {
        "key": "document_collection",
        "label": "Collect GST, PAN, SOC2, ISO cert, pen test report",
        "description": "Core onboarding evidence is collected and validated.",
        "progress": 25,
    },
    {
        "key": "risk_tiering",
        "label": "Risk Tiering (Tier 1-3)",
        "description": "Initial inherent risk tier is assigned before detailed review.",
        "progress": 35,
    },
    {
        "key": "security_review",
        "label": "Security Review",
        "description": "Security controls such as RBAC, MFA, SSO, and API credentials are reviewed.",
        "progress": 50,
    },
    {
        "key": "legal_review",
        "label": "Legal Review",
        "description": "DPA and MSA readiness are checked before approval routing.",
        "progress": 65,
    },
    {
        "key": "multi_dept_approvals",
        "label": "Multi-dept Approvals",
        "description": "Legal, Finance, and IT approvals are collected.",
        "progress": 80,
    },
    {
        "key": "erp_setup",
        "label": "ERP Setup",
        "description": "Approved vendor is configured in internal systems.",
        "progress": 90,
    },
    {
        "key": "activation",
        "label": "Activation",
        "description": "Vendor is activated for operational use.",
        "progress": 95,
    },
    {
        "key": "annual_soc2_renewal",
        "label": "Annual SOC2 Renewal",
        "description": "Annual follow-up for SOC2 renewal is scheduled.",
        "progress": 100,
    },
]

WORKFLOW_STAGE_INDEX = {stage["key"]: index for index, stage in enumerate(WORKFLOW_STAGES)}
WORKFLOW_STAGE_LABELS = {stage["key"]: stage["label"] for stage in WORKFLOW_STAGES}
WORKFLOW_STAGE_PROGRESS = {stage["key"]: stage["progress"] for stage in WORKFLOW_STAGES}

DEPARTMENT_APPROVERS = [
    {"role": "legal", "department": "Legal", "name": "Legal Approval", "order": 1},
    {"role": "finance", "department": "Finance", "name": "Finance Approval", "order": 1},
    {"role": "it", "department": "IT", "name": "IT Approval", "order": 1},
]

REQUIRED_COLLECTION_DOCUMENTS = [
    {
        "type": "gst_registration",
        "label": "GST certificate",
        "criticality": "required",
        "reason": "Tax registration evidence is required for vendor onboarding.",
    },
    {
        "type": "pan_card",
        "label": "PAN card",
        "criticality": "required",
        "reason": "PAN documentation is required for vendor identity verification.",
    },
    {
        "type": "soc2_report",
        "label": "SOC2 report",
        "criticality": "required",
        "reason": "Independent security assurance is required for the review.",
    },
    {
        "type": "iso27001_certificate",
        "label": "ISO certificate",
        "criticality": "required",
        "reason": "ISO security certification is required for the review packet.",
    },
    {
        "type": "penetration_test",
        "label": "Penetration test report",
        "criticality": "required",
        "reason": "A recent penetration test report is required before approval.",
    },
]

REQUIRED_LEGAL_DOCUMENTS = [
    {
        "type": "data_processing_agreement",
        "label": "DPA",
        "criticality": "required",
        "reason": "Data Processing Agreement is required for legal review.",
    },
    {
        "type": "master_service_agreement",
        "label": "MSA",
        "criticality": "required",
        "reason": "Master Service Agreement is required for legal review.",
    },
]

DOCUMENT_TYPE_ALIASES = {
    "gst_registration": {
        "gst",
        "gst_registration",
        "gst_certificate",
        "goods_and_services_tax",
    },
    "pan_card": {"pan", "pan_card", "pan_document", "permanent_account_number"},
    "soc2_report": {"soc2", "soc2_report", "soc_2", "soc2_type_ii"},
    "iso27001_certificate": {
        "iso",
        "iso27001",
        "iso_27001",
        "iso27001_certificate",
        "iso_certificate",
    },
    "penetration_test": {
        "pen_test",
        "pen_test_report",
        "penetration_test",
        "penetration_test_report",
        "pentest",
    },
    "data_processing_agreement": {
        "dpa",
        "data_processing_agreement",
        "data_processing_addendum",
    },
    "master_service_agreement": {
        "msa",
        "master_service_agreement",
        "service_agreement",
    },
}


def _normalize_token(value: str) -> str:
    return str(value or "").strip().lower().replace(" ", "_").replace("-", "_")


def _workflow_meta(vendor: dict[str, Any]) -> dict[str, Any]:
    metadata = vendor.get("metadata") or {}
    if isinstance(metadata, str):
        return {"raw": metadata}
    if isinstance(metadata, dict):
        return metadata
    return {}


def deep_merge_dict(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = deep_merge_dict(merged[key], value)
        else:
            merged[key] = deepcopy(value)
    return merged


def build_vendor_metadata_update(vendor: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    metadata = _workflow_meta(vendor)
    return deep_merge_dict(metadata, updates)


def required_collection_documents() -> list[dict[str, Any]]:
    return deepcopy(REQUIRED_COLLECTION_DOCUMENTS)


def required_legal_documents() -> list[dict[str, Any]]:
    return deepcopy(REQUIRED_LEGAL_DOCUMENTS)


def derive_business_risk_tier(
    vendor_type: str = "",
    contract_value: float = 0.0,
    overall_score: float | None = None,
) -> dict[str, Any]:
    if overall_score is not None:
        if overall_score >= 80:
            return {"code": "tier_3", "label": "Tier 3", "rationale": "Low residual risk."}
        if overall_score >= 60:
            return {"code": "tier_2", "label": "Tier 2", "rationale": "Moderate residual risk."}
        return {"code": "tier_1", "label": "Tier 1", "rationale": "High residual risk or blockers present."}

    normalized_vendor_type = _normalize_token(vendor_type)
    score = 0
    if normalized_vendor_type in {"saas", "technology", "software", "cloud", "infrastructure", "data_processor"}:
        score += 2
    if contract_value >= 500_000:
        score += 2
    elif contract_value >= 100_000:
        score += 1

    if score >= 4:
        return {"code": "tier_1", "label": "Tier 1", "rationale": "High-value and high-exposure vendor."}
    if score >= 2:
        return {"code": "tier_2", "label": "Tier 2", "rationale": "Moderate inherent risk vendor."}
    return {"code": "tier_3", "label": "Tier 3", "rationale": "Lower inherent risk vendor."}


def approval_departments_for_tier(risk_tier: str) -> list[dict[str, Any]]:
    normalized_tier = _normalize_token(risk_tier)
    timeout_hours = 48 if normalized_tier in {"tier_3", "auto_approve", "manager"} else 72
    approvers: list[dict[str, Any]] = []
    for approver in DEPARTMENT_APPROVERS:
        approvers.append(
            {
                **approver,
                "email": f"{approver['role']}@vendorsols.local",
                "timeout_hours": timeout_hours,
            }
        )
    return approvers


def _document_haystack(document: dict[str, Any]) -> set[str]:
    parts = {
        _normalize_token(document.get("classification", "")),
        _normalize_token(document.get("file_name", "")),
        _normalize_token(document.get("file_type", "")),
    }
    metadata = document.get("extracted_metadata") or {}
    if isinstance(metadata, dict):
        for value in metadata.values():
            if isinstance(value, str):
                parts.add(_normalize_token(value))
    return {part for part in parts if part}


def document_matches_requirement(document: dict[str, Any], required_type: str) -> bool:
    required = _normalize_token(required_type)
    aliases = DOCUMENT_TYPE_ALIASES.get(required, {required})
    haystack = _document_haystack(document)
    for alias in aliases:
        if alias in haystack:
            return True
        for token in haystack:
            if alias and (alias in token or token in alias):
                return True
    return False


def find_missing_documents(
    documents: list[dict[str, Any]],
    requirements: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for requirement in requirements:
        if not any(document_matches_requirement(document, requirement["type"]) for document in documents):
            missing.append(requirement)
    return missing


def build_post_approval_operations(
    vendor: dict[str, Any],
    *,
    approved_at: datetime | None = None,
) -> dict[str, Any]:
    approved_at = approved_at or datetime.now(timezone.utc)
    renewal_due = approved_at + timedelta(days=365)
    return build_vendor_metadata_update(
        vendor,
        {
            "business_workflow": {
                "operations": {
                    "erp_setup": {
                        "status": "completed",
                        "completed_at": approved_at.isoformat(),
                    },
                    "activation": {
                        "status": "completed",
                        "completed_at": approved_at.isoformat(),
                    },
                    "annual_soc2_renewal": {
                        "status": "scheduled",
                        "scheduled_at": approved_at.isoformat(),
                        "due_date": renewal_due.date().isoformat(),
                    },
                }
            }
        },
    )


def _stage_status(*, completed: bool, in_progress: bool = False, blocked: bool = False, skipped: bool = False, scheduled: bool = False) -> str:
    if skipped:
        return "skipped"
    if blocked:
        return "blocked"
    if scheduled:
        return "scheduled"
    if completed:
        return "completed"
    if in_progress:
        return "in_progress"
    return "pending"


def _active_business_stage(active_state: dict[str, Any] | None) -> str:
    if not active_state:
        return ""
    current_phase = _normalize_token(active_state.get("current_phase", ""))
    current_agent = _normalize_token(active_state.get("current_agent", ""))

    if current_phase in {"intake", "intake_complete"} or current_agent == "document_intake":
        return "document_collection"
    if current_phase == "risk_tiering" or current_agent == "risk_tiering":
        return "risk_tiering"
    if current_phase in {"security_review"} or current_agent in {"security_review", "financial_review"}:
        return "security_review"
    if current_phase in {"compliance_review", "evidence_coordination"} or current_agent in {"compliance_review", "evidence_coordinator"}:
        return "legal_review"
    if current_phase in {"approval", "approval_complete"} or current_agent == "approval_orchestrator":
        return "multi_dept_approvals"
    if current_phase == "erp_setup":
        return "erp_setup"
    if current_phase == "activation":
        return "activation"
    if current_phase == "annual_soc2_renewal":
        return "annual_soc2_renewal"
    return ""


def derive_business_workflow_snapshot(
    *,
    vendor: dict[str, Any],
    documents: list[dict[str, Any]],
    security_review: dict[str, Any] | None = None,
    compliance_review: dict[str, Any] | None = None,
    financial_review: dict[str, Any] | None = None,
    risk_assessment: dict[str, Any] | None = None,
    approval: dict[str, Any] | None = None,
    active_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    security_review = security_review or {}
    compliance_review = compliance_review or {}
    financial_review = financial_review or {}
    risk_assessment = risk_assessment or {}
    approval = approval or {}

    metadata = _workflow_meta(vendor)
    business_meta = metadata.get("business_workflow", {}) if isinstance(metadata, dict) else {}
    initial_risk_tier = (
        business_meta.get("initial_risk_tier")
        or derive_business_risk_tier(
            vendor_type=vendor.get("vendor_type", ""),
            contract_value=float(vendor.get("contract_value", 0) or 0),
            overall_score=None,
        )
    )
    residual_risk_tier = derive_business_risk_tier(
        overall_score=float(risk_assessment.get("overall_risk_score", 0) or 0)
    ) if risk_assessment else None

    collection_requirements = required_collection_documents()
    legal_requirements = required_legal_documents()
    missing_collection = find_missing_documents(documents, collection_requirements)
    missing_legal = find_missing_documents(documents, legal_requirements)

    security_complete = bool(security_review) and (
        _normalize_token(str(security_review.get("status", ""))) in {"completed", "success"}
        or security_review.get("overall_score") is not None
    )
    legal_complete = bool(compliance_review) and not missing_legal and (
        _normalize_token(str(compliance_review.get("status", ""))) in {"completed", "success"}
        or compliance_review.get("overall_score") is not None
    )
    approval_status = _normalize_token(str(approval.get("status", "")))
    approval_terminal = approval_status in {"approved", "conditional", "rejected"}
    approved_flow = approval_status in {"approved", "conditional"} or vendor.get("status") in {"approved", "conditional_approval"}
    operations = (business_meta.get("operations", {}) if isinstance(business_meta, dict) else {}) or {}
    erp_setup = operations.get("erp_setup", {})
    activation = operations.get("activation", {})
    renewal = operations.get("annual_soc2_renewal", {})

    erp_complete = erp_setup.get("status") == "completed"
    activation_complete = activation.get("status") == "completed"
    renewal_scheduled = renewal.get("status") == "scheduled"

    active_stage = _active_business_stage(active_state)

    if vendor.get("status") == "error":
        current_stage = active_stage or "legal_review"
    elif active_stage:
        current_stage = active_stage
    elif missing_collection:
        current_stage = "document_collection"
    elif not initial_risk_tier:
        current_stage = "risk_tiering"
    elif not security_complete:
        current_stage = "security_review"
    elif not legal_complete:
        current_stage = "legal_review"
    elif not approval_terminal:
        current_stage = "multi_dept_approvals"
    elif approved_flow and not erp_complete:
        current_stage = "erp_setup"
    elif approved_flow and not activation_complete:
        current_stage = "activation"
    elif approved_flow:
        current_stage = "annual_soc2_renewal"
    else:
        current_stage = "multi_dept_approvals"

    workflow_stages: list[dict[str, Any]] = []
    for stage in WORKFLOW_STAGES:
        key = stage["key"]
        status = "pending"
        notes: list[str] = []
        if key == "internal_request":
            status = "completed"
            notes.append("Onboarding prompt captured.")
        elif key == "vendor_registration":
            status = "completed"
            notes.append("Vendor record created.")
        elif key == "document_collection":
            status = _stage_status(
                completed=not missing_collection,
                in_progress=bool(documents) or current_stage == key,
                blocked=vendor.get("status") == "error" and current_stage == key,
            )
            if missing_collection:
                notes.extend([item["label"] for item in missing_collection])
            else:
                notes.append("Core onboarding documents collected.")
        elif key == "risk_tiering":
            status = _stage_status(
                completed=bool(initial_risk_tier),
                in_progress=current_stage == key,
                blocked=vendor.get("status") == "error" and current_stage == key,
            )
            notes.append((residual_risk_tier or initial_risk_tier).get("label", "Tier Pending"))
        elif key == "security_review":
            status = _stage_status(
                completed=security_complete,
                in_progress=current_stage == key or bool(financial_review),
                blocked=vendor.get("status") == "error" and current_stage == key,
            )
            if security_complete:
                notes.append(f"Security score {security_review.get('overall_score', '-')}")
        elif key == "legal_review":
            status = _stage_status(
                completed=legal_complete,
                in_progress=current_stage == key or bool(compliance_review),
                blocked=vendor.get("status") == "error" and current_stage == key,
            )
            if missing_legal:
                notes.extend([item["label"] for item in missing_legal])
            else:
                notes.append("DPA and MSA accounted for.")
        elif key == "multi_dept_approvals":
            status = _stage_status(
                completed=approval_terminal,
                in_progress=bool(approval) or current_stage == key,
                blocked=vendor.get("status") == "error" and current_stage == key,
            )
            if approval:
                notes.append(str(approval.get("status", "pending")).replace("_", " ").title())
            else:
                notes.append("Awaiting approval packet.")
        elif key == "erp_setup":
            status = _stage_status(
                completed=erp_complete,
                in_progress=approved_flow and not erp_complete,
                skipped=approval_status == "rejected",
            )
            if erp_setup.get("completed_at"):
                notes.append(str(erp_setup.get("completed_at")))
        elif key == "activation":
            status = _stage_status(
                completed=activation_complete,
                in_progress=approved_flow and erp_complete and not activation_complete,
                skipped=approval_status == "rejected",
            )
            if activation.get("completed_at"):
                notes.append(str(activation.get("completed_at")))
        elif key == "annual_soc2_renewal":
            status = _stage_status(
                completed=False,
                scheduled=renewal_scheduled,
                in_progress=approved_flow and activation_complete and not renewal_scheduled,
                skipped=approval_status == "rejected",
            )
            if renewal.get("due_date"):
                notes.append(f"Due {renewal.get('due_date')}")

        workflow_stages.append(
            {
                "key": key,
                "label": stage["label"],
                "description": stage["description"],
                "status": status,
                "progress": stage["progress"],
                "notes": notes,
            }
        )

    current_progress = WORKFLOW_STAGE_PROGRESS.get(current_stage, 0)
    if current_stage == "annual_soc2_renewal" and renewal_scheduled:
        current_progress = 100
    elif approval_status == "rejected":
        current_progress = WORKFLOW_STAGE_PROGRESS["multi_dept_approvals"]

    return {
        "workflow_stage": current_stage,
        "workflow_stage_label": WORKFLOW_STAGE_LABELS.get(current_stage, "Workflow"),
        "workflow_progress_percentage": current_progress,
        "workflow_stages": workflow_stages,
        "risk_tier": (residual_risk_tier or initial_risk_tier).get("code"),
        "risk_tier_label": (residual_risk_tier or initial_risk_tier).get("label"),
        "risk_tier_rationale": (residual_risk_tier or initial_risk_tier).get("rationale"),
        "required_documents": collection_requirements,
        "missing_required_documents": missing_collection,
        "required_legal_documents": legal_requirements,
        "missing_legal_documents": missing_legal,
        "approval_departments": approval_departments_for_tier(
            (residual_risk_tier or initial_risk_tier).get("code", "tier_2")
        ),
        "operational_tasks": {
            "erp_setup": erp_setup,
            "activation": activation,
            "annual_soc2_renewal": renewal,
        },
    }
