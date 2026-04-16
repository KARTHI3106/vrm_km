import { useMutation, useQuery } from "@tanstack/react-query";
import { useMemo, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { StateView } from "../components/StateView";
import { getVendorStatus, onboardVendor, uploadVendorDocuments } from "../lib/api";

export function IntakePage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const existingVendorId = searchParams.get("vendor") || "";
  const [prompt, setPrompt] = useState("");
  const [files, setFiles] = useState<File[]>([]);

  const existingVendorQuery = useQuery({
    queryKey: ["vendor", existingVendorId, "intake-status"],
    queryFn: () => getVendorStatus(existingVendorId),
    enabled: Boolean(existingVendorId),
  });

  const mode = useMemo(() => (existingVendorId ? "upload" : "new"), [existingVendorId]);

  const intakeMutation = useMutation({
    mutationFn: async () => {
      if (mode === "upload") {
        return uploadVendorDocuments(existingVendorId, files);
      }
      return onboardVendor({ prompt, files });
    },
    onSuccess: (result) => {
      const targetVendorId =
        mode === "upload" ? existingVendorId : result?.vendor_id || "";
      navigate(`/vendors/${targetVendorId}`);
    },
  });

  if (mode === "upload" && existingVendorQuery.isLoading) {
    return (
      <div className="page">
        <StateView detail="Loading existing vendor intake context." title="Intake Loading" />
      </div>
    );
  }

  return (
    <div className="page">
      <section className="page__header">
        <div>
          <h1 className="page__title page__title--compact">
            {mode === "upload" ? "Add Documents" : "New Assessment"}
          </h1>
          <p className="page__subtitle">
            {mode === "upload"
              ? `Upload more evidence for ${existingVendorQuery.data?.vendor_name || existingVendorId}.`
              : "Create a vendor assessment and start the multi-agent workflow."}
          </p>
        </div>
      </section>

      <section className="split-grid">
        <div className="form-panel">
          <div className="card__header">
            <div>
              <p className="page__kicker">Primary Input</p>
              <h2 className="section-title">
                {mode === "upload" ? "Additional Documents" : "Onboard Vendor"}
              </h2>
            </div>
          </div>
          <div className="stack">
            {mode === "new" ? (
              <label className="field">
                <span>Vendor prompt</span>
                <textarea
                  onChange={(event) => setPrompt(event.target.value)}
                  placeholder="Example: onboard Datastream.io, enterprise observability vendor, $240000 contract, domain datastream.io"
                  rows={7}
                  value={prompt}
                />
              </label>
            ) : null}

            <label className="field">
              <span>Files</span>
              <input
                multiple
                onChange={(event) => setFiles(Array.from(event.target.files || []))}
                type="file"
              />
            </label>

            {files.length ? (
              <div className="file-list">
                {files.map((file) => (
                  <span className="file-pill" key={`${file.name}-${file.size}`}>
                    {file.name}
                  </span>
                ))}
              </div>
            ) : null}

            <button
              className="button button--primary"
              disabled={
                intakeMutation.isPending ||
                !files.length ||
                (mode === "new" && !prompt.trim())
              }
              onClick={() => intakeMutation.mutate()}
              type="button"
            >
              {intakeMutation.isPending
                ? "Submitting..."
                : mode === "upload"
                  ? "Upload Documents"
                  : "Start Assessment"}
            </button>
          </div>
        </div>

        <div className="detail-grid__column">
          <div className="card">
            <div className="card__header">
              <div>
                <p className="page__kicker">Flow Mapping</p>
                <h2 className="section-title">What Happens Next</h2>
              </div>
            </div>
            <div className="stack">
              <div className="item-row">
                <div className="item-row__title">1. Intake</div>
                <div>Vendor record is created and documents are stored.</div>
              </div>
              <div className="item-row">
                <div className="item-row__title">2. Review</div>
                <div>Security, compliance, and financial agents assess the vendor in parallel.</div>
              </div>
              <div className="item-row">
                <div className="item-row__title">3. Evidence / Risk / Approval</div>
                <div>Evidence gaps, risk scoring, and approval routing follow automatically.</div>
              </div>
            </div>
          </div>

          {intakeMutation.isError ? (
            <StateView
              detail="The backend rejected the intake request. Check the prompt, files, and API base configuration."
              title="Submission Failed"
              tone="danger"
            />
          ) : null}
        </div>
      </section>
    </div>
  );
}
