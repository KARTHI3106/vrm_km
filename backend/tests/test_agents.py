"""
Agent behavior tests for the Phase 3 workflow (v2 — post-refactor).

Validates:
  - Tool registration across all agent modules
  - Agent factory functions
  - Graph structure with the FIXED topology:
    intake → [security, compliance, financial] → supervisor → evidence →
    risk → approval → supervisor_final → END
"""
from unittest.mock import MagicMock, patch


class TestToolRegistration:
    def test_intake_tools_registered(self):
        from app.tools.intake_tools import INTAKE_TOOLS

        assert len(INTAKE_TOOLS) == 8
        assert {tool.name for tool in INTAKE_TOOLS} >= {
            "parse_pdf",
            "parse_docx",
            "parse_excel",
            "classify_document",
            "extract_vendor_metadata",
            "extract_dates",
            "store_document_metadata",
            "ocr_scan",
        }

    def test_security_tools_registered(self):
        from app.tools.security_tools import SECURITY_TOOLS

        assert len(SECURITY_TOOLS) == 10
        assert {tool.name for tool in SECURITY_TOOLS} >= {
            "search_security_policies",
            "validate_soc2_certificate",
            "validate_iso27001_certificate",
            "check_certificate_expiry",
            "scan_domain_security",
            "check_breach_history",
            "analyze_security_questionnaire",
            "calculate_security_score",
            "generate_security_report",
            "flag_critical_issues",
        }

    def test_supervisor_tools_registered(self):
        from app.tools.supervisor_tools import SUPERVISOR_TOOLS

        assert len(SUPERVISOR_TOOLS) == 6
        assert {tool.name for tool in SUPERVISOR_TOOLS} >= {
            "delegate_to_security_agent",
            "delegate_to_compliance_agent",
            "delegate_to_financial_agent",
            "delegate_to_evidence_agent",
            "compile_approval_packet",
            "get_worker_status",
        }

    def test_phase3_tools_registered(self):
        from app.tools.approval_tools import APPROVAL_TOOLS
        from app.tools.risk_tools import RISK_TOOLS

        assert len(RISK_TOOLS) == 8
        assert len(APPROVAL_TOOLS) == 9

    def test_security_deterministic_scoring_exists(self):
        """Verify calculate_security_score_data is importable."""
        from app.tools.security_tools import calculate_security_score_data
        assert callable(calculate_security_score_data)

    def test_compliance_deterministic_scoring_exists(self):
        """Verify calculate_compliance_score_data is importable."""
        from app.tools.compliance_tools import calculate_compliance_score_data
        assert callable(calculate_compliance_score_data)

    def test_financial_deterministic_scoring_exists(self):
        """Verify calculate_financial_risk_score_data is importable."""
        from app.tools.financial_tools import calculate_financial_risk_score_data
        assert callable(calculate_financial_risk_score_data)


class TestAgentCreation:
    @patch("app.agents.document_intake.get_tool_llm")
    def test_intake_agent_creation(self, mock_llm):
        from app.agents.document_intake import create_intake_agent

        mock_llm.return_value = MagicMock()
        assert create_intake_agent is not None

    @patch("app.agents.risk_assessment.get_tool_llm")
    def test_risk_agent_creation(self, mock_llm):
        from app.agents.risk_assessment import create_risk_assessment_agent

        mock_llm.return_value = MagicMock()
        assert create_risk_assessment_agent is not None

    @patch("app.agents.approval_orchestrator.get_tool_llm")
    def test_approval_agent_creation(self, mock_llm):
        from app.agents.approval_orchestrator import create_approval_orchestrator_agent

        mock_llm.return_value = MagicMock()
        assert create_approval_orchestrator_agent is not None


class TestGraphStructure:
    def test_graph_builds(self):
        from app.agents.graph import build_workflow_graph

        graph = build_workflow_graph()
        assert graph is not None

    def test_graph_has_phase3_nodes(self):
        from app.agents.graph import build_workflow_graph

        graph = build_workflow_graph()
        node_names = set(graph.nodes.keys())
        assert node_names >= {
            "intake_node",
            "security_node",
            "compliance_node",
            "financial_node",
            "supervisor_aggregate_node",
            "evidence_node",
            "risk_assessment_node",
            "approval_orchestrator_node",
            "supervisor_final_node",
        }

    def test_graph_state_has_shared_context(self):
        """GraphState should include shared_review_context field."""
        from app.agents.graph import GraphState

        annotations = GraphState.__annotations__
        assert "shared_review_context" in annotations

    def test_evidence_runs_after_supervisor_aggregate(self):
        """CRITICAL: evidence_node must come AFTER supervisor_aggregate_node,
        not before the parallel review agents."""
        from app.agents.graph import build_workflow_graph

        graph = build_workflow_graph()

        # supervisor_aggregate_node should have an edge to evidence_node
        # Evidence should NOT have edges to security/compliance/financial
        edges = graph.edges
        found_agg_to_evidence = False
        found_evidence_to_review = False

        for edge in edges:
            source = edge[0] if isinstance(edge, tuple) else str(edge)
            target = edge[1] if isinstance(edge, tuple) else None
            if source == "supervisor_aggregate_node" and target == "evidence_node":
                found_agg_to_evidence = True
            if source == "evidence_node" and target in (
                "security_node",
                "compliance_node",
                "financial_node",
            ):
                found_evidence_to_review = True

        assert found_agg_to_evidence, (
            "supervisor_aggregate_node → evidence_node edge must exist"
        )
        assert not found_evidence_to_review, (
            "evidence_node MUST NOT have edges to review agents "
            "(that was the critical bug)"
        )

    def test_review_agents_fan_in_to_supervisor(self):
        """All three review nodes should fan-in to supervisor_aggregate_node."""
        from app.agents.graph import build_workflow_graph

        graph = build_workflow_graph()
        edges = graph.edges

        fan_in_sources = set()
        for edge in edges:
            if isinstance(edge, tuple) and edge[1] == "supervisor_aggregate_node":
                fan_in_sources.add(edge[0])

        assert "security_node" in fan_in_sources
        assert "compliance_node" in fan_in_sources
        assert "financial_node" in fan_in_sources
