import React, { FormEvent, KeyboardEvent, useLayoutEffect, useRef } from "react";

interface ChatComposerProps {
  value: string;
  isGenerating: boolean;
  isEditing: boolean;
  onChange: (value: string) => void;
  onSubmit: () => void;
  onStop: () => void;
  onCancelEdit: () => void;
}

export const ChatComposer: React.FC<ChatComposerProps> = ({
  value,
  isGenerating,
  isEditing,
  onChange,
  onSubmit,
  onStop,
  onCancelEdit,
}) => {
  const inputRef = useRef<HTMLTextAreaElement>(null);

  useLayoutEffect(() => {
    const input = inputRef.current;
    if (!input) return;
    input.style.height = "auto";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
    input.style.overflowY = input.scrollHeight > 120 ? "auto" : "hidden";
  }, [value]);

  const handleSubmit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (isGenerating) {
      onStop();
    } else if (value.trim()) {
      onSubmit();
    }
  };

  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      if (isGenerating) onStop();
      else if (value.trim()) onSubmit();
    }
  };

  return (
    <div className="input-bar-container">
      {isEditing && (
        <div className="chat-editing-indicator">
          Editing message
          <button type="button" onClick={onCancelEdit}>
            Cancel
          </button>
        </div>
      )}
      <form onSubmit={handleSubmit} className="input-bar-pill">
        <textarea
          ref={inputRef}
          rows={1}
          className="chat-composer-input"
          placeholder="Ask a question..."
          value={value}
          onChange={(event) => onChange(event.target.value)}
          onKeyDown={handleKeyDown}
          aria-label="Ask a question about your documents"
        />
        <button
          type="submit"
          className={`send-pill-btn${isGenerating ? " stop-pill-btn" : ""}`}
          disabled={!isGenerating && !value.trim()}
          aria-label={isGenerating ? "Stop generating" : "Send question"}
          title={isGenerating ? "Stop generating" : "Send question"}
        >
          {isGenerating ? "Stop" : "Send"}
        </button>
      </form>
    </div>
  );
};
