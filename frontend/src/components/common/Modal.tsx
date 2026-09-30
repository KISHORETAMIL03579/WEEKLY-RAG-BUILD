import React, { useEffect, useId, useRef } from "react";
import { createPortal } from "react-dom";

const FOCUSABLE =
  'a[href], button:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])';

// Escape must only close the topmost of several stacked modals.
const openModals: symbol[] = [];

interface ModalProps {
  onClose: () => void;
  /** Renders the standard header (title + Close button) and a padded scrolling body. */
  title?: React.ReactNode;
  /** Accessible name when there is no visible `title`. */
  ariaLabel?: string;
  size?: "sm" | "md" | "lg" | "xl";
  /** Children render directly inside the panel (caller supplies header/body layout). */
  bare?: boolean;
  /** With `bare`: pad and scroll the panel itself. */
  padded?: boolean;
  closeOnBackdrop?: boolean;
  children: React.ReactNode;
}

/**
 * Accessible dialog: role=dialog + aria-modal, Escape closes (topmost only), focus moves
 * into the dialog on open, Tab is trapped inside, and focus returns to the opener on close.
 */
export const Modal: React.FC<ModalProps> = ({
  onClose,
  title,
  ariaLabel,
  size = "lg",
  bare = false,
  padded = false,
  closeOnBackdrop = true,
  children,
}) => {
  const panelRef = useRef<HTMLDivElement>(null);
  const titleId = useId();
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;
  const pressStartedOnBackdrop = useRef(false);

  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null;
    const token = Symbol("modal");
    openModals.push(token);
    const panel = panelRef.current;
    if (panel) {
      const preferred = panel.querySelector<HTMLElement>("[data-autofocus]");
      (preferred || panel).focus();
    }

    const onKeyDown = (event: KeyboardEvent) => {
      if (openModals[openModals.length - 1] !== token) return;
      if (event.key === "Escape") {
        event.stopPropagation();
        event.preventDefault();
        onCloseRef.current();
        return;
      }
      if (event.key !== "Tab" || !panel) return;
      const items = Array.from(
        panel.querySelectorAll<HTMLElement>(FOCUSABLE),
      ).filter(
        (el) => el.offsetParent !== null || el === document.activeElement,
      );
      if (items.length === 0) {
        event.preventDefault();
        panel.focus();
        return;
      }
      const first = items[0];
      const last = items[items.length - 1];
      const current = document.activeElement;
      if (event.shiftKey && (current === first || current === panel)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && current === last) {
        event.preventDefault();
        first.focus();
      }
    };

    document.addEventListener("keydown", onKeyDown, true);
    return () => {
      document.removeEventListener("keydown", onKeyDown, true);
      const index = openModals.indexOf(token);
      if (index >= 0) openModals.splice(index, 1);
      if (
        opener &&
        typeof opener.focus === "function" &&
        document.contains(opener)
      ) {
        opener.focus();
      }
    };
  }, []);

  const panelClasses = [
    "modal-panel",
    `is-${size}`,
    bare && padded ? "is-padded" : "",
  ]
    .filter(Boolean)
    .join(" ");

  return createPortal(
    <div
      className="modal-backdrop"
      onMouseDown={(event) => {
        pressStartedOnBackdrop.current = event.target === event.currentTarget;
      }}
      onClick={(event) => {
        if (
          closeOnBackdrop &&
          pressStartedOnBackdrop.current &&
          event.target === event.currentTarget
        ) {
          onCloseRef.current();
        }
        pressStartedOnBackdrop.current = false;
      }}
    >
      <div
        ref={panelRef}
        className={panelClasses}
        role="dialog"
        aria-modal="true"
        aria-labelledby={title ? titleId : undefined}
        aria-label={title ? undefined : ariaLabel}
        tabIndex={-1}
      >
        {bare ? (
          children
        ) : (
          <>
            <div className="modal-header">
              <h2 className="modal-title" id={titleId}>
                {title}
              </h2>
              <button
                type="button"
                className="modal-close"
                onClick={() => onCloseRef.current()}
                aria-label="Close dialog"
              >
                ✕ Close
              </button>
            </div>
            <div className="modal-body">{children}</div>
          </>
        )}
      </div>
    </div>,
    document.body,
  );
};
