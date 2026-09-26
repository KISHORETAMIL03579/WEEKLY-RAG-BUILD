import React from "react";
import { CancelButton } from "../common/CancelButton";
import { ProgressBar } from "../common/ProgressBar";

export interface SignalStatus {
  label: string;
  completed: number;
  total: number;
  agreementPct?: number | string | null;
  statusText?: string;
  color?: string;
}

export interface EvaluationProgressCardProps {
  title?: string;
  current: number;
  total: number;
  pct?: number;
  currentCaseId?: string | null;
  currentQuestion?: string | null;
  elapsedSeconds?: number;
  estRemainingSeconds?: number;
  isRunning: boolean;
  isComplete: boolean;
  statusText?: string;
  configurationText?: string;
  signals?: SignalStatus[];
  onCancel?: () => void;
  error?: string | null;
}

const formatDuration = (seconds?: number) => {
  if (seconds === undefined || seconds === null || isNaN(seconds))
    return "00:00";
  const mins = Math.floor(seconds / 60);
  const secs = Math.max(0, Math.floor(seconds % 60));
  return `${mins.toString().padStart(2, "0")}:${secs.toString().padStart(2, "0")}`;
};

export const EvaluationProgressCard: React.FC<EvaluationProgressCardProps> = ({
  title,
  current,
  total,
  pct: customPct,
  currentCaseId,
  currentQuestion,
  elapsedSeconds = 0,
  estRemainingSeconds = 0,
  isRunning,
  isComplete,
  statusText,
  configurationText,
  signals = [],
  onCancel,
  error,
}) => {
  const calculatedPct =
    total > 0
      ? Math.min(100, Math.max(0, Math.round((current / total) * 100)))
      : 0;
  const pct = customPct !== undefined ? customPct : calculatedPct;

  const displayTitle =
    title ||
    (isComplete
      ? `Evaluation Complete: 100% (All ${total} Cases)`
      : isRunning
        ? `Evaluation Running: ${pct}%`
        : "Evaluation Ready");

  return (
    <div
      style={{
        background: isComplete
          ? "linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(15, 23, 42, 0.95))"
          : error
            ? "linear-gradient(135deg, rgba(239, 68, 68, 0.15), rgba(15, 23, 42, 0.95))"
            : "linear-gradient(135deg, rgba(30, 58, 138, 0.35), rgba(15, 23, 42, 0.95))",
        border: isComplete
          ? "1px solid rgba(16, 185, 129, 0.4)"
          : error
            ? "1px solid rgba(239, 68, 68, 0.45)"
            : "1px solid rgba(59, 130, 246, 0.45)",
        borderRadius: "12px",
        padding: "18px 24px",
        boxShadow: "0 8px 32px rgba(0, 0, 0, 0.35)",
        display: "flex",
        flexDirection: "column",
        gap: "12px",
      }}
    >
      {/* Top Header Row */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: "12px" }}>
          {isRunning ? (
            <span
              className="spinner"
              style={{ width: "20px", height: "20px" }}
            />
          ) : isComplete ? (
            <span style={{ fontSize: "1.3rem" }}>✅</span>
          ) : error ? (
            <span style={{ fontSize: "1.3rem" }}>⚠️</span>
          ) : (
            <span style={{ fontSize: "1.3rem" }}>⚡</span>
          )}
          <div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                gap: "10px",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{ fontWeight: 800, fontSize: "1.15rem", color: "#fff" }}
              >
                {displayTitle}
              </span>
              <span
                style={{
                  background: isComplete
                    ? "rgba(16, 185, 129, 0.2)"
                    : isRunning
                      ? "rgba(59, 130, 246, 0.2)"
                      : "rgba(255, 255, 255, 0.1)",
                  color: isComplete
                    ? "#34d399"
                    : isRunning
                      ? "#60a5fa"
                      : "var(--text-muted)",
                  fontSize: "0.78rem",
                  fontWeight: 700,
                  padding: "2px 8px",
                  borderRadius: "6px",
                  fontFamily: "ui-monospace, monospace",
                }}
              >
                {current} / {total} COMPLETED
              </span>
            </div>
            <div
              style={{
                fontSize: "0.78rem",
                color: "var(--text-muted)",
                marginTop: "2px",
              }}
            >
              {statusText ||
                (isComplete
                  ? `Processed all ${total} test cases successfully.`
                  : isRunning
                    ? `${Math.max(0, total - current)} test case(s) remaining in this run.`
                    : `Ready to run benchmark across ${total} canonical cases.`)}
            </div>
          </div>
        </div>

        {/* Timers & Actions */}
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "10px",
            flexWrap: "wrap",
          }}
        >
          {elapsedSeconds > 0 && (
            <div
              style={{
                background: "rgba(255, 255, 255, 0.05)",
                border: "1px solid var(--border)",
                padding: "4px 10px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                color: "var(--text-muted)",
              }}
            >
              ⏱ Elapsed:{" "}
              <strong style={{ color: "#fff" }}>
                {formatDuration(elapsedSeconds)}
              </strong>
            </div>
          )}
          {isRunning && estRemainingSeconds > 0 && (
            <div
              style={{
                background: "rgba(59, 130, 246, 0.1)",
                border: "1px solid rgba(59, 130, 246, 0.25)",
                padding: "4px 10px",
                borderRadius: "6px",
                fontSize: "0.8rem",
                color: "#93c5fd",
              }}
            >
              ⏳ Est. Left:{" "}
              <strong>~{formatDuration(estRemainingSeconds)}</strong>
            </div>
          )}
          {isRunning && onCancel && (
            <CancelButton
              onClick={onCancel}
              className="btn-secondary"
              style={{
                color: "#f87171",
                borderColor: "rgba(239, 68, 68, 0.4)",
                background: "rgba(239, 68, 68, 0.1)",
                padding: "5px 12px",
                fontSize: "0.8rem",
                fontWeight: 600,
              }}
              title="Cancel ongoing evaluation"
            >
              🛑 Cancel
            </CancelButton>
          )}
        </div>
      </div>

      {/* Progress Bar Track */}
      <ProgressBar
        ariaLabel="Evaluation progress"
        percentage={pct}
        trackStyle={{
          width: "100%",
          height: "12px",
          background: "rgba(255, 255, 255, 0.07)",
          borderRadius: "8px",
          overflow: "hidden",
          position: "relative",
          boxShadow: "inset 0 1px 3px rgba(0, 0, 0, 0.4)",
        }}
        fillStyle={{
          height: "100%",
          background: isComplete
            ? "linear-gradient(90deg, #10b981, #34d399)"
            : error
              ? "linear-gradient(90deg, #ef4444, #f87171)"
              : "linear-gradient(90deg, #2563eb, #3b82f6, #60a5fa, #34d399)",
          borderRadius: "8px",
          transition: "width 0.35s cubic-bezier(0.4, 0, 0.2, 1)",
          boxShadow: "0 0 14px rgba(59, 130, 246, 0.65)",
        }}
      />

      {/* Signals Status Bar */}
      {signals.length > 0 && (
        <div
          style={{
            display: "flex",
            gap: "12px",
            alignItems: "center",
            flexWrap: "wrap",
            padding: "8px 12px",
            background: "rgba(0, 0, 0, 0.25)",
            borderRadius: "8px",
            border: "1px solid rgba(255, 255, 255, 0.06)",
            fontSize: "0.8rem",
          }}
        >
          <span style={{ color: "var(--text-muted)", fontWeight: 600 }}>
            Signals:
          </span>
          {signals.map((sig, idx) => (
            <div
              key={idx}
              style={{
                display: "inline-flex",
                alignItems: "center",
                gap: "6px",
                background: "rgba(255, 255, 255, 0.04)",
                padding: "3px 8px",
                borderRadius: "5px",
                border: "1px solid rgba(255, 255, 255, 0.08)",
              }}
            >
              <strong style={{ color: sig.color || "#93c5fd" }}>
                {sig.label}:
              </strong>
              <span
                style={{ fontFamily: "ui-monospace, monospace", color: "#fff" }}
              >
                {sig.completed}/{sig.total}
              </span>
              {sig.agreementPct !== undefined && sig.agreementPct !== null && (
                <span
                  style={{
                    fontSize: "0.72rem",
                    color: "#34d399",
                    background: "rgba(16, 185, 129, 0.15)",
                    padding: "1px 5px",
                    borderRadius: "4px",
                    fontWeight: 700,
                  }}
                >
                  {sig.agreementPct}%
                </span>
              )}
              {sig.statusText && (
                <span
                  style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}
                >
                  ({sig.statusText})
                </span>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Current Case Step Footer */}
      {isRunning && (currentCaseId || currentQuestion) && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "0.78rem",
            color: "var(--text-muted)",
            background: "rgba(0, 0, 0, 0.3)",
            padding: "7px 12px",
            borderRadius: "6px",
            border: "1px solid rgba(255, 255, 255, 0.05)",
          }}
        >
          <span
            style={{
              color: "#fbbf24",
              fontWeight: 700,
              letterSpacing: "0.04em",
            }}
          >
            ⚡ CURRENT STEP:
          </span>
          {currentCaseId && (
            <span
              style={{
                fontFamily: "ui-monospace, monospace",
                color: "#93c5fd",
                background: "rgba(59, 130, 246, 0.2)",
                padding: "1px 7px",
                borderRadius: "4px",
                fontWeight: 700,
              }}
            >
              {currentCaseId}
            </span>
          )}
          {currentQuestion && (
            <span
              style={{
                color: "#e2e8f0",
                overflow: "hidden",
                textOverflow: "ellipsis",
                whiteSpace: "nowrap",
                maxWidth: "700px",
              }}
            >
              "{currentQuestion}"
            </span>
          )}
        </div>
      )}

      {/* Frozen Active Configuration Tag */}
      {configurationText && (
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "8px",
            fontSize: "0.74rem",
            color: "var(--text-muted)",
            fontFamily: "ui-monospace, monospace",
          }}
        >
          <span>
            {isRunning ? "🔒 Configuration Frozen:" : "⚙️ Configuration:"}
          </span>
          <span style={{ color: "#93c5fd" }}>{configurationText}</span>
        </div>
      )}
    </div>
  );
};
