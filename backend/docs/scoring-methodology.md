# Vendorsols Scoring Methodology

## Overview

Vendorsols uses **deterministic scoring** for all three review domains.  Scores are
computed by pure Python functions — the LLM is never asked to generate,
interpret, or report numeric scores.  This is the **Hybrid Pattern**.

## Why Deterministic Scoring?

| Problem | Solution |
|---------|----------|
| LLM hallucinated scores (e.g. "92/100" when data supported ~60) | Scores calculated from tool output, not LLM text |
| Regex extraction from agent text was fragile | No regex needed — scores are structured dict values |
| Non-reproducible results across runs | Same tool outputs always produce the same score |
| Inconsistent grading criteria | Hardcoded grade/risk-level thresholds |

## Grading Scale

All three domains use the same grading scale:

| Score Range | Grade | Risk Level |
|-------------|-------|------------|
| 90–100 | A | Low |
| 80–89 | B | Low |
| 70–79 | C | Medium |
| 60–69 | D | Medium |
| 40–59 | — | High |
| 0–39 | F | Critical |

---

## Security Scoring

**Function**: `calculate_security_score_data(tool_outputs)`  
**Location**: `app/tools/security_tools.py`

### Component Weights

| Component | Weight | Data Source |
|-----------|--------|------------|
| Certificates | **40%** | SOC2 + ISO27001 validation |
| Domain Security | **30%** | SSL/TLS, headers scan |
| Breach History | **20%** | HaveIBeenPwned checks |
| Questionnaire | **10%** | Security questionnaire analysis |

### Certificate Scoring Rules

| Scenario | Base Score |
|----------|-----------|
| SOC2 Type 2 + ISO27001 | 100 |
| SOC2 only | 70 |
| ISO27001 only | 60 |
| No certificates | 0 |

**Penalties**:
- Expired certificate → score halved (×0.5)
- Expiring soon → score reduced (×0.75)

### Breach History Scoring

| Breaches Found | Score |
|---------------|-------|
| 0 | 100 |
| 1 | 60 |
| 2 | 30 |
| 3+ | 0 |

### Critical Flags

Triggered automatically when:
- 3+ data breaches detected
- Security certificate expired
- SSL/TLS validation failed

---

## Compliance Scoring

**Function**: `calculate_compliance_score_data(tool_outputs)`  
**Location**: `app/tools/compliance_tools.py`

### Component Weights

| Component | Weight | Data Source |
|-----------|--------|------------|
| GDPR | **30%** | GDPR compliance check |
| HIPAA | **20%** | HIPAA compliance check |
| PCI-DSS | **15%** | PCI compliance check |
| DPA | **20%** | Data Processing Agreement verification |
| Privacy Policy | **15%** | Privacy policy validation |

### Critical Flags

Triggered automatically when:
- GDPR overall compliance = "non_compliant"
- HIPAA overall compliance = "non_compliant"
- DPA is invalid (`is_valid_dpa: false`)

### N/A Handling

If a regulation does not apply (e.g. HIPAA for a non-healthcare vendor),
the tool returns a score of 0.  This means the component contributes 0
to the weighted total, effectively redistributing weight to other components.

---

## Financial Scoring

**Function**: `calculate_financial_risk_score_data(tool_outputs)`  
**Location**: `app/tools/financial_tools.py`

### Component Weights

| Component | Weight | Data Source |
|-----------|--------|------------|
| Insurance | **35%** | Insurance coverage verification |
| Credit Rating | **30%** | Credit rating lookup |
| Financial Stability | **25%** | Financial statement analysis |
| BCP | **10%** | Business Continuity Plan check |

### Credit Rating Mapping

| Rating | Score |
|--------|-------|
| AAA | 100 |
| AA / AA+ / AA- | 90–95 |
| A / A+ / A- | 80–85 |
| BBB / BBB+ / BBB- | 65–70 |
| BB / BB+ / BB- | 50–55 |
| B / B+ / B- | 35–40 |
| CCC / CCC+ | 20 |
| CC | 10 |
| C | 5 |
| D | 0 |

Default when unavailable: **50** (neutral assumption).

### Critical Flags

Triggered automatically when:
- Bankruptcy records found
- Active bankruptcy proceedings
- No insurance coverage verified
- Poor credit rating (high risk level)

---

## Overall Risk Score

**Function**: `calculate_overall_risk_score_data()`  
**Location**: `app/tools/risk_tools.py`

The overall risk score is a weighted average of the three domain scores:

```
overall = security × W_s + compliance × W_c + financial × W_f
```

### Default Weights

| Domain | Default Weight |
|--------|---------------|
| Security | 40% |
| Compliance | 35% |
| Financial | 25% |

### Dynamic Weight Adjustments

Weights are adjusted based on vendor characteristics:

- **SaaS/Technology/Infrastructure/Data Processor**: +5% security, +5% compliance, -10% financial
- **Consulting/Services**: +5% compliance, -2% security, -3% financial
- **Applicable regulations**: +5% compliance, -5% financial

### Approval Tier Mapping

| Overall Score | Base Tier |
|--------------|-----------|
| ≥ 90 | Auto-approve |
| ≥ 80 | Manager |
| ≥ 60 | VP |
| ≥ 40 | Executive |
| < 40 | Board |

Tiers are escalated based on:
- Contract value ≥ $1M → Board/Executive
- Contract value ≥ $500K → VP minimum
- Sensitive vendor type (SaaS/tech) → VP minimum
- Active blockers → disqualifies auto-approve
- Applicable regulations → disqualifies auto-approve
