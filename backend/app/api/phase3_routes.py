"""
Phase 3 API routes — Risk Assessment, Approvals, Audit Trail, Dashboard, Auth, SSE.
"""

import json
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.core.auth import (
    get_current_user,
    get_optional_user,
    require_role,
    authenticate_user,
    hash_password,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.core.db import (
    get_vendor,
    get_risk_assessment,
    get_approval_workflow,
    get_approval_request,
    get_approval_requests_for_vendor,
    get_approval_decisions_for_vendor,
    get_audit_logs,
    get_approval_workflow_by_tier,
    list_approval_workflows,
    create_approval_workflow,
    update_approval_workflow,
    create_approval_decision,
    create_user,
    get_user_by_email,
    get_user_by_id,
    update_user,
    list_users,
    get_dashboard_stats,
    get_recent_vendors,
    get_recent_approvals,
    get_vendor_status_history,
    get_security_review,
    get_compliance_review,
    get_financial_review,
    get_evidence_requests,
)
from app.tools.approval_tools import (
    generate_audit_trail_data,
    record_approval_decision_data,
    sync_approval_completion,
    track_approval_status_data,
)
from app.tools.supervisor_tools import compile_approval_packet
from app.core.events import event_manager

logger = logging.getLogger(__name__)

phase3_router = APIRouter(prefix="/api/v1")


# ═══════════════════════════════════════════════════════════════════
# Request / Response Models
# ═══════════════════════════════════════════════════════════════════


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str = "reviewer"
    department: str = ""


class ApprovalDecisionRequest(BaseModel):
    decision: str  # approve, reject, request_changes
    comments: str = ""
    conditions: list[str] = Field(default_factory=list)


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class WorkflowCreateRequest(BaseModel):
    name: str
    risk_tier: str
    approvers: list[dict] = Field(default_factory=list)
    approval_order: str = "sequential"
    timeout_hours: int = 72


# ═══════════════════════════════════════════════════════════════════
# Auth Endpoints
# ═══════════════════════════════════════════════════════════════════


@phase3_router.post("/auth/login")
async def login(req: LoginRequest):
    """Authenticate and receive JWT tokens."""
    user = authenticate_user(req.email, req.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid email or password")

    update_user(user["id"], {"last_login": datetime.now(timezone.utc).isoformat()})

    tokens = {
        "access_token": create_access_token({"sub": user["id"], "role": user["role"]}),
        "refresh_token": create_refresh_token({"sub": user["id"]}),
        "token_type": "bearer",
        "user": {
            "id": user["id"],
            "email": user["email"],
            "full_name": user["full_name"],
            "role": user["role"],
        },
    }
    return tokens


@phase3_router.post("/auth/register")
async def register(req: RegisterRequest):
    """Register a new user."""
    existing = get_user_by_email(req.email)
    if existing:
        raise HTTPException(status_code=400, detail="Email already registered")

    user = create_user(
        {
            "email": req.email,
            "password_hash": hash_password(req.password),
            "full_name": req.full_name,
            "role": req.role,
            "department": req.department,
        }
    )

    return {
        "status": "success",
        "user": {
            "id": user.get("id"),
            "email": user.get("email"),
            "full_name": user.get("full_name"),
            "role": user.get("role"),
        },
    }


@phase3_router.post("/auth/refresh")
async def refresh_token(req: RefreshTokenRequest):
    """Get a new access token using a refresh token."""
    payload = decode_token(req.refresh_token)
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=400, detail="Invalid refresh token")

    user = get_user_by_id(payload.get("sub"))
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    return {
        "access_token": create_access_token({"sub": user["id"], "role": user["role"]}),
        "token_type": "bearer",
    }


@phase3_router.get("/auth/me")
async def get_me(user: dict = Depends(get_current_user)):
    """Get current user profile."""
    return {
        "id": user.get("id"),
        "email": user.get("email"),
        "full_name": user.get("full_name"),
        "role": user.get("role"),
    }


# ═══════════════════════════════════════════════════════════════════
# Risk Assessment Endpoints
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors/{vendor_id}/risk-assessment")
async def get_vendor_risk_assessment(vendor_id: str):
    """Return overall risk score, level, breakdown, executive summary, and recommendations."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    risk = get_risk_assessment(vendor_id)
    if not risk:
        return {
            "vendor_id": vendor_id,
            "status": "not_started",
            "message": "No risk assessment completed for this vendor.",
        }

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.get("name"),
        "risk_assessment": {
            "overall_risk_score": float(risk.get("overall_risk_score", 0)),
            "risk_level": risk.get("risk_level"),
            "approval_tier": risk.get("approval_tier"),
            "breakdown": {
                "security": {
                    "score": float(risk.get("security_score", 0)),
                    "weight": float(risk.get("security_weight", 0.40)),
                },
                "compliance": {
                    "score": float(risk.get("compliance_score", 0)),
                    "weight": float(risk.get("compliance_weight", 0.35)),
                },
                "financial": {
                    "score": float(risk.get("financial_score", 0)),
                    "weight": float(risk.get("financial_weight", 0.25)),
                },
            },
            "executive_summary": risk.get("executive_summary"),
            "critical_blockers": risk.get("critical_blockers", []),
            "conditional_items": risk.get("conditional_items", []),
            "mitigation_recommendations": risk.get("mitigation_recommendations", []),
            "status": risk.get("status"),
            "completed_at": risk.get("completed_at"),
        },
    }


@phase3_router.get("/vendors/{vendor_id}/risk-matrix")
async def get_vendor_risk_matrix(vendor_id: str):
    """Return risk matrix data for visualization."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    risk = get_risk_assessment(vendor_id)
    if not risk:
        return {"vendor_id": vendor_id, "status": "not_started"}

    return {
        "vendor_id": vendor_id,
        "risk_matrix": risk.get("risk_matrix", {}),
    }


# ═══════════════════════════════════════════════════════════════════
# Approval Endpoints
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors/{vendor_id}/approval-workflow")
async def get_vendor_approval_workflow(vendor_id: str):
    """Return required approvers, order, and current status."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    approval = get_approval_request(vendor_id)
    if not approval:
        return {
            "vendor_id": vendor_id,
            "status": "no_approval",
            "message": "No approval workflow initiated.",
        }

    workflow_id = approval.get("workflow_id")
    workflow = None
    if workflow_id:
        workflow = get_approval_workflow(workflow_id)
    if not workflow:
        workflow = get_approval_workflow_by_tier(approval.get("approval_tier", ""))

    return {
        "vendor_id": vendor_id,
        "approval_id": approval.get("id"),
        "approval_tier": approval.get("approval_tier"),
        "status": approval.get("status"),
        "required_approvers": approval.get("required_approvers", []),
        "workflow": {
            "id": workflow.get("id") if workflow else None,
            "name": workflow.get("name") if workflow else "N/A",
            "approval_order": workflow.get("approval_order")
            if workflow
            else "sequential",
            "timeout_hours": workflow.get("timeout_hours") if workflow else 72,
        },
        "deadline": approval.get("deadline"),
    }


@phase3_router.post("/vendors/{vendor_id}/approvals")
async def submit_approval_decision(
    vendor_id: str,
    req: ApprovalDecisionRequest,
    user: dict = Depends(require_role("admin", "approver")),
):
    """Submit an approval decision for a vendor. Requires authentication."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    approval = get_approval_request(vendor_id)
    if not approval:
        raise HTTPException(status_code=404, detail="No approval request found")

    if req.decision not in ("approve", "reject", "request_changes"):
        raise HTTPException(
            status_code=400,
            detail="Decision must be: approve, reject, or request_changes",
        )

    decision = record_approval_decision_data(
        vendor_id=vendor_id,
        approval_id=approval["id"],
        approver_id=user.get("id"),
        approver_name=user.get("full_name", "Unknown"),
        approver_role=user.get("role", "approver"),
        decision=req.decision,
        comments=req.comments,
        conditions=req.conditions,
    )
    completion = sync_approval_completion(vendor_id)

    return {
        "status": "success",
        "decision_id": decision.get("id"),
        "vendor_id": vendor_id,
        "decision": req.decision,
        "approval_complete": completion.get("complete", False),
        "final_outcome": completion.get("final_outcome"),
        "message": f"Decision '{req.decision}' recorded successfully.",
    }


@phase3_router.get("/vendors/{vendor_id}/approvals")
async def list_approval_decisions(vendor_id: str):
    """List all approval decisions for a vendor."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    decisions = get_approval_decisions_for_vendor(vendor_id)

    return {
        "vendor_id": vendor_id,
        "total": len(decisions),
        "decisions": [
            {
                "id": d.get("id"),
                "approver_name": d.get("approver_name"),
                "approver_role": d.get("approver_role"),
                "decision": d.get("decision"),
                "comments": d.get("comments"),
                "conditions": d.get("conditions", []),
                "decided_at": d.get("decided_at"),
            }
            for d in decisions
        ],
    }


@phase3_router.get("/vendors/{vendor_id}/approval-status")
async def get_vendor_approval_status(vendor_id: str):
    """Return completion percentage, pending approvers, and final decision."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    approval = get_approval_request(vendor_id)
    if not approval:
        return {"vendor_id": vendor_id, "status": "no_approval"}

    tracked = track_approval_status_data(vendor_id)
    final_decision = None
    if tracked.get("status") in {"approved", "rejected", "conditional"}:
        final_decision = (
            "conditional_approval"
            if tracked["status"] == "conditional"
            else tracked["status"]
        )

    return {
        "vendor_id": vendor_id,
        "approval_id": approval.get("id"),
        "status": tracked.get("status"),
        "completion_percentage": tracked.get("completion_percentage", 0),
        "total_required": tracked.get("total_required", 0),
        "total_decided": tracked.get("total_decided", 0),
        "pending_approvers": tracked.get("pending_approvers", []),
        "overdue": tracked.get("overdue", False),
        "final_decision": final_decision,
        "decisions": [
            {
                "approver": d.get("approver_name"),
                "role": d.get("approver_role"),
                "decision": d.get("decision"),
                "decided_at": d.get("decided_at"),
            }
            for d in tracked.get("decisions", [])
        ],
    }


# ═══════════════════════════════════════════════════════════════════
# Audit Trail
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors/{vendor_id}/audit-trail")
async def get_vendor_audit_trail(vendor_id: str):
    """Return the complete audit log for a vendor."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")

    trail = generate_audit_trail_data(vendor_id)
    return trail


# ═══════════════════════════════════════════════════════════════════
# Approval Packet (Full Report)
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors/{vendor_id}/approval-packet")
async def get_vendor_approval_packet(vendor_id: str):
    """Return the complete approval packet including all review findings,
    risk assessment, approval decisions, and audit trail."""
    vendor = get_vendor(vendor_id)
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
    packet = compile_approval_packet.invoke({"vendor_id": vendor_id})
    parsed = json.loads(packet)
    return parsed.get("approval_packet", parsed)


# ═══════════════════════════════════════════════════════════════════
# Dashboard
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/dashboard/stats")
async def dashboard_stats():
    """Dashboard statistics: active reviews, pending approvals, completed reviews."""
    stats = get_dashboard_stats()
    return stats


@phase3_router.get("/dashboard/recent")
async def dashboard_recent():
    """Recent vendor reviews, approvals, and completions."""
    vendors = get_recent_vendors(10)
    approvals = get_recent_approvals(10)

    return {
        "recent_vendors": vendors,
        "recent_approvals": approvals,
        "recent_completions": [
            vendor
            for vendor in vendors
            if vendor.get("status") in ("approved", "rejected", "conditional_approval")
        ][:10],
    }


# ═══════════════════════════════════════════════════════════════════
# Admin — Workflow Management
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/approval-workflows")
async def list_workflows():
    """List all approval workflows."""
    workflows = list_approval_workflows()
    return {
        "total": len(workflows),
        "workflows": workflows,
    }


@phase3_router.post("/approval-workflows")
async def create_workflow(
    req: WorkflowCreateRequest,
    user: dict = Depends(require_role("admin")),
):
    """Create a new approval workflow. Admin only."""
    workflow = create_approval_workflow(
        {
            "name": req.name,
            "risk_tier": req.risk_tier,
            "approvers": req.approvers,
            "approval_order": req.approval_order,
            "timeout_hours": req.timeout_hours,
        }
    )

    return {
        "status": "success",
        "workflow": workflow,
    }


# ═══════════════════════════════════════════════════════════════════
# Admin — Users
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/users")
async def list_all_users(
    role: Optional[str] = None, user: dict = Depends(require_role("admin"))
):
    """List all users. Optionally filter by role."""
    users = list_users(role=role)
    return {"total": len(users), "users": users}


# ═══════════════════════════════════════════════════════════════════
# Vendor List (enhanced for frontend)
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors")
async def list_vendors(
    status: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
):
    """List all vendors with optional filtering."""
    from app.core.db import get_supabase

    sb = get_supabase()
    query = (
        sb.table("vendors")
        .select("*")
        .order("updated_at", desc=True)
        .limit(limit)
        .offset(offset)
    )
    if status:
        query = query.eq("status", status)
    result = query.execute()
    vendors = result.data or []

    enriched = []
    for vendor in vendors:
        risk = get_risk_assessment(vendor.get("id"))
        approval = get_approval_request(vendor.get("id"))
        enriched.append(
            {
                "id": vendor.get("id"),
                "name": vendor.get("name"),
                "vendor_type": vendor.get("vendor_type"),
                "status": vendor.get("status"),
                "contract_value": float(vendor.get("contract_value", 0)),
                "domain": vendor.get("domain"),
                "contact_email": vendor.get("contact_email"),
                "created_at": vendor.get("created_at"),
                "updated_at": vendor.get("updated_at"),
                "overall_risk_score": float(risk.get("overall_risk_score", 0))
                if risk
                else None,
                "risk_level": risk.get("risk_level") if risk else None,
                "approval_tier": risk.get("approval_tier") if risk else None,
                "approval_status": approval.get("status") if approval else None,
            }
        )

    return {
        "total": len(enriched),
        "vendors": enriched,
    }


# ═══════════════════════════════════════════════════════════════════
# SSE — Real-time workflow updates
# ═══════════════════════════════════════════════════════════════════


@phase3_router.get("/vendors/{vendor_id}/events")
async def vendor_sse(vendor_id: str, request: Request):
    """Server-Sent Events stream for real-time vendor workflow updates."""

    async def event_generator():
        queue = event_manager.subscribe(vendor_id)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=30)
                    yield f"data: {json.dumps(event, default=str)}\n\n"
                except asyncio.TimeoutError:
                    yield f": keepalive\n\n"
        finally:
            event_manager.unsubscribe(vendor_id, queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════
# Admin — Policy Management
# ═══════════════════════════════════════════════════════════════════


class PolicyCreateRequest(BaseModel):
    title: str
    content: str
    category: str = "security"
    source: str = ""
    version: str = "1.0"


@phase3_router.get("/policies")
async def list_policies_admin(category: Optional[str] = None):
    """List all policies for admin management."""
    from app.core.db import get_active_policies, get_supabase

    sb = get_supabase()
    query = sb.table("policies").select("*").order("created_at", desc=True)
    if category:
        query = query.eq("category", category)
    result = query.execute()
    return {"total": len(result.data or []), "policies": result.data or []}


@phase3_router.post("/policies")
async def create_policy_admin(
    req: PolicyCreateRequest, user: dict = Depends(require_role("admin"))
):
    """Create a new policy. Admin only."""
    from app.core.db import create_policy
    from app.core.vector import upsert_policy

    policy = create_policy(
        {
            "title": req.title,
            "content": req.content,
            "category": req.category,
            "source": req.source,
            "version": req.version,
            "is_active": True,
        }
    )
    import uuid

    upsert_policy(
        collection=f"{req.category}_policies",
        policy_id=policy.get("id", str(uuid.uuid4())),
        title=req.title,
        content=req.content,
        metadata={
            "source": req.source,
            "version": req.version,
            "category": req.category,
        },
    )
    return {"status": "success", "policy": policy}


@phase3_router.delete("/policies/{policy_id}")
async def delete_policy_admin(
    policy_id: str, user: dict = Depends(require_role("admin"))
):
    """Deactivate a policy. Admin only."""
    from app.core.db import get_supabase

    sb = get_supabase()
    sb.table("policies").update(
        {"is_active": False, "updated_at": datetime.now(timezone.utc).isoformat()}
    ).eq("id", policy_id).execute()
    return {"status": "success", "message": "Policy deactivated."}


# ═══════════════════════════════════════════════════════════════════
# Admin — Approval Workflow Management
# ═══════════════════════════════════════════════════════════════════


@phase3_router.put("/approval-workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    req: WorkflowCreateRequest,
    user: dict = Depends(require_role("admin")),
):
    """Update an approval workflow. Admin only."""
    workflow = update_approval_workflow(
        workflow_id,
        {
            "name": req.name,
            "risk_tier": req.risk_tier,
            "approvers": req.approvers,
            "approval_order": req.approval_order,
            "timeout_hours": req.timeout_hours,
        },
    )
    return {"status": "success", "workflow": workflow}
