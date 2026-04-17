"""
Phase 3 integration tests - risk assessment, approvals, audit trail, auth, dashboard.
"""

import asyncio
import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient
from starlette.requests import Request
from starlette.responses import StreamingResponse

from app.api.phase3_routes import vendor_sse
from app.main import app


@pytest.fixture
def client():
    return TestClient(app)


# ═══════════════════════════════════════════════════════════════════
# Risk Assessment
# ═══════════════════════════════════════════════════════════════════


class TestRiskAssessmentAPI:
    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Acme"}
    )
    @patch("app.api.phase3_routes.get_risk_assessment", return_value=None)
    def test_risk_assessment_not_started(self, mock_risk, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/risk-assessment")
        assert resp.status_code == 200
        assert resp.json()["status"] == "not_started"

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Acme"}
    )
    @patch(
        "app.api.phase3_routes.get_risk_assessment",
        return_value={
            "overall_risk_score": 82,
            "risk_level": "low",
            "approval_tier": "manager",
            "security_score": 87,
            "compliance_score": 78,
            "financial_score": 82,
            "security_weight": 0.40,
            "compliance_weight": 0.35,
            "financial_weight": 0.25,
            "executive_summary": "Acme completed assessment with 82/100.",
            "critical_blockers": [],
            "conditional_items": [],
            "mitigation_recommendations": [],
            "status": "completed",
            "completed_at": "2025-01-01T00:00:00+00:00",
        },
    )
    def test_risk_assessment_complete(self, mock_risk, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/risk-assessment")
        assert resp.status_code == 200
        data = resp.json()
        assert data["risk_assessment"]["overall_risk_score"] == 82
        assert data["risk_assessment"]["risk_level"] == "low"

    @patch("app.api.phase3_routes.get_vendor", return_value=None)
    def test_risk_assessment_vendor_not_found(self, mock_vendor, client):
        resp = client.get("/api/v1/vendors/nonexistent/risk-assessment")
        assert resp.status_code == 404

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Acme"}
    )
    @patch(
        "app.api.phase3_routes.get_risk_assessment",
        return_value={
            "overall_risk_score": 75,
            "risk_matrix": {
                "dimensions": [
                    {
                        "name": "Security",
                        "score": 80,
                        "color": "green",
                        "sub_scores": [],
                    },
                    {
                        "name": "Compliance",
                        "score": 65,
                        "color": "yellow",
                        "sub_scores": [],
                    },
                    {
                        "name": "Financial",
                        "score": 78,
                        "color": "green",
                        "sub_scores": [],
                    },
                ]
            },
        },
    )
    def test_risk_matrix(self, mock_risk, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/risk-matrix")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["risk_matrix"]["dimensions"]) == 3


# ═══════════════════════════════════════════════════════════════════
# Approval Workflow
# ═══════════════════════════════════════════════════════════════════


class TestApprovalAPI:
    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch("app.api.phase3_routes.get_approval_request", return_value=None)
    def test_approval_workflow_no_approval(self, mock_approval, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/approval-workflow")
        assert resp.status_code == 200
        assert resp.json()["status"] == "no_approval"

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch(
        "app.api.phase3_routes.get_approval_request",
        return_value={
            "id": "a1",
            "approval_tier": "vp",
            "status": "pending",
            "required_approvers": [{"role": "vp_security", "order": 1}],
            "workflow_id": None,
            "deadline": "2025-12-31T00:00:00+00:00",
        },
    )
    @patch(
        "app.api.phase3_routes.get_approval_workflow_by_tier",
        return_value={
            "id": "wf1",
            "name": "VP Approval",
            "approval_order": "parallel",
            "timeout_hours": 72,
        },
    )
    def test_approval_workflow_with_approvers(
        self, mock_wf, mock_approval, mock_vendor, client
    ):
        resp = client.get("/api/v1/vendors/v1/approval-workflow")
        assert resp.status_code == 200
        data = resp.json()
        assert data["approval_tier"] == "vp"
        assert len(data["required_approvers"]) == 1

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch("app.api.phase3_routes.get_approval_request", return_value=None)
    def test_submit_approval_no_request(self, mock_approval, mock_vendor, client):
        resp = client.post(
            "/api/v1/vendors/v1/approvals",
            json={
                "decision": "approve",
                "comments": "Looks good",
            },
        )
        assert resp.status_code == 401

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch(
        "app.api.phase3_routes.get_approval_request",
        return_value={
            "id": "a1",
            "status": "pending",
            "required_approvers": [{"role": "admin"}],
        },
    )
    @patch(
        "app.api.phase3_routes.record_approval_decision_data",
        return_value={
            "status": "recorded",
            "id": "d1",
        },
    )
    @patch(
        "app.api.phase3_routes.sync_approval_completion",
        return_value={
            "complete": True,
            "final_outcome": "approved",
        },
    )
    def test_submit_approval_success(
        self, mock_sync, mock_record, mock_approval, mock_vendor, client
    ):
        from app.api import phase3_routes

        app.dependency_overrides[phase3_routes.get_current_user] = lambda: {
            "id": "user-1",
            "full_name": "Admin",
            "role": "admin",
        }
        try:
            resp = client.post(
                "/api/v1/vendors/v1/approvals",
                json={
                    "decision": "approve",
                    "comments": "Approved",
                    "conditions": [],
                },
            )
            assert resp.status_code == 200
        finally:
            app.dependency_overrides.pop(phase3_routes.get_current_user, None)

    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch(
        "app.api.phase3_routes.get_approval_decisions_for_vendor",
        return_value=[
            {
                "id": "d1",
                "approver_name": "Admin",
                "approver_role": "admin",
                "decision": "approve",
                "comments": "OK",
                "conditions": [],
                "decided_at": "2025-01-01T00:00:00+00:00",
            },
        ],
    )
    def test_list_approval_decisions(self, mock_decisions, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/approvals")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ═══════════════════════════════════════════════════════════════════
# Audit Trail
# ═══════════════════════════════════════════════════════════════════


class TestAuditTrailAPI:
    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch(
        "app.api.phase3_routes.generate_audit_trail_data",
        return_value={
            "vendor_id": "v1",
            "vendor_name": "Vendor",
            "total_events": 3,
            "timeline": [
                {
                    "type": "agent_action",
                    "agent": "security_review",
                    "action": "agent_started",
                    "timestamp": "2025-01-01T00:00:00+00:00",
                },
                {
                    "type": "approval_decision",
                    "approver": "Admin",
                    "decision": "approve",
                    "timestamp": "2025-01-01T01:00:00+00:00",
                },
                {
                    "type": "status_change",
                    "old_status": "pending",
                    "new_status": "approved",
                    "timestamp": "2025-01-01T02:00:00+00:00",
                },
            ],
        },
    )
    def test_audit_trail(self, mock_audit, mock_vendor, client):
        resp = client.get("/api/v1/vendors/v1/audit-trail")
        assert resp.status_code == 200
        assert resp.json()["total_events"] == 3

    @patch("app.api.phase3_routes.get_vendor", return_value=None)
    def test_audit_trail_vendor_not_found(self, mock_vendor, client):
        resp = client.get("/api/v1/vendors/nonexistent/audit-trail")
        assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════
# Approval Packet
# ═══════════════════════════════════════════════════════════════════


class TestApprovalPacketAPI:
    @patch(
        "app.api.phase3_routes.get_vendor", return_value={"id": "v1", "name": "Vendor"}
    )
    @patch(
        "app.tools.supervisor_tools.get_vendor",
        return_value={
            "id": "v1",
            "name": "Vendor",
            "vendor_type": "saas",
            "contract_value": 50000,
            "domain": "example.com",
        },
    )
    @patch("app.tools.supervisor_tools.get_documents_for_vendor", return_value=[])
    @patch(
        "app.tools.supervisor_tools.get_security_review",
        return_value={
            "overall_score": 80,
            "grade": "B",
            "status": "completed",
            "report": {},
        },
    )
    @patch(
        "app.tools.supervisor_tools.get_compliance_review",
        return_value={
            "overall_score": 75,
            "grade": "C",
            "status": "completed",
            "report": {},
        },
    )
    @patch(
        "app.tools.supervisor_tools.get_financial_review",
        return_value={
            "overall_score": 90,
            "grade": "A",
            "status": "completed",
            "report": {},
        },
    )
    @patch(
        "app.tools.supervisor_tools.get_risk_assessment",
        return_value={
            "overall_risk_score": 81,
            "risk_level": "low",
            "approval_tier": "manager",
            "executive_summary": "Good vendor.",
            "critical_blockers": [],
            "conditional_items": [],
            "mitigation_recommendations": [],
        },
    )
    @patch(
        "app.tools.supervisor_tools.get_approval_request",
        return_value={
            "id": "a1",
            "approval_tier": "manager",
            "status": "approved",
            "required_approvers": [],
            "deadline": "2025-12-31T00:00:00+00:00",
        },
    )
    @patch(
        "app.tools.supervisor_tools.get_approval_decisions_for_vendor", return_value=[]
    )
    @patch("app.tools.supervisor_tools.get_evidence_requests", return_value=[])
    @patch("app.tools.supervisor_tools.get_audit_logs", return_value=[])
    @patch("app.tools.supervisor_tools.get_vendor_status_history", return_value=[])
    def test_approval_packet(
        self,
        mock_status_history,
        mock_audit_logs,
        mock_evidence_requests,
        mock_approval_decisions,
        mock_approval_request,
        mock_risk_assessment,
        mock_financial_review,
        mock_compliance_review,
        mock_security_review,
        mock_documents,
        mock_supervisor_vendor,
        mock_vendor,
        client,
    ):
        resp = client.get("/api/v1/vendors/v1/approval-packet")
        assert resp.status_code == 200
        data = resp.json()
        assert "vendor" in data
        assert data["aggregate_score"] > 0


# ═══════════════════════════════════════════════════════════════════
# Dashboard
# ═══════════════════════════════════════════════════════════════════


class TestDashboardAPI:
    @patch(
        "app.api.phase3_routes.get_dashboard_stats",
        return_value={
            "total_vendors": 10,
            "active_reviews": 3,
            "pending_approvals": 2,
            "completed_reviews": 5,
            "average_review_time_hours": 4.5,
            "success_rate": 80.0,
        },
    )
    def test_dashboard_stats(self, mock_stats, client):
        resp = client.get("/api/v1/dashboard/stats")
        assert resp.status_code == 200
        assert resp.json()["total_vendors"] == 10

    @patch(
        "app.api.phase3_routes.get_recent_vendors",
        return_value=[
            {"id": "v1", "name": "Vendor1", "status": "approved"},
        ],
    )
    @patch("app.api.phase3_routes.get_recent_approvals", return_value=[])
    def test_dashboard_recent(self, mock_approvals, mock_vendors, client):
        resp = client.get("/api/v1/dashboard/recent")
        assert resp.status_code == 200
        assert len(resp.json()["recent_vendors"]) == 1


# ═══════════════════════════════════════════════════════════════════
# Auth
# ═══════════════════════════════════════════════════════════════════


class TestAuthAPI:
    @patch("app.api.phase3_routes.authenticate_user", return_value=None)
    def test_login_invalid_user(self, mock_authenticate, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "email": "noone@example.com",
                "password": "wrong",
            },
        )
        assert resp.status_code == 401

    @patch("app.api.phase3_routes.authenticate_user", return_value=None)
    def test_login_wrong_password(self, mock_authenticate, client):
        resp = client.post(
            "/api/v1/auth/login",
            json={
                "email": "admin@vendorsols.com",
                "password": "wrong",
            },
        )
        assert resp.status_code == 401

    @patch("app.api.phase3_routes.get_user_by_email", return_value=None)
    def test_register_new_user(self, mock_user, client):
        with patch(
            "app.api.phase3_routes.create_user",
            return_value={
                "id": "u2",
                "email": "new@example.com",
                "full_name": "New User",
                "role": "reviewer",
            },
        ):
            resp = client.post(
                "/api/v1/auth/register",
                json={
                    "email": "new@example.com",
                    "password": "password123",
                    "full_name": "New User",
                    "role": "reviewer",
                },
            )
            assert resp.status_code == 200
            assert resp.json()["status"] == "success"

    @patch("app.api.phase3_routes.get_user_by_email", return_value={"id": "existing"})
    def test_register_duplicate_email(self, mock_user, client):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": "existing@example.com",
                "password": "password123",
                "full_name": "Existing",
            },
        )
        assert resp.status_code == 400


# ═══════════════════════════════════════════════════════════════════
# Admin / Workflow Management
# ═══════════════════════════════════════════════════════════════════


class TestAdminWorkflowAPI:
    @patch(
        "app.api.phase3_routes.list_approval_workflows",
        return_value=[
            {"id": "wf1", "name": "VP Approval", "risk_tier": "vp"},
        ],
    )
    def test_list_workflows(self, mock_list, client):
        resp = client.get("/api/v1/approval-workflows")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1

    @patch("app.api.phase3_routes.list_users", return_value=[])
    def test_list_users(self, mock_users, client):
        resp = client.get("/api/v1/users")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════
# Vendor List (Enhanced)
# ═══════════════════════════════════════════════════════════════════


class TestVendorListAPI:
    @patch("app.api.phase3_routes.get_risk_assessment", return_value=None)
    @patch("app.api.phase3_routes.get_approval_request", return_value=None)
    @patch("app.core.db.get_supabase")
    def test_list_vendors(self, mock_sb, mock_approval, mock_risk, client):
        mock_execute = MagicMock()
        mock_execute.data = [
            {
                "id": "v1",
                "name": "Vendor1",
                "vendor_type": "saas",
                "status": "pending",
                "contract_value": 50000,
                "domain": "v1.com",
                "contact_email": None,
                "created_at": "2025-01-01T00:00:00+00:00",
                "updated_at": "2025-01-01T00:00:00+00:00",
            },
        ]
        mock_query = MagicMock()
        mock_query.limit.return_value = mock_query
        mock_query.offset.return_value = mock_query
        mock_query.order.return_value = mock_query
        mock_query.eq.return_value = mock_query
        mock_query.select.return_value = mock_query
        mock_query.execute.return_value = mock_execute

        mock_sb_instance = MagicMock()
        mock_sb_instance.table.return_value = mock_query
        mock_sb.return_value = mock_sb_instance

        resp = client.get("/api/v1/vendors")
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ═══════════════════════════════════════════════════════════════════
# SSE
# ═══════════════════════════════════════════════════════════════════


class TestSSEEndpoint:
    def test_sse_endpoint_exists(self):
        async def receive():
            return {"type": "http.request", "body": b"", "more_body": False}

        request = Request(
            {
                "type": "http",
                "asgi": {"version": "3.0"},
                "http_version": "1.1",
                "method": "GET",
                "scheme": "http",
                "path": "/api/v1/vendors/v1/events",
                "raw_path": b"/api/v1/vendors/v1/events",
                "query_string": b"",
                "headers": [],
                "client": ("testclient", 50000),
                "server": ("testserver", 80),
            },
            receive=receive,
        )

        response = asyncio.run(vendor_sse("v1", request))
        assert isinstance(response, StreamingResponse)
        assert response.media_type == "text/event-stream"
