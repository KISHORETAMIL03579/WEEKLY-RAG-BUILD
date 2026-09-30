import React from "react";

export type ProgressTone =
  "accent" | "success" | "warning" | "danger" | "rainbow";

interface ProgressBarProps {
  percentage: number;
  ariaLabel: string;
  tone?: ProgressTone;
  size?: "md" | "lg";
  className?: string;
}

/** Class-based progress bar (styles: .progress, .progress-fill.tone-*). */
export const ProgressBar: React.FC<ProgressBarProps> = ({
  percentage,
  ariaLabel,
  tone = "accent",
  size = "md",
  className,
}) => {
  const safePercentage = Number.isFinite(percentage)
    ? Math.min(100, Math.max(0, percentage))
    : 0;

  return (
    <div
      role="progressbar"
      aria-label={ariaLabel}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={safePercentage}
      className={["progress", size === "lg" ? "is-lg" : "", className || ""]
        .filter(Boolean)
        .join(" ")}
    >
      <div
        className={`progress-fill tone-${tone}`}
        style={{ width: `${safePercentage}%` }}
      />
    </div>
  );
};
