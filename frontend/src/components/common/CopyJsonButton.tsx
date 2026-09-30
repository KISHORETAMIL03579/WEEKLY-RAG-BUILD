import React, { useEffect, useRef, useState } from "react";
import { copyText, prettyJson } from "../../utils/helpers";

interface CopyJsonButtonProps {
  /** Anything JSON-serialisable; copied pretty-printed. */
  value: unknown;
  label?: string;
  className?: string;
}

export const CopyJsonButton: React.FC<CopyJsonButtonProps> = ({
  value,
  label = "Copy JSON",
  className = "btn-secondary btn-small",
}) => {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  const onClick = async () => {
    const ok = await copyText(prettyJson(value));
    setState(ok ? "copied" : "failed");
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setState("idle"), 2000);
  };

  return (
    <button type="button" className={className} onClick={onClick}>
      {state === "copied"
        ? "Copied ✓"
        : state === "failed"
          ? "Copy failed"
          : label}
    </button>
  );
};
