from types import SimpleNamespace
from unittest.mock import MagicMock, patch


SECURITY_SCORE = {
    "overall_score": 85,
    "grade": "B",
    "breakdown": {"certificates": 80},
    "critical_flags": [],
    "risk_level": "low",
}

COMPLIANCE_SCORE = {
    "overall_score": 78,
    "grade": "C",
    "breakdown": {"gdpr": 80},
    "critical_flags": [],
    "risk_level": "medium",
}

FINANCIAL_SCORE = {
    "overall_score": 82,
    "grade": "B",
    "breakdown": {"insurance": 85},
    "critical_flags": [],
    "risk_level": "low",
}


class TestReviewAgentsPersistOwnRows:
    @patch("app.agents.security_review.save_state")
    @patch("app.agents.security_review.load_state", return_value={})
    @patch("app.agents.security_review.publish_event")
    @patch("app.agents.security_review.update_security_review")
    @patch("app.agents.security_review.create_security_review", return_value={"id": "sec-review-1"})
    @patch("app.agents.security_review.calculate_security_score_data", return_value=SECURITY_SCORE)
    @patch("app.agents.security_review.create_security_agent")
    @patch("app.agents.security_review.get_documents_for_vendor", return_value=[])
    @patch(
        "app.agents.security_review.get_vendor",
        return_value={
            "id": "vendor-1",
            "name": "Vendor One",
            "vendor_type": "technology",
            "domain": "example.com",
            "contract_value": 10000,
        },
    )
    def test_security_agent_creates_and_completes_its_own_review(
        self,
        mock_vendor,
        mock_documents,
        mock_create_agent,
        mock_score,
        mock_create_review,
        mock_update_review,
        mock_publish,
        mock_load_state,
        mock_save_state,
    ):
        from app.agents.security_review import run_security_agent

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="Security review summary")]
        }
        mock_create_agent.return_value = mock_agent

        result = run_security_agent("vendor-1")

        assert result["status"] == "success"
        mock_create_review.assert_called_once()
        mock_update_review.assert_called_once()
        review_id, payload = mock_update_review.call_args.args
        assert review_id == "sec-review-1"
        assert payload["status"] == "completed"
        assert payload["overall_score"] == 85
        assert payload["grade"] == "B"
        assert payload["report"]["agent_output"] == "Security review summary"
        assert payload["completed_at"]

    @patch("app.agents.compliance_review.save_state")
    @patch("app.agents.compliance_review.load_state", return_value={})
    @patch("app.agents.compliance_review.publish_event")
    @patch("app.agents.compliance_review.update_compliance_review")
    @patch("app.agents.compliance_review.create_compliance_review", return_value={"id": "comp-review-1"})
    @patch("app.agents.compliance_review.calculate_compliance_score_data", return_value=COMPLIANCE_SCORE)
    @patch("app.agents.compliance_review.create_react_agent")
    @patch("app.agents.compliance_review.get_tool_llm", return_value=MagicMock())
    @patch("app.agents.compliance_review.get_documents_for_vendor", return_value=[])
    @patch(
        "app.agents.compliance_review.get_vendor",
        return_value={
            "id": "vendor-1",
            "name": "Vendor One",
            "vendor_type": "technology",
            "domain": "example.com",
            "contract_value": 10000,
        },
    )
    def test_compliance_agent_creates_and_completes_its_own_review(
        self,
        mock_vendor,
        mock_documents,
        mock_tool_llm,
        mock_create_react_agent,
        mock_score,
        mock_create_review,
        mock_update_review,
        mock_publish,
        mock_load_state,
        mock_save_state,
    ):
        from app.agents.compliance_review import run_compliance_agent

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="Compliance review summary")]
        }
        mock_create_react_agent.return_value = mock_agent

        result = run_compliance_agent("vendor-1")

        assert result["status"] == "success"
        mock_create_review.assert_called_once()
        mock_update_review.assert_called_once()
        review_id, payload = mock_update_review.call_args.args
        assert review_id == "comp-review-1"
        assert payload["status"] == "completed"
        assert payload["overall_score"] == 78
        assert payload["grade"] == "C"
        assert payload["report"]["agent_output"] == "Compliance review summary"
        assert payload["completed_at"]

    @patch("app.agents.financial_review.save_state")
    @patch("app.agents.financial_review.load_state", return_value={})
    @patch("app.agents.financial_review.publish_event")
    @patch("app.agents.financial_review.update_financial_review")
    @patch("app.agents.financial_review.create_financial_review", return_value={"id": "fin-review-1"})
    @patch("app.agents.financial_review.calculate_financial_risk_score_data", return_value=FINANCIAL_SCORE)
    @patch("app.agents.financial_review.create_react_agent")
    @patch("app.agents.financial_review.get_tool_llm", return_value=MagicMock())
    @patch("app.agents.financial_review.get_documents_for_vendor", return_value=[])
    @patch(
        "app.agents.financial_review.get_vendor",
        return_value={
            "id": "vendor-1",
            "name": "Vendor One",
            "vendor_type": "technology",
            "domain": "example.com",
            "contract_value": 10000,
        },
    )
    def test_financial_agent_creates_and_completes_its_own_review(
        self,
        mock_vendor,
        mock_documents,
        mock_tool_llm,
        mock_create_react_agent,
        mock_score,
        mock_create_review,
        mock_update_review,
        mock_publish,
        mock_load_state,
        mock_save_state,
    ):
        from app.agents.financial_review import run_financial_agent

        mock_agent = MagicMock()
        mock_agent.invoke.return_value = {
            "messages": [SimpleNamespace(content="Financial review summary")]
        }
        mock_create_react_agent.return_value = mock_agent

        result = run_financial_agent("vendor-1")

        assert result["status"] == "success"
        mock_create_review.assert_called_once()
        mock_update_review.assert_called_once()
        review_id, payload = mock_update_review.call_args.args
        assert review_id == "fin-review-1"
        assert payload["status"] == "completed"
        assert payload["overall_score"] == 82
        assert payload["grade"] == "B"
        assert payload["report"]["agent_output"] == "Financial review summary"
        assert payload["completed_at"]


class TestApprovalWorkflowRepair:
    @patch("app.tools.approval_tools.create_audit_log")
    @patch("app.tools.approval_tools.update_vendor")
    @patch(
        "app.tools.approval_tools.db_create_approval",
        return_value={"id": "approval-1", "workflow_id": "workflow-1"},
    )
    @patch(
        "app.tools.approval_tools.db_get_approval_workflow",
        return_value={
            "id": "workflow-1",
            "name": "Manager Workflow",
            "approvers": [{"role": "manager"}],
            "approval_order": "parallel",
            "timeout_hours": 24,
        },
    )
    @patch(
        "app.tools.approval_tools.get_risk_assessment",
        return_value={
            "id": "risk-1",
            "overall_risk_score": 82,
            "risk_level": "low",
            "approval_tier": "manager",
            "critical_blockers": [],
            "conditional_items": [],
            "executive_summary": "Approved for manager review.",
        },
    )
    @patch(
        "app.tools.approval_tools.get_vendor",
        return_value={
            "id": "vendor-1",
            "name": "Vendor One",
            "vendor_type": "technology",
            "contract_value": 10000,
            "domain": "example.com",
        },
    )
    @patch("app.tools.approval_tools.get_approval_request", return_value=None)
    def test_create_approval_request_uses_db_workflow_lookup_when_workflow_id_present(
        self,
        mock_existing,
        mock_vendor,
        mock_risk,
        mock_db_workflow,
        mock_create_approval,
        mock_update_vendor,
        mock_audit,
    ):
        from app.tools.approval_tools import create_approval_request_data

        result = create_approval_request_data(
            vendor_id="vendor-1",
            approval_tier="manager",
            workflow_id="workflow-1",
        )

        assert result["id"] == "approval-1"
        mock_db_workflow.assert_called_once_with("workflow-1")
        payload = mock_create_approval.call_args.args[0]
        assert payload["workflow_id"] == "workflow-1"
        assert payload["approval_tier"] == "manager"
        assert payload["required_approvers"] == [{"role": "manager"}]


class TestGraphWorkflowRepair:
    @patch("app.agents.graph.save_state")
    @patch("app.agents.graph.load_state", return_value={})
    @patch("app.agents.graph.publish_event")
    @patch("app.agents.graph.create_audit_log")
    @patch("app.agents.graph.update_vendor")
    @patch("app.agents.graph.run_supervisor", return_value={"status": "success", "approval_status": "pending"})
    @patch(
        "app.agents.graph.run_approval_orchestrator",
        return_value={"status": "success", "approval_tier": "manager", "current_status": "pending"},
    )
    @patch(
        "app.agents.graph.run_risk_assessment_agent",
        return_value={"status": "success", "overall_risk_score": 82, "risk_level": "low"},
    )
    @patch("app.agents.graph.run_evidence_coordinator", return_value={"status": "success"})
    @patch("app.agents.graph.run_financial_agent", return_value={"status": "success", "overall_score": 82, "grade": "B"})
    @patch("app.agents.graph.run_compliance_agent", return_value={"status": "success", "overall_score": 78, "grade": "C"})
    @patch("app.agents.graph.run_security_agent", return_value={"status": "success", "overall_score": 85, "grade": "B"})
    @patch("app.agents.graph.run_intake_agent", return_value={"status": "success", "files_processed": 1})
    def test_graph_workflow_reaches_risk_assessment_after_reviews(
        self,
        mock_intake,
        mock_security,
        mock_compliance,
        mock_financial,
        mock_evidence,
        mock_risk,
        mock_approval,
        mock_supervisor,
        mock_update_vendor,
        mock_audit,
        mock_publish,
        mock_load_state,
        mock_save_state,
    ):
        from app.agents.graph import run_full_workflow

        result = run_full_workflow(
            vendor_id="vendor-1",
            vendor_name="Vendor One",
            vendor_type="technology",
            contract_value=10000,
            vendor_domain="example.com",
            file_paths=["doc.pdf"],
        )

        assert result["status"] == "success"
        assert result["risk_assessment_result"]["status"] == "success"
        mock_security.assert_called_once_with("vendor-1")
        mock_compliance.assert_called_once_with("vendor-1")
        mock_financial.assert_called_once_with("vendor-1")
        mock_risk.assert_called_once_with("vendor-1")
