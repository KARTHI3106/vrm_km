"""
Approval orchestration tools and helpers.

The public tool API remains available for ReAct agents, but the core approval
workflow is deterministic so real vendor decisions are persisted reliably.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from langchain_core.tools import tool

from app.config import get_settings
from app.core.db import (
    create_approval_decision,
    create_approval_request as db_create_approval,
    create_audit_log,
    create_notification,
    create_vendor_status_history,
    get_approval_decisions,
    get_approval_decisions_for_vendor,
    get_approval_request,
    get_approval_workflow as db_get_approval_workflow,
    get_approval_workflow_by_tier,
    get_audit_logs,
    get_notifications_for_approval,
    get_risk_assessment,
    get_user_by_id,
    get_vendor,
    get_vendor_status_history,
    update_approval_request,
    update_notification,
    update_vendor,
)

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _parse_json_array(value: Any) -> list[Any]:
    if isinstance(value, list):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _decision_status(final_decision: str) -> str:
    return {
        "approved": "approved",
        "rejected": "rejected",
        "conditional_approval": "conditional",
    }.get(final_decision, final_decision)


def _send_email(recipient_email: str, subject: str, body: str) -> tuple[str, str | None]:
    settings = get_settings()
    if not recipient_email:
        return "simulated", "No recipient email configured."

    if settings.mailgun_api_key and settings.mailgun_domain:
        try:
            import httpx

            response = httpx.post(
                f"{settings.mailgun_base_url}/{settings.mailgun_domain}/messages",
                auth=("api", settings.mailgun_api_key),
                data={
                    "from": f"{settings.mailtrap_sender_name} <{settings.mailtrap_sender_email}>",
                    "to": [recipient_email],
                    "subject": subject,
                    "text": body,
                },
                timeout=10,
            )
            if response.status_code in (200, 201):
                return "sent", None
            return "failed", response.text[:500]
        except Exception as exc:
            logger.warning("Mailgun send failed for %s: %s", recipient_email, exc)
            return "failed", str(exc)

    if settings.mailtrap_api_key:
        try:
            import httpx

            response = httpx.post(
                "https://send.api.mailtrap.io/api/send",
                headers={
                    "Authorization": f"Bearer {settings.mailtrap_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "from": {
                        "email": settings.mailtrap_sender_email,
                        "name": settings.mailtrap_sender_name,
                    },
                    "to": [{"email": recipient_email}],
                    "subject": subject,
                    "text": body,
                },
                timeout=10,
            )
            if response.status_code in (200, 201, 202):
                return "sent", None
            return "failed", response.text[:500]
        except Exception as exc:
            logger.warning("Mailtrap send failed for %s: %s", recipient_email, exc)
            return "failed", str(exc)

    return "simulated", "No outbound email provider configured."


def _workflow_for_tier(risk_tier: str) -> dict[str, Any]:
    workflow = get_approval_workflow_by_tier(risk_tier)
    if workflow:
        return workflow
    return {
        "id": None,
        "name": f"Fallback {risk_tier}",
        "risk_tier": risk_tier,
        "approvers": [],
        "approval_order": "parallel",
        "timeout_hours": 72,
    }


def get_approval_workflow_data(risk_tier: str) -> dict[str, Any]:
    workflow = _workflow_for_tier(risk_tier)
    return {
        "workflow_id": workflow.get("id"),
        "name": workflow.get("name"),
        "risk_tier": workflow.get("risk_tier"),
        "approvers": workflow.get("approvers", []),
        "approval_order": workflow.get("approval_order", "parallel"),
        "timeout_hours": workflow.get("timeout_hours", 72),
    }


def create_approval_request_data(
    vendor_id: str,
    approval_tier: str,
    workflow_id: str = "",
    required_approvers: list[dict[str, Any]] | None = None,
    created_by: str | None = None,
) -> dict[str, Any]:
    existing = get_approval_request(vendor_id)
    if existing and existing.get("status") in {"pending", "conditional"}:
        return existing

    vendor = get_vendor(vendor_id) or {}
    risk = get_risk_assessment(vendor_id) or {}

    workflow = db_get_approval_workflow(workflow_id) if workflow_id else None
    if not workflow:
        workflow = _workflow_for_tier(approval_tier)

    approvers = required_approvers if required_approvers is not None else workflow.get("approvers", [])
    timeout_hours = int(workflow.get("timeout_hours", 72) or 72)
    deadline = datetime.now(timezone.utc) + timedelta(hours=max(timeout_hours, 0))

    approval = db_create_approval(
        {
            "vendor_id": vendor_id,
            "risk_assessment_id": risk.get("id"),
            "workflow_id": workflow.get("id"),
            "approval_tier": approval_tier,
            "status": "pending",
            "required_approvers": approvers,
            "review_context": {
                "vendor": {
                    "name": vendor.get("name"),
                    "vendor_type": vendor.get("vendor_type"),
                    "contract_value": _safe_float(vendor.get("contract_value")),
                    "domain": vendor.get("domain"),
                },
                "risk_assessment": {
                    "overall_risk_score": _safe_float(risk.get("overall_risk_score")),
                    "risk_level": risk.get("risk_level"),
                    "approval_tier": risk.get("approval_tier"),
                    "critical_blockers": risk.get("critical_blockers", []),
                    "conditional_items": risk.get("conditional_items", []),
                    "executive_summary": risk.get("executive_summary"),
                },
                "workflow": {
                    "name": workflow.get("name"),
                    "approval_order": workflow.get("approval_order", "parallel"),
                    "timeout_hours": timeout_hours,
                },
            },
            "deadline": deadline.isoformat(),
            "created_by": created_by,
        }
    )

    update_vendor(vendor_id, {"status": "pending_approval"})
    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="approval_request_created",
        output_data={
            "approval_id": approval.get("id"),
            "approval_tier": approval_tier,
            "required_approvers": approvers,
        },
    )
    return approval


def send_approval_notification_data(
    vendor_id: str,
    approval_id: str,
    recipient_email: str,
    recipient_role: str,
    vendor_name: str = "",
    risk_score: float = 0.0,
    approval_tier: str = "",
) -> dict[str, Any]:
    subject = f"[Vendorsols] Approval required: {vendor_name or vendor_id}"
    body = (
        f"Vendor: {vendor_name or vendor_id}\n"
        f"Risk score: {risk_score}/100\n"
        f"Approval tier: {approval_tier}\n"
        f"Approver role: {recipient_role}\n\n"
        "Please review the vendor in Vendorsols and record your decision before the approval deadline."
    )

    notification = create_notification(
        {
            "approval_id": approval_id,
            "vendor_id": vendor_id,
            "recipient_email": recipient_email,
            "notification_type": "approval_request",
            "subject": subject,
            "body": body,
            "channel": "email",
            "status": "pending",
        }
    )

    status, error_message = _send_email(recipient_email, subject, body)
    if notification.get("id"):
        update_notification(
            notification["id"],
            {
                "status": status,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "error_message": error_message,
            },
        )

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="approval_notification_sent",
        output_data={
            "approval_id": approval_id,
            "recipient_email": recipient_email,
            "recipient_role": recipient_role,
            "status": status,
        },
    )

    return {
        "notification_id": notification.get("id"),
        "recipient_email": recipient_email,
        "recipient_role": recipient_role,
        "status": status,
        "error_message": error_message,
    }


def _latest_decisions_by_role(approval_id: str) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for decision in get_approval_decisions(approval_id):
        latest[str(decision.get("approver_role") or decision.get("approver_id") or decision.get("id"))] = decision
    return latest


def track_approval_status_data(vendor_id: str) -> dict[str, Any]:
    approval = get_approval_request(vendor_id)
    if not approval:
        return {
            "vendor_id": vendor_id,
            "status": "no_approval_request",
            "completion_percentage": 0.0,
            "pending_approvers": [],
            "decisions": [],
        }

    latest_decisions = _latest_decisions_by_role(approval["id"])
    required = approval.get("required_approvers", [])
    required_roles = [str(item.get("role")) for item in required if item.get("role")]
    decided_roles = {role for role in latest_decisions if role}
    pending_roles = [role for role in required_roles if role not in decided_roles]

    total_required = len(required_roles)
    total_decided = len(decided_roles) if total_required else 0
    completion = 100.0 if total_required == 0 else round((total_decided / total_required) * 100, 1)

    deadline = approval.get("deadline")
    overdue = False
    if deadline:
        try:
            overdue = datetime.now(timezone.utc) > datetime.fromisoformat(str(deadline).replace("Z", "+00:00"))
        except ValueError:
            overdue = False

    return {
        "vendor_id": vendor_id,
        "approval_id": approval.get("id"),
        "status": approval.get("status"),
        "completion_percentage": completion,
        "total_required": total_required,
        "total_decided": total_decided,
        "pending_approvers": pending_roles,
        "overdue": overdue,
        "decisions": list(latest_decisions.values()),
    }


def record_approval_decision_data(
    vendor_id: str,
    approval_id: str,
    approver_name: str,
    approver_role: str,
    decision: str,
    comments: str = "",
    conditions: list[Any] | None = None,
    approver_id: str | None = None,
) -> dict[str, Any]:
    decision = decision.lower().strip()
    if decision not in {"approve", "reject", "request_changes"}:
        raise ValueError("Decision must be approve, reject, or request_changes.")

    existing_by_role = _latest_decisions_by_role(approval_id)
    existing = existing_by_role.get(approver_role)
    if existing:
        return {"status": "already_recorded", **existing}

    payload = {
        "approval_id": approval_id,
        "vendor_id": vendor_id,
        "approver_id": approver_id,
        "approver_name": approver_name,
        "approver_role": approver_role,
        "decision": decision,
        "comments": comments,
        "conditions": conditions or [],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    created = create_approval_decision(payload)

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="approval_decision_recorded",
        output_data={
            "approval_id": approval_id,
            "approver_name": approver_name,
            "approver_role": approver_role,
            "decision": decision,
        },
    )
    return {"status": "recorded", **created}


def check_all_approvals_complete_data(vendor_id: str) -> dict[str, Any]:
    approval = get_approval_request(vendor_id)
    if not approval:
        return {
            "vendor_id": vendor_id,
            "complete": False,
            "final_outcome": "pending",
            "all_conditions": [],
            "has_rejections": False,
        }

    latest_decisions = _latest_decisions_by_role(approval["id"])
    required = approval.get("required_approvers", [])
    required_roles = [str(item.get("role")) for item in required if item.get("role")]
    decided_roles = {role for role in latest_decisions if role}
    decisions = list(latest_decisions.values())

    has_rejections = any(decision.get("decision") == "reject" for decision in decisions)
    all_responded = len(required_roles) == 0 or all(role in decided_roles for role in required_roles)
    complete = has_rejections or all_responded

    all_conditions: list[str] = []
    for decision in decisions:
        for condition in decision.get("conditions", []):
            text = condition if isinstance(condition, str) else json.dumps(condition, default=str)
            if text not in all_conditions:
                all_conditions.append(text)

    if has_rejections:
        final_outcome = "rejected"
    elif any(decision.get("decision") == "request_changes" for decision in decisions) or all_conditions:
        final_outcome = "conditional_approval" if complete else "pending"
    elif complete:
        final_outcome = "approved"
    else:
        final_outcome = "pending"

    return {
        "vendor_id": vendor_id,
        "approval_id": approval.get("id"),
        "complete": complete,
        "all_responded": all_responded,
        "has_rejections": has_rejections,
        "final_outcome": final_outcome,
        "all_conditions": all_conditions,
        "decisions_count": len(decisions),
        "required_count": len(required_roles),
    }


def finalize_vendor_status_data(vendor_id: str, final_decision: str, conditions: list[Any] | None = None) -> dict[str, Any]:
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise ValueError(f"Vendor {vendor_id} not found.")

    old_status = vendor.get("status", "unknown")
    normalized_conditions = conditions or []

    update_vendor(vendor_id, {"status": final_decision})
    create_vendor_status_history(
        {
            "vendor_id": vendor_id,
            "old_status": old_status,
            "new_status": final_decision,
            "changed_by": "approval_orchestrator",
            "reason": f"Approval workflow finalized as {final_decision}.",
            "conditions": normalized_conditions,
            "effective_date": datetime.now(timezone.utc).date().isoformat(),
        }
    )

    approval = get_approval_request(vendor_id)
    if approval:
        update_approval_request(approval["id"], {"status": _decision_status(final_decision)})

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="vendor_status_finalized",
        output_data={
            "old_status": old_status,
            "new_status": final_decision,
            "conditions": normalized_conditions,
        },
    )

    return {
        "vendor_id": vendor_id,
        "old_status": old_status,
        "new_status": final_decision,
        "conditions": normalized_conditions,
        "effective_date": datetime.now(timezone.utc).date().isoformat(),
        "status": "finalized",
    }


def generate_audit_trail_data(vendor_id: str) -> dict[str, Any]:
    vendor = get_vendor(vendor_id) or {}
    logs = get_audit_logs(vendor_id)
    decisions = get_approval_decisions_for_vendor(vendor_id)
    history = get_vendor_status_history(vendor_id)

    approval = get_approval_request(vendor_id)
    notifications = get_notifications_for_approval(approval["id"]) if approval else []

    timeline: list[dict[str, Any]] = []

    for log in logs:
        timeline.append(
            {
                "timestamp": log.get("created_at"),
                "type": "agent_action",
                "agent": log.get("agent_name"),
                "action": log.get("action"),
                "tool": log.get("tool_name"),
                "status": log.get("status"),
                "input_data": log.get("input_data", {}),
                "output_data": log.get("output_data", {}),
                "duration_ms": log.get("duration_ms"),
            }
        )

    for decision in decisions:
        timeline.append(
            {
                "timestamp": decision.get("decided_at") or decision.get("created_at"),
                "type": "approval_decision",
                "approver": decision.get("approver_name"),
                "role": decision.get("approver_role"),
                "decision": decision.get("decision"),
                "comments": decision.get("comments"),
                "conditions": decision.get("conditions", []),
            }
        )

    for notification in notifications:
        timeline.append(
            {
                "timestamp": notification.get("sent_at") or notification.get("created_at"),
                "type": "notification",
                "recipient": notification.get("recipient_email"),
                "notification_type": notification.get("notification_type"),
                "status": notification.get("status"),
                "channel": notification.get("channel"),
            }
        )

    for status_change in history:
        timeline.append(
            {
                "timestamp": status_change.get("created_at"),
                "type": "status_change",
                "old_status": status_change.get("old_status"),
                "new_status": status_change.get("new_status"),
                "changed_by": status_change.get("changed_by"),
                "reason": status_change.get("reason"),
                "conditions": status_change.get("conditions", []),
            }
        )

    timeline.sort(key=lambda item: item.get("timestamp", ""))

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.get("name"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_events": len(timeline),
        "timeline": timeline,
    }


def send_vendor_notification_data(vendor_id: str, decision: str, conditions: list[Any] | None = None) -> dict[str, Any]:
    vendor = get_vendor(vendor_id) or {}
    recipient_email = vendor.get("contact_email", "")
    recipient_name = vendor.get("contact_name", "Vendor Partner")
    normalized_conditions = [str(item) for item in (conditions or [])]

    subject = f"[Vendorsols] Vendor assessment result: {decision.replace('_', ' ').title()}"
    body_lines = [
        f"Hello {recipient_name},",
        "",
        f"The review for {vendor.get('name', 'your organization')} has completed.",
        f"Decision: {decision.replace('_', ' ').title()}",
    ]
    if normalized_conditions:
        body_lines.extend(["", "Conditions:", *[f"- {item}" for item in normalized_conditions]])
    body_lines.extend(
        [
            "",
            "If you have questions, please contact the Vendorsols vendor management team.",
        ]
    )
    body = "\n".join(body_lines)

    notification = create_notification(
        {
            "approval_id": (get_approval_request(vendor_id) or {}).get("id"),
            "vendor_id": vendor_id,
            "recipient_email": recipient_email,
            "notification_type": "vendor_outcome",
            "subject": subject,
            "body": body,
            "channel": "email",
            "status": "pending",
        }
    )

    status, error_message = _send_email(recipient_email, subject, body)
    if notification.get("id"):
        update_notification(
            notification["id"],
            {
                "status": status,
                "sent_at": datetime.now(timezone.utc).isoformat(),
                "error_message": error_message,
            },
        )

    create_audit_log(
        vendor_id=vendor_id,
        agent_name="approval_orchestrator",
        action="vendor_notification_sent",
        output_data={
            "decision": decision,
            "recipient_email": recipient_email,
            "status": status,
        },
    )

    return {
        "notification_id": notification.get("id"),
        "recipient_email": recipient_email,
        "status": status,
        "error_message": error_message,
    }


def sync_approval_completion(vendor_id: str) -> dict[str, Any]:
    approval = get_approval_request(vendor_id)
    if approval and approval.get("status") in {"approved", "rejected", "conditional"}:
        final_outcome = "conditional_approval" if approval.get("status") == "conditional" else approval.get("status")
        return {
            "vendor_id": vendor_id,
            "approval_id": approval.get("id"),
            "complete": True,
            "final_outcome": final_outcome,
            "all_conditions": [],
            "status": "already_finalized",
        }

    completion = check_all_approvals_complete_data(vendor_id)
    if not completion.get("complete"):
        return completion

    final_decision = completion["final_outcome"]
    conditions = completion.get("all_conditions", [])
    finalize_vendor_status_data(vendor_id, final_decision, conditions)
    send_vendor_notification_data(vendor_id, final_decision, conditions)
    return {
        **completion,
        "status": "finalized",
    }


def orchestrate_approval_setup(vendor_id: str) -> dict[str, Any]:
    vendor = get_vendor(vendor_id) or {}
    risk = get_risk_assessment(vendor_id) or {}
    approval_tier = risk.get("approval_tier") or "vp"

    workflow = get_approval_workflow_data(approval_tier)
    approval = create_approval_request_data(
        vendor_id=vendor_id,
        approval_tier=approval_tier,
        workflow_id=workflow.get("workflow_id") or "",
        required_approvers=workflow.get("approvers", []),
    )

    for approver in workflow.get("approvers", []):
        recipient_email = approver.get("email", "")
        recipient_role = approver.get("role", "approver")
        send_approval_notification_data(
            vendor_id=vendor_id,
            approval_id=approval.get("id"),
            recipient_email=recipient_email,
            recipient_role=recipient_role,
            vendor_name=vendor.get("name", ""),
            risk_score=_safe_float(risk.get("overall_risk_score")),
            approval_tier=approval_tier,
        )

    if approval_tier == "auto_approve" or not workflow.get("approvers"):
        sync_approval_completion(vendor_id)

    return {
        "vendor_id": vendor_id,
        "approval_id": approval.get("id"),
        "approval_tier": approval_tier,
        "workflow": workflow,
        "status": get_approval_request(vendor_id).get("status") if get_approval_request(vendor_id) else "pending",
    }


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


@tool
def get_approval_workflow(risk_tier: str) -> str:
    """Return the workflow definition for a risk tier."""
    return _json({"status": "success", **get_approval_workflow_data(risk_tier)})


@tool
def create_approval_request(
    vendor_id: str,
    approval_tier: str,
    workflow_id: str = "",
    required_approvers: str = "[]",
) -> str:
    """Create the approval request record for a vendor."""
    created = create_approval_request_data(
        vendor_id=vendor_id,
        approval_tier=approval_tier,
        workflow_id=workflow_id,
        required_approvers=_parse_json_array(required_approvers),
    )
    return _json({"status": "success", **created})


@tool
def send_approval_notification(
    vendor_id: str,
    approval_id: str,
    recipient_email: str,
    recipient_role: str,
    vendor_name: str = "",
    risk_score: float = 0.0,
    approval_tier: str = "",
) -> str:
    """Send or simulate an approval notification."""
    result = send_approval_notification_data(
        vendor_id=vendor_id,
        approval_id=approval_id,
        recipient_email=recipient_email,
        recipient_role=recipient_role,
        vendor_name=vendor_name,
        risk_score=risk_score,
        approval_tier=approval_tier,
    )
    return _json(
        {
            "status": "success",
            "delivery_status": result.get("status"),
            **{key: value for key, value in result.items() if key != "status"},
        }
    )


@tool
def track_approval_status(vendor_id: str) -> str:
    """Track current approval progress for a vendor."""
    return _json({"status": "success", **track_approval_status_data(vendor_id)})


@tool
def record_approval_decision(
    vendor_id: str,
    approval_id: str,
    approver_name: str,
    approver_role: str,
    decision: str,
    comments: str = "",
    conditions: str = "[]",
) -> str:
    """Record an approver decision."""
    result = record_approval_decision_data(
        vendor_id=vendor_id,
        approval_id=approval_id,
        approver_name=approver_name,
        approver_role=approver_role,
        decision=decision,
        comments=comments,
        conditions=_parse_json_array(conditions),
    )
    return _json(result)


@tool
def check_all_approvals_complete(vendor_id: str) -> str:
    """Check whether the approval workflow has reached a terminal state."""
    return _json({"status": "success", **check_all_approvals_complete_data(vendor_id)})


@tool
def finalize_vendor_status(
    vendor_id: str,
    final_decision: str,
    conditions: str = "[]",
) -> str:
    """Finalize the vendor record after approval completion."""
    return _json(
        {
            "status": "success",
            **finalize_vendor_status_data(vendor_id, final_decision, _parse_json_array(conditions)),
        }
    )


@tool
def generate_audit_trail(vendor_id: str) -> str:
    """Generate the complete audit trail for compliance review."""
    return _json({"status": "success", **generate_audit_trail_data(vendor_id)})


@tool
def send_vendor_notification(vendor_id: str, decision: str, conditions: str = "[]") -> str:
    """Send or simulate the final vendor notification."""
    result = send_vendor_notification_data(vendor_id, decision, _parse_json_array(conditions))
    return _json(
        {
            "status": "success",
            "delivery_status": result.get("status"),
            **{key: value for key, value in result.items() if key != "status"},
        }
    )


APPROVAL_TOOLS = [
    get_approval_workflow,
    create_approval_request,
    send_approval_notification,
    track_approval_status,
    record_approval_decision,
    check_all_approvals_complete,
    finalize_vendor_status,
    generate_audit_trail,
    send_vendor_notification,
]
