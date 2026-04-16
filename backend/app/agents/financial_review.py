"""
Financial Review Agent — autonomous financial risk assessment.

**Hybrid Pattern**: The ReAct agent gathers data via tools.  Scores are
computed deterministically in ``calculate_financial_risk_score_data`` — the LLM
is only used for narrative summaries after scoring.

Input  state fields consumed:
    vendor_id, vendor_name, shared_review_context
Output state fields produced:
    financial_result, shared_review_context (updated)
Tools called:
    search_financial_policies, verify_insurance_coverage,
    check_insurance_expiry, get_credit_rating,
    analyze_financial_statements, check_bankruptcy_records,
    verify_business_continuity_plan, calculate_financial_risk_score,
    generate_financial_report
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
    create_financial_review,
    get_vendor,
    get_documents_for_vendor,
    update_financial_review,
)
from app.core.redis_state import save_state, load_state
from app.core.events import publish_event
from app.tools.financial_tools import FINANCIAL_TOOLS, calculate_financial_risk_score_data

logger = logging.getLogger(__name__)

FINANCIAL_SYSTEM_PROMPT = """You are the Financial Review Agent for the OPUS Vendor Risk Assessment System.
Your role is to assess a vendor's financial stability and risk profile.

## Your Capabilities
You have 9 specialized tools:
1. search_financial_policies — RAG search against internal financial policies
2. verify_insurance_coverage — Verify liability, cyber, E&O insurance
3. check_insurance_expiry — Check if insurance policies are current
4. get_credit_rating — Retrieve and assess vendor credit rating
5. analyze_financial_statements — Analyze financial health indicators
6. check_bankruptcy_records — Search for bankruptcy history
7. verify_business_continuity_plan — Evaluate BCP/DR planning
8. calculate_financial_risk_score — Calculate weighted financial score
9. generate_financial_report — Generate comprehensive financial report

## Assessment Process
1. Search internal financial policies for requirements.
2. Verify insurance coverage and expiry.
3. Get credit rating (mock or real depending on config).
4. Analyze financial statements if available.
5. Check bankruptcy records.
6. Verify business continuity plan if available.
7. Summarise all findings.

## Decision Making
- Insurance is critical for all vendor engagements
- Credit rating provides baseline financial health signal
- Check for bankruptcy/insolvency indicators — these are blocking issues
- BCP is important for critical/strategic vendors
- If no financial documents are submitted, note the gap clearly

## Output
After completing your assessment, provide a clear summary.
Do NOT calculate a final numeric score — scoring is handled deterministically.
"""

# Map tool names → deterministic scoring keys
_TOOL_OUTPUT_MAP = {
    "verify_insurance_coverage": "insurance_verification",
    "get_credit_rating": "credit_rating",
    "analyze_financial_statements": "financial_statements",
    "verify_business_continuity_plan": "bcp_verification",
    "check_bankruptcy_records": "bankruptcy_check",
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


def run_financial_agent(vendor_id: str) -> dict:
    """Execute the financial review for a vendor.

    Uses the Hybrid Pattern:
      1. ReAct agent gathers data via tools.
      2. Deterministic scoring via calculate_financial_risk_score_data().
      3. LLM narrative is the agent's final message (best-effort).

    Returns:
        dict with financial assessment results including deterministic score.
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

        review = create_financial_review(
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
            "phase": "financial_review", "tool_name": "agent_start", "status": "calling"
        })

        save_state(vendor_id, {"current_step": "financial_validating_context", "progress_percentage": 24})

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
        if "insurance_certificate" not in doc_texts and "insurance" not in doc_texts:
            data_warnings.append("⚠️ No insurance certificate text found — insurance coverage score will be 0.")
        if "financial_statement" not in doc_texts and "financial_statements" not in doc_texts:
            data_warnings.append("⚠️ No financial statement text found — financial stability defaults to 50.")
        if "bcp" not in doc_texts and "business_continuity" not in doc_texts:
            data_warnings.append("⚠️ No BCP document text found — BCP score will be 0.")

        if data_warnings:
            logger.warning(
                f"Financial agent for vendor {vendor_id} proceeding with missing evidence: "
                + "; ".join(data_warnings)
            )

        save_state(vendor_id, {"current_step": "financial_running_assessment", "progress_percentage": 29})

        context_msg = f"""Perform a complete financial review for vendor: {vendor.get('name')}
Vendor type: {vendor.get('vendor_type', 'unknown')}
Domain: {vendor.get('domain', 'unknown')}
Contract value: ${float(vendor.get('contract_value', 0)):,.2f}
Vendor ID: {vendor_id}

Submitted documents:
{chr(10).join(doc_summaries) if doc_summaries else 'No documents submitted.'}

DATA AVAILABILITY WARNINGS:
{chr(10).join(data_warnings) if data_warnings else '✅ All expected document types have extractable text.'}

{'Document texts available:' if doc_texts else 'No extracted text available.'}
{chr(10).join(f'[{k}]: {v[:1000]}...' for k, v in list(doc_texts.items())[:5]) if doc_texts else ''}
{shared_context_note}

Complete the full financial assessment using your tools.
Do NOT calculate a final score — scoring is handled programmatically.
Where financial documents are missing, flag the gap clearly."""

        llm = get_tool_llm()
        agent = create_react_agent(llm, FINANCIAL_TOOLS, prompt=FINANCIAL_SYSTEM_PROMPT)

        result = agent.invoke({"messages": [HumanMessage(content=context_msg)]})

        # Extract final message
        messages = result.get("messages", [])
        final_msg = messages[-1].content if messages else "No response"

        # ── Deterministic scoring (Hybrid Pattern) ──────────────────
        tool_outputs = _extract_tool_outputs(messages)
        score_data = calculate_financial_risk_score_data(tool_outputs)

        score = score_data["overall_score"]
        grade = score_data["grade"]
        completed_at = datetime.now(timezone.utc).isoformat()

        # Update the financial review record
        if review_id:
            update_financial_review(review_id, {
                "overall_score": score,
                "grade": grade,
                "status": "completed",
                "report": {"agent_output": final_msg[:5000]},
                "completed_at": completed_at,
            })

        # Write shared context for other parallel agents (best-effort)
        try:
            shared = load_state(f"shared_context:{vendor_id}") or {}
            shared["financial"] = {
                "score": score,
                "grade": grade,
                "critical_flags": score_data.get("critical_flags", []),
                "data_warnings": data_warnings,
            }
            save_state(f"shared_context:{vendor_id}", shared)
        except Exception as ctx_err:
            logger.debug("Failed to update shared context: %s", ctx_err)

        save_state(vendor_id, {"current_step": "financial_complete", "progress_percentage": 40})

        publish_event(vendor_id, "tool_status", {
            "phase": "financial_review", "tool_name": "agent_end", "status": "complete"
        })

        return {
            "status": "success",
            "overall_score": score,
            "score": score,
            "grade": grade,
            "score_breakdown": score_data["breakdown"],
            "critical_flags": score_data.get("critical_flags", []),
            "risk_level": score_data["risk_level"],
            "agent_output": final_msg[:3000],
            "data_warnings": data_warnings,
        }

    except Exception as e:
        logger.error(f"Financial agent failed for vendor {vendor_id}: {e}")
        if review_id:
            update_financial_review(
                review_id,
                {
                    "status": "error",
                    "completed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        return {"status": "error", "vendor_id": vendor_id, "error": str(e)}
