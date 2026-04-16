# Vendorsols Agent Flow

## Overview

Vendorsols uses a multi-agent LangGraph state machine to orchestrate vendor risk
assessments.  Each node in the graph is a specialised agent backed by
LangChain ReAct pattern and Groq-powered LLMs.

## Graph Topology (v2 — Fixed)

```
START
  │
  ▼
intake_node  (Document Intake Agent)
  │
  ├── route_after_intake()
  │     ├── [on error + retries left]  → intake_node (retry)
  │     ├── [on error + retries exhausted] → supervisor_final_node
  │     └── [on success] → parallel fan-out ────────────────┐
  │                                                          │
  ▼                     ▼                     ▼              │
security_node      compliance_node      financial_node       │
  │                     │                     │              │
  └─────────────────────┴─────────────────────┘              │
                        │                                    │
                        ▼                                    │
          supervisor_aggregate_node  ◄───────────────────────┘
                        │
                        ▼
                 evidence_node        ← runs AFTER reviews
                        │
                        ▼
             risk_assessment_node
                        │
                        ▼
          approval_orchestrator_node
                        │
                        ▼
            supervisor_final_node
                        │
                        ▼
                       END
```

## Phase Descriptions

| Phase | Node | Agent | Description |
|-------|------|-------|-------------|
| 1 - Intake | `intake_node` | Document Intake | Parses, validates, classifies uploaded vendor documents (PDF, DOCX, XLSX). Performs OCR fallback when text extraction fails. |
| 2 - Parallel Reviews | `security_node` | Security Review | Validates SOC2/ISO27001 certificates, scans domain security, checks breach history, analyses questionnaires. Score computed deterministically. |
| 2 - Parallel Reviews | `compliance_node` | Compliance Review | Checks GDPR/HIPAA/PCI compliance, verifies DPA, validates privacy policy. Score computed deterministically. |
| 2 - Parallel Reviews | `financial_node` | Financial Review | Verifies insurance, checks credit rating, analyses financial statements, checks bankruptcy records. Score computed deterministically. |
| 3 - Aggregation | `supervisor_aggregate_node` | Supervisor | Collects all three parallel review results and persists shared_review_context. |
| 4 - Evidence | `evidence_node` | Evidence Coordinator | Post-review gap analysis using consolidated findings. Sends ONE deduplicated evidence request email. |
| 5 - Risk | `risk_assessment_node` | Risk Assessment | Aggregates scores with weighted formula, identifies blockers, generates executive summary, recommends approval tier. |
| 6 - Approval | `approval_orchestrator_node` | Approval Orchestrator | Creates approval request, routes to appropriate tier, optionally auto-simulates decisions. |
| 7 - Final | `supervisor_final_node` | Supervisor | Compiles final approval packet, updates vendor status, closes workflow. |

## Data Flow

### Shared Review Context

Parallel review agents write their results to a Redis key
`shared_context:{vendor_id}` so downstream nodes
(evidence coordinator, risk assessment) can access consolidated findings.

```json
{
  "security":   { "score": 85, "grade": "B", "critical_flags": [], "data_warnings": [] },
  "compliance": { "score": 72, "grade": "C", "critical_flags": ["GDPR non-compliance"], "data_warnings": [] },
  "financial":  { "score": 90, "grade": "A", "critical_flags": [], "data_warnings": [] },
  "aggregated_at": "2025-01-15T10:30:00Z"
}
```

### Hybrid Pattern (Deterministic Scoring)

Each review agent uses the **Hybrid Pattern**:

1. **ReAct Agent** (LLM) — gathers data by calling specialised tools
2. **Deterministic Scoring** (Python) — computes scores from tool outputs using hardcoded business rules
3. **LLM Narrative** — the agent's final message provides qualitative summary

This eliminates score hallucination: the LLM never generates or interprets numeric scores.

## Rate Limiting

Groq free tier allows 30 RPM.  Vendorsols uses a `TokenBucketRateLimiter`
(default: 25 RPM with 5 headroom) to prevent API exhaustion across
all concurrent agents.  The `call_llm_with_backoff` wrapper adds
exponential retry on 429/5xx errors.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `LLM_REQUESTS_PER_MINUTE` | 25 | Rate limiter budget |
| `AGENT_TIMEOUT_SECONDS` | 120 | Per-agent execution timeout |
| `MAX_WORKFLOW_RETRIES` | 2 | Transient intake retry count |
