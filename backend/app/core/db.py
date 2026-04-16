"""
Supabase database client and helper functions.
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional
from supabase import create_client, Client
from app.config import get_settings

logger = logging.getLogger(__name__)

_supabase_client: Optional[Client] = None


def get_supabase() -> Client:
    """Get or create a Supabase client singleton."""
    global _supabase_client
    if _supabase_client is None:
        settings = get_settings()
        _supabase_client = create_client(settings.supabase_url, settings.supabase_key)
        logger.info("Supabase client initialized")
    return _supabase_client


# ── Vendor Operations ──────────────────────────────────────────────


def create_vendor(data: dict) -> dict:
    """Insert a new vendor record."""
    sb = get_supabase()
    result = sb.table("vendors").insert(data).execute()
    return result.data[0] if result.data else {}


def get_vendor(vendor_id: str) -> Optional[dict]:
    """Retrieve a vendor by ID."""
    sb = get_supabase()
    result = sb.table("vendors").select("*").eq("id", vendor_id).execute()
    return result.data[0] if result.data else None


def update_vendor(vendor_id: str, data: dict) -> dict:
    """Update a vendor record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("vendors").update(data).eq("id", vendor_id).execute()
    return result.data[0] if result.data else {}


# ── Document Operations ────────────────────────────────────────────


def create_document(data: dict) -> dict:
    """Insert a new document record."""
    sb = get_supabase()
    result = sb.table("documents").insert(data).execute()
    return result.data[0] if result.data else {}


def get_documents_for_vendor(vendor_id: str) -> list[dict]:
    """Get all documents for a vendor."""
    sb = get_supabase()
    result = sb.table("documents").select("*").eq("vendor_id", vendor_id).execute()
    return result.data or []


def update_document(doc_id: str, data: dict) -> dict:
    """Update a document record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("documents").update(data).eq("id", doc_id).execute()
    return result.data[0] if result.data else {}


def check_duplicate_document(vendor_id: str, file_name: str) -> bool:
    """Check if a document with the same name already exists for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("documents")
        .select("id")
        .eq("vendor_id", vendor_id)
        .eq("file_name", file_name)
        .execute()
    )
    return len(result.data) > 0


# ── Security Review Operations ─────────────────────────────────────


def create_security_review(data: dict) -> dict:
    """Insert a new security review record."""
    sb = get_supabase()
    result = sb.table("security_reviews").insert(data).execute()
    return result.data[0] if result.data else {}


def get_security_review(vendor_id: str) -> Optional[dict]:
    """Get the latest security review for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("security_reviews")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_security_review(review_id: str, data: dict) -> dict:
    """Update a security review record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("security_reviews").update(data).eq("id", review_id).execute()
    return result.data[0] if result.data else {}


# ── Audit Log Operations ──────────────────────────────────────────


def create_audit_log(
    vendor_id: Optional[str],
    agent_name: str,
    action: str,
    tool_name: Optional[str] = None,
    input_data: Optional[dict] = None,
    output_data: Optional[dict] = None,
    status: str = "success",
    error_message: Optional[str] = None,
    duration_ms: Optional[int] = None,
    token_usage: Optional[dict] = None,
) -> dict:
    """Create an audit log entry."""
    sb = get_supabase()
    log_data = {
        "vendor_id": vendor_id,
        "agent_name": agent_name,
        "action": action,
        "tool_name": tool_name,
        "input_data": input_data or {},
        "output_data": output_data or {},
        "status": status,
        "error_message": error_message,
        "duration_ms": duration_ms,
        "token_usage": token_usage or {},
    }
    result = sb.table("audit_logs").insert(log_data).execute()
    return result.data[0] if result.data else {}


def get_audit_logs(vendor_id: str) -> list[dict]:
    """Get all audit logs for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("audit_logs")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ── Policy Operations ─────────────────────────────────────────────


def create_policy(data: dict) -> dict:
    """Insert a new policy record."""
    sb = get_supabase()
    result = sb.table("policies").insert(data).execute()
    return result.data[0] if result.data else {}


def get_active_policies(category: str = "security") -> list[dict]:
    """Get all active policies for a category."""
    sb = get_supabase()
    result = (
        sb.table("policies")
        .select("*")
        .eq("category", category)
        .eq("is_active", True)
        .execute()
    )
    return result.data or []


# ── Breach Operations ─────────────────────────────────────────────


def search_breaches(company_name: str, domain: Optional[str] = None) -> list[dict]:
    """Search for breaches by company name or domain."""
    sb = get_supabase()
    query = sb.table("breaches").select("*")
    # Search by company name (case-insensitive partial match)
    query = query.ilike("company_name", f"%{company_name}%")
    result = query.execute()
    results = result.data or []

    if domain:
        domain_result = (
            sb.table("breaches").select("*").ilike("domain", f"%{domain}%").execute()
        )
        # Merge unique results
        existing_ids = {r["id"] for r in results}
        for r in domain_result.data or []:
            if r["id"] not in existing_ids:
                results.append(r)

    return results


# ── Vendor Review State Operations ─────────────────────────────────


def save_review_state(vendor_id: str, state_data: dict, current_phase: str) -> dict:
    """Save or update the vendor review state."""
    sb = get_supabase()
    # Check if exists
    existing = (
        sb.table("vendor_review_states")
        .select("id")
        .eq("vendor_id", vendor_id)
        .execute()
    )
    payload = {
        "vendor_id": vendor_id,
        "state_data": state_data,
        "current_phase": current_phase,
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    if existing.data:
        result = (
            sb.table("vendor_review_states")
            .update(payload)
            .eq("vendor_id", vendor_id)
            .execute()
        )
    else:
        result = sb.table("vendor_review_states").insert(payload).execute()
    return result.data[0] if result.data else {}


def get_review_state(vendor_id: str) -> Optional[dict]:
    """Get the current review state for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("vendor_review_states")
        .select("*")
        .eq("vendor_id", vendor_id)
        .execute()
    )
    return result.data[0] if result.data else None


# ── File Storage Operations ────────────────────────────────────────


def upload_file(vendor_id: str, file_name: str, file_content: bytes) -> str:
    """Upload a file to Supabase Storage and return its path."""
    sb = get_supabase()
    storage_path = f"{vendor_id}/{file_name}"
    sb.storage.from_("vendor-documents").upload(storage_path, file_content)
    return storage_path


def get_file_url(storage_path: str) -> str:
    """Get a signed URL for a file in Supabase Storage."""
    sb = get_supabase()
    result = sb.storage.from_("vendor-documents").create_signed_url(
        storage_path,
        3600,  # 1 hour expiry
    )
    return result.get("signedURL", "")


# ── Health Check ───────────────────────────────────────────────────


def check_db_health() -> bool:
    """Check if the database connection is healthy."""
    try:
        sb = get_supabase()
        sb.table("vendors").select("id").limit(1).execute()
        return True
    except Exception as e:
        logger.error(f"Database health check failed: {e}")
        return False


# ══════════════════════════════════════════════════════════════════
# PHASE 2: Compliance Review Operations
# ══════════════════════════════════════════════════════════════════


def create_compliance_review(data: dict) -> dict:
    """Insert a new compliance review record."""
    sb = get_supabase()
    result = sb.table("compliance_reviews").insert(data).execute()
    return result.data[0] if result.data else {}


def get_compliance_review(vendor_id: str) -> Optional[dict]:
    """Get the latest compliance review for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("compliance_reviews")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_compliance_review(review_id: str, data: dict) -> dict:
    """Update a compliance review record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("compliance_reviews").update(data).eq("id", review_id).execute()
    return result.data[0] if result.data else {}


# ══════════════════════════════════════════════════════════════════
# PHASE 2: Financial Review Operations
# ══════════════════════════════════════════════════════════════════


def create_financial_review(data: dict) -> dict:
    """Insert a new financial review record."""
    sb = get_supabase()
    result = sb.table("financial_reviews").insert(data).execute()
    return result.data[0] if result.data else {}


def get_financial_review(vendor_id: str) -> Optional[dict]:
    """Get the latest financial review for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("financial_reviews")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_financial_review(review_id: str, data: dict) -> dict:
    """Update a financial review record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("financial_reviews").update(data).eq("id", review_id).execute()
    return result.data[0] if result.data else {}


# ══════════════════════════════════════════════════════════════════
# PHASE 2: Evidence Operations
# ══════════════════════════════════════════════════════════════════


def create_evidence_request(data: dict) -> dict:
    """Insert a new evidence request record."""
    sb = get_supabase()
    result = sb.table("evidence_requests").insert(data).execute()
    return result.data[0] if result.data else {}


def get_evidence_requests(vendor_id: str) -> list[dict]:
    """Get all evidence requests for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("evidence_requests")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def update_evidence_request(request_id: str, data: dict) -> dict:
    """Update an evidence request record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("evidence_requests").update(data).eq("id", request_id).execute()
    return result.data[0] if result.data else {}


def create_evidence_tracking_entry(data: dict) -> dict:
    """Insert an evidence tracking log entry."""
    sb = get_supabase()
    result = sb.table("evidence_tracking").insert(data).execute()
    return result.data[0] if result.data else {}


def get_evidence_tracking(vendor_id: str) -> list[dict]:
    """Get all evidence tracking entries for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("evidence_tracking")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Risk Assessment Operations
# ══════════════════════════════════════════════════════════════════


def create_risk_assessment(data: dict) -> dict:
    """Insert a new risk assessment record."""
    sb = get_supabase()
    result = sb.table("risk_assessments").insert(data).execute()
    return result.data[0] if result.data else {}


def get_risk_assessment(vendor_id: str) -> Optional[dict]:
    """Get the latest risk assessment for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("risk_assessments")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def update_risk_assessment(assessment_id: str, data: dict) -> dict:
    """Update a risk assessment record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("risk_assessments").update(data).eq("id", assessment_id).execute()
    return result.data[0] if result.data else {}


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Approval Workflow Operations
# ══════════════════════════════════════════════════════════════════


def get_approval_workflow_by_tier(risk_tier: str) -> Optional[dict]:
    """Get the active approval workflow for a given risk tier."""
    sb = get_supabase()
    result = (
        sb.table("approval_workflows")
        .select("*")
        .eq("risk_tier", risk_tier)
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_approval_workflow(workflow_id: str) -> Optional[dict]:
    """Get an approval workflow by its ID."""
    sb = get_supabase()
    result = (
        sb.table("approval_workflows")
        .select("*")
        .eq("id", workflow_id)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def list_approval_workflows() -> list[dict]:
    """List all approval workflows."""
    sb = get_supabase()
    result = sb.table("approval_workflows").select("*").order("created_at").execute()
    return result.data or []


def create_approval_workflow(data: dict) -> dict:
    """Create or update an approval workflow."""
    sb = get_supabase()
    result = sb.table("approval_workflows").insert(data).execute()
    return result.data[0] if result.data else {}


def update_approval_workflow(workflow_id: str, data: dict) -> dict:
    """Update an approval workflow."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("approval_workflows").update(data).eq("id", workflow_id).execute()
    return result.data[0] if result.data else {}


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Approval Request Operations
# ══════════════════════════════════════════════════════════════════


def create_approval_request(data: dict) -> dict:
    """Create a new approval request."""
    sb = get_supabase()
    result = sb.table("approvals").insert(data).execute()
    return result.data[0] if result.data else {}


def get_approval_request(vendor_id: str) -> Optional[dict]:
    """Get the latest approval request for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("approvals")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_approval_requests_for_vendor(vendor_id: str) -> list[dict]:
    """Get all approval requests for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("approvals")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def update_approval_request(approval_id: str, data: dict) -> dict:
    """Update an approval request."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("approvals").update(data).eq("id", approval_id).execute()
    return result.data[0] if result.data else {}


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Approval Decision Operations
# ══════════════════════════════════════════════════════════════════


def create_approval_decision(data: dict) -> dict:
    """Record an approval decision."""
    sb = get_supabase()
    result = sb.table("approval_decisions").insert(data).execute()
    return result.data[0] if result.data else {}


def get_approval_decisions(approval_id: str) -> list[dict]:
    """Get all decisions for an approval request."""
    sb = get_supabase()
    result = (
        sb.table("approval_decisions")
        .select("*")
        .eq("approval_id", approval_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


def get_approval_decisions_for_vendor(vendor_id: str) -> list[dict]:
    """Get all approval decisions for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("approval_decisions")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Notification Operations
# ══════════════════════════════════════════════════════════════════


def create_notification(data: dict) -> dict:
    """Create a notification record."""
    sb = get_supabase()
    result = sb.table("approval_notifications").insert(data).execute()
    return result.data[0] if result.data else {}


def update_notification(notification_id: str, data: dict) -> dict:
    """Update a notification status."""
    sb = get_supabase()
    result = (
        sb.table("approval_notifications")
        .update(data)
        .eq("id", notification_id)
        .execute()
    )
    return result.data[0] if result.data else {}


def get_notifications_for_approval(approval_id: str) -> list[dict]:
    """Get all notifications for an approval."""
    sb = get_supabase()
    result = (
        sb.table("approval_notifications")
        .select("*")
        .eq("approval_id", approval_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Vendor Status History
# ══════════════════════════════════════════════════════════════════


def create_vendor_status_history(data: dict) -> dict:
    """Record a vendor status change."""
    sb = get_supabase()
    result = sb.table("vendor_status_history").insert(data).execute()
    return result.data[0] if result.data else {}


def get_vendor_status_history(vendor_id: str) -> list[dict]:
    """Get the status history for a vendor."""
    sb = get_supabase()
    result = (
        sb.table("vendor_status_history")
        .select("*")
        .eq("vendor_id", vendor_id)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data or []


# ══════════════════════════════════════════════════════════════════
# PHASE 3: User Operations (Auth)
# ══════════════════════════════════════════════════════════════════


def create_user(data: dict) -> dict:
    """Create a new user."""
    sb = get_supabase()
    result = sb.table("users").insert(data).execute()
    return result.data[0] if result.data else {}


def get_user_by_email(email: str) -> Optional[dict]:
    """Get a user by email address."""
    sb = get_supabase()
    result = sb.table("users").select("*").eq("email", email).limit(1).execute()
    return result.data[0] if result.data else None


def get_user_by_id(user_id: str) -> Optional[dict]:
    """Get a user by ID."""
    sb = get_supabase()
    result = sb.table("users").select("*").eq("id", user_id).limit(1).execute()
    return result.data[0] if result.data else None


def update_user(user_id: str, data: dict) -> dict:
    """Update a user record."""
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    sb = get_supabase()
    result = sb.table("users").update(data).eq("id", user_id).execute()
    return result.data[0] if result.data else {}


def list_users(role: Optional[str] = None) -> list[dict]:
    """List users, optionally filtered by role."""
    sb = get_supabase()
    query = sb.table("users").select(
        "id, email, full_name, role, department, is_active, created_at"
    )
    if role:
        query = query.eq("role", role)
    result = query.order("created_at").execute()
    return result.data or []


# ══════════════════════════════════════════════════════════════════
# PHASE 3: Dashboard / Stats Operations
# ══════════════════════════════════════════════════════════════════


def get_dashboard_stats() -> dict:
    """Get dashboard statistics (with Redis caching)."""
    try:
        from app.core.redis_state import cache_get, cache_set

        cached = cache_get("dashboard_stats")
        if cached:
            return cached
    except Exception:
        pass

    sb = get_supabase()

    # Vendor counts by status
    all_vendors = sb.table("vendors").select("id, status, created_at").execute()
    vendors = all_vendors.data or []
    active = sum(1 for v in vendors if v.get("status") == "processing")
    completed = sum(
        1
        for v in vendors
        if v.get("status") in ("review_completed", "approved", "rejected")
    )
    pending_approval = sum(1 for v in vendors if v.get("status") == "pending_approval")

    # Recent approvals
    pending_approvals = (
        sb.table("approvals").select("id").eq("status", "pending").execute()
    )

    history = (
        sb.table("vendor_status_history")
        .select("vendor_id, new_status, created_at")
        .execute()
    )
    history_rows = history.data or []

    first_completed_by_vendor: dict[str, str] = {}
    approved_like = {"approved", "conditional_approval"}
    completed_like = {
        "review_completed",
        "approved",
        "rejected",
        "conditional_approval",
    }

    for row in history_rows:
        vendor_id = row.get("vendor_id")
        new_status = row.get("new_status")
        created_at = row.get("created_at")
        if (
            vendor_id
            and new_status in completed_like
            and vendor_id not in first_completed_by_vendor
        ):
            first_completed_by_vendor[vendor_id] = created_at

    review_durations_hours: list[float] = []
    success_count = 0
    terminal_count = 0

    for vendor in vendors:
        vendor_id = vendor.get("id")
        completed_at = first_completed_by_vendor.get(vendor_id)
        created_at = vendor.get("created_at")
        status = vendor.get("status")

        if status in approved_like:
            success_count += 1
        if status in completed_like:
            terminal_count += 1

        if not created_at or not completed_at:
            continue

        try:
            started = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ended = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
        except (AttributeError, ValueError):
            continue

        review_durations_hours.append(
            max((ended - started).total_seconds() / 3600, 0.0)
        )

    avg_review_time = (
        round(sum(review_durations_hours) / len(review_durations_hours), 2)
        if review_durations_hours
        else 0.0
    )
    success_rate = (
        round((success_count / terminal_count) * 100, 1) if terminal_count else 0.0
    )

    result = {
        "total_vendors": len(vendors),
        "active_reviews": active,
        "pending_approvals": len(pending_approvals.data or []),
        "completed_reviews": completed,
        "average_review_time_hours": avg_review_time,
        "success_rate": success_rate,
    }

    try:
        from app.core.redis_state import cache_set

        cache_set("dashboard_stats", result, ttl=60)
    except Exception:
        pass

    return result


def get_recent_vendors(limit: int = 10) -> list[dict]:
    """Get the most recently created/updated vendors."""
    sb = get_supabase()
    result = (
        sb.table("vendors")
        .select(
            "id, name, vendor_type, status, contract_value, domain, created_at, updated_at"
        )
        .order("updated_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def get_recent_approvals(limit: int = 10) -> list[dict]:
    """Get the most recent approval decisions."""
    sb = get_supabase()
    result = (
        sb.table("approval_decisions")
        .select("*")
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []
