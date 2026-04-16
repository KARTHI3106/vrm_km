# Vendorsols — Vendor Risk Management System (Vendorsols)

> Multi-agent autonomous vendor risk assessment platform. Eight specialized AI agents collaborate via a LangGraph state machine to intake, review, score, and approve vendors through a deterministic, auditable workflow.

---

## Table of Contents

- [Project Overview](#project-overview)
- [Architecture](#architecture)
- [Technology Stack](#technology-stack)
- [Project Structure](#project-structure)
- [Multi-Agent System](#multi-agent-system)
- [Data Flow](#data-flow)
- [Scoring Methodology](#scoring-methodology)
- [Database Schema](#database-schema)
- [API Reference](#api-reference)
- [Frontend](#frontend)
- [Configuration](#configuration)
- [Environment Variables](#environment-variables)
- [Local Development](#local-development)
- [Docker Deployment](#docker-deployment)
- [Testing](#testing)
- [Monitoring](#monitoring)
- [Known Issues & Technical Debt](#known-issues--technical-debt)
- [Contribution Guidelines](#contribution-guidelines)

---

## Project Overview

Vendorsols (codenamed **Vendorsols**) automates the complete lifecycle of vendor risk assessment:

1. **Intake** — Upload vendor documents (PDF, DOCX, XLSX); agents parse, classify, and extract metadata
2. **Parallel Review** — Three domain agents (Security, Compliance, Financial) run concurrently with deterministic scoring
3. **Evidence Coordination** — Post-review gap analysis with consolidated evidence request emails
4. **Risk Assessment** — Weighted aggregation of domain scores, blocker identification, executive summary generation
5. **Approval Orchestration** — Tier-based approval routing with RBAC, auto-simulation for dev, and email notifications
6. **Final Compilation** — Supervisor assembles the complete approval packet and closes the workflow

**Version**: 3.0.0 (Phase 3 — Production Ready)

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    Frontend (React)                      │
│  Vite + React Router + TanStack Query + SSE Events      │
└────────────────────────┬────────────────────────────────┘
                         │ HTTP / SSE
┌────────────────────────▼───────────────────────────────┐
│                 FastAPI Backend (Python)               │
│  ┌──────────┐  ┌──────────┐  ┌───────────────────────┐ │
│  │ Routes   │  │ Phase3   │  │ Middleware            │ │
│  │ (v1 API) │  │ Routes   │  │ (Rate Limit, Security,│ │
│  │          │  │ (Auth,   │  │  Input Validation)    │ │
│  │          │  │  Approv) │  │                       │ │
│  └────┬─────┘  └────┬─────┘  └───────────────────────┘ │
│       │              │                                 │
│  ┌────▼──────────────▼──────────────────────────────┐  │
│  │         LangGraph State Machine                  │  │
│  │  intake → [security|compliance|financial] →      │  │
│  │  supervisor_aggregate → evidence → risk →        │  │
│  │  approval → supervisor_final                     │  │
│  └──────┬──────────────────────────────────────────┘   │
│         │                                                │
│  ┌──────▼──────────────────────────────────────────┐    │
│  │              Core Services                        │    │
│  │  LLM (Groq/Ollama) │ Redis │ Qdrant │ Auth     │    │
│  └──────┬──────────────┬────────┬──────────────────┘    │
└─────────┼──────────────┼────────┼──────────────────────┘
          │              │        │
   ┌──────▼──────┐ ┌─────▼────┐ ┌─▼──────────┐
   │  Supabase   │ │  Redis   │ │  Qdrant    │
   │  (Postgres) │ │  (Cache/  │ │ (Vector DB │
   │  + Storage  │ │  State/  │ │  for RAG)  │
   │  + RLS)     │ │  PubSub) │ │            │
   └─────────────┘ └──────────┘ └────────────┘
```

### Key Architectural Decisions

| Decision | Rationale |
|----------|-----------|
| **Hybrid Pattern** (LLM + Deterministic) | LLM gathers data via tools; scoring is pure Python. Eliminates score hallucination. |
| **LangGraph State Machine** | Explicit workflow topology with conditional routing and parallel fan-out. |
| **Parallel Review Agents** | Security, Compliance, and Financial agents run concurrently, reducing total workflow time by ~60%. |
| **Redis as State Bus** | Shared review context between parallel agents; SSE event delivery via PubSub; cache layer. |
| **Supabase + RLS** | Managed Postgres with Row Level Security for data isolation; built-in storage for vendor documents. |
| **Qdrant for Policy RAG** | Semantic search over internal security/compliance/financial policies using `all-MiniLM-L6-v2` embeddings. |

---

## Technology Stack

### Backend

| Category | Technology | Version |
|----------|-----------|---------|
| Framework | FastAPI | 0.115.6 |
| LLM Orchestration | LangChain + LangGraph | ≥0.3.14 / ≥0.2.60 |
| Primary LLM | Groq (llama-3.3-70b-versatile) | Cloud API |
| Fallback LLM | Ollama (llama3.1:8b) | Local |
| Vector Store | Qdrant | ≥1.12 |
| Embeddings | Sentence Transformers (all-MiniLM-L6-v2) | ≥3.3 |
| Database | Supabase (PostgreSQL) | ≥2.11 |
| Cache / PubSub | Redis | ≥5.2 |
| Auth | python-jose + passlib + bcrypt | JWT/RBAC |
| Document Processing | pdfplumber, python-docx, openpyxl | — |
| OCR | EasyOCR | ≥1.7 |
| Monitoring | Prometheus + Grafana | — |
| Logging | structlog | ≥24.4 |
| Runtime | Python 3.12, Uvicorn | — |

### Frontend

| Category | Technology | Version |
|----------|-----------|---------|
| Framework | React | 19.1 |
| Build | Vite | 6.3.5 |
| Routing | React Router DOM | 7.6 |
| Data Fetching | TanStack React Query | 5.80 |
| Language | TypeScript | 5.8 |
| Testing | Vitest + Testing Library + MSW | — |

---

## Project Structure

```
vrm/
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                  # FastAPI entrypoint, lifespan, middleware
│   │   ├── config.py                 # Pydantic Settings from .env
│   │   ├── agents/
│   │   │   ├── __init__.py
│   │   │   ├── graph.py              # LangGraph state machine definition
│   │   │   ├── supervisor.py         # Final packet compilation agent
│   │   │   ├── document_intake.py    # Document parsing agent (ReAct)
│   │   │   ├── security_review.py    # Security assessment agent (Hybrid)
│   │   │   ├── compliance_review.py  # Compliance review agent (Hybrid)
│   │   │   ├── financial_review.py   # Financial review agent (Hybrid)
│   │   │   ├── evidence_coordinator.py # Post-review gap analysis agent
│   │   │   ├── risk_assessment.py    # Risk aggregation agent (Hybrid)
│   │   │   └── approval_orchestrator.py # Approval routing agent
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── routes.py             # Phase 1-2 API routes
│   │   │   └── phase3_routes.py      # Phase 3: Auth, Approvals, SSE, Dashboard
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── auth.py               # JWT auth + RBAC (admin/approver/reviewer)
│   │   │   ├── db.py                 # Supabase CRUD operations (all tables)
│   │   │   ├── events.py             # SSE event manager via Redis PubSub
│   │   │   ├── llm.py                # LLM factory (Groq primary, Ollama fallback)
│   │   │   ├── llm_wrapper.py        # Retry + rate-limit wrapper for LLM calls
│   │   │   ├── llm_rate_limiter.py   # Token-bucket rate limiter (25 RPM default)
│   │   │   ├── middleware.py         # Rate limit, security headers, input validation
│   │   │   ├── redis_state.py        # Redis state + cache (in-memory fallback)
│   │   │   ├── state.py             # Pydantic models for LangGraph state
│   │   │   └── vector.py            # Qdrant client + embedding + RAG search
│   │   └── tools/
│   │       ├── __init__.py
│   │       ├── base.py               # ToolRegistry, traced_tool, with_retry
│   │       ├── intake_tools.py       # Document parsing/classification tools
│   │       ├── security_tools.py     # Security assessment tools + deterministic scoring
│   │       ├── compliance_tools.py   # Compliance check tools + deterministic scoring
│   │       ├── financial_tools.py    # Financial review tools + deterministic scoring
│   │       ├── evidence_tools.py     # Evidence gap + email tools
│   │       ├── risk_tools.py         # Risk aggregation + tier recommendation tools
│   │       ├── approval_tools.py     # Approval workflow + decision + notification tools
│   │       └── supervisor_tools.py   # Approval packet compilation tools
│   ├── tests/
│   │   ├── test_agents.py
│   │   ├── test_api.py
│   │   ├── test_phase3.py
│   │   ├── test_rate_limiter.py
│   │   ├── test_scoring.py
│   │   ├── test_tools.py
│   │   └── test_workflow_repairs.py
│   ├── docs/
│   │   ├── agent-flow.md
│   │   └── scoring-methodology.md
│   ├── scripts/
│   │   └── seed.py
│   ├── .env.example
│   ├── requirements.txt
│   ├── schema.sql
│   ├── Dockerfile
│   ├── docker-compose.yml
│   ├── prometheus.yml
│   └── pytest.ini
├── frontend/
│   ├── index.html
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   └── src/
│       ├── main.tsx
│       ├── styles.css
│       ├── app/
│       │   ├── App.tsx               # Router + QueryClient setup
│       │   └── ShellContext.tsx       # Global shell state (search, panels, token)
│       ├── components/
│       │   ├── AppShell.tsx          # Layout: topbar, sidebar, panels, outlet
│       │   ├── StateView.tsx          # Empty/error state component
│       │   └── StatusBadge.tsx        # Color-coded status badge
│       ├── pages/
│       │   ├── PipelinesPage.tsx     # Pipeline dashboard with stage filtering
│       │   ├── VendorsPage.tsx        # Vendor list
│       │   ├── VendorDetailPage.tsx  # Full vendor workspace (risk, findings, evidence, docs)
│       │   ├── VendorReportPage.tsx  # Printable report
│       │   ├── IntakePage.tsx        # New vendor onboarding form
│       │   ├── TracePage.tsx         # Real-time SSE workflow trace
│       │   ├── AuditPage.tsx         # Approval packet + decisions
│       │   └── NotFoundPage.tsx
│       ├── lib/
│       │   ├── api.ts                # API client (fetch wrapper + typed functions)
│       │   ├── config.ts             # VITE_API_BASE_URL normalization
│       │   ├── events.ts             # useVendorEventStream SSE hook
│       │   ├── status.ts             # Pipeline stage resolution + tone helpers
│       │   ├── storage.ts            # LocalStorage approval token
│       │   ├── types.ts              # TypeScript interfaces for all API responses
│       │   └── utils.ts             # Currency, date, percent formatters
│       └── test/
│           └── setup.ts
└── stitch_vendorsols_vendor_risk_tower/   # Design artifacts / reference materials
```

---

## Multi-Agent System

### Workflow Graph

```
START → intake_node
  │
  ├── [on error + retries left]  → intake_node (retry)
  ├── [on error + exhausted]     → supervisor_final_node
  └── [on success]               → parallel fan-out
                                      │
              ┌───────────────────────┼───────────────────────┐
              ▼                       ▼                       ▼
      security_node           compliance_node          financial_node
              │                       │                       │
              └───────────────────────┴───────────────────────┘
                                      │
                                      ▼
                      supervisor_aggregate_node
                                      │
                                      ▼
                           evidence_node
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

### Agent Details

| Agent | Tools | LLM Role | Deterministic Role |
|-------|-------|----------|-------------------|
| Document Intake | 7 (parse_pdf, parse_docx, parse_excel, ocr_scan, classify_document, extract_vendor_metadata, extract_dates, store_document_metadata) | Data extraction, classification | — |
| Security Review | 10 (search_security_policies, validate_soc2_certificate, validate_iso27001_certificate, check_certificate_expiry, scan_domain_security, check_breach_history, analyze_security_questionnaire, generate_security_report, flag_critical_issues, calculate_security_score) | Data gathering, narrative | Score computation from tool outputs |
| Compliance Review | 10 (search_compliance_policies, check_gdpr_compliance, check_hipaa_compliance, check_pci_compliance, verify_data_processing_agreement, assess_data_retention_policy, check_subprocessor_list, validate_privacy_policy, calculate_compliance_score, generate_compliance_report) | Data gathering, narrative | Score computation from tool outputs |
| Financial Review | 9 (search_financial_policies, verify_insurance_coverage, check_insurance_expiry, get_credit_rating, analyze_financial_statements, check_bankruptcy_records, verify_business_continuity_plan, calculate_financial_risk_score, generate_financial_report) | Data gathering, narrative | Score computation from tool outputs |
| Evidence Coordinator | 8 (get_required_documents, compare_required_vs_submitted, generate_evidence_request_email, send_email, create_followup_task, track_document_status, send_reminder_email, update_evidence_log) | Gap analysis, email composition | — |
| Risk Assessment | 7 (aggregate_findings, calculate_overall_risk_score, identify_critical_blockers, identify_conditional_approvals, generate_executive_summary, recommend_approval_tier, create_risk_matrix, generate_mitigation_recommendations) | Executive summary, mitigation recommendations | Weighted scoring, blocker identification, tier recommendation |
| Approval Orchestrator | 9 (get_approval_workflow, create_approval_request, send_approval_notification, track_approval_status, record_approval_decision, check_all_approvals_complete, finalize_vendor_status, generate_audit_trail, send_vendor_notification) | — (fully deterministic) | Workflow setup, decision recording, vendor notification |
| Supervisor | 1 (compile_approval_packet) | Final summary narrative | Packet compilation |

### GraphState

```python
class GraphState(TypedDict):
    vendor_id: str
    vendor_name: str
    vendor_type: str
    contract_value: float
    vendor_domain: str
    file_paths: list[str]
    current_phase: str
    messages: Annotated[list, add_messages]
    intake_result: dict
    security_result: dict
    compliance_result: dict
    financial_result: dict
    evidence_result: dict
    risk_assessment_result: dict
    approval_result: dict
    supervisor_result: dict
    errors: list[str]
    final_report: dict
    retry_count: int
    shared_review_context: dict
```

---

## Data Flow

### 1. Vendor Onboarding
```
User → POST /api/v1/vendors/onboard (prompt + files)
  → LLM extracts vendor details from natural language
  → Vendor record created in Supabase
  → Files saved to ./uploads/{vendor_id}/
  → Background task triggers run_full_workflow()
```

### 2. Parallel Review (Hybrid Pattern)
```
Each review agent:
  1. ReAct agent invokes LLM with specialized tools
  2. Tools gather data (certificates, domain scans, compliance checks, etc.)
  3. Tool outputs collected from message history
  4. Deterministic scoring function computes score/grade/risk_level
  5. Review record updated in Supabase
  6. Results written to Redis shared_context:{vendor_id}
```

### 3. Cross-Agent Communication
```
Parallel agents write to Redis:
  shared_context:{vendor_id} → {
    "security":   { "score": 85, "grade": "B", ... },
    "compliance": { "score": 72, "grade": "C", ... },
    "financial":  { "score": 90, "grade": "A", ... },
    "aggregated_at": "2025-01-15T10:30:00Z"
  }

Downstream agents (evidence, risk) read this context.
Note: Best-effort — truly parallel agents may not see each other's results immediately.
```

### 4. Real-Time Updates
```
Agent publishes event → Redis PubSub → SSE EventManager → Frontend EventSource
```

### 5. Approval Flow
```
Risk assessment → approval_tier (auto_approve/manager/vp/executive/board)
  → Approval request created in DB
  → Notification emails sent (Mailtrap/Mailgun)
  → [If auto_simulate_approvals=true] Decisions auto-generated
  → [If human approval] POST /api/v1/vendors/{id}/approvals (JWT required)
  → Vendor status finalized + notification sent
```

---

## Scoring Methodology

All scoring is **deterministic** — the LLM never generates numeric scores.

### Security (40% default weight)
| Component | Weight | Scoring Rules |
|-----------|--------|---------------|
| Certificates | 40% | SOC2+ISO27001=100, SOC2 only=70, ISO only=60, none=0; expired×0.5, expiring×0.75 |
| Domain Security | 30% | SSL/TLS + security headers scan |
| Breach History | 20% | 0=100, 1=60, 2=30, 3+=0 |
| Questionnaire | 10% | Default 50 if unavailable |

### Compliance (35% default weight)
| Component | Weight |
|-----------|--------|
| GDPR | 30% |
| HIPAA | 20% |
| PCI-DSS | 15% |
| DPA | 20% |
| Privacy Policy | 15% |

### Financial (25% default weight)
| Component | Weight | Scoring Rules |
|-----------|--------|---------------|
| Insurance | 35% | Coverage verification |
| Credit Rating | 30% | AAA=100 → D=0, default=50 |
| Financial Stability | 25% | Statement analysis |
| BCP | 10% | Business continuity plan check |

### Grading Scale
| Score | Grade | Risk Level |
|-------|-------|------------|
| 90-100 | A | Low |
| 80-89 | B | Low |
| 70-79 | C | Medium |
| 60-69 | D | Medium |
| 40-59 | — | High |
| 0-39 | F | Critical |

### Approval Tier Escalation
| Overall Score | Base Tier | Escalation Triggers |
|--------------|----------|-------------------|
| ≥90 | Auto-approve | Blockers → manager; regulations → manager |
| ≥80 | Manager | Sensitive vendor → VP; contract ≥$500K → VP |
| ≥60 | VP | Contract ≥$1M → board/executive |
| ≥40 | Executive | — |
| <40 | Board | — |

---

## Database Schema

Supabase (PostgreSQL) with RLS enabled on all tables.

### Core Tables (Phase 1)
| Table | Purpose |
|-------|---------|
| `vendors` | Vendor records (name, type, domain, contract_value, status) |
| `documents` | Uploaded documents (classification, extracted_text, metadata) |
| `security_reviews` | Security assessment results (scores, findings, critical_issues) |
| `audit_logs` | Agent/tool audit trail (action, duration_ms, token_usage) |
| `policies` | Internal policies for RAG search |
| `breaches` | Internal breach database |
| `vendor_review_states` | Active workflow state (JSONB) |

### Phase 2 Tables
| Table | Purpose |
|-------|---------|
| `compliance_reviews` | Compliance assessment (GDPR, HIPAA, PCI, DPA, privacy scores) |
| `financial_reviews` | Financial assessment (insurance, credit, stability, BCP scores) |
| `evidence_requests` | Missing document tracking (criticality, deadline, email status) |
| `evidence_tracking` | Evidence action log |

### Phase 3 Tables
| Table | Purpose |
|-------|---------|
| `users` | Authentication + RBAC (admin, approver, reviewer roles) |
| `risk_assessments` | Aggregated risk (overall score, level, blockers, tier) |
| `approval_workflows` | Tier definitions (approvers, order, timeout) |
| `approvals` | Active approval requests (status, required_approvers, deadline) |
| `approval_decisions` | Individual approver decisions (approve/reject/request_changes) |
| `approval_notifications` | Email notification tracking |
| `vendor_status_history` | Status change audit trail |

### Storage
- Bucket: `vendor-documents` (Supabase Storage, non-public)

---

## API Reference

### Base URL: `/api/v1`

#### Vendor Onboarding
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/vendors/onboard` | Start vendor onboarding (NL prompt + file uploads) |

#### Vendor Status & Reports
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/vendors` | — | List vendors (filter by status) |
| GET | `/vendors/{id}/status` | — | Live workflow status + progress |
| GET | `/vendors/{id}/report` | — | Complete assessment report |
| GET | `/vendors/{id}/approval-packet` | — | Full approval packet |

#### Domain Reviews
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/vendors/{id}/security` | Security review findings |
| GET | `/vendors/{id}/compliance` | Compliance review findings |
| GET | `/vendors/{id}/financial` | Financial review findings |

#### Documents & Evidence
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/vendors/{id}/documents` | List classified documents |
| POST | `/vendors/{id}/documents` | Upload additional documents |
| GET | `/vendors/{id}/evidence-gaps` | Missing evidence items |
| POST | `/vendors/{id}/request-evidence` | Trigger evidence coordination |
| POST | `/vendors/{id}/evidence/{doc_type}/received` | Mark evidence received |

#### Risk & Approval
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/vendors/{id}/risk-assessment` | — | Risk score, level, breakdown |
| GET | `/vendors/{id}/risk-matrix` | — | Visualization-ready risk matrix |
| GET | `/vendors/{id}/approval-workflow` | — | Approval workflow details |
| POST | `/vendors/{id}/approvals` | approver/admin | Submit approval decision |
| GET | `/vendors/{id}/approvals` | — | List approval decisions |
| GET | `/vendors/{id}/approval-status` | — | Approval completion status |
| GET | `/vendors/{id}/audit-trail` | — | Complete audit timeline |

#### Real-Time
| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/vendors/{id}/events` | SSE stream for workflow updates |

#### Authentication
| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/auth/login` | Authenticate, get JWT tokens |
| POST | `/auth/register` | Create user (admin/approver/reviewer) |
| POST | `/auth/refresh` | Refresh access token |
| GET | `/auth/me` | Current user profile |

#### Dashboard & Admin
| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| GET | `/dashboard/stats` | — | Aggregate statistics |
| GET | `/dashboard/recent` | — | Recent vendors/approvals |
| GET | `/approval-workflows` | — | List workflows |
| POST | `/approval-workflows` | admin | Create workflow |
| PUT | `/approval-workflows/{id}` | admin | Update workflow |
| GET | `/policies` | — | List policies |
| POST | `/policies` | admin | Create policy + vectorize |
| DELETE | `/policies/{id}` | admin | Deactivate policy |
| GET | `/users` | admin | List users |
| GET | `/health` | — | System health check |

---

## Frontend

### Routes
| Path | Page | Description |
|------|------|-------------|
| `/pipelines` | PipelinesPage | Main dashboard with 5-stage pipeline view |
| `/vendors` | VendorsPage | Vendor list |
| `/vendors/:vendorId` | VendorDetailPage | Full vendor workspace (risk, findings, evidence, documents) |
| `/vendors/:vendorId/report` | VendorReportPage | Printable report |
| `/intake` | IntakePage | New vendor onboarding |
| `/trace` | TracePage | Real-time SSE event viewer |
| `/trace/:vendorId` | TracePage | Vendor-scoped trace |
| `/audit` | AuditPage | Approval packet + decisions |
| `/audit/:vendorId` | AuditPage | Vendor-scoped audit |

### Data Flow Pattern
```
Component → TanStack Query → fetchJson<T>(api.ts) → FastAPI /api/v1/...
                                                         ↑
SSE events (useVendorEventStream) ← Redis PubSub ← Agent publish_event()
```

### Key Hooks & Utilities
- `useVendorEventStream(vendorId)` — SSE connection with polling fallback
- `useShell()` — Global search, panel state, approval token
- `resolveStageFromStatus()` / `resolveStageFromVendorStatus()` — Map vendor status to pipeline stage
- `toneForRisk()` / `toneForStatus()` — Color tone derivation for badges

### Environment Variables
| Variable | Default | Description |
|----------|---------|-------------|
| `VITE_API_BASE_URL` | `http://127.0.0.1:8000` | Backend API base URL |
| `VITE_APPROVER_BEARER_TOKEN` | — | Pre-configured approval JWT |

---

## Configuration

Backend configuration uses Pydantic Settings loaded from `.env`:

```python
class Settings(BaseSettings):
    supabase_url: str
    supabase_key: str
    supabase_db_url: str
    ollama_base_url: str    # http://localhost:11434
    ollama_model: str        # llama3.1:8b
    groq_api_key: str
    redis_url: str            # redis://localhost:6379/0
    qdrant_url: str           # http://localhost:6333
    app_env: str              # development
    log_level: str            # DEBUG
    upload_dir: str           # ./uploads
    jwt_secret: str           # Set to enable auth
    auto_simulate_approvals: bool  # false
    max_workflow_retries: int      # 2
    llm_requests_per_minute: int   # 25
    agent_timeout_seconds: int      # 120
    risk_threshold_high: float     # 80.0
    risk_threshold_medium: float   # 60.0
    risk_threshold_low: float      # 40.0
```

---

## Environment Variables

### Backend (`.env`)
```env
SUPABASE_URL=https://foijpyqxfqlsugjzjtef.supabase.co
SUPABASE_KEY=<your_supabase_key>
SUPABASE_DB_URL=postgresql://postgres:PASSWORD@db.foijpyqxfqlsugjzjtef.supabase.co:5432/postgres
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1:8b
GROQ_API_KEY=<your_groq_key>
REDIS_URL=redis://localhost:6379/0
QDRANT_URL=http://localhost:6333
APP_ENV=development
LOG_LEVEL=DEBUG
UPLOAD_DIR=./uploads
JWT_SECRET=
AUTO_SIMULATE_APPROVALS=false
MAX_WORKFLOW_RETRIES=2
LLM_REQUESTS_PER_MINUTE=25
AGENT_TIMEOUT_SECONDS=120
MAILTRAP_API_KEY=
MAILTRAP_SENDER_EMAIL=Vendorsols@vrm-system.com
CREDIT_API_MODE=mock
OPENCORPORATES_API_KEY=
```

### Frontend
```env
VITE_API_BASE_URL=http://127.0.0.1:8000
VITE_APPROVER_BEARER_TOKEN=
```

---

## Local Development

### Prerequisites
- Python 3.12+
- Node.js 18+
- Redis (or use docker-compose)
- Qdrant (or use docker-compose)
- Ollama (optional, for local LLM)
- Groq API key (required for ReAct agents)

### Backend Setup

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your keys
```

### Start Infrastructure

```bash
cd backend
docker-compose up -d redis qdrant prometheus grafana
```

### Run Backend

```bash
cd backend
uvicorn app.main:app --reload --port 8000
```

API docs available at `http://localhost:8000/docs`

### Run Database Migration

Apply `schema.sql` to your Supabase project via the SQL editor or `psql`:

```bash
psql "$SUPABASE_DB_URL" -f schema.sql
```

### Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Frontend available at `http://localhost:5173`

---

## Docker Deployment

### Full Stack (Backend + Infrastructure)

```bash
cd backend
docker-compose up -d
```

This starts:
- **Redis** on port 6379
- **Qdrant** on ports 6333/6334
- **Prometheus** on port 9090
- **Grafana** on port 3000 (admin/admin)

### Backend Container

```bash
cd backend
docker build -t Vendorsols-vrm .
docker run -p 8000:8000 --env-file .env Vendorsols-vrm
```

### Dockerfile
```dockerfile
FROM python:3.12-slim
# Installs: build-essential, curl, poppler-utils, tesseract-ocr
# Exposes port 8000
# CMD: uvicorn app.main:app --host 0.0.0.0 --port 8000
```

---

## Testing

### Backend Tests

```bash
cd backend
pytest                          # Run all tests
pytest tests/test_scoring.py     # Run specific test file
pytest -v --cov=app             # With coverage
```

Configuration (`pytest.ini`):
```ini
[pytest]
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
asyncio_mode = auto
```

Test files:
| File | Coverage |
|------|----------|
| `test_agents.py` | Agent creation and execution |
| `test_api.py` | API endpoint tests |
| `test_phase3.py` | Phase 3 features (auth, approvals, dashboard) |
| `test_rate_limiter.py` | Token bucket rate limiter |
| `test_scoring.py` | Deterministic scoring functions |
| `test_tools.py` | Individual tool tests |
| `test_workflow_repairs.py` | Graph topology and retry logic |

### Frontend Tests

```bash
cd frontend
npm test            # Run once
npm run test:watch  # Watch mode
```

Uses Vitest with jsdom environment, Testing Library, and MSW for API mocking.

---

## Monitoring

### Prometheus
Scrapes `http://host.docker.internal:8000/metrics` every 15s. Configured in `backend/prometheus.yml`.

### Grafana
Available at `http://localhost:3000` (admin/admin). Connected to Prometheus data source.

### Health Check
```
GET /api/v1/health
```
Returns status of all services:
```json
{
  "status": "healthy",
  "services": {
    "database": {"status": "up", "type": "supabase"},
    "redis": {"status": "up"},
    "vector_store": {"status": "up", "type": "qdrant"},
    "llm": {"ollama": "up", "groq": "up"}
  }
}
```

---

## Known Issues & Technical Debt

### Critical
1. **CORS allows all origins** (`allow_origins=["*"]`) — must be restricted in production
2. **RLS policies are permissive** (`USING (true) WITH CHECK (true)`) — all tables grant full service_role access; no tenant isolation
3. **JWT secret defaults to empty** — auth is completely bypassed when `JWT_SECRET` is not set (dev mode returns a default admin user)
4. **Supabase key in .env.example** contains a publishable key that should be rotated

### Architecture
5. **Parallel agent cross-visibility is best-effort** — agents running truly in parallel may not see each other's Redis context updates immediately
6. **No async DB operations** — all Supabase calls are synchronous; this blocks the event loop under load
7. **Global LLM singletons** — `_llm_instance` and `_tool_llm_instance` are module-level globals with no thread safety
8. **Redis fallback to in-memory dict** — `_mock_store` and `_mock_cache` are not shared across workers; multi-process deployments will have inconsistent state
9. **No database connection pooling** — Supabase client is a singleton with no pool management

### Code Quality
10. **Mixed `__pycache__` from Python 3.12 and 3.13** — suggests development environment inconsistency
11. **No type checking enforcement** — `mypy` or `pyright` not configured; Pydantic models in `state.py` are defined but not used by the actual `GraphState` TypedDict
12. **Tool output parsing is fragile** — `_extract_tool_outputs()` relies on `ToolMessage.name` matching hardcoded `_TOOL_OUTPUT_MAP` keys
13. **`update.py` and `fix_template.py` are undocumented utility scripts** at the backend root

### Missing Features
14. **No pagination on audit_logs** — `get_audit_logs()` returns all entries with no limit
15. **No WebSocket support** — SSE is one-directional; frontend cannot push commands
16. **No file size/type validation** — uploaded files have no restrictions
17. **No vendor deletion API** — only status transitions are exposed
18. **No email template system** — email bodies are string-concatenated in Python
19. **No rate limit persistence** — rate limiting uses Redis ZADD but falls back to no-op when Redis is unavailable
20. **Frontend pages directory is empty at `src/pages/`** but pages exist at the same level — likely a stale directory

---

## Contribution Guidelines

### Branch Naming
- `feature/<short-description>` — new features
- `fix/<short-description>` — bug fixes
- `refactor/<short-description>` — code restructuring

### Code Style
- **Backend**: Follow PEP 8; use `structlog` for all logging; type hints on all function signatures
- **Frontend**: TypeScript strict mode; functional components with hooks; TanStack Query for all data fetching
- **No comments in code** unless explicitly requested — code should be self-documenting

### Agent Development Pattern
When adding a new agent:
1. Create `app/agents/<agent_name>.py` with a `run_<agent_name>()` function
2. Create `app/tools/<agent_name>_tools.py` with tool definitions and deterministic scoring functions
3. Add node to `app/agents/graph.py` and update the graph topology
4. Add any new database tables to `schema.sql`
5. Add API routes in `app/api/routes.py` or `app/api/phase3_routes.py`
6. Add corresponding frontend types in `frontend/src/lib/types.ts` and API functions in `frontend/src/lib/api.ts`

### Commit Messages
- Use conventional commit format: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`
- Focus on the "why" not the "what"

### Testing Requirements
- All new tools must have unit tests in `tests/test_tools.py`
- All new API endpoints must have integration tests
- Deterministic scoring functions must have property-based test coverage
- Frontend components must render without errors in Vitest
