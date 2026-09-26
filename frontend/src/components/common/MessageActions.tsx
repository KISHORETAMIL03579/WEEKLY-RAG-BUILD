import React from "react";

interface MessageActionsProps {
  role: "user" | "assistant";
  copied: boolean;
  disabled?: boolean;
  onCopy: () => void;
  onEdit?: () => void;
  onRetry?: () => void;
}

export const MessageActions: React.FC<MessageActionsProps> = ({
  role,
  copied,
  disabled = false,
  onCopy,
  onEdit,
  onRetry,
}) => (
  <div className="message-actions">
    {role === "user" && onEdit && (
      <button
        type="button"
        className="copy-answer-btn"
        onClick={onEdit}
        disabled={disabled}
        aria-label="Edit question"
      >
        ✎ Edit
      </button>
    )}
    <button
      type="button"
      className="copy-answer-btn"
      onClick={onCopy}
      aria-label={`Copy ${role === "user" ? "question" : "answer"} to clipboard`}
    >
      {copied ? "✓ Copied" : "📋 Copy"}
    </button>
    {role === "assistant" && onRetry && (
      <button
        type="button"
        className="copy-answer-btn"
        onClick={onRetry}
        disabled={disabled}
        aria-label="Retry question"
      >
        ↻ Retry
      </button>
    )}
  </div>
);
