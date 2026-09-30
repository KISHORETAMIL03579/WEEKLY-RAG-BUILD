import React from "react";

export type MetricTone =
  "neutral" | "success" | "info" | "warning" | "danger" | "purple";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  hint?: React.ReactNode;
  tone?: MetricTone;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  hint,
  tone = "neutral",
}) => (
  <div className={`metric-card tone-${tone}`}>
    <div className="metric-card-label">{label}</div>
    <div className="metric-card-value">{value}</div>
    {hint ? <div className="metric-card-hint">{hint}</div> : null}
  </div>
);
