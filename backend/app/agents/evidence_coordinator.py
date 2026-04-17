"""
Evidence Coordinator Agent - deterministic post-review evidence orchestration.

This phase intentionally persists evidence requests and tracking records even
when email delivery is mocked or unavailable.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from app.core.agent_trace import (
    trace_agent_complete,
    trace_agent_decision,
    trace_agent_error,
    trace_agent_start,
    trace_agent_thinking,
    trace_tool_call,
)
from app.core.db import (
    create_evidence_request,
    create_evidence_tracking_entry,
    get_compliance_review,
    get_documents_for_vendor,
    get_evidence_requests,
    get_financial_review,
    get_security_review,
    get_vendor,
    update_evidence_request,
)
from app.core.events import publish_event
from app.tools.evidence_tools import (
    compare_required_vs_submitted,
    create_followup_task,
    generate_evidence_request_email,
    get_required_documents,
    send_email,
    track_document_status,
)

logger = logging.getLogger(__name__)


def _parse_json(value: str | dict[str, Any]) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    except Exception:
        return {}


def _normalize_document_type(document_type: str) -> str:
    return str(document_type or "").strip().lower().replace(" ", "_")


def _deadline_days(criticality: str) -> int:
    return 7 if str(criticality).lower() == "required" else 14


def _required_gap_candidates(vendor_id: str, vendor: dict[str, Any]) -> list[dict[str, Any]]:
    required_raw = get_required_documents.invoke(
        {
            "vendor_type": vendor.get("vendor_type", "technology"),
            "contract_value": float(vendor.get("contract_value", 0) or 0),
        }
    )
    required_payload = _parse_json(required_raw)
    compare_raw = compare_required_vs_submitted.invoke(
        {
            "vendor_id": vendor_id,
            "required_docs_json": json.dumps(required_payload),
        }
    )
    compare_payload = _parse_json(compare_raw)
    candidates = []
    for item in compare_payload.get("missing_documents", []):
        candidates.append(
            {
                "document_type": _normalize_document_type(item.get("type")),
                "criticality": item.get("criticality", "required"),
                "reason": item.get("reason", "Required evidence remains outstanding."),
                "source": "requirements",
            }
        )
    return candidates


def _review_gap_candidates(security: dict[str, Any], compliance: dict[str, Any], financial: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []

    if security:
        if float(security.get("certificate_score", 0) or 0) <= 0:
            candidates.append(
                {
                    "document_type": "soc2_report",
                    "criticality": "required",
                    "reason": "Security review could not validate independent security assurance.",
                    "source": "security_review",
                }
            )
        if float(security.get("questionnaire_score", 0) or 0) <= 50:
            candidates.append(
                {
                    "document_type": "security_questionnaire",
                    "criticality": "required",
                    "reason": "Security questionnaire evidence is missing or incomplete.",
                    "source": "security_review",
                }
            )

    for gap in compliance.get("gaps", []) or []:
        candidates.append(
            {
                "document_type": _normalize_document_type(
                    gap.get("document_type")
                    or gap.get("requirement")
                    or "compliance_supporting_document"
                ),
                "criticality": gap.get("criticality", "required"),
                "reason": gap.get("description", "Compliance remediation evidence is required."),
                "source": "compliance_review",
            }
        )

    if financial:
        if float(financial.get("insurance_score", 0) or 0) <= 0:
            candidates.append(
                {
                    "document_type": "insurance_certificate",
                    "criticality": "required",
                    "reason": "Financial review could not validate insurance coverage.",
                    "source": "financial_review",
                }
            )
        if float(financial.get("financial_stability_score", 50) or 50) <= 50:
            candidates.append(
                {
                    "document_type": "financial_statement",
                    "criticality": "required",
                    "reason": "Financial stability evidence is missing or insufficient.",
                    "source": "financial_review",
                }
            )
        if float(financial.get("bcp_score", 0) or 0) <= 0:
            candidates.append(
                {
                    "document_type": "business_continuity_plan",
                    "criticality": "recommended",
                    "reason": "Business continuity evidence is missing or incomplete.",
                    "source": "financial_review",
                }
            )

    return candidates


def _dedupe_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for candidate in candidates:
        document_type = _normalize_document_type(candidate.get("document_type"))
        if not document_type:
            continue
        current = deduped.get(document_type)
        if not current:
            deduped[document_type] = {
                "document_type": document_type,
                "criticality": candidate.get("criticality", "required"),
                "reason": candidate.get("reason", "Evidence required."),
                "source": [candidate.get("source", "workflow")],
            }
            continue
        if current["criticality"] != "required" and candidate.get("criticality") == "required":
            current["criticality"] = "required"
        current["reason"] = current["reason"] or candidate.get("reason", "")
        current["source"] = sorted(set([*current.get("source", []), candidate.get("source", "workflow")]))
    return list(deduped.values())


def _persist_evidence_requests(vendor: dict[str, Any], candidates: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    vendor_id = vendor["id"]
    existing_requests = get_evidence_requests(vendor_id)
    existing_by_type = {
        _normalize_document_type(request.get("document_type")): request
        for request in existing_requests
    }
    created: list[dict[str, Any]] = []
    skipped: list[dict[str, Any]] = []

    for candidate in candidates:
        document_type = candidate["document_type"]
        existing = existing_by_type.get(document_type)
        if existing and existing.get("status") in {"pending", "received", "reviewed"}:
            skipped.append(
                {
                    "document_type": document_type,
                    "existing_status": existing.get("status"),
                    "request_id": existing.get("id"),
                }
            )
            create_evidence_tracking_entry(
                {
                    "vendor_id": vendor_id,
                    "evidence_request_id": existing.get("id"),
                    "action": "request_deduplicated",
                    "actor": "evidence_coordinator",
                    "details": {
                        "document_type": document_type,
                        "existing_status": existing.get("status"),
                    },
                }
            )
            continue

        deadline = (datetime.now(timezone.utc) + timedelta(days=_deadline_days(candidate["criticality"]))).date().isoformat()
        created_request = create_evidence_request(
            {
                "vendor_id": vendor_id,
                "document_type": document_type,
                "criticality": candidate["criticality"],
                "reason": candidate["reason"],
                "email_recipient": vendor.get("contact_email"),
                "deadline": deadline,
                "notes": f"Generated from {', '.join(candidate.get('source', []))}.",
            }
        )
        created.append(created_request)
        create_evidence_tracking_entry(
            {
                "vendor_id": vendor_id,
                "evidence_request_id": created_request.get("id"),
                "action": "evidence_requested",
                "actor": "evidence_coordinator",
                "details": {
                    "document_type": document_type,
                    "criticality": candidate["criticality"],
                    "reason": candidate["reason"],
                    "source": candidate.get("source", []),
                },
            }
        )
    return created, skipped


def run_evidence_coordinator(vendor_id: str) -> dict:
    """Persist deduplicated evidence requests and workflow notes."""
    try:
        vendor = get_vendor(vendor_id)
        if not vendor:
            return {"status": "error", "error": f"Vendor {vendor_id} not found"}

        trace_id = trace_agent_start(
            vendor_id,
            "evidence_coordinator",
            {
                "vendor_name": vendor.get("name"),
                "vendor_type": vendor.get("vendor_type"),
                "contact_email": vendor.get("contact_email"),
            },
        )
        publish_event(
            vendor_id,
            "tool_status",
            {
                "phase": "evidence_coordination",
                "tool_name": "agent_start",
                "status": "calling",
            },
        )
        trace_agent_thinking(
            vendor_id,
            "evidence_coordinator",
            "Reconciling required documents with submitted evidence and review-derived gaps, then persisting deduplicated requests.",
            trace_id=trace_id,
        )

        documents = get_documents_for_vendor(vendor_id)
        security = get_security_review(vendor_id) or {}
        compliance = get_compliance_review(vendor_id) or {}
        financial = get_financial_review(vendor_id) or {}

        required_candidates = _required_gap_candidates(vendor_id, vendor)
        review_candidates = _review_gap_candidates(security, compliance, financial)
        candidates = _dedupe_candidates([*required_candidates, *review_candidates])
        created_requests, skipped_requests = _persist_evidence_requests(vendor, candidates)

        trace_agent_decision(
            vendor_id,
            "evidence_coordinator",
            "Evidence request set derived from workflow requirements and review gaps.",
            {
                "submitted_documents": len(documents),
                "candidate_count": len(candidates),
                "created_requests": len(created_requests),
                "skipped_requests": len(skipped_requests),
            },
            trace_id=trace_id,
        )

        email_result: dict[str, Any] = {
            "status": "skipped",
            "delivery": "not_required",
        }
        if created_requests and vendor.get("contact_email"):
            missing_documents = [
                {
                    "type": request.get("document_type"),
                    "reason": request.get("reason"),
                }
                for request in created_requests
            ]
            email_raw = generate_evidence_request_email.invoke(
                {
                    "vendor_name": vendor.get("name", "Vendor"),
                    "contact_name": vendor.get("contact_name") or "Vendor Contact",
                    "missing_documents_json": json.dumps(missing_documents),
                    "deadline_days": 7 if any(request.get("criticality") == "required" for request in created_requests) else 14,
                }
            )
            email_payload = _parse_json(email_raw)
            send_raw = send_email.invoke(
                {
                    "to_email": vendor.get("contact_email"),
                    "subject": email_payload.get("subject", f"Document Request - {vendor.get('name', 'Vendor')}"),
                    "body": email_payload.get("body", ""),
                    "vendor_id": vendor_id,
                }
            )
            email_result = _parse_json(send_raw)
            trace_tool_call(
                vendor_id,
                "evidence_coordinator",
                "send_email",
                {"recipient": vendor.get("contact_email"), "request_count": len(created_requests)},
                email_result.get("status", "success"),
                email_result.get("delivery"),
                trace_id=trace_id,
            )
            if email_result.get("status") == "success":
                sent_at = datetime.now(timezone.utc).isoformat()
                for request in created_requests:
                    if request.get("id"):
                        update_evidence_request(
                            request["id"],
                            {
                                "email_sent": True,
                                "email_sent_at": sent_at,
                                "email_recipient": vendor.get("contact_email"),
                            },
                        )
                        create_evidence_tracking_entry(
                            {
                                "vendor_id": vendor_id,
                                "evidence_request_id": request["id"],
                                "action": "request_sent",
                                "actor": "evidence_coordinator",
                                "details": {
                                    "recipient": vendor.get("contact_email"),
                                    "delivery": email_result.get("delivery"),
                                },
                            }
                        )
        elif created_requests:
            create_evidence_tracking_entry(
                {
                    "vendor_id": vendor_id,
                    "action": "email_skipped_no_contact",
                    "actor": "evidence_coordinator",
                    "details": {
                        "request_count": len(created_requests),
                    },
                }
            )

        followup_payload = _parse_json(
            create_followup_task.invoke(
                {
                    "vendor_id": vendor_id,
                    "task_description": (
                        f"Follow up on {len(created_requests)} evidence request(s) for {vendor.get('name', 'vendor')}."
                    ),
                    "assigned_to": "procurement",
                    "due_days": 7,
                }
            )
        )
        status_payload = _parse_json(track_document_status.invoke({"vendor_id": vendor_id}))

        publish_event(
            vendor_id,
            "tool_status",
            {
                "phase": "evidence_coordination",
                "tool_name": "agent_end",
                "status": "complete",
            },
        )
        result = {
            "status": "success",
            "vendor_id": vendor_id,
            "requests_created": len(created_requests),
            "requests_skipped": len(skipped_requests),
            "email_delivery": email_result.get("delivery"),
            "tracking_summary": status_payload,
            "followup_task": followup_payload,
            "db_write_summary": {
                "created_requests": len(created_requests),
                "skipped_requests": len(skipped_requests),
            },
        }
        trace_agent_complete(vendor_id, "evidence_coordinator", result, trace_id=trace_id)
        return result

    except Exception as exc:
        logger.error("Evidence coordinator failed for vendor %s: %s", vendor_id, exc)
        trace_agent_error(
            vendor_id,
            "evidence_coordinator",
            str(exc),
            error_type=type(exc).__name__,
        )
        return {"status": "error", "error": str(exc)}
