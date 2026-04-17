"""
Compliance Review Agent — autonomous regulatory compliance assessment.

**Hybrid Pattern**: The ReAct agent gathers data via tools.  Scores are
computed deterministically in ``calculate_compliance_score_data`` — the LLM is
only used for narrative summaries after scoring.

Input  state fields consumed:
    vendor_id, vendor_name, shared_review_context
Output state fields produced:
    compliance_result, shared_review_context (updated)
Tools called:
    search_compliance_policies, check_gdpr_compliance, check_hipaa_compliance,
    check_pci_compliance, verify_data_processing_agreement,
    assess_data_retention_policy, check_subprocessor_list,
    validate_privacy_policy, calculate_compliance_score,
    generate_compliance_report
LLM vs deterministic:
    LLM → data gathering + narrative summary
    Deterministic → score, grade, breakdown, critical_flags
"""

import json
import logging
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import HumanMessage, ToolMessage
from langgraph.prebuilt import create_react_agent

from app.core.llm import get_tool_llm
from app.core.db import (
    create_compliance_review,
    get_vendor,
    get_documents_for_vendor,
    update_compliance_review,
)
from app.core.agent_trace import (
    trace_agent_complete,
    trace_agent_decision,
    trace_agent_error,
    trace_agent_start,
    trace_agent_thinking,
)
from app.core.redis_state import save_state, load_state
from app.core.events import publish_event
from app.tools.compliance_tools import COMPLIANCE_TOOLS, calculate_compliance_score_data

logger = logging.getLogger(__name__)

COMPLIANCE_SYSTEM_PROMPT = """You are the Compliance Review Agent for the Vendorsols Vendor Risk Assessment System.
Your role is to assess a vendor's regulatory compliance posture autonomously.

## Your Capabilities
You have 10 specialized tools:
1. search_compliance_policies — RAG search against internal compliance policies
2. check_gdpr_compliance — Verify GDPR requirements
3. check_hipaa_compliance — Verify HIPAA requirements
4. check_pci_compliance — Verify PCI-DSS requirements
5. verify_data_processing_agreement — Parse and validate DPA
6. assess_data_retention_policy — Evaluate data retention practices
7. check_subprocessor_list — Analyze sub-processor disclosures
8. validate_privacy_policy — Check privacy policy completeness
9. calculate_compliance_score — Compute weighted compliance score
10. generate_compliance_report — Create comprehensive report

## Assessment Process
1. First, search internal compliance policies to understand organizational requirements.
2. Determine which regulations apply based on vendor type and data handling.
3. Check applicable regulations (GDPR always, HIPAA/PCI if relevant).
4. Verify DPA, retention policy, sub-processors, and privacy policy.
5. Identify and summarise all compliance gaps.

## Decision Making
- GDPR applies to ALL vendors handling EU personal data
- HIPAA applies only if vendor handles PHI (healthcare data)
- PCI-DSS applies only if vendor handles cardholder data
- Always check DPA and privacy policy regardless
- Adapt assessment depth based on data sensitivity
- If no document text is available for a required check, flag it clearly

## Output
After completing your assessment, provide a clear summary of findings and gaps.
Do NOT calculate a final numeric score — scoring is handled deterministically.
"""

# Map tool names → deterministic scoring keys
_TOOL_OUTPUT_MAP = {
    "check_gdpr_compliance": "gdpr_check",
    "check_hipaa_compliance": "hipaa_check",
    "check_pci_compliance": "pci_check",
    "verify_data_processing_agreement": "dpa_verification",
    "validate_privacy_policy": "privacy_policy",
}


def _extract_tool_outputs(messages: list) -> dict[str, Any]:
    """Walk message history and collect structured tool outputs."""
    outputs: dict[str, Any] = {}
    for msg in messages:
        if isinstance(msg, ToolMessage):
            key = _TOOL_OUTPUT_MAP.get(msg.name)
            if key:
                try:
                    parsed = json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    outputs[key] = parsed
                except (json.JSONDecodeError, TypeError):
                    outputs[key] = {"raw": msg.content}
    return outputs


def _component_score(score_data: dict[str, Any], key: str) -> float:
    breakdown = (score_data or {}).get("breakdown", {}) or {}
    value = breakdown.get(key, 0)
    if isinstance(value, dict):
        value = value.get("score", 0)
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _build_compliance_details(tool_outputs: dict[str, Any], data_warnings: list[str]) -> dict[str, Any]:
    findings: list[dict[str, Any]] = []
    gaps: list[dict[str, Any]] = []
    recommendations: list[dict[str, Any]] = []
    applicable_regulations: list[str] = []

    gdpr = tool_outputs.get("gdpr_check", {})
    if gdpr:
        applicable_regulations.append("GDPR")
        findings.append(
            {
                "title": "GDPR review",
                "severity": "info" if gdpr.get("score", 0) >= 70 else "high",
                "description": f"GDPR score {gdpr.get('score', 0)}/100.",
            }
        )
        for gap in gdpr.get("gaps", [])[:5]:
            gaps.append(
                {
                    "requirement": "GDPR",
                    "severity": "high",
                    "criticality": "required",
                    "description": str(gap),
                    "document_type": "data_processing_agreement",
                }
            )
        for recommendation in gdpr.get("recommendations", [])[:3]:
            recommendations.append(
                {
                    "title": "GDPR remediation",
                    "description": str(recommendation),
                }
            )

    hipaa = tool_outputs.get("hipaa_check", {})
    if hipaa and hipaa.get("overall_compliance") != "not_applicable":
        applicable_regulations.append("HIPAA")
        findings.append(
            {
                "title": "HIPAA review",
                "severity": "info" if hipaa.get("score", 0) >= 70 else "high",
                "description": f"HIPAA score {hipaa.get('score', 0)}/100.",
            }
        )
        for gap in hipaa.get("gaps", [])[:5]:
            gaps.append(
                {
                    "requirement": "HIPAA",
                    "severity": "high",
                    "criticality": "required",
                    "description": str(gap),
                    "document_type": "baa",
                }
            )

    pci = tool_outputs.get("pci_check", {})
    if pci and pci.get("overall_compliance") != "not_applicable":
        applicable_regulations.append("PCI-DSS")
        findings.append(
            {
                "title": "PCI-DSS review",
                "severity": "info" if pci.get("score", 0) >= 70 else "high",
                "description": f"PCI-DSS score {pci.get('score', 0)}/100.",
            }
        )
        for gap in pci.get("gaps", [])[:5]:
            gaps.append(
                {
                    "requirement": "PCI-DSS",
                    "severity": "high",
                    "criticality": "required",
                    "description": str(gap),
                    "document_type": "pci_aoc",
                }
            )

    dpa = tool_outputs.get("dpa_verification", {})
    if dpa:
        findings.append(
            {
                "title": "Data Processing Agreement",
                "severity": "info" if dpa.get("is_valid_dpa") else "high",
                "description": f"DPA completeness {dpa.get('completeness_score', 0)}/100.",
            }
        )
        for clause in dpa.get("clauses_missing", [])[:5]:
            gaps.append(
                {
                    "requirement": "DPA clause",
                    "severity": "high",
                    "criticality": "required",
                    "description": f"Missing DPA clause: {clause}",
                    "document_type": "data_processing_agreement",
                }
            )
        for recommendation in dpa.get("recommendations", [])[:3]:
            recommendations.append(
                {
                    "title": "DPA remediation",
                    "description": str(recommendation),
                }
            )

    privacy = tool_outputs.get("privacy_policy", {})
    if privacy:
        findings.append(
            {
                "title": "Privacy policy",
                "severity": "info" if privacy.get("completeness_score", 0) >= 70 else "medium",
                "description": f"Privacy policy completeness {privacy.get('completeness_score', 0)}/100.",
            }
        )
        for issue in privacy.get("issues", [])[:5]:
            gaps.append(
                {
                    "requirement": "Privacy policy",
                    "severity": "medium",
                    "criticality": "recommended",
                    "description": str(issue),
                    "document_type": "privacy_policy",
                }
            )
        for recommendation in privacy.get("recommendations", [])[:3]:
            recommendations.append(
                {
                    "title": "Privacy disclosure improvement",
                    "description": str(recommendation),
                }
            )

    for warning in data_warnings:
        gaps.append(
            {
                "requirement": "Submitted evidence",
                "severity": "medium",
                "criticality": "required",
                "description": warning,
                "document_type": "supporting_document",
            }
        )

    deduped_recommendations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in recommendations:
        key = f"{item.get('title')}|{item.get('description')}"
        if key in seen:
            continue
        seen.add(key)
        deduped_recommendations.append(item)

    return {
        "findings": findings,
        "gaps": gaps,
        "recommendations": deduped_recommendations,
        "applicable_regulations": list(dict.fromkeys(applicable_regulations)),
    }


def run_compliance_agent(vendor_id: str) -> dict:
    """Execute the compliance review for a vendor.

    Uses the Hybrid Pattern:
      1. ReAct agent gathers data via tools.
      2. Deterministic scoring via calculate_compliance_score_data().
      3. LLM narrative is the agent's final message (best-effort).

    Returns:
        dict with compliance assessment results including deterministic score.
    """
    review_id = None

    try:
        vendor = get_vendor(vendor_id)
        if not vendor:
            return {
                "status": "error",
                "vendor_id": vendor_id,
                "error": f"Vendor {vendor_id} not found",
            }

        trace_id = trace_agent_start(
            vendor_id,
            "compliance_review",
            {
                "vendor_name": vendor.get("name"),
                "vendor_type": vendor.get("vendor_type"),
                "domain": vendor.get("domain"),
            },
        )

        review = create_compliance_review(
            {
                "vendor_id": vendor_id,
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        review_id = review.get("id")

        documents = get_documents_for_vendor(vendor_id)

        # Read shared context from other parallel agents (best-effort)
        shared_ctx = load_state(f"shared_context:{vendor_id}") or {}
        shared_context_note = ""
        if shared_ctx:
            shared_context_note = (
                "\n\nSHARED CONTEXT FROM OTHER AGENTS (best-effort, may be incomplete):\n"
                + json.dumps(shared_ctx, indent=2, default=str)[:2000]
            )

        publish_event(vendor_id, "tool_status", {
            "phase": "compliance_review", "tool_name": "agent_start", "status": "calling"
        })
        trace_agent_thinking(
            vendor_id,
            "compliance_review",
            "Assessing regulatory obligations, agreement completeness, and disclosures before deterministic scoring.",
            trace_id=trace_id,
        )

        save_state(vendor_id, {"current_step": "compliance_validating_context", "progress_percentage": 23})

        # Build context — only include documents with actual text
        doc_summaries = []
        doc_texts = {}
        for doc in documents:
            cls = doc.get("classification", "unknown")
            doc_summaries.append(f"- {doc['file_name']} (classified: {cls})")
            text = doc.get("extracted_text", "").strip()
            if text:
                doc_texts[cls.lower()] = text[:3000]

        # Data availability warnings
        data_warnings = []
        if not doc_texts:
            data_warnings.append(
                "⚠️ NO EXTRACTED TEXT AVAILABLE from any document — "
                "all document-based compliance checks must score 0."
            )
        if "dpa" not in doc_texts:
            data_warnings.append("⚠️ No DPA text found — DPA verification score will be 0.")
        if "privacy_policy" not in doc_texts:
            data_warnings.append("⚠️ No Privacy Policy text found — privacy policy score will be 0.")

        if data_warnings:
            logger.warning(
                f"Compliance agent for vendor {vendor_id} proceeding with missing evidence: "
                + "; ".join(data_warnings)
            )

        save_state(vendor_id, {"current_step": "compliance_running_assessment", "progress_percentage": 28})

        context_msg = f"""Perform a complete compliance review for vendor: {vendor.get('name')}
Vendor type: {vendor.get('vendor_type', 'unknown')}
Domain: {vendor.get('domain', 'unknown')}
Industry: {vendor.get('industry', 'unknown')}
Contract value: ${float(vendor.get('contract_value', 0)):,.2f}

Submitted documents:
{chr(10).join(doc_summaries) if doc_summaries else 'No documents submitted.'}

DATA AVAILABILITY WARNINGS:
{chr(10).join(data_warnings) if data_warnings else '✅ Document text available for analysis.'}

{'Document texts available for analysis:' if doc_texts else 'No extracted text available — score all document checks as 0.'}
{chr(10).join(f'[{k}]: {v[:1000]}...' for k, v in list(doc_texts.items())[:5]) if doc_texts else ''}
{shared_context_note}

Complete the full compliance assessment using your tools.
Do NOT calculate a final score — scoring is handled programmatically.
Where document text is missing, flag the gap clearly."""

        llm = get_tool_llm()
        agent = create_react_agent(llm, COMPLIANCE_TOOLS, prompt=COMPLIANCE_SYSTEM_PROMPT)

        result = agent.invoke({"messages": [HumanMessage(content=context_msg)]})

        # Extract final message
        messages = result.get("messages", [])
        final_msg = messages[-1].content if messages else "No response"

        # ── Deterministic scoring (Hybrid Pattern) ──────────────────
        tool_outputs = _extract_tool_outputs(messages)
        score_data = calculate_compliance_score_data(tool_outputs)
        detail_data = _build_compliance_details(tool_outputs, data_warnings)

        score = score_data["overall_score"]
        grade = score_data["grade"]
        completed_at = datetime.now(timezone.utc).isoformat()
        report_payload = {
            "summary": (
                f"Compliance review completed with {score}/100 ({grade}). "
                f"{len(detail_data['gaps'])} gap(s) and {len(detail_data['recommendations'])} recommendation(s)."
            ),
            "agent_output": final_msg[:5000],
            "data_warnings": data_warnings,
        }
        db_write_summary = {
            "review_id": review_id,
            "overall_score": score,
            "grade": grade,
            "gap_count": len(detail_data["gaps"]),
            "regulations": detail_data["applicable_regulations"],
        }

        # Update the compliance review record
        if review_id:
            update_compliance_review(review_id, {
                "overall_score": score,
                "grade": grade,
                "gdpr_score": _component_score(score_data, "gdpr"),
                "hipaa_score": _component_score(score_data, "hipaa"),
                "pci_score": _component_score(score_data, "pci"),
                "dpa_score": _component_score(score_data, "dpa"),
                "privacy_policy_score": _component_score(score_data, "privacy_policy"),
                "applicable_regulations": detail_data["applicable_regulations"],
                "findings": detail_data["findings"],
                "gaps": detail_data["gaps"],
                "recommendations": detail_data["recommendations"],
                "status": "completed",
                "report": report_payload,
                "completed_at": completed_at,
            })

        # Write shared context for other parallel agents (best-effort)
        try:
            shared = load_state(f"shared_context:{vendor_id}") or {}
            shared["compliance"] = {
                "score": score,
                "grade": grade,
                "critical_flags": score_data.get("critical_flags", []),
                "data_warnings": data_warnings,
            }
            save_state(f"shared_context:{vendor_id}", shared)
        except Exception as ctx_err:
            logger.debug("Failed to update shared context: %s", ctx_err)

        save_state(vendor_id, {"current_step": "compliance_complete", "progress_percentage": 39})

        publish_event(vendor_id, "tool_status", {
            "phase": "compliance_review", "tool_name": "agent_end", "status": "complete"
        })

        trace_agent_decision(
            vendor_id,
            "compliance_review",
            "Compliance score and gap inventory persisted from structured tool outputs.",
            db_write_summary,
            trace_id=trace_id,
        )

        result_payload = {
            "status": "success",
            "overall_score": score,
            "score": score,
            "grade": grade,
            "score_breakdown": score_data["breakdown"],
            "critical_flags": score_data.get("critical_flags", []),
            "findings": detail_data["findings"],
            "gaps": detail_data["gaps"],
            "recommendations": detail_data["recommendations"],
            "applicable_regulations": detail_data["applicable_regulations"],
            "risk_level": score_data["risk_level"],
            "agent_output": final_msg[:3000],
            "data_warnings": data_warnings,
            "db_write_summary": db_write_summary,
        }
        trace_agent_complete(vendor_id, "compliance_review", result_payload, trace_id=trace_id)
        return result_payload

    except Exception as e:
        logger.error(f"Compliance agent failed for vendor {vendor_id}: {e}")
        trace_agent_error(
            vendor_id,
            "compliance_review",
            str(e),
            error_type=type(e).__name__,
        )
        if review_id:
            update_compliance_review(
                review_id,
                {
                    "status": "error",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {"status": "error", "vendor_id": vendor_id, "error": str(e)}
