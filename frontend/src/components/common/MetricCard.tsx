import React from "react";

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  description: React.ReactNode;
  valueColor: string;
}

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  description,
  valueColor,
}) => (
  <div
    style={{
      background: "var(--bg-surface-elevated)",
      padding: "14px 16px",
      borderRadius: "8px",
      border: "1px solid var(--border)",
    }}
  >
    <div style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
      {label}
    </div>
    <div
      style={{
        fontSize: "1.2rem",
        fontWeight: 800,
        color: valueColor,
        marginTop: "4px",
      }}
    >
      {value}
    </div>
    <div
      style={{
        fontSize: "0.72rem",
        color: "var(--text-muted)",
        marginTop: "2px",
      }}
    >
      {description}
    </div>
  </div>
);
