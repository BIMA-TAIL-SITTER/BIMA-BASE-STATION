"use client";

/* eslint-disable @next/next/no-img-element */

import { useState } from "react";
import {
  getIntermediateImageUrl,
  getResultImageUrl,
} from "@/lib/stitchApi";
import type { StitchSessionStatus } from "@/types/stitching";

interface StitchingResultViewerProps {
  sessionId: string | null;
  status: StitchSessionStatus | null;
  intermediates: string[];
  resultRevision: number;
  pendingAction: string | null;
  onTrigger: () => Promise<void>;
}

export function StitchingResultViewer({
  sessionId,
  status,
  intermediates,
  resultRevision,
  pendingAction,
  onTrigger,
}: StitchingResultViewerProps) {
  const [failedResultKey, setFailedResultKey] = useState<string | null>(null);
  const resultKey = `${sessionId ?? "none"}-${resultRevision}`;
  const resultUnavailable = failedResultKey === resultKey;

  const canAttemptResult = Boolean(sessionId && status?.image_count);
  const recentIntermediates = intermediates.slice(-8).reverse();

  return (
    <section className="operations-section stitching-result-section">
      <div className="operations-section-heading">
        <div>
          <h2>Orthomosaic Result</h2>
          <span>
            {sessionId
              ? `Latest output for ${sessionId}`
              : "Select or create a session to begin."}
          </span>
        </div>
        <button
          type="button"
          className="operations-button is-primary"
          onClick={() => void onTrigger()}
          disabled={
            !sessionId
            || !status?.image_count
            || status.is_stitching
            || Boolean(pendingAction)
          }
        >
          {status?.is_stitching ? "Stitching" : "Run Stitch"}
        </button>
      </div>

      <div className="stitching-result-canvas">
        {status?.is_stitching ? (
          <div className="operations-loading-state">
            <span />
            <span />
            <span />
            <strong>Building orthomosaic</strong>
          </div>
        ) : canAttemptResult && !resultUnavailable && sessionId ? (
          <img
            key={resultKey}
            src={getResultImageUrl(sessionId, resultRevision)}
            alt={`Latest stitched orthomosaic for ${sessionId}`}
            onError={() => setFailedResultKey(resultKey)}
          />
        ) : (
          <div className="operations-empty-state">
            <strong>No mosaic result yet</strong>
            <span>
              Upload overlapping aerial images, then run a manual stitch or enable auto-stitch.
            </span>
          </div>
        )}
      </div>

      <div className="stitching-intermediates">
        <div className="stitching-intermediate-heading">
          <strong>Intermediate outputs</strong>
          <span>{intermediates.length} available</span>
        </div>
        {sessionId && recentIntermediates.length ? (
          <div className="stitching-intermediate-list">
            {recentIntermediates.map((fileName) => (
              <a
                key={fileName}
                href={getIntermediateImageUrl(sessionId, fileName)}
                target="_blank"
                rel="noreferrer"
                title={`Open ${fileName}`}
              >
                <img
                  src={getIntermediateImageUrl(sessionId, fileName)}
                  alt={`Intermediate mosaic ${fileName}`}
                  loading="lazy"
                />
                <span>{fileName.replace("intermediateResult_", "PASS ").replace(".png", "")}</span>
              </a>
            ))}
          </div>
        ) : (
          <span className="stitching-intermediate-empty">
            Intermediate passes will appear here during stitching.
          </span>
        )}
      </div>
    </section>
  );
}
