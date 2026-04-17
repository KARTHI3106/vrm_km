import { API_BASE_URL } from "./config";
import type {
  ApprovalDecisionListResponse,
  ApprovalPacket,
  ApprovalStatusResponse,
  ApprovalWorkflowResponse,
  AuditTrailResponse,
  DashboardRecentResponse,
  DashboardStatsResponse,
  DocumentListResponse,
  EvidenceGapResponse,
  EvidenceStatusResponse,
  RiskAssessmentResponse,
  ReviewResponse,
  VendorReport,
  VendorStatus,
  VendorSummary,
} from "./types";

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

type RequestOptions = {
  method?: string;
  body?: BodyInit | null;
  headers?: HeadersInit;
  allow404?: boolean;
};

async function fetchJson<T>(path: string, options: RequestOptions = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    method: options.method || "GET",
    body: options.body,
    headers: options.headers,
  });

  if (options.allow404 && response.status === 404) {
    return null;
  }

  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }

  return (await response.json()) as T;
}

export function getVendorEventsUrl(vendorId: string) {
  return `${API_BASE_URL}/vendors/${vendorId}/events`;
}

export function listVendors(status?: string) {
  const params = new URLSearchParams();
  if (status) {
    params.set("status", status);
  }

  const query = params.toString();
  return fetchJson<{ total: number; vendors: VendorSummary[] }>(
    `/vendors${query ? `?${query}` : ""}`,
  );
}

export function getDashboardStats() {
  return fetchJson<DashboardStatsResponse>("/dashboard/stats");
}

export function getDashboardRecent() {
  return fetchJson<DashboardRecentResponse>("/dashboard/recent");
}

export function getVendorStatus(vendorId: string) {
  return fetchJson<VendorStatus>(`/vendors/${vendorId}/status`);
}

export function getVendorReport(vendorId: string) {
  return fetchJson<VendorReport>(`/vendors/${vendorId}/report`);
}

export function getVendorSecurity(vendorId: string) {
  return fetchJson<ReviewResponse>(`/vendors/${vendorId}/security`);
}

export function getVendorCompliance(vendorId: string) {
  return fetchJson<ReviewResponse>(`/vendors/${vendorId}/compliance`);
}

export function getVendorFinancial(vendorId: string) {
  return fetchJson<ReviewResponse>(`/vendors/${vendorId}/financial`);
}

export function getVendorDocuments(vendorId: string) {
  return fetchJson<DocumentListResponse>(`/vendors/${vendorId}/documents`);
}

export function getVendorEvidenceGaps(vendorId: string) {
  return fetchJson<EvidenceGapResponse>(`/vendors/${vendorId}/evidence-gaps`);
}

export function getVendorEvidenceStatus(vendorId: string) {
  return fetchJson<EvidenceStatusResponse>(`/vendors/${vendorId}/evidence-status`);
}

export function requestVendorEvidence(vendorId: string) {
  return fetchJson<{ status: string; message: string }>(
    `/vendors/${vendorId}/request-evidence`,
    { method: "POST" },
  );
}

export function getVendorRiskAssessment(vendorId: string) {
  return fetchJson<RiskAssessmentResponse>(
    `/vendors/${vendorId}/risk-assessment`,
  );
}

export function getVendorApprovalPacket(vendorId: string) {
  return fetchJson<ApprovalPacket>(`/vendors/${vendorId}/approval-packet`, {
    allow404: true,
  });
}

export function getVendorApprovalWorkflow(vendorId: string) {
  return fetchJson<ApprovalWorkflowResponse>(
    `/vendors/${vendorId}/approval-workflow`,
  );
}

export function getVendorApprovalDecisions(vendorId: string) {
  return fetchJson<ApprovalDecisionListResponse>(
    `/vendors/${vendorId}/approvals`,
  );
}

export function getVendorApprovalStatus(vendorId: string) {
  return fetchJson<ApprovalStatusResponse>(
    `/vendors/${vendorId}/approval-status`,
  );
}

export function getVendorAuditTrail(vendorId: string) {
  return fetchJson<AuditTrailResponse>(`/vendors/${vendorId}/audit-trail`, {
    allow404: true,
  });
}

export function submitApprovalDecision(
  vendorId: string,
  token: string,
  payload: {
    decision: "approve" | "reject" | "request_changes";
    comments: string;
    conditions: string[];
  },
) {
  return fetchJson<{
    status: string;
    message: string;
    decision_id: string;
    approval_complete: boolean;
    final_outcome?: string;
  }>(`/vendors/${vendorId}/approvals`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(payload),
  });
}

export function onboardVendor(input: { prompt: string; files: File[] }) {
  const formData = new FormData();
  formData.append("prompt", input.prompt);
  for (const file of input.files) {
    formData.append("files", file);
  }

  return fetchJson<{
    status: string;
    vendor_id: string;
    message: string;
    status_url: string;
    report_url: string;
  }>("/vendors/onboard", {
    method: "POST",
    body: formData,
  });
}

export function uploadVendorDocuments(vendorId: string, files: File[]) {
  const formData = new FormData();
  for (const file of files) {
    formData.append("files", file);
  }

  return fetchJson<{
    status: string;
    message: string;
    vendor_id: string;
    files_uploaded: string[];
  }>(`/vendors/${vendorId}/documents`, {
    method: "POST",
    body: formData,
  });
}

export function getVendorTraces(vendorId: string) {
  return fetchJson<{
    vendor_id: string;
    total_traces: number;
    traces: Array<{
      trace_id: string;
      timestamp: string;
      phase?: string;
      agent_name: string;
      step?: string;
      event_type: string;
      level: string;
      status?: string;
      message: string;
      thinking: string | null;
      provider?: string | null;
      model?: string | null;
      tool_name?: string | null;
      input_summary?: Record<string, unknown> | string | null;
      output_summary?: Record<string, unknown> | string | null;
      tool_calls: Array<{
        tool_name?: string;
        tool?: string;
        input?: Record<string, unknown>;
        output_status?: string;
        duration_ms?: number;
      }>;
      decisions: Array<{
        decision: string;
        data?: Record<string, unknown>;
      }>;
    }>;
  }>(`/vendors/${vendorId}/traces`);
}
