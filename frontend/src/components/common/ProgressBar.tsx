import React from "react";

interface ProgressBarProps {
  percentage: number;
  ariaLabel: string;
  trackStyle: React.CSSProperties;
  fillStyle: React.CSSProperties;
}

export const ProgressBar: React.FC<ProgressBarProps> = ({
  percentage,
  ariaLabel,
  trackStyle,
  fillStyle,
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
      style={trackStyle}
    >
      <div
        style={{
          ...fillStyle,
          width: `${safePercentage}%`,
        }}
      />
    </div>
  );
};
