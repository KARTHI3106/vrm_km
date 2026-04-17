import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useDeferredValue, useMemo, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { useShell } from "../app/ShellContext";
import { StateView } from "../components/StateView";
import { StatusBadge } from "../components/StatusBadge";
import {
  getVendorApprovalDecisions,
  getVendorApprovalPacket,
  getVendorApprovalStatus,
  getVendorApprovalWorkflow,
  getVendorAuditTrail,
  listVendors,
  submitApprovalDecision,
} from "../lib/api";
import { toneForRisk } from "../lib/status";
import { formatDateTime, formatPercent, normalizeText } from "../lib/utils";

function summarizeValue(value: unknown) {
  if (value == null) {
    return "";
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (typeof value === "object") {
    const record = value as Record<string, unknown>;
    return String(
      record.title ||
        record.condition ||
        record.requirement ||
        record.description ||
        JSON.stringify(record),
    );
  }
  return String(value);
}

function asStringList(value: unknown) {
  return Array.isArray(value) ? value.map((entry) => summarizeValue(entry)) : [];
}

function asRecordList(value: unknown) {
  return Array.isArray(value) ? (value as Array<Record<string, unknown>>) : [];
}

export function AuditPage() {
  const { vendorId } = useParams();
  const queryClient = useQueryClient();
  const { searchValue, approvalToken } = useShell();
  const deferredSearch = useDeferredValue(normalizeText(searchValue));
  const [comments, setComments] = useState("");
  const [conditionsText, setConditionsText] = useState("");

  const vendorsQuery = useQuery({
    queryKey: ["vendors", "audit-queue"],
    queryFn: () => listVendors(),
  });
  const packetQuery = useQuery({
    queryKey: ["vendor", vendorId, "approval-packet"],
    queryFn: () => getVendorApprovalPacket(vendorId || ""),
    enabled: Boolean(vendorId),
  });
  const workflowQuery = useQuery({
    queryKey: ["vendor", vendorId, "approval-workflow"],
    queryFn: () => getVendorApprovalWorkflow(vendorId || ""),
    enabled: Boolean(vendorId),
  });
  const decisionsQuery = useQuery({
    queryKey: ["vendor", vendorId, "approvals"],
    queryFn: () => getVendorApprovalDecisions(vendorId || ""),
    enabled: Boolean(vendorId),
  });
  const statusQuery = useQuery({
    queryKey: ["vendor", vendorId, "approval-status"],
    queryFn: () => getVendorApprovalStatus(vendorId || ""),
    enabled: Boolean(vendorId),
  });
  const auditQuery = useQuery({
    queryKey: ["vendor", vendorId, "audit-trail"],
    queryFn: () => getVendorAuditTrail(vendorId || ""),
    enabled: Boolean(vendorId),
  });

  const submitDecisionMutation = useMutation({
    mutationFn: (decision: "approve" | "reject" | "request_changes") =>
      submitApprovalDecision(vendorId || "", approvalToken, {
        decision,
        comments,
        conditions: conditionsText
          .split(/\n|,/)
          .map((entry) => entry.trim())
          .filter(Boolean),
      }),
    onSuccess: async () => {
      setComments("");
      setConditionsText("");
      await Promise.all([
        queryClient.invalidateQueries({ queryKey: ["vendor", vendorId, "approvals"] }),
        queryClient.invalidateQueries({ queryKey: ["vendor", vendorId, "approval-status"] }),
        queryClient.invalidateQueries({ queryKey: ["vendor", vendorId, "approval-workflow"] }),
        queryClient.invalidateQueries({ queryKey: ["vendors", "audit-queue"] }),
      ]);
    },
  });

  const queue = useMemo(() => {
    const items = vendorsQuery.data?.vendors || [];
    return items
      .filter((vendor) => {
        const status = normalizeText(vendor.status || "");
        return Boolean(vendor.approval_status) || status.includes("approval") || status.includes("review");
      })
      .filter((vendor) => {
        const haystack = normalizeText(
          `${vendor.name} ${vendor.status || ""} ${vendor.approval_status || ""} ${vendor.risk_level || ""}`,
        );
        return deferredSearch ? haystack.includes(deferredSearch) : true;
      });
  }, [deferredSearch, vendorsQuery.data?.vendors]);

  if (vendorsQuery.isLoading) {
    return (
      <div className="page">
        <StateView detail="Loading approval queue." title="Audit Workspace Loading" />
      </div>
    );
  }

  if (vendorsQuery.isError) {
    return (
      <div className="page">
        <StateView
          detail="The vendor queue could not be loaded, so the approval workspace is unavailable."
          title="Audit Workspace Unavailable"
          tone="danger"
        />
      </div>
    );
  }

  const auditEntries = [
    ...asRecordList(auditQuery.data?.audit_trail),
    ...asRecordList(auditQuery.data?.trail),
    ...asRecordList(auditQuery.data?.timeline),
  ];
  const packet = packetQuery.data;
  const risk = packet?.risk_assessment || null;
  const blockers = [
    ...asStringList(risk?.critical_blockers),
    ...asStringList(risk?.conditional_items),
  ];

  return (
    <div className="page">
      <section className="page__header">
        <div>
          <h1 className="page__title page__title--compact">Final Decision</h1>
          <p className="page__subtitle">
            Approval packet, rationale, blockers, and audit sequence mapped to the backend approval flow.
          </p>
        </div>
        <div className="metrics-grid">
          <div className="metric-card">
            <span className="metric-card__label">Queue Size</span>
            <span className="metric-card__value">{queue.length}</span>
          </div>
          <div className="metric-card metric-card--accent">
            <span className="metric-card__label">Token Mode</span>
            <span className="metric-card__value">{approvalToken ? "WRITE" : "READ"}</span>
          </div>
        </div>
      </section>

      <section className="page-grid">
        <div className="queue-panel">
          <div className="queue-panel__header">
            <div>
              <p className="page__kicker">Approval Queue</p>
              <h2 className="section-title">Assessments</h2>
            </div>
          </div>
          <div className="stack">
            {queue.map((vendor) => (
              <Link className="approval-item" key={vendor.id} to={`/audit/${vendor.id}`}>
                <span className="approval-item__title">{vendor.name}</span>
                <span>{vendor.status || "processing"} | {vendor.approval_status || "no approval"}</span>
                <span className="approval-item__meta">
                  {vendor.risk_level || "risk pending"} | {formatDateTime(vendor.updated_at)}
                </span>
              </Link>
            ))}
          </div>
        </div>

        {!vendorId ? (
          <StateView
            detail="Select a vendor from the queue to open the approval packet and final decision form."
            title="Select an Assessment"
          />
        ) : (
          <div className="detail-grid__column">
            <div className="card">
              <div className="card__header">
                <div>
                  <p className="page__kicker">Decision Rationale</p>
                  <h2 className="section-title">
                    {String(packet?.vendor?.name || workflowQuery.data?.vendor_id || "Approval Packet")}
                  </h2>
                </div>
                <StatusBadge tone={toneForRisk(String(risk?.risk_level || ""))}>
                  {String(risk?.risk_level || statusQuery.data?.status || "pending")}
                </StatusBadge>
              </div>
              <p className="panel-muted">
                {String(risk?.executive_summary || packet?.recommendation || "Approval packet generated from persisted review output.")}
              </p>
              <div className="metrics-grid">
                <div className="data-row">
                  <div className="data-row__title">Score</div>
                  <div>{String(risk?.overall_risk_score || "N/A")}</div>
                </div>
                <div className="data-row">
                  <div className="data-row__title">Approval Status</div>
                  <div>{statusQuery.data?.status || workflowQuery.data?.status || "no approval"}</div>
                </div>
                <div className="data-row">
                  <div className="data-row__title">Completion</div>
                  <div>{formatPercent(statusQuery.data?.completion_percentage)}</div>
                </div>
                <div className="data-row">
                  <div className="data-row__title">Workflow</div>
                  <div>{workflowQuery.data?.workflow?.name || "Fallback workflow"}</div>
                </div>
              </div>
            </div>

            <div className="split-grid">
              <div className="card">
                <div className="card__header">
                  <div>
                    <p className="page__kicker">Outstanding Blockers</p>
                    <h2 className="section-title">Review Holds</h2>
                  </div>
                </div>
                <div className="stack">
                  {blockers.map((blocker, index) => (
                    <div className="item-row item-row--warning" key={`${blocker}-${index}`}>
                      <div className="item-row__title">Blocker {index + 1}</div>
                      <div>{blocker}</div>
                    </div>
                  ))}
                  {!blockers.length ? (
                    <div className="item-row">
                      <div className="item-row__title">No blockers</div>
                      <div>No unresolved blockers are present in the current approval packet.</div>
                    </div>
                  ) : null}
                </div>
              </div>

              <div className="card">
                <div className="card__header">
                  <div>
                    <p className="page__kicker">Decision Input</p>
                    <h2 className="section-title">Approver Action</h2>
                  </div>
                </div>
                <div className="stack">
                  <label className="field">
                    <span>Required decision commentary</span>
                    <textarea
                      onChange={(event) => setComments(event.target.value)}
                      placeholder="Enter the final rationale here"
                      rows={5}
                      value={comments}
                    />
                  </label>
                  <label className="field">
                    <span>Conditions</span>
                    <textarea
                      onChange={(event) => setConditionsText(event.target.value)}
                      placeholder="Optional. One item per line."
                      rows={4}
                      value={conditionsText}
                    />
                  </label>
                  <p className="panel-muted">
                    {approvalToken
                      ? "Bearer token present. Decisions will be submitted to the backend."
                      : "Read-only mode. Add an approver token in Settings to enable submission."}
                  </p>
                  <div className="button-row">
                    <button
                      className="button button--blue"
                      disabled={!approvalToken || submitDecisionMutation.isPending}
                      onClick={() => submitDecisionMutation.mutate("approve")}
                      type="button"
                    >
                      Approve
                    </button>
                    <button
                      className="button button--danger"
                      disabled={!approvalToken || submitDecisionMutation.isPending}
                      onClick={() => submitDecisionMutation.mutate("reject")}
                      type="button"
                    >
                      Reject
                    </button>
                    <button
                      className="button"
                      disabled={!approvalToken || submitDecisionMutation.isPending}
                      onClick={() => submitDecisionMutation.mutate("request_changes")}
                      type="button"
                    >
                      Request Changes
                    </button>
                  </div>
                </div>
              </div>
            </div>

            <div className="split-grid">
              <div className="card">
                <div className="card__header">
                  <div>
                    <p className="page__kicker">Decision History</p>
                    <h2 className="section-title">Approvals</h2>
                  </div>
                </div>
                <div className="stack">
                  {(decisionsQuery.data?.decisions || []).map((decision) => (
                    <div className="approval-item" key={decision.id}>
                      <span className="approval-item__title">{decision.approver_name || "Approver"}</span>
                      <span>{decision.decision || "pending"} | {decision.comments || "No commentary provided."}</span>
                      <span className="approval-item__meta">{formatDateTime(decision.decided_at)}</span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="card">
                <div className="card__header">
                  <div>
                    <p className="page__kicker">Audit Trail</p>
                    <h2 className="section-title">Persisted Events</h2>
                  </div>
                </div>
                <div className="stack">
                  {auditEntries.slice(0, 8).map((entry, index) => (
                    <div className="timeline-item" key={`${String(entry.action || entry.agent_name || index)}-${index}`}>
                      <span className="timeline-item__title">
                        {String(entry.action || entry.event_type || entry.agent_name || "Audit Event")}
                      </span>
                      <span>
                        {String(entry.agent_name || entry.agent || "system")} | {String(entry.status || "recorded")}
                      </span>
                      <span className="timeline-item__meta">
                        {formatDateTime(String(entry.created_at || entry.timestamp || ""))}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          </div>
        )}
      </section>
    </div>
  );
}
