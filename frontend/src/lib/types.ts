export interface VendorSummary {
  id: string;
  name: string;
  vendor_type?: string;
  status?: string;
  contract_value?: number;
  domain?: string;
  contact_email?: string;
  created_at?: string;
  updated_at?: string;
  overall_risk_score?: number | null;
  risk_level?: string | null;
  risk_tier?: string | null;
  risk_tier_label?: string | null;
  approval_tier?: string | null;
  approval_status?: string | null;
  workflow_stage?: string | null;
  workflow_stage_label?: string | null;
  workflow_progress_percentage?: number | null;
}

export interface VendorStatus {
  vendor_id: string;
  vendor_name: string;
  vendor_type?: string;
  vendor_domain?: string;
  contract_value?: number;
  contact_email?: string;
  status?: string;
  current_phase?: string;
  current_agent?: string;
  current_step?: string;
  progress_percentage?: number;
  workflow_stage?: string | null;
  workflow_stage_label?: string | null;
  workflow_progress_percentage?: number | null;
  workflow_stages?: Array<{
    key: string;
    label: string;
    description?: string;
    status?: string;
    progress?: number;
    notes?: string[];
  }>;
  risk_tier?: string | null;
  risk_tier_label?: string | null;
  risk_tier_rationale?: string | null;
  required_documents?: Array<Record<string, unknown>>;
  missing_required_documents?: Array<Record<string, unknown>>;
  required_legal_documents?: Array<Record<string, unknown>>;
  missing_legal_documents?: Array<Record<string, unknown>>;
  approval_departments?: Array<Record<string, unknown>>;
  operational_tasks?: Record<string, unknown>;
  errors?: string[];
  agent_errors?: Array<{
    agent?: string;
    action?: string;
    error?: string;
    timestamp?: string;
  }>;
  has_errors?: boolean;
  overall_risk_score?: number | null;
  risk_level?: string | null;
  approval_tier?: string | null;
  approval_status?: string | null;
  approval_id?: string | null;
}

export interface ReviewResponse {
  vendor_id: string;
  vendor_name?: string;
  status?: string;
  message?: string;
  security_review?: Record<string, unknown>;
  compliance_review?: Record<string, unknown>;
  financial_review?: Record<string, unknown>;
}

export interface EvidenceRequest {
  id: string;
  document_type: string;
  criticality?: string;
  reason?: string;
  status?: string;
  email_sent?: boolean;
  deadline?: string;
  created_at?: string;
}

export interface EvidenceGapResponse {
  vendor_id: string;
  vendor_name?: string;
  total_requests?: number;
  pending?: number;
  received?: number;
  completion_percentage?: number;
  evidence_requests?: EvidenceRequest[];
}

export interface EvidenceStatusResponse {
  vendor_id: string;
  vendor_name?: string;
  evidence_requests?: number;
  tracking_entries?: number;
  requests?: Array<{
    id: string;
    document_type: string;
    status?: string;
    email_sent?: boolean;
    deadline?: string;
  }>;
  recent_tracking?: Array<{
    action?: string;
    actor?: string;
    details?: string;
    created_at?: string;
  }>;
}

export interface RiskAssessmentResponse {
  vendor_id: string;
  status?: string;
  message?: string;
  risk_assessment?: {
    overall_risk_score?: number;
    risk_level?: string;
    approval_tier?: string;
    breakdown?: Record<string, { score?: number; weight?: number }>;
    executive_summary?: string;
    critical_blockers?: string[];
    conditional_items?: string[];
    mitigation_recommendations?: string[];
    completed_at?: string;
  };
}

export interface VendorReport {
  vendor: {
    id: string;
    name: string;
    type?: string;
    contract_value?: number;
    domain?: string;
    status?: string;
  };
  documents: {
    total?: number;
    items?: Array<{
      id: string;
      file_name?: string;
      classification?: string;
      classification_confidence?: number;
      processing_status?: string;
      extracted_dates?: Record<string, unknown>;
    }>;
  };
  security_review?: {
    overall_score?: number;
    grade?: string;
    status?: string;
    report?: Record<string, unknown>;
  } | null;
  compliance_review?: {
    overall_score?: number;
    grade?: string;
    status?: string;
    report?: Record<string, unknown>;
  } | null;
  financial_review?: {
    overall_score?: number;
    grade?: string;
    status?: string;
    report?: Record<string, unknown>;
  } | null;
  risk_assessment?: {
    overall_risk_score?: number;
    risk_level?: string;
    approval_tier?: string;
    executive_summary?: string;
    critical_blockers?: string[];
    conditional_items?: string[];
  } | null;
  approval?: {
    id?: string;
    status?: string;
    approval_tier?: string;
    required_approvers?: Array<Record<string, unknown>>;
    deadline?: string;
  } | null;
  evidence_gaps?: {
    total?: number;
    pending?: number;
    received?: number;
  };
  audit_trail?: Array<{
    agent?: string;
    action?: string;
    tool?: string;
    status?: string;
    duration_ms?: number;
    timestamp?: string;
  }>;
  business_workflow?: Record<string, unknown>;
}

export interface DocumentListResponse {
  vendor_id: string;
  vendor_name?: string;
  total_documents?: number;
  documents?: Array<{
    id: string;
    file_name?: string;
    file_type?: string;
    classification?: string;
    classification_confidence?: number;
    extracted_metadata?: Record<string, unknown>;
    extracted_dates?: Record<string, unknown>;
    processing_status?: string;
    created_at?: string;
  }>;
}

export interface ApprovalWorkflowResponse {
  vendor_id: string;
  approval_id?: string;
  approval_tier?: string;
  status?: string;
  message?: string;
  required_approvers?: Array<Record<string, unknown>>;
  workflow?: {
    id?: string | null;
    name?: string;
    approval_order?: string;
    timeout_hours?: number;
  };
  deadline?: string;
}

export interface ApprovalDecisionListResponse {
  vendor_id: string;
  total?: number;
  decisions?: Array<{
    id: string;
    approver_name?: string;
    approver_role?: string;
    decision?: string;
    comments?: string;
    conditions?: string[];
    decided_at?: string;
  }>;
}

export interface ApprovalStatusResponse {
  vendor_id: string;
  approval_id?: string;
  status?: string;
  completion_percentage?: number;
  total_required?: number;
  total_decided?: number;
  pending_approvers?: Array<Record<string, unknown>>;
  overdue?: boolean;
  final_decision?: string | null;
  decisions?: Array<{
    approver?: string;
    role?: string;
    decision?: string;
    decided_at?: string;
  }>;
}

export interface ApprovalPacket {
  vendor?: Record<string, unknown>;
  documents?: unknown[];
  security_review?: Record<string, unknown> | null;
  compliance_review?: Record<string, unknown> | null;
  financial_review?: Record<string, unknown> | null;
  aggregate_score?: number | null;
  risk_assessment?: {
    overall_risk_score?: number;
    risk_level?: string;
    approval_tier?: string;
    executive_summary?: string;
    critical_blockers?: string[];
    conditional_items?: string[];
    mitigation_recommendations?: Array<{
      description?: string;
      implementation?: string;
    }>;
  } | null;
  approval_workflow?: {
    name?: string;
    approval_order?: string;
    approvers?: Array<Record<string, unknown>>;
  } | null;
  evidence_gaps?: Array<Record<string, unknown>>;
  recommendation?: string;
  audit_trail_count?: number;
  status_history?: Array<Record<string, unknown>>;
  generated_at?: string;
}

export interface AuditTrailResponse {
  vendor_id?: string;
  vendor_name?: string;
  total_events?: number;
  trail?: Array<Record<string, unknown>>;
  audit_trail?: Array<Record<string, unknown>>;
  timeline?: Array<Record<string, unknown>>;
}

export interface DashboardRecentResponse {
  recent_vendors?: VendorSummary[];
  recent_approvals?: Array<Record<string, unknown>>;
  recent_completions?: VendorSummary[];
}

export interface DashboardStatsResponse {
  [key: string]: number | string | boolean | null | undefined;
}

export interface WorkflowEvent {
  vendor_id: string;
  event_type: string;
  data: Record<string, unknown>;
}
