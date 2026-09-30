import React from "react";

export type BadgeTone =
  "success" | "danger" | "warning" | "info" | "purple" | "neutral";

interface BadgeSpec {
  tone: BadgeTone;
  icon?: string;
  label?: string;
  live?: boolean;
}

const KNOWN: Record<string, BadgeSpec> = {
  // Case / run statuses
  PASS: { tone: "success", icon: "✓" },
  FAIL: { tone: "danger", icon: "✗" },
  ERROR: { tone: "danger", icon: "!" },
  SKIPPED: { tone: "neutral", icon: "↷" },
  WAITING: { tone: "neutral", icon: "○" },
  INTERRUPTED: { tone: "warning", icon: "■" },
  RUNNING: { tone: "info", icon: "⚡", live: true },
  CANCELLING: { tone: "warning", icon: "…", live: true },
  CANCELLED: { tone: "warning", icon: "■" },
  COMPLETED: { tone: "success", icon: "✓" },
  CONNECTED: { tone: "success", icon: "●" },
  // Termination reasons
  SUCCESS: { tone: "success", icon: "✓" },
  NO_EVIDENCE: { tone: "warning", icon: "?" },
  NO_INDEXED_DOCUMENTS: { tone: "warning", icon: "?" },
  // Execution modes
  WORKFLOW: { tone: "success" },
  AGENT: { tone: "warning" },
};

/** Tone for termination reasons the table above does not list explicitly. */
function inferSpec(status: string): BadgeSpec {
  if (status.startsWith("BUDGET_")) return { tone: "warning", icon: "⚠" };
  if (
    status.startsWith("PROVIDER_") ||
    status.startsWith("GROQ_") ||
    status.endsWith("_ERROR") ||
    status.endsWith("_FAILED") ||
    status.endsWith("_UNAVAILABLE")
  ) {
    return { tone: "danger", icon: "!" };
  }
  return { tone: "neutral" };
}

interface StatusBadgeProps {
  /** PASS/FAIL/ERROR/SKIPPED/RUNNING/CANCELLING/WAITING/…, or any termination reason. */
  status: string | null | undefined;
  /** Override the visible text (defaults to the status with underscores as spaces). */
  label?: string;
  size?: "sm" | "lg";
  /** Hide the leading glyph. */
  plain?: boolean;
  title?: string;
}

/**
 * The one place a status becomes a coloured pill. Unknown values render a neutral
 * pill with their own text, and a missing value renders "UNKNOWN", never an empty box.
 */
export const StatusBadge: React.FC<StatusBadgeProps> = ({
  status,
  label,
  size = "sm",
  plain = false,
  title,
}) => {
  const key = (status || "").toString().trim().toUpperCase();
  const spec = KNOWN[key] || inferSpec(key);
  const text = label ?? (key ? key.replace(/_/g, " ") : "UNKNOWN");
  const classes = [
    "status-badge",
    `tone-${spec.tone}`,
    size === "lg" ? "is-lg" : "",
    spec.live ? "is-live" : "",
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <span className={classes} title={title ?? key}>
      {!plain && spec.icon ? (
        <span className="status-badge-icon" aria-hidden="true">
          {spec.icon}
        </span>
      ) : null}
      {text}
    </span>
  );
};

/** PASS / FAIL / not-run pill for a nullable boolean verdict. */
export const VerdictBadge: React.FC<{
  passed: boolean | null | undefined;
  fallback?: string | null;
}> = ({ passed, fallback }) => (
  <StatusBadge
    status={passed === true ? "PASS" : passed === false ? "FAIL" : fallback}
  />
);
