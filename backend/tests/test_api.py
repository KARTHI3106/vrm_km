"""
Integration tests for the API endpoints.
"""
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def client():
    """Create a test client."""
    return TestClient(app)


class TestHealthEndpoint:
    """Tests for the health check endpoint."""

    @patch("app.api.routes.check_db_health", return_value=True)
    @patch("app.api.routes.check_redis_health", return_value=True)
    @patch("app.api.routes.check_vector_health", return_value=True)
    @patch("app.api.routes.check_llm_health", return_value={"openai": True, "groq": False})
    def test_all_healthy(self, mock_llm, mock_vec, mock_redis, mock_db, client):
        """Test health check when all services are up."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert data["services"]["database"]["status"] == "up"
        assert data["services"]["redis"]["status"] == "up"

    @patch("app.api.routes.check_db_health", return_value=False)
    @patch("app.api.routes.check_redis_health", return_value=True)
    @patch("app.api.routes.check_vector_health", return_value=True)
    @patch("app.api.routes.check_llm_health", return_value={"openai": True, "groq": False})
    def test_degraded_health(self, mock_llm, mock_vec, mock_redis, mock_db, client):
        """Test health check when database is down."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "degraded"


class TestRootEndpoint:
    """Tests for the root endpoint."""

    def test_root(self, client):
        """Test root endpoint returns system info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert "Vendorsols" in data["system"]
        assert "agents" in data


class TestVendorStatusEndpoint:
    """Tests for vendor status endpoint."""

    @patch("app.api.routes.get_vendor", return_value=None)
    def test_vendor_not_found(self, mock_get, client):
        """Test getting status for non-existent vendor."""
        response = client.get("/api/v1/vendors/nonexistent-id/status")
        assert response.status_code == 404

    @patch("app.api.routes.load_state", return_value=None)
    @patch("app.api.routes.get_approval_request", return_value={"id": "approval-1", "status": "pending"})
    @patch("app.api.routes.get_risk_assessment", return_value={"overall_risk_score": 82, "risk_level": "low", "approval_tier": "manager"})
    @patch("app.api.routes.get_vendor", return_value={
        "id": "test-id",
        "name": "Test Vendor",
        "vendor_type": "technology",
        "domain": "example.com",
        "status": "processing",
    })
    def test_vendor_found(self, mock_get, mock_risk, mock_approval, mock_state, client):
        """Test getting status for existing vendor."""
        response = client.get("/api/v1/vendors/test-id/status")
        assert response.status_code == 200
        data = response.json()
        assert data["vendor_name"] == "Test Vendor"
        assert data["vendor_type"] == "technology"
        assert data["risk_level"] == "low"
        assert data["approval_status"] == "pending"


class TestPolicyUploadEndpoint:
    """Tests for security policy upload endpoint."""

    @patch("app.api.routes.upsert_policy")
    @patch("app.api.routes.create_policy", return_value={"id": "policy-123"})
    def test_upload_policy(self, mock_create, mock_upsert, client):
        """Test uploading a security policy."""
        response = client.post(
            "/api/v1/policies/security",
            json={
                "title": "Data Encryption Policy",
                "content": "All data must be encrypted at rest and in transit...",
                "category": "security",
                "source": "Internal",
                "version": "1.0",
            },
        )
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "success"
        assert data["policy_id"] == "policy-123"


class TestPhase3Routes:
    @patch("app.api.phase3_routes.get_vendor", return_value={"id": "vendor-1", "name": "Vendor One"})
    @patch("app.api.phase3_routes.get_approval_request", return_value={"id": "approval-1", "status": "pending"})
    @patch("app.api.phase3_routes.track_approval_status_data", return_value={
        "status": "pending",
        "completion_percentage": 50,
        "total_required": 2,
        "total_decided": 1,
        "pending_approvers": ["vp_security"],
        "overdue": False,
        "decisions": [{"approver_name": "Alex", "approver_role": "vp_procurement", "decision": "approve", "decided_at": "2025-01-01T00:00:00+00:00"}],
    })
    def test_approval_status_endpoint(self, mock_track, mock_approval, mock_vendor, client):
        response = client.get("/api/v1/vendors/vendor-1/approval-status")
        assert response.status_code == 200
        data = response.json()
        assert data["completion_percentage"] == 50
        assert data["pending_approvers"] == ["vp_security"]

    @patch("app.api.phase3_routes.get_vendor", return_value={"id": "vendor-1", "name": "Vendor One"})
    @patch("app.api.phase3_routes.generate_audit_trail_data", return_value={"vendor_id": "vendor-1", "timeline": [{"type": "agent_action"}], "total_events": 1})
    def test_audit_trail_endpoint(self, mock_audit, mock_vendor, client):
        response = client.get("/api/v1/vendors/vendor-1/audit-trail")
        assert response.status_code == 200
        data = response.json()
        assert data["total_events"] == 1


class TestOnboardingAndTraceRoutes:
    @patch("app.api.routes._run_workflow_sync")
    @patch("app.api.routes.create_vendor", return_value={"id": "vendor-123"})
    @patch(
        "app.api.routes.infer_vendor_context_from_files",
        return_value={
            "vendor_name": "CyberShield",
            "vendor_type": "saas",
            "contract_value": 125000.0,
            "vendor_domain": "cybershield.example",
            "contact_email": "security@cybershield.example",
            "contact_name": "Alex Analyst",
            "industry": "security",
            "parse_notes": ["Vendor name inferred from uploaded document metadata."],
            "candidate_count": 1,
        },
    )
    @patch(
        "app.api.routes._extract_vendor_from_prompt",
        return_value=SimpleNamespace(
            vendor_name="",
            vendor_type="technology",
            contract_value=0.0,
            vendor_domain="",
            contact_email="",
            contact_name="",
        ),
    )
    def test_onboard_vendor_backfills_identity_from_documents(
        self,
        mock_extract,
        mock_infer,
        mock_create_vendor,
        mock_run_workflow,
        client,
    ):
        upload_dir = Path(__file__).resolve().parent / "_tmp_uploads" / str(uuid.uuid4())
        upload_dir.mkdir(parents=True, exist_ok=True)

        try:
            with patch(
                "app.api.routes.get_settings",
                return_value=SimpleNamespace(upload_dir=str(upload_dir)),
            ):
                response = client.post(
                    "/api/v1/vendors/onboard",
                    data={"prompt": "check the files"},
                    files=[
                        ("files", ("CyberShield_SOC2.pdf", b"%PDF-1.4 mock", "application/pdf")),
                    ],
                )
        finally:
            shutil.rmtree(upload_dir, ignore_errors=True)

        assert response.status_code == 200
        payload = response.json()
        assert payload["status"] == "accepted"
        assert payload["vendor_id"] == "vendor-123"
        assert "CyberShield" in payload["message"]
        assert payload["parse_notes"] == [
            "Vendor name inferred from uploaded document metadata."
        ]

        created_vendor = mock_create_vendor.call_args.args[0]
        assert created_vendor["name"] == "CyberShield"
        assert created_vendor["vendor_type"] == "saas"
        assert created_vendor["domain"] == "cybershield.example"
        assert created_vendor["metadata"]["onboarding_prompt"] == "check the files"
        assert sorted(created_vendor["metadata"]["ingest_basis"])
        mock_run_workflow.assert_called_once()

    @patch("app.api.routes.get_agent_traces", return_value=[{"trace_id": "live-1", "timestamp": "2026-04-17T02:20:00+00:00", "phase": "review", "step": "decision", "status": "success", "message": "Live decision", "provider": "openai", "model": "gpt-4o", "tool_name": None, "input_summary": {"documents": 1}, "output_summary": {"overall_score": 82}}])
    @patch("app.api.routes.get_persisted_traces", return_value=[{"trace_id": "persisted-1", "timestamp": "2026-04-17T02:19:00+00:00", "phase": "intake", "step": "start", "status": "in_progress", "message": "Intake started", "provider": "openai", "model": "gpt-4o", "tool_name": "parse_uploaded_files", "input_summary": {"files": 1}, "output_summary": {"message": "Parsing staged uploads"}}])
    @patch("app.api.routes.get_vendor", return_value={"id": "vendor-123", "name": "CyberShield"})
    def test_vendor_traces_returns_structured_trace_payload(
        self,
        mock_vendor,
        mock_persisted,
        mock_live,
        client,
    ):
        response = client.get("/api/v1/vendors/vendor-123/traces")

        assert response.status_code == 200
        payload = response.json()
        assert payload["vendor_id"] == "vendor-123"
        assert payload["total_traces"] == 2
        assert [trace["trace_id"] for trace in payload["traces"]] == [
            "persisted-1",
            "live-1",
        ]
        assert payload["traces"][0]["phase"] == "intake"
        assert payload["traces"][0]["tool_name"] == "parse_uploaded_files"
        assert payload["traces"][1]["model"] == "gpt-4o"
