import React, { useState, useEffect, useRef } from "react";
import { SourceInfo } from "../../types/api";
import { ChatComposer } from "../common/ChatComposer";
import { MessageActions } from "../common/MessageActions";
import { GroundedSources } from "../Sources/GroundedSources";
import { renderMarkdown } from "../../utils/markdown";

export interface ChatMessage {
  id: string;
  turnId: string;
  role: "user" | "ai";
  text: string;
  sources?: SourceInfo[];
  query?: string;
  runId?: string;
  topK?: number;
  temperature?: number;
}

interface ChatAreaProps {
  messages: ChatMessage[];
  onSend: (query: string, turnId?: string) => void;
  onStop: () => void;
  isThinking: boolean;
  filesCount: number;
  selectedFilesCount: number;
  strategy: string;
  strategySelected: boolean;
}

export const ChatArea: React.FC<ChatAreaProps> = ({
  messages,
  onSend,
  onStop,
  isThinking,
  filesCount,
  selectedFilesCount,
  strategy,
  strategySelected,
}) => {
  const [input, setInput] = useState("");
  const [editingTurnId, setEditingTurnId] = useState<string | null>(null);
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);

  const handleCopy = async (id: string, text: string) => {
    if (typeof navigator === "undefined" || !navigator.clipboard) return;
    try {
      await navigator.clipboard.writeText(text);
      setCopiedId(id);
      setTimeout(() => {
        setCopiedId((previous) => (previous === id ? null : previous));
      }, 2000);
    } catch {
      setCopiedId(null);
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages, isThinking]);

  const handleSubmit = () => {
    const query = input.trim();
    if (!query || isThinking) return;
    onSend(query, editingTurnId || undefined);
    setInput("");
    setEditingTurnId(null);
  };

  const startEditing = (turnId: string, text: string) => {
    setInput(text);
    setEditingTurnId(turnId);
  };

  /* ── Sequential Onboarding State Machine ─────── */
  const hasIndexedDocs = filesCount > 0;
  const hasStagedFiles = selectedFilesCount > 0;

  const isStep1Done = hasStagedFiles || hasIndexedDocs;
  const isStep1Active = !hasStagedFiles && !hasIndexedDocs;
  const isStep2Done = strategySelected || hasIndexedDocs;
  const isStep2Active = hasStagedFiles && !strategySelected && !hasIndexedDocs;
  const isStep3Done = hasIndexedDocs;
  const isStep3Active =
    hasStagedFiles &&
    (strategySelected || strategy === "structured") &&
    !hasIndexedDocs;
  const isStep4Active = hasIndexedDocs;

  return (
    <main className="chat-container">
      <div className="messages-area">
        {messages.length === 0 ? (
          <div className="onboarding-container">
            <div className="onboarding-icon">💬</div>
            <h2 className="onboarding-title">
              Ask questions about your documents
            </h2>
            <p className="onboarding-sub">
              Answers are based only on your indexed documents and include
              source references.
            </p>

            <div className="onboarding-steps">
              <div
                className={`onboarding-step ${isStep1Done ? "completed" : isStep1Active ? "active" : ""}`}
              >
                {isStep1Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>1. Upload your document</span>
              </div>

              <div
                className={`onboarding-step ${isStep2Done ? "completed" : isStep2Active ? "active" : ""}`}
              >
                {isStep2Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>2. Configure chunking strategy</span>
              </div>

              <div
                className={`onboarding-step ${isStep3Done ? "completed" : isStep3Active ? "active" : ""}`}
              >
                {isStep3Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>3. Upload & Index</span>
              </div>

              <div
                className={`onboarding-step ${isStep4Active ? "active" : ""}`}
              >
                <div className="onboarding-step-radio"></div>
                <span>4. Ask a question</span>
              </div>
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <div
              key={message.id}
              className={`message-row ${message.role === "ai" ? "ai" : "user"}`}
            >
              <div
                className={`message-bubble ${message.role === "ai" ? "message-ai-content" : ""}`}
              >
                {message.role === "ai" ? (
                  <div dangerouslySetInnerHTML={renderMarkdown(message.text)} />
                ) : (
                  <div>{message.text}</div>
                )}
                {message.role === "ai" && (
                  <>
                    <GroundedSources sources={message.sources} />
                    <div className="message-meta-bar">
                      <span className="meta-pill">
                        🎯 Top-K: {message.topK != null ? message.topK : 8}
                      </span>
                      <span className="meta-pill">
                        🌡️ Temp:{" "}
                        {message.temperature != null
                          ? Number(message.temperature).toFixed(2)
                          : "0.00"}
                      </span>
                      {message.sources && message.sources.length > 0 && (
                        <span className="meta-pill">
                          📄 {message.sources.length} sources
                        </span>
                      )}
                      {message.runId && (
                        <span className="meta-pill" title={message.runId}>
                          Run: {message.runId}
                        </span>
                      )}
                      <MessageActions
                        role="assistant"
                        copied={copiedId === message.id}
                        disabled={isThinking}
                        onCopy={() => handleCopy(message.id, message.text)}
                        onRetry={
                          message.query
                            ? () => onSend(message.query!, message.turnId)
                            : undefined
                        }
                      />
                    </div>
                  </>
                )}
                {message.role === "user" && (
                  <MessageActions
                    role="user"
                    copied={copiedId === message.id}
                    disabled={isThinking}
                    onCopy={() => handleCopy(message.id, message.text)}
                    onEdit={() => startEditing(message.turnId, message.text)}
                  />
                )}
              </div>
            </div>
          ))
        )}

        {isThinking && (
          <div className="message-row ai">
            <div className="message-bubble message-thinking">
              Generating grounded answer...
            </div>
          </div>
        )}
        <div ref={bottomRef} />
      </div>

      <ChatComposer
        value={input}
        isGenerating={isThinking}
        isEditing={editingTurnId !== null}
        onChange={setInput}
        onSubmit={handleSubmit}
        onStop={onStop}
        onCancelEdit={() => {
          setEditingTurnId(null);
          setInput("");
        }}
      />
    </main>
  );
};
