"""
Evidence Coordinator Agent — post-review gap analysis and consolidated collection.

**Runs AFTER supervisor_aggregate_node** so it has access to all three
domain review results.  This enables:
  - Consolidated gap identification across security, compliance, and financial reviews
  - A single deduplicated evidence request email (no vendor spam)
  - Prioritised evidence collection based on review findings

Uses ReAct pattern with 8 evidence tools.
"""

import json
import logging
from typing import Optional

from langchain_core.messages import HumanMessage
from langgraph.prebuilt import create_react_agent

from app.core.llm import get_tool_llm
from app.core.db import (
    get_vendor,
    get_documents_for_vendor,
    get_security_review,
    get_compliance_review,
    get_financial_review,
)
from app.core.redis_state import load_state
from app.core.events import publish_event
from app.tools.evidence_tools import EVIDENCE_TOOLS

logger = logging.getLogger(__name__)

EVIDENCE_SYSTEM_PROMPT = """You are the Evidence Coordinator Agent for the OPUS Vendor Risk Assessment System.
Your role is to identify missing evidence and coordinate its collection.

IMPORTANT: You are running AFTER the Security, Compliance, and Financial review
agents have completed.  You have their aggregated findings and identified gaps.

## Your Capabilities
You have 8 specialized tools:
1. get_required_documents — Determine required documents by vendor type
2. compare_required_vs_submitted — Gap analysis of submitted vs required
3. generate_evidence_request_email — Generate professional request email
4. send_email — Send email via Mailtrap
5. create_followup_task — Create internal follow-up task
6. track_document_status — Check status of all evidence requests
7. send_reminder_email — Send reminder for outstanding docs
8. update_evidence_log — Log evidence tracking actions

## Workflow
1. Review the aggregated findings from all three domain reviews.
2. Determine what documents are required for this vendor type and contract value.
3. Compare required documents against what has been submitted.
4. CONSOLIDATE all gaps from all three reviews into a single prioritised list.
5. Generate ONE professional email listing ALL missing documents (not multiple emails).
6. Send the evidence request email to the vendor contact.
7. Create a follow-up task for the internal procurement team.
8. Update the evidence log with all actions taken.

## Decision Making
- Prioritize "required" documents over "recommended" and "optional"
- Set deadline based on criticality (7 days for critical, 14 for standard)
- Be professional and clear in all communications
- If no contact email is available, log the request but skip email
- Always create follow-up tasks for the internal team
- DEDUPLICATE: If multiple reviews flag the same missing document, list it once

## Output
Summarize what evidence is missing and what actions were taken."""


def _build_review_context(vendor_id: str) -> str:
    """Build a context string from completed review results for the agent.

    Pulls from both DB review records and the Redis shared context to give
    the evidence coordinator full visibility into what the reviews found.
    """
    parts: list[str] = []

    # Pull shared context written by supervisor_aggregate_node
    shared_ctx = load_state(f"shared_context:{vendor_id}") or {}
    if shared_ctx:
        parts.append("## AGGREGATED REVIEW CONTEXT (from supervisor)")
        for domain in ("security", "compliance", "financial"):
            info = shared_ctx.get(domain, {})
            if info:
                parts.append(
                    f"  {domain.title()}: score={info.get('score', 'N/A')}, "
                    f"grade={info.get('grade', 'N/A')}, "
                    f"critical_flags={info.get('critical_flags', [])}, "
                    f"data_warnings={info.get('data_warnings', [])}"
                )

    # Pull from DB for more detailed gaps/recommendations
    sec = get_security_review(vendor_id)
    if sec:
        parts.append(f"\n## Security Review Summary")
        parts.append(f"  Score: {sec.get('overall_score', 'N/A')}, Grade: {sec.get('grade', 'N/A')}")
        findings = sec.get("findings", [])
        if findings:
            parts.append(f"  Findings ({len(findings)}): {str(findings[:5])[:500]}")
        critical = sec.get("critical_issues", [])
        if critical:
            parts.append(f"  Critical issues: {str(critical)[:500]}")

    comp = get_compliance_review(vendor_id)
    if comp:
        parts.append(f"\n## Compliance Review Summary")
        parts.append(f"  Score: {comp.get('overall_score', 'N/A')}, Grade: {comp.get('grade', 'N/A')}")
        gaps = comp.get("gaps", [])
        if gaps:
            parts.append(f"  Compliance gaps ({len(gaps)}): {str(gaps[:5])[:500]}")

    fin = get_financial_review(vendor_id)
    if fin:
        parts.append(f"\n## Financial Review Summary")
        parts.append(f"  Score: {fin.get('overall_score', 'N/A')}, Grade: {fin.get('grade', 'N/A')}")
        recs = fin.get("recommendations", [])
        if recs:
            parts.append(f"  Recommendations: {str(recs[:5])[:500]}")

    if not parts:
        return "No review results available yet."

    return "\n".join(parts)


def run_evidence_coordinator(vendor_id: str) -> dict:
    """
    Execute the evidence coordination for a vendor.

    Now runs AFTER all three domain reviews, enabling consolidated
    gap identification and a single evidence request email.

    Returns a dict with status, gaps identified, and actions taken.
    """
    try:
        vendor = get_vendor(vendor_id)
        if not vendor:
            return {"status": "error", "error": f"Vendor {vendor_id} not found"}

        documents = get_documents_for_vendor(vendor_id)

        publish_event(vendor_id, "tool_status", {
            "phase": "evidence_coordination", "tool_name": "agent_start", "status": "calling"
        })

        doc_summaries = []
        for doc in documents:
            cls = doc.get("classification", "unknown")
            doc_summaries.append(f"- {doc['file_name']} (classified: {cls})")

        # Build context from completed reviews
        review_context = _build_review_context(vendor_id)

        context_msg = f"""Coordinate evidence collection for vendor: {vendor.get('name')}
Vendor type: {vendor.get('vendor_type', 'unknown')}
Contract value: ${float(vendor.get('contract_value', 0)):,.2f}
Contact email: {vendor.get('contact_email', 'not provided')}
Contact name: {vendor.get('contact_name', 'Vendor Contact')}

Currently submitted documents:
{chr(10).join(doc_summaries) if doc_summaries else 'No documents submitted yet.'}

─────────────────────────────────────────────────────────
COMPLETED REVIEW RESULTS (use these to identify evidence gaps):
─────────────────────────────────────────────────────────
{review_context}
─────────────────────────────────────────────────────────

Instructions:
1. Review the aggregated findings above to understand what evidence is missing.
2. Use get_required_documents to determine what's needed for this vendor type.
3. Use compare_required_vs_submitted to find gaps.
4. CONSOLIDATE all gaps from all three reviews into a SINGLE prioritised list.
5. Generate ONE comprehensive email listing ALL missing documents (not multiple emails).
6. If vendor has contact email, send the evidence request email.
7. Create a follow-up task for the procurement team.
8. Provide a summary of gaps and actions taken."""

        llm = get_tool_llm()
        agent = create_react_agent(llm, EVIDENCE_TOOLS, prompt=EVIDENCE_SYSTEM_PROMPT)

        result = agent.invoke({"messages": [HumanMessage(content=context_msg)]})

        messages = result.get("messages", [])
        final_msg = messages[-1].content if messages else "No response"

        publish_event(vendor_id, "tool_status", {
            "phase": "evidence_coordination", "tool_name": "agent_end", "status": "complete"
        })

        return {
            "status": "success",
            "agent_output": final_msg[:3000],
        }

    except Exception as e:
        logger.error(f"Evidence coordinator failed for vendor {vendor_id}: {e}")
        return {"status": "error", "error": str(e)}
