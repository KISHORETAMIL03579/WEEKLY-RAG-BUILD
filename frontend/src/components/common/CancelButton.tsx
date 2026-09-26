import React from "react";

type CancelButtonProps = Omit<
  React.ButtonHTMLAttributes<HTMLButtonElement>,
  "type"
>;

export const CancelButton: React.FC<CancelButtonProps> = ({
  children,
  ...buttonProps
}) => (
  <button type="button" {...buttonProps}>
    {children}
  </button>
);
