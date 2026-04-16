"""
Security Review Agent — autonomous security assessment with ReAct pattern.

**Hybrid Pattern**: The ReAct agent gathers data via tools.  Scores are
computed deterministically in ``calculate_security_score_data`` — the LLM is
only used for narrative summaries and recommendations after scoring.

Input  state fields consumed:
    vendor_id, vendor_name, vendor_domain, shared_review_context
Output state fields produced:
    security_result, shared_review_context (updated)
Tools called:
    search_security_policies, validate_soc2_certificate,
    validate_iso27001_certificate, check_certificate_expiry,
    scan_domain_security, check_breach_history,
    analyze_security_questionnaire, generate_security_report,
    flag_critical_issues, calculate_security_score
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
    create_security_review,
    get_documents_for_vendor,
    get_vendor,
    update_security_review,
)
from app.core.redis_state import save_state, load_state, cache_get, cache_set
from app.core.events import publish_event
from app.tools.security_tools import SECURITY_TOOLS, calculate_security_score_data

logger = logging.getLogger(__name__)

SECURITY_SYSTEM_PROMPT = """You are the Security Review Agent for a Vendor Risk Assessment system.

Your role is to autonomously and comprehensively assess the security posture of a vendor.
You use the ReAct pattern: Reason about what to do → Act by calling tools → Observe results → Repeat.

ASSESSMENT WORKFLOW:
1. **Search Internal Policies**: Use search_security_policies to find relevant security requirements
2. **Validate Certifications**: If SOC2 or ISO27001 documents are available, validate them
3. **Check Certificate Expiry**: Verify any certificates are not expired
4. **Scan Domain Security**: If a domain is provided, scan SSL/TLS and security headers
5. **Check Breach History**: Search for any data breaches involving the vendor
6. **Analyze Questionnaire**: If a security questionnaire is available, analyze it
7. **Flag Critical Issues**: Identify any blocking issues

RULES:
- Be thorough — check every available piece of evidence
- If certain documents are missing, note it but continue with what's available
- Flag any critical issues that would block approval
- Use your judgment to adapt — if something seems suspicious, investigate further
- Use certificate scores of 0 if no certificates were submitted
- Do NOT calculate a final numeric score — scoring is handled deterministically after your review

When done, summarize your findings and any concerns.
"""

# Map LangChain tool names → structured output keys for deterministic scoring
_TOOL_OUTPUT_MAP = {
    "validate_soc2_certificate": "soc2_validation",
    "validate_iso27001_certificate": "iso27001_validation",
    "check_certificate_expiry": "certificate_expiry",
    "scan_domain_security": "domain_scan",
    "check_breach_history": "breach_history",
    "analyze_security_questionnaire": "questionnaire_analysis",
}


def _extract_tool_outputs(messages: list) -> dict[str, Any]:
    """Walk the message history and collect structured tool outputs."""
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


def create_security_agent():
    """Create the Security Review Agent using the ReAct pattern."""
    llm = get_tool_llm()
    agent = create_react_agent(
        llm,
        SECURITY_TOOLS,
        prompt=SECURITY_SYSTEM_PROMPT,
    )
    return agent


def run_security_agent(vendor_id: str) -> dict:
    """Run the Security Review Agent for a vendor.

    Uses the Hybrid Pattern:
      1. ReAct agent gathers data via tools.
      2. Deterministic scoring via calculate_security_score_data().
      3. LLM narrative is the agent's final message (best-effort).

    Args:
        vendor_id: The vendor UUID to assess.

    Returns:
        dict with security assessment results including deterministic score.
    """
    review_id = None

    try:
        # Gather context
        vendor = get_vendor(vendor_id)
        if not vendor:
            return {
                "status": "error",
                "vendor_id": vendor_id,
                "error": f"Vendor {vendor_id} not found",
            }

        review = create_security_review(
            {
                "vendor_id": vendor_id,
                "status": "in_progress",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        review_id = review.get("id")

        documents = get_documents_for_vendor(vendor_id)
        agent = create_security_agent()

        # Read shared context from other parallel agents (best-effort)
        shared_ctx = load_state(f"shared_context:{vendor_id}") or {}
        shared_context_note = ""
        if shared_ctx:
            shared_context_note = (
                "\n\nSHARED CONTEXT FROM OTHER AGENTS (best-effort, may be incomplete):\n"
                + json.dumps(shared_ctx, indent=2, default=str)[:2000]
            )

        publish_event(vendor_id, "tool_status", {
            "phase": "security_review", "tool_name": "agent_start", "status": "calling"
        })

        save_state(vendor_id, {"current_step": "security_validating_context", "progress_percentage": 22})

        # Build document context
        doc_context = []
        for doc in documents:
            doc_context.append(
                f"- {doc.get('file_name')} "
                f"(Classification: {doc.get('classification', 'unknown')}, "
                f"Status: {doc.get('processing_status', 'unknown')})"
            )

        # Find relevant document texts — only include docs with actual extracted text
        soc2_texts = [
            doc.get("extracted_text", "")[:3000]
            for doc in documents
            if doc.get("classification") == "SOC2" and doc.get("extracted_text", "").strip()
        ]
        iso_texts = [
            doc.get("extracted_text", "")[:3000]
            for doc in documents
            if doc.get("classification") == "ISO27001" and doc.get("extracted_text", "").strip()
        ]
        questionnaire_texts = [
            doc.get("extracted_text", "")[:3000]
            for doc in documents
            if doc.get("classification") == "Security_Questionnaire" and doc.get("extracted_text", "").strip()
        ]

        # Data availability warnings — surfaced clearly to the agent and logs
        data_warnings = []
        if not soc2_texts:
            data_warnings.append("⚠️ NO SOC2 REPORT TEXT AVAILABLE — certificate score will be 0 for this component.")
        if not iso_texts:
            data_warnings.append("⚠️ NO ISO27001 CERTIFICATE TEXT AVAILABLE — certificate score will be 0 for this component.")
        if not questionnaire_texts:
            data_warnings.append("⚠️ NO SECURITY QUESTIONNAIRE TEXT AVAILABLE — questionnaire score defaults to 50.")
        if not documents:
            data_warnings.append("⚠️ NO DOCUMENTS SUBMITTED — all document-based scores will be 0.")

        if data_warnings:
            logger.warning(
                f"Security agent for vendor {vendor_id} proceeding with missing evidence: "
                + "; ".join(data_warnings)
            )

        save_state(vendor_id, {"current_step": "security_running_assessment", "progress_percentage": 27})

        # Build the assessment task
        task = f"""Perform a comprehensive security assessment for vendor: {vendor.get('name', 'Unknown')}

VENDOR INFORMATION:
- Vendor ID: {vendor_id}
- Name: {vendor.get('name', 'Unknown')}
- Type: {vendor.get('vendor_type', 'Unknown')}
- Domain: {vendor.get('domain', 'Not provided')}
- Contract Value: ${vendor.get('contract_value', 0)}

AVAILABLE DOCUMENTS ({len(documents)} total):
{chr(10).join(doc_context) if doc_context else 'No documents available'}

DATA AVAILABILITY WARNINGS:
{chr(10).join(data_warnings) if data_warnings else '✅ All expected document types have extractable text.'}

{("SOC2 REPORT EXCERPT:" + chr(10) + soc2_texts[0]) if soc2_texts else "NO SOC2 REPORT TEXT — score certificate component as 0."}

{("ISO 27001 CERTIFICATE EXCERPT:" + chr(10) + iso_texts[0]) if iso_texts else "NO ISO 27001 CERTIFICATE TEXT — score certificate component as 0."}

{("SECURITY QUESTIONNAIRE EXCERPT:" + chr(10) + questionnaire_texts[0]) if questionnaire_texts else "NO SECURITY QUESTIONNAIRE TEXT — use default score of 50 for this component."}
{shared_context_note}

Please perform a security assessment following your workflow.
Do NOT calculate a final score — scoring is handled programmatically.
Focus on gathering data, validating documents, and identifying concerns.

Vendor name for the report: {vendor.get('name', 'Unknown')}
"""

        result = agent.invoke({
            "messages": [HumanMessage(content=task)],
        })

        # Extract final response
        final_messages = result.get("messages", [])
        final_response = ""
        if final_messages:
            last_msg = final_messages[-1]
            final_response = (
                last_msg.content
                if hasattr(last_msg, "content")
                else str(last_msg)
            )

        # ── Deterministic scoring (Hybrid Pattern) ──────────────────
        tool_outputs = _extract_tool_outputs(final_messages)
        score_data = calculate_security_score_data(tool_outputs)

        overall_score = score_data["overall_score"]
        grade = score_data["grade"]
        completed_at = datetime.now(timezone.utc).isoformat()

        # Update the security review record with deterministic score
        if review_id:
            update_security_review(review_id, {
                "status": "completed",
                "overall_score": overall_score,
                "grade": grade,
                "report": {"agent_output": final_response[:5000]},
                "completed_at": completed_at,
            })

        # Write shared context for other parallel agents (best-effort)
        # NOTE: Since agents run truly in parallel, other agents may
        # not see this until their next run. This is best-effort.
        try:
            shared = load_state(f"shared_context:{vendor_id}") or {}
            shared["security"] = {
                "score": overall_score,
                "grade": grade,
                "critical_flags": score_data.get("critical_flags", []),
                "data_warnings": data_warnings,
            }
            save_state(f"shared_context:{vendor_id}", shared)
        except Exception as ctx_err:
            logger.debug("Failed to update shared context: %s", ctx_err)

        save_state(vendor_id, {"current_step": "security_complete", "progress_percentage": 38})

        publish_event(vendor_id, "tool_status", {
            "phase": "security_review", "tool_name": "agent_end", "status": "complete"
        })

        logger.info(
            f"Security agent completed for vendor {vendor_id}: "
            f"score={overall_score}, grade={grade}"
        )

        return {
            "status": "success",
            "vendor_id": vendor_id,
            "overall_score": overall_score,
            "grade": grade,
            "score_breakdown": score_data["breakdown"],
            "critical_flags": score_data.get("critical_flags", []),
            "risk_level": score_data["risk_level"],
            "agent_response": final_response[:3000],
            "data_warnings": data_warnings,
        }

    except Exception as e:
        logger.error(
            f"Security agent failed for vendor {vendor_id}: {e}"
        )
        if review_id:
            update_security_review(
                review_id,
                {
                    "status": "error",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {
            "status": "error",
            "vendor_id": vendor_id,
            "error": str(e),
        }
