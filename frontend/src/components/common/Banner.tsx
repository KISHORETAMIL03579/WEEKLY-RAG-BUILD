import React from "react";

interface BannerProps {
  tone?: "neutral" | "success" | "warning" | "danger" | "info";
  icon?: React.ReactNode;
  title?: React.ReactNode;
  actions?: React.ReactNode;
  /** role="alert" for problems that appeared after a user action; "status" otherwise. */
  live?: "alert" | "status";
  className?: string;
  children?: React.ReactNode;
}

export const Banner: React.FC<BannerProps> = ({
  tone = "neutral",
  icon,
  title,
  actions,
  live = "status",
  className,
  children,
}) => (
  <div
    className={`banner tone-${tone}${className ? ` ${className}` : ""}`}
    role={live}
  >
    {icon ? (
      <span className="banner-icon" aria-hidden="true">
        {icon}
      </span>
    ) : null}
    <div className="banner-body">
      {title ? <div className="banner-title">{title}</div> : null}
      {children ? <div className="banner-text">{children}</div> : null}
    </div>
    {actions ? <div className="banner-actions">{actions}</div> : null}
  </div>
);
