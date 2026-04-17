import type { VendorStatus, VendorSummary } from "./types";

export const PIPELINE_STAGES = [
  { key: "internal_request", label: "Internal Request" },
  { key: "vendor_registration", label: "Vendor Registration" },
  { key: "document_collection", label: "Document Collection" },
  { key: "risk_tiering", label: "Risk Tiering" },
  { key: "security_review", label: "Security Review" },
  { key: "legal_review", label: "Legal Review" },
  { key: "multi_dept_approvals", label: "Multi-dept Approvals" },
  { key: "erp_setup", label: "ERP Setup" },
  { key: "activation", label: "Activation" },
  { key: "annual_soc2_renewal", label: "Annual SOC2 Renewal" },
] as const;

export type StageKey = (typeof PIPELINE_STAGES)[number]["key"];

function lower(value?: string | null) {
  return (value || "").toLowerCase();
}

function asStageKey(value?: string | null): StageKey | null {
  const normalized = lower(value) as StageKey;
  return PIPELINE_STAGES.some((stage) => stage.key === normalized) ? normalized : null;
}

export function resolveStageFromStatus(
  vendor: Pick<VendorSummary, "status" | "approval_status" | "workflow_stage">,
): StageKey {
  const explicit = asStageKey(vendor.workflow_stage);
  if (explicit) {
    return explicit;
  }

  const status = lower(vendor.status);
  const approvalStatus = lower(vendor.approval_status);

  if (approvalStatus || status.includes("approval") || status.includes("approved")) {
    return "multi_dept_approvals";
  }
  if (status.includes("risk")) {
    return "risk_tiering";
  }
  if (status.includes("legal") || status.includes("compliance")) {
    return "legal_review";
  }
  if (status.includes("security") || status.includes("financial") || status.includes("review")) {
    return "security_review";
  }
  if (status.includes("processing") || status.includes("intake")) {
    return "document_collection";
  }
  return "vendor_registration";
}

export function resolveStageFromVendorStatus(status: VendorStatus): StageKey {
  const explicit = asStageKey(status.workflow_stage);
  if (explicit) {
    return explicit;
  }

  const currentPhase = lower(status.current_phase);
  if (currentPhase.includes("annual_soc2_renewal")) {
    return "annual_soc2_renewal";
  }
  if (currentPhase.includes("activation")) {
    return "activation";
  }
  if (currentPhase.includes("erp_setup")) {
    return "erp_setup";
  }
  if (currentPhase.includes("approval")) {
    return "multi_dept_approvals";
  }
  if (currentPhase.includes("risk")) {
    return "risk_tiering";
  }
  if (currentPhase.includes("compliance") || currentPhase.includes("legal") || currentPhase.includes("evidence")) {
    return "legal_review";
  }
  if (currentPhase.includes("security") || currentPhase.includes("financial")) {
    return "security_review";
  }
  if (currentPhase.includes("intake") || currentPhase.includes("processing")) {
    return "document_collection";
  }
  return "vendor_registration";
}

export function deriveStageCounts(vendors: VendorSummary[]) {
  return vendors.reduce<Record<StageKey, number>>(
    (counts, vendor) => {
      const stage = resolveStageFromStatus(vendor);
      counts[stage] += 1;
      return counts;
    },
    {
      internal_request: 0,
      vendor_registration: 0,
      document_collection: 0,
      risk_tiering: 0,
      security_review: 0,
      legal_review: 0,
      multi_dept_approvals: 0,
      erp_setup: 0,
      activation: 0,
      annual_soc2_renewal: 0,
    },
  );
}

export function toneForRisk(riskLevel?: string | null) {
  const normalized = lower(riskLevel);
  if (normalized.includes("critical") || normalized.includes("high") || normalized.includes("tier 1")) {
    return "danger";
  }
  if (normalized.includes("moderate") || normalized.includes("medium") || normalized.includes("tier 2")) {
    return "warning";
  }
  if (normalized.includes("low") || normalized.includes("tier 3")) {
    return "info";
  }
  return "muted";
}

export function toneForStatus(status?: string | null) {
  const normalized = lower(status);
  if (
    normalized.includes("error") ||
    normalized.includes("rejected") ||
    normalized.includes("failed") ||
    normalized.includes("blocked")
  ) {
    return "danger";
  }
  if (
    normalized.includes("pending") ||
    normalized.includes("processing") ||
    normalized.includes("review") ||
    normalized.includes("in_progress")
  ) {
    return "warning";
  }
  if (
    normalized.includes("approved") ||
    normalized.includes("completed") ||
    normalized.includes("received") ||
    normalized.includes("scheduled")
  ) {
    return "info";
  }
  return "muted";
}
