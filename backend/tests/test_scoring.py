"""
Tests for deterministic scoring functions across all three review domains.

These functions are the core of the Hybrid Pattern — they guarantee
reproducible scores regardless of LLM variance.
"""

import pytest

from app.tools.security_tools import calculate_security_score_data
from app.tools.compliance_tools import calculate_compliance_score_data
from app.tools.financial_tools import calculate_financial_risk_score_data


# ═══════════════════════════════════════════════════════════════════
# Security Scoring
# ═══════════════════════════════════════════════════════════════════


class TestSecurityScoring:
    """Tests for calculate_security_score_data()."""

    def test_perfect_score_all_certs_no_breaches(self):
        """SOC2 + ISO27001, perfect domain, no breaches → near 100."""
        tool_outputs = {
            "soc2_validation": {"is_valid_format": True, "report_type": "Type 2"},
            "iso27001_validation": {"is_valid_format": True},
            "certificate_expiry": {"expiry_status": "valid"},
            "domain_scan": {"score": 95, "ssl": {"valid": True}},
            "breach_history": {"total_breaches_found": 0},
            "questionnaire_analysis": {"overall_score": 90},
        }
        result = calculate_security_score_data(tool_outputs)
        assert result["overall_score"] >= 90
        assert result["grade"] == "A"
        assert result["risk_level"] == "low"
        assert result["critical_flags"] == []

    def test_no_certs_submitted(self):
        """No certificates → 0 for certificate component (40% weight)."""
        tool_outputs = {
            "soc2_validation": {},
            "iso27001_validation": {},
            "certificate_expiry": {},
            "domain_scan": {"score": 80, "ssl": {"valid": True}},
            "breach_history": {"total_breaches_found": 0},
            "questionnaire_analysis": {"overall_score": 70},
        }
        result = calculate_security_score_data(tool_outputs)
        # cert=0 (40%), domain=80 (30%), breach=100 (20%), quest=70 (10%)
        # => 0 + 24 + 20 + 7 = 51
        assert result["overall_score"] == 51.0
        assert result["breakdown"]["certificates"]["score"] == 0.0

    def test_expired_certificate_penalty(self):
        """Expired certificates halve the cert score."""
        tool_outputs = {
            "soc2_validation": {"is_valid_format": True, "report_type": "Type 2"},
            "iso27001_validation": {"is_valid_format": True},
            "certificate_expiry": {"expiry_status": "expired"},
            "domain_scan": {"score": 80},
            "breach_history": {"total_breaches_found": 0},
            "questionnaire_analysis": {"overall_score": 80},
        }
        result = calculate_security_score_data(tool_outputs)
        # cert=100*0.5=50, so weighted=50*0.4=20
        assert result["breakdown"]["certificates"]["score"] == 50.0
        assert "Security certificate expired" in result["critical_flags"]

    def test_multiple_breaches_critical_flag(self):
        """3+ breaches → score 0 for breach component + critical flag."""
        tool_outputs = {
            "soc2_validation": {"is_valid_format": True},
            "iso27001_validation": {},
            "certificate_expiry": {},
            "domain_scan": {"score": 60},
            "breach_history": {"total_breaches_found": 5},
            "questionnaire_analysis": {"overall_score": 50},
        }
        result = calculate_security_score_data(tool_outputs)
        assert result["breakdown"]["breach_history"]["score"] == 0.0
        assert "Multiple data breaches detected (3+)" in result["critical_flags"]

    def test_ssl_failure_critical_flag(self):
        """Invalid SSL triggers a critical flag."""
        tool_outputs = {
            "domain_scan": {"score": 20, "ssl": {"valid": False}},
            "breach_history": {"total_breaches_found": 0},
        }
        result = calculate_security_score_data(tool_outputs)
        assert "SSL/TLS validation failed" in result["critical_flags"]

    def test_empty_inputs_returns_safe_defaults(self):
        """Completely empty tool outputs produce valid structure."""
        result = calculate_security_score_data({})
        assert "overall_score" in result
        assert "grade" in result
        assert result["overall_score"] >= 0
        assert result["overall_score"] <= 100

    def test_soc2_only_cert_score(self):
        """SOC2 only → cert base = 70, domain default = 0."""
        tool_outputs = {
            "soc2_validation": {"report_type": "Type 2"},
            "iso27001_validation": {},
            "certificate_expiry": {"expiry_status": "valid"},
            "domain_scan": {},
            "breach_history": {"total_breaches_found": 0},
            "questionnaire_analysis": {},
        }
        result = calculate_security_score_data(tool_outputs)
        assert result["breakdown"]["certificates"]["score"] == 70.0

    def test_one_breach_score(self):
        """One breach → breach score = 60."""
        tool_outputs = {
            "breach_history": {"total_breaches_found": 1},
        }
        result = calculate_security_score_data(tool_outputs)
        assert result["breakdown"]["breach_history"]["score"] == 60.0


# ═══════════════════════════════════════════════════════════════════
# Compliance Scoring
# ═══════════════════════════════════════════════════════════════════


class TestComplianceScoring:
    """Tests for calculate_compliance_score_data()."""

    def test_perfect_compliance(self):
        """All frameworks at 100 → overall 100."""
        tool_outputs = {
            "gdpr_check": {"score": 100, "overall_compliance": "compliant"},
            "hipaa_check": {"score": 100, "overall_compliance": "compliant"},
            "pci_check": {"score": 100},
            "dpa_verification": {"completeness_score": 100, "is_valid_dpa": True},
            "privacy_policy": {"completeness_score": 100},
        }
        result = calculate_compliance_score_data(tool_outputs)
        assert result["overall_score"] == 100.0
        assert result["grade"] == "A"
        assert result["critical_flags"] == []

    def test_gdpr_non_compliant_flag(self):
        """GDPR non-compliance triggers a critical flag."""
        tool_outputs = {
            "gdpr_check": {"score": 20, "overall_compliance": "non_compliant"},
            "hipaa_check": {},
            "pci_check": {},
            "dpa_verification": {},
            "privacy_policy": {},
        }
        result = calculate_compliance_score_data(tool_outputs)
        assert "GDPR non-compliance detected" in result["critical_flags"]

    def test_dpa_invalid_flag(self):
        """Invalid DPA triggers a flag."""
        tool_outputs = {
            "dpa_verification": {"completeness_score": 30, "is_valid_dpa": False},
        }
        result = calculate_compliance_score_data(tool_outputs)
        assert "Data Processing Agreement incomplete or invalid" in result["critical_flags"]

    def test_zero_across_board(self):
        """All zeros → overall 0."""
        result = calculate_compliance_score_data({})
        assert result["overall_score"] == 0.0
        assert result["grade"] == "F"

    def test_weight_distribution(self):
        """Verify weights: GDPR=30%, HIPAA=20%, PCI=15%, DPA=20%, Privacy=15%."""
        tool_outputs = {
            "gdpr_check": {"score": 100},
            "hipaa_check": {"score": 0},
            "pci_check": {"score": 0},
            "dpa_verification": {"completeness_score": 0},
            "privacy_policy": {"completeness_score": 0},
        }
        result = calculate_compliance_score_data(tool_outputs)
        assert result["overall_score"] == 30.0  # 100 * 0.30


# ═══════════════════════════════════════════════════════════════════
# Financial Scoring
# ═══════════════════════════════════════════════════════════════════


class TestFinancialScoring:
    """Tests for calculate_financial_risk_score_data()."""

    def test_perfect_financial(self):
        """All components at max → near 100."""
        tool_outputs = {
            "insurance_verification": {"adequacy_score": 100},
            "credit_rating": {"credit_rating": "AAA"},
            "financial_statements": {"stability_score": 100},
            "bcp_verification": {"completeness_score": 100},
            "bankruptcy_check": {"bankruptcy_found": False},
        }
        result = calculate_financial_risk_score_data(tool_outputs)
        assert result["overall_score"] >= 95
        assert result["grade"] == "A"
        assert result["critical_flags"] == []

    def test_bankruptcy_found_flag(self):
        """Bankruptcy triggers two critical flags."""
        tool_outputs = {
            "insurance_verification": {"adequacy_score": 50},
            "credit_rating": {"credit_rating": "B"},
            "financial_statements": {"stability_score": 30},
            "bcp_verification": {"completeness_score": 20},
            "bankruptcy_check": {
                "bankruptcy_found": True,
                "active_proceedings": True,
            },
        }
        result = calculate_financial_risk_score_data(tool_outputs)
        assert "Bankruptcy records found" in result["critical_flags"]
        assert "Active bankruptcy proceedings" in result["critical_flags"]

    def test_no_insurance_flag(self):
        """Zero insurance → critical flag."""
        tool_outputs = {
            "insurance_verification": {"adequacy_score": 0},
            "credit_rating": {"credit_rating": "A"},
            "financial_statements": {"stability_score": 80},
            "bcp_verification": {"completeness_score": 60},
            "bankruptcy_check": {"bankruptcy_found": False},
        }
        result = calculate_financial_risk_score_data(tool_outputs)
        assert "No insurance coverage verified" in result["critical_flags"]

    def test_credit_rating_mapping(self):
        """AAA=100, BBB=70, D=0."""
        for rating, expected in [("AAA", 100), ("BBB", 70), ("D", 0)]:
            tool_outputs = {
                "credit_rating": {"credit_rating": rating},
            }
            result = calculate_financial_risk_score_data(tool_outputs)
            assert result["breakdown"]["credit_rating"]["score"] == expected, \
                f"Rating {rating} should map to {expected}"

    def test_empty_gives_defaults(self):
        """Empty tool outputs use safe defaults (50 for credit & stability)."""
        result = calculate_financial_risk_score_data({})
        assert result["overall_score"] > 0
        assert result["breakdown"]["credit_rating"]["score"] == 50.0
        assert result["breakdown"]["financial_stability"]["score"] == 50.0

    def test_weight_distribution(self):
        """Verify weights: insurance=35%, credit=30%, stability=25%, bcp=10%."""
        tool_outputs = {
            "insurance_verification": {"adequacy_score": 100},
            "credit_rating": {"credit_rating": "D"},  # 0
            "financial_statements": {"stability_score": 0},
            "bcp_verification": {"completeness_score": 0},
            "bankruptcy_check": {"bankruptcy_found": False},
        }
        result = calculate_financial_risk_score_data(tool_outputs)
        assert result["overall_score"] == 35.0  # 100 * 0.35
