"""
Risk Assessment Agent tools.

The LangGraph agent can still use these as tools, but the core logic is
deterministic so risk assessments can complete even when the LLM layer is
offline or unavailable.
"""
from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.tools import tool

from app.core.db import (
    get_compliance_review,
    get_evidence_requests,
    get_financial_review,
    get_security_review,
    get_vendor,
)
from app.core.llm import get_llm

logger = logging.getLogger(__name__)

DEFAULT_WEIGHTS = {
    "security": 0.40,
    "compliance": 0.35,
    "financial": 0.25,
}


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return default


def _normalize_weights(weights: dict[str, float]) -> dict[str, float]:
    total = sum(max(value, 0.0) for value in weights.values())
    if total <= 0:
        return DEFAULT_WEIGHTS.copy()
    return {key: round(max(value, 0.0) / total, 4) for key, value in weights.items()}


def _risk_level(score: float) -> str:
    if score >= 80:
        return "low"
    if score >= 60:
        return "medium"
    if score >= 40:
        return "high"
    return "critical"


def _score_color(score: float) -> str:
    if score >= 80:
        return "green"
    if score >= 60:
        return "yellow"
    if score >= 40:
        return "orange"
    return "red"


def _review_data(vendor_id: str) -> tuple[dict, dict, dict, dict, list[dict]]:
    vendor = get_vendor(vendor_id) or {}
    security = get_security_review(vendor_id) or {}
    compliance = get_compliance_review(vendor_id) or {}
    financial = get_financial_review(vendor_id) or {}
    evidence = get_evidence_requests(vendor_id) or []
    return vendor, security, compliance, financial, evidence


def derive_risk_weights(vendor_id: str) -> dict[str, float]:
    vendor, _, compliance, _, _ = _review_data(vendor_id)
    weights = DEFAULT_WEIGHTS.copy()
    vendor_type = str(vendor.get("vendor_type", "")).lower()
    regulations = [str(item).lower() for item in compliance.get("applicable_regulations", [])]

    if vendor_type in {"saas", "technology", "infrastructure", "data_processor"}:
        weights["security"] += 0.05
        weights["compliance"] += 0.05
        weights["financial"] -= 0.10
    elif vendor_type in {"consulting", "services"}:
        weights["compliance"] += 0.05
        weights["security"] -= 0.02
        weights["financial"] -= 0.03

    if regulations:
        weights["compliance"] += 0.05
        weights["financial"] -= 0.05

    return _normalize_weights(weights)


def aggregate_findings_data(vendor_id: str) -> dict[str, Any]:
    vendor, security, compliance, financial, evidence = _review_data(vendor_id)

    pending_evidence = [item for item in evidence if item.get("status") == "pending"]
    received_evidence = [item for item in evidence if item.get("status") == "received"]

    common_themes: list[str] = []
    all_recommendations = [
        *security.get("recommendations", []),
        *compliance.get("recommendations", []),
        *financial.get("recommendations", []),
    ]

    text_blob = " ".join(str(item).lower() for item in all_recommendations)
    if "certificate" in text_blob or "expiry" in text_blob or "expire" in text_blob:
        common_themes.append("Certificate hygiene requires attention.")
    if "missing" in text_blob or "document" in text_blob or pending_evidence:
        common_themes.append("Documentation gaps remain open.")
    if "policy" in text_blob or compliance.get("gaps"):
        common_themes.append("Policy and compliance alignment is incomplete.")
    if _safe_float(financial.get("overall_score"), 100.0) < 70:
        common_themes.append("Financial resilience should be monitored.")

    return {
        "vendor_id": vendor_id,
        "vendor_name": vendor.get("name"),
        "security": {
            "score": _safe_float(security.get("overall_score")),
            "grade": security.get("grade", "N/A"),
            "findings_count": len(security.get("findings", [])),
            "findings": security.get("findings", []),
            "critical_issues": security.get("critical_issues", []),
            "recommendations": security.get("recommendations", []),
            "component_scores": {
                "certificates": _safe_float(security.get("certificate_score")),
                "domain_security": _safe_float(security.get("domain_security_score")),
                "breach_history": _safe_float(security.get("breach_history_score")),
                "questionnaire": _safe_float(security.get("questionnaire_score")),
            },
        },
        "compliance": {
            "score": _safe_float(compliance.get("overall_score")),
            "grade": compliance.get("grade", "N/A"),
            "findings_count": len(compliance.get("findings", [])),
            "findings": compliance.get("findings", []),
            "gaps": compliance.get("gaps", []),
            "applicable_regulations": compliance.get("applicable_regulations", []),
            "recommendations": compliance.get("recommendations", []),
            "component_scores": {
                "gdpr": _safe_float(compliance.get("gdpr_score")),
                "hipaa": _safe_float(compliance.get("hipaa_score")),
                "pci": _safe_float(compliance.get("pci_score")),
                "dpa": _safe_float(compliance.get("dpa_score")),
                "privacy_policy": _safe_float(compliance.get("privacy_policy_score")),
            },
        },
        "financial": {
            "score": _safe_float(financial.get("overall_score")),
            "grade": financial.get("grade", "N/A"),
            "findings_count": len(financial.get("findings", [])),
            "findings": financial.get("findings", []),
            "recommendations": financial.get("recommendations", []),
            "component_scores": {
                "insurance": _safe_float(financial.get("insurance_score")),
                "credit_rating": _safe_float(financial.get("credit_rating_score")),
                "financial_stability": _safe_float(financial.get("financial_stability_score")),
                "bcp": _safe_float(financial.get("bcp_score")),
            },
        },
        "evidence_gaps": {
            "total": len(evidence),
            "pending": len(pending_evidence),
            "received": len(received_evidence),
            "items": evidence,
        },
        "common_themes": common_themes,
    }


def calculate_overall_risk_score_data(
    vendor_id: str,
    security_score: float,
    compliance_score: float,
    financial_score: float,
    security_weight: float | None = None,
    compliance_weight: float | None = None,
    financial_weight: float | None = None,
) -> dict[str, Any]:
    if (
        security_weight is None
        or compliance_weight is None
        or financial_weight is None
        or (security_weight, compliance_weight, financial_weight) == (0.40, 0.35, 0.25)
    ):
        weights = derive_risk_weights(vendor_id)
    else:
        weights = _normalize_weights(
            {
                "security": security_weight,
                "compliance": compliance_weight,
                "financial": financial_weight,
            }
        )

    overall = round(
        (_safe_float(security_score) * weights["security"])
        + (_safe_float(compliance_score) * weights["compliance"])
        + (_safe_float(financial_score) * weights["financial"]),
        2,
    )

    return {
        "vendor_id": vendor_id,
        "overall_risk_score": overall,
        "risk_level": _risk_level(overall),
        "breakdown": {
            "security": {
                "score": _safe_float(security_score),
                "weight": weights["security"],
                "weighted": round(_safe_float(security_score) * weights["security"], 2),
            },
            "compliance": {
                "score": _safe_float(compliance_score),
                "weight": weights["compliance"],
                "weighted": round(_safe_float(compliance_score) * weights["compliance"], 2),
            },
            "financial": {
                "score": _safe_float(financial_score),
                "weight": weights["financial"],
                "weighted": round(_safe_float(financial_score) * weights["financial"], 2),
            },
        },
    }


def identify_critical_blockers_data(vendor_id: str) -> list[dict[str, Any]]:
    _, security, compliance, financial, evidence = _review_data(vendor_id)
    blockers: list[dict[str, Any]] = []

    for issue in security.get("critical_issues", []):
        blockers.append(
            {
                "domain": "security",
                "severity": issue.get("severity", "critical"),
                "title": issue.get("title", "Critical security issue"),
                "description": issue.get("description", str(issue)),
                "impact": "Vendor approval should pause until this issue is resolved.",
            }
        )

    if _safe_float(security.get("certificate_score"), 100.0) == 0 and security:
        blockers.append(
            {
                "domain": "security",
                "severity": "critical",
                "title": "Certificate evidence unavailable or expired",
                "description": "The security review did not produce a valid certificate score.",
                "impact": "Independent security assurance could not be confirmed.",
            }
        )

    if _safe_float(security.get("overall_score"), 100.0) < 30:
        blockers.append(
            {
                "domain": "security",
                "severity": "critical",
                "title": "Security posture below minimum threshold",
                "description": f"Security score is {_safe_float(security.get('overall_score'))}/100.",
                "impact": "Risk remains too high for onboarding.",
            }
        )

    for gap in compliance.get("gaps", []):
        severity = str(gap.get("severity", "")).lower()
        criticality = str(gap.get("criticality", "")).lower()
        if severity == "critical" or criticality == "required":
            blockers.append(
                {
                    "domain": "compliance",
                    "severity": "critical",
                    "title": gap.get("requirement") or gap.get("document_type") or "Critical compliance gap",
                    "description": gap.get("description", str(gap)),
                    "impact": "Onboarding would create legal or regulatory exposure.",
                }
            )

    if _safe_float(compliance.get("overall_score"), 100.0) < 30:
        blockers.append(
            {
                "domain": "compliance",
                "severity": "critical",
                "title": "Compliance coverage below minimum threshold",
                "description": f"Compliance score is {_safe_float(compliance.get('overall_score'))}/100.",
                "impact": "Required control coverage is materially incomplete.",
            }
        )

    findings_text = " ".join(
        str(item).lower()
        for item in financial.get("findings", []) + financial.get("recommendations", [])
    )
    if any(term in findings_text for term in ("bankrupt", "insolvent", "liquidation")):
        blockers.append(
            {
                "domain": "financial",
                "severity": "critical",
                "title": "Financial distress indicators detected",
                "description": "Financial review output references insolvency or bankruptcy-related concerns.",
                "impact": "Vendor continuity cannot be relied upon.",
            }
        )

    if _safe_float(financial.get("overall_score"), 100.0) < 20:
        blockers.append(
            {
                "domain": "financial",
                "severity": "critical",
                "title": "Financial resilience below minimum threshold",
                "description": f"Financial score is {_safe_float(financial.get('overall_score'))}/100.",
                "impact": "Vendor delivery risk is unacceptably high.",
            }
        )

    for request in evidence:
        if request.get("criticality") == "required" and request.get("status") == "pending":
            blockers.append(
                {
                    "domain": "evidence",
                    "severity": "high",
                    "title": f"Missing required evidence: {request.get('document_type', 'Unknown')}",
                    "description": request.get("reason", "Required evidence remains outstanding."),
                    "impact": "Risk review cannot be closed with missing required evidence.",
                }
            )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for blocker in blockers:
        key = (blocker["domain"], blocker["title"])
        if key not in seen:
            seen.add(key)
            deduped.append(blocker)
    return deduped


def identify_conditional_approvals_data(vendor_id: str) -> list[dict[str, Any]]:
    _, security, compliance, financial, evidence = _review_data(vendor_id)
    conditions: list[dict[str, Any]] = []

    security_score = _safe_float(security.get("overall_score"))
    if 40 <= security_score < 80:
        conditions.append(
            {
                "domain": "security",
                "condition": "Raise security posture to the approved operating threshold.",
                "description": f"Current security score is {security_score}/100.",
                "deadline_days": 90,
                "priority": "high" if security_score < 60 else "medium",
            }
        )

    certificate_score = _safe_float(security.get("certificate_score"), 100.0)
    if 0 < certificate_score < 75:
        conditions.append(
            {
                "domain": "security",
                "condition": "Renew or refresh independent security assurance artifacts.",
                "description": "Certificate evidence appears close to expiry or incomplete.",
                "deadline_days": 30,
                "priority": "high",
            }
        )

    for gap in compliance.get("gaps", []):
        severity = str(gap.get("severity", "")).lower()
        criticality = str(gap.get("criticality", "")).lower()
        if severity not in {"critical", "high"} and criticality != "required":
            conditions.append(
                {
                    "domain": "compliance",
                    "condition": gap.get("requirement") or gap.get("document_type") or "Remediate compliance gap",
                    "description": gap.get("description", str(gap)),
                    "deadline_days": 60,
                    "priority": "medium",
                }
            )

    for request in evidence:
        if request.get("criticality") in {"recommended", "optional"} and request.get("status") == "pending":
            conditions.append(
                {
                    "domain": "evidence",
                    "condition": f"Submit {request.get('document_type', 'recommended evidence')}",
                    "description": request.get("reason", "Requested supporting evidence is still pending."),
                    "deadline_days": 90,
                    "priority": "low",
                }
            )

    if 40 <= _safe_float(financial.get("overall_score")) < 70:
        conditions.append(
            {
                "domain": "financial",
                "condition": "Provide refreshed proof of financial stability or insurance coverage.",
                "description": "Financial review indicates moderate risk that should be monitored post-approval.",
                "deadline_days": 60,
                "priority": "medium",
            }
        )

    deduped: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for condition in conditions:
        key = (condition["domain"], condition["condition"])
        if key not in seen:
            seen.add(key)
            deduped.append(condition)
    return deduped


def generate_executive_summary_data(
    vendor_id: str,
    overall_score: float,
    risk_level: str,
    blockers: list[dict[str, Any]],
    conditions: list[dict[str, Any]],
) -> str:
    vendor, security, compliance, financial, _ = _review_data(vendor_id)
    recommendation = (
        "reject"
        if blockers
        else "conditional approval"
        if conditions
        else "approve"
    )

    prompt = f"""Write a concise executive summary for a vendor risk assessment.

Vendor: {vendor.get('name', 'Unknown')}
Vendor type: {vendor.get('vendor_type', 'Unknown')}
Contract value: ${_safe_float(vendor.get('contract_value')):,.2f}
Overall score: {overall_score}/100
Risk level: {risk_level}
Security score: {_safe_float(security.get('overall_score'))}/100
Compliance score: {_safe_float(compliance.get('overall_score'))}/100
Financial score: {_safe_float(financial.get('overall_score'))}/100
Critical blockers: {len(blockers)}
Conditional items: {len(conditions)}
Recommendation: {recommendation}

Write 1-2 short paragraphs in clear leadership language.
"""

    try:
        summary = get_llm().invoke(prompt)
        content = summary.content if hasattr(summary, "content") else str(summary)
        if content and content.strip():
            return content.strip()
    except Exception as exc:
        logger.warning("Executive summary generation failed for %s: %s", vendor_id, exc)

    first_sentence = (
        f"{vendor.get('name', 'This vendor')} completed assessment with an overall risk score of "
        f"{overall_score}/100, which maps to {risk_level} risk."
    )
    if blockers:
        second_sentence = (
            f"{len(blockers)} blocking issue(s) remain open, so the current recommendation is to reject "
            "or hold approval until remediation is verified."
        )
    elif conditions:
        second_sentence = (
            f"The review supports conditional approval with {len(conditions)} follow-up requirement(s) "
            "to be completed within defined timeframes."
        )
    else:
        second_sentence = "No blocking issues were identified and the vendor can proceed through approval."
    return f"{first_sentence} {second_sentence}"


def recommend_approval_tier_data(
    vendor_id: str,
    overall_score: float,
    blockers: list[dict[str, Any]],
) -> dict[str, Any]:
    vendor, _, compliance, _, _ = _review_data(vendor_id)
    vendor_type = str(vendor.get("vendor_type", "")).lower()
    contract_value = _safe_float(vendor.get("contract_value"))
    sensitive_vendor = vendor_type in {"saas", "technology", "data_processor", "infrastructure"}
    regulations = compliance.get("applicable_regulations", [])

    if overall_score >= 90:
        tier = "auto_approve"
    elif overall_score >= 80:
        tier = "manager"
    elif overall_score >= 60:
        tier = "vp"
    elif overall_score >= 40:
        tier = "executive"
    else:
        tier = "board"

    rationale = [f"Base tier derived from overall score {overall_score}/100."]

    if blockers and tier == "auto_approve":
        tier = "manager"
        rationale.append("Auto-approval is disallowed when blockers exist.")

    if contract_value >= 1_000_000 and tier != "board":
        tier = "board" if overall_score < 60 else "executive"
        rationale.append("Contract value triggered executive escalation.")
    elif contract_value >= 500_000 and tier in {"auto_approve", "manager"}:
        tier = "vp"
        rationale.append("Contract value triggered VP review.")

    if sensitive_vendor and tier == "manager":
        tier = "vp"
        rationale.append("Sensitive vendor type requires VP oversight.")

    if regulations and tier == "auto_approve":
        tier = "manager"
        rationale.append("Applicable regulations require a human approval step.")

    return {
        "vendor_id": vendor_id,
        "recommended_tier": tier,
        "rationale": rationale,
        "factors": {
            "overall_score": overall_score,
            "contract_value": contract_value,
            "vendor_type": vendor_type,
            "has_blockers": bool(blockers),
            "applicable_regulations": regulations,
        },
    }


def create_risk_matrix_data(vendor_id: str) -> dict[str, Any]:
    aggregated = aggregate_findings_data(vendor_id)
    dimensions = []

    for name, key in (
        ("Security", "security"),
        ("Compliance", "compliance"),
        ("Financial", "financial"),
    ):
        section = aggregated[key]
        score = _safe_float(section.get("score"))
        dimensions.append(
            {
                "name": name,
                "score": score,
                "color": _score_color(score),
                "sub_scores": [
                    {
                        "name": sub_name.replace("_", " ").title(),
                        "score": _safe_float(sub_score),
                        "color": _score_color(_safe_float(sub_score)),
                    }
                    for sub_name, sub_score in section.get("component_scores", {}).items()
                ],
            }
        )

    return {"vendor_id": vendor_id, "dimensions": dimensions}


def generate_mitigation_recommendations_data(vendor_id: str) -> list[dict[str, Any]]:
    blockers = identify_critical_blockers_data(vendor_id)
    conditions = identify_conditional_approvals_data(vendor_id)
    findings = [
        f"[{item['domain']}] {item['title']}: {item['description']}"
        for item in blockers
    ] + [
        f"[{item['domain']}] {item['condition']}: {item['description']}"
        for item in conditions
    ]

    if not findings:
        return [
            {
                "priority": "low",
                "title": "Maintain standard vendor monitoring",
                "description": "No material remediation items were identified in the current assessment.",
                "implementation": "Review the vendor during the next scheduled reassessment cycle.",
            }
        ]

    prompt = (
        "Generate 3 to 5 prioritized mitigation recommendations as JSON. "
        "Each item must include priority, title, description, and implementation.\n\n"
        + "\n".join(findings[:12])
    )

    try:
        response = get_llm().invoke(prompt)
        content = response.content if hasattr(response, "content") else str(response)
        start = content.find("[")
        end = content.rfind("]") + 1
        if start >= 0 and end > start:
            parsed = json.loads(content[start:end])
            if isinstance(parsed, list) and parsed:
                return parsed
    except Exception as exc:
        logger.warning("Mitigation generation failed for %s: %s", vendor_id, exc)

    recommendations = []
    for blocker in blockers[:3]:
        recommendations.append(
            {
                "priority": "critical" if blocker["severity"] == "critical" else "high",
                "title": blocker["title"],
                "description": blocker["description"],
                "implementation": "Resolve the issue and attach verified evidence before final approval.",
            }
        )
    for condition in conditions[:2]:
        recommendations.append(
            {
                "priority": condition["priority"],
                "title": condition["condition"],
                "description": condition["description"],
                "implementation": f"Track remediation and confirm completion within {condition['deadline_days']} days.",
            }
        )
    return recommendations


def build_risk_assessment_result(vendor_id: str) -> dict[str, Any]:
    aggregated = aggregate_findings_data(vendor_id)
    scoring = calculate_overall_risk_score_data(
        vendor_id=vendor_id,
        security_score=aggregated["security"]["score"],
        compliance_score=aggregated["compliance"]["score"],
        financial_score=aggregated["financial"]["score"],
    )
    blockers = identify_critical_blockers_data(vendor_id)
    conditions = identify_conditional_approvals_data(vendor_id)
    summary = generate_executive_summary_data(
        vendor_id=vendor_id,
        overall_score=scoring["overall_risk_score"],
        risk_level=scoring["risk_level"],
        blockers=blockers,
        conditions=conditions,
    )
    approval = recommend_approval_tier_data(
        vendor_id=vendor_id,
        overall_score=scoring["overall_risk_score"],
        blockers=blockers,
    )
    matrix = create_risk_matrix_data(vendor_id)
    recommendations = generate_mitigation_recommendations_data(vendor_id)

    return {
        "vendor_id": vendor_id,
        "overall_risk_score": scoring["overall_risk_score"],
        "risk_level": scoring["risk_level"],
        "security_score": aggregated["security"]["score"],
        "compliance_score": aggregated["compliance"]["score"],
        "financial_score": aggregated["financial"]["score"],
        "security_weight": scoring["breakdown"]["security"]["weight"],
        "compliance_weight": scoring["breakdown"]["compliance"]["weight"],
        "financial_weight": scoring["breakdown"]["financial"]["weight"],
        "critical_blockers": blockers,
        "conditional_items": conditions,
        "executive_summary": summary,
        "risk_matrix": matrix,
        "mitigation_recommendations": recommendations,
        "approval_tier": approval["recommended_tier"],
        "approval_tier_rationale": approval["rationale"],
        "aggregated_findings": aggregated,
    }


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


@tool
def aggregate_findings(vendor_id: str) -> str:
    """Combine all completed review findings into a unified structure."""
    return _json({"status": "success", **aggregate_findings_data(vendor_id)})


@tool
def calculate_overall_risk_score(
    vendor_id: str,
    security_score: float,
    compliance_score: float,
    financial_score: float,
    security_weight: float = 0.40,
    compliance_weight: float = 0.35,
    financial_weight: float = 0.25,
) -> str:
    """Calculate the overall weighted risk score for a vendor."""
    result = calculate_overall_risk_score_data(
        vendor_id=vendor_id,
        security_score=security_score,
        compliance_score=compliance_score,
        financial_score=financial_score,
        security_weight=security_weight,
        compliance_weight=compliance_weight,
        financial_weight=financial_weight,
    )
    return _json({"status": "success", **result})


@tool
def identify_critical_blockers(vendor_id: str) -> str:
    """Identify issues that should block approval."""
    blockers = identify_critical_blockers_data(vendor_id)
    return _json(
        {
            "status": "success",
            "vendor_id": vendor_id,
            "total_blockers": len(blockers),
            "blockers": blockers,
        }
    )


@tool
def identify_conditional_approvals(vendor_id: str) -> str:
    """Identify follow-up items that allow conditional approval."""
    conditions = identify_conditional_approvals_data(vendor_id)
    return _json(
        {
            "status": "success",
            "vendor_id": vendor_id,
            "total_conditions": len(conditions),
            "conditions": conditions,
        }
    )


@tool
def generate_executive_summary(
    vendor_id: str,
    overall_score: float,
    risk_level: str,
    blockers_count: int,
    conditions_count: int,
) -> str:
    """Generate a leadership-facing executive summary."""
    blockers = identify_critical_blockers_data(vendor_id)[:blockers_count]
    conditions = identify_conditional_approvals_data(vendor_id)[:conditions_count]
    return generate_executive_summary_data(vendor_id, overall_score, risk_level, blockers, conditions)


@tool
def recommend_approval_tier(
    vendor_id: str,
    overall_score: float,
    contract_value: float = 0.0,
    has_blockers: bool = False,
) -> str:
    """Recommend the approval tier based on the assessment outcome."""
    blockers = identify_critical_blockers_data(vendor_id) if has_blockers else []
    result = recommend_approval_tier_data(vendor_id, overall_score, blockers)
    if contract_value:
        result["factors"]["contract_value"] = contract_value
    return _json({"status": "success", **result})


@tool
def create_risk_matrix(vendor_id: str) -> str:
    """Generate visualization-friendly risk matrix data."""
    return _json({"status": "success", **create_risk_matrix_data(vendor_id)})


@tool
def generate_mitigation_recommendations(vendor_id: str) -> str:
    """Generate prioritized mitigation recommendations."""
    return _json(
        {
            "status": "success",
            "vendor_id": vendor_id,
            "recommendations": generate_mitigation_recommendations_data(vendor_id),
        }
    )


RISK_TOOLS = [
    aggregate_findings,
    calculate_overall_risk_score,
    identify_critical_blockers,
    identify_conditional_approvals,
    generate_executive_summary,
    recommend_approval_tier,
    create_risk_matrix,
    generate_mitigation_recommendations,
]
