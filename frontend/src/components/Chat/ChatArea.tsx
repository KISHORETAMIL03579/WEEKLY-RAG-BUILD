import React, { useState, useEffect, useRef } from 'react';
import { SourceInfo } from '../../types/api';
import { SourceItem } from '../Sources/SourceItem';
import { renderMarkdown } from '../../utils/markdown';
import { copyToClipboard } from '../../utils/helpers';

export interface ChatMessage {
  id: string;
  role: 'user' | 'ai';
  text: string;
  sources?: SourceInfo[];
  query?: string;
  topK?: number;
  temperature?: number;
}

interface ChatAreaProps {
  messages: ChatMessage[];
  onSend: (query: string) => void;
  onStop?: () => void;
  isThinking: boolean;
  filesCount: number;
  selectedFilesCount: number;
  strategy: string;
  strategySelected: boolean;
}

function GroundedSourcesBlock({ sources }: { sources: SourceInfo[] }) {
  const [showDocs, setShowDocs] = useState(false);

  if (!sources || sources.length === 0) return null;

  return (
    <div className="sources-card" style={{ marginTop: 8, overflow: 'hidden' }}>
      <div
        className="sources-header"
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          cursor: 'pointer',
          userSelect: 'none',
          padding: '4px 0',
        }}
        onClick={() => setShowDocs((v) => !v)}
      >
        <span>📄 GROUNDED SOURCES ({sources.length})</span>
        <button
          type="button"
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--accent, #60a5fa)',
            cursor: 'pointer',
            fontSize: '0.75rem',
            fontWeight: 600,
          }}
          aria-expanded={showDocs}
          aria-label={showDocs ? 'Hide documents' : 'View documents'}
        >
          {showDocs ? 'Hide Documents ▲' : 'View Documents ▼'}
        </button>
      </div>

      {showDocs && (
        <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 6 }}>
          {sources.map((src, i) => (
            <SourceItem
              key={`${src.doc_id || 'doc'}-${src.page || 'p'}-${i}`}
              src={src}
              index={i}
            />
          ))}
        </div>
      )}
    </div>
  );
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
  const [input, setInput] = useState('');
  const [copiedId, setCopiedId] = useState<string | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleCopy = async (id: string, text: string) => {
    const ok = await copyToClipboard(text);
    if (ok) {
      setCopiedId(id);
      setTimeout(() => {
        setCopiedId((prev) => (prev === id ? null : prev));
      }, 2000);
    }
  };

  const handleEdit = (text: string) => {
    setInput(text);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(140, Math.max(24, textareaRef.current.scrollHeight))}px`;
      textareaRef.current.focus();
    }
  };

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value);
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
      textareaRef.current.style.height = `${Math.min(140, Math.max(24, textareaRef.current.scrollHeight))}px`;
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      const query = input.trim();
      if (!query || isThinking) return;
      onSend(query);
      setInput('');
      if (textareaRef.current) {
        textareaRef.current.style.height = '24px';
      }
    }
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const query = input.trim();
    if (!query || isThinking) return;
    onSend(query);
    setInput('');
    if (textareaRef.current) {
      textareaRef.current.style.height = '24px';
    }
  };

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, isThinking]);

  /* ── Sequential Onboarding State Machine ─────── */
  const hasIndexedDocs = filesCount > 0;
  const hasStagedFiles = selectedFilesCount > 0;

  // Step 1: Upload / select document
  const isStep1Done = hasStagedFiles || hasIndexedDocs;
  const isStep1Active = !hasStagedFiles && !hasIndexedDocs;

  // Step 2: Choose chunking strategy
  const isStep2Done = strategySelected || hasIndexedDocs;
  const isStep2Active = hasStagedFiles && !strategySelected && !hasIndexedDocs;

  // Step 3: Upload & Index
  const isStep3Done = hasIndexedDocs;
  const isStep3Active = hasStagedFiles && (strategySelected || strategy === 'structured') && !hasIndexedDocs;

  // Step 4: Ask a question
  const isStep4Active = hasIndexedDocs;

  return (
    <main className="chat-container">
      <div className="messages-area" style={{ paddingBottom: '32px' }}>
        {messages.length === 0 ? (
          <div className="onboarding-container">
            <div className="onboarding-icon">💬</div>
            <h2 className="onboarding-title">Ask questions about your documents</h2>
            <p className="onboarding-sub">
              Answers are based only on your indexed documents and include source references.
            </p>

            <div className="onboarding-steps">
              <div className={`onboarding-step ${isStep1Done ? 'completed' : isStep1Active ? 'active' : ''}`}>
                {isStep1Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>1. Upload your document</span>
              </div>

              <div className={`onboarding-step ${isStep2Done ? 'completed' : isStep2Active ? 'active' : ''}`}>
                {isStep2Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>2. Configure chunking strategy</span>
              </div>

              <div className={`onboarding-step ${isStep3Done ? 'completed' : isStep3Active ? 'active' : ''}`}>
                {isStep3Done ? (
                  <div className="onboarding-step-check">✓</div>
                ) : (
                  <div className="onboarding-step-radio"></div>
                )}
                <span>3. Upload & Index</span>
              </div>

              <div className={`onboarding-step ${isStep4Active ? 'active' : ''}`}>
                <div className="onboarding-step-radio"></div>
                <span>4. Ask a question</span>
              </div>
            </div>
          </div>
        ) : (
          messages.map((m) => (
            <div key={m.id} className={`message-row ${m.role}`}>
              <div
                className={`message-bubble ${m.role === 'ai' ? 'message-ai-content' : ''}`}
                style={{
                  minWidth: 0,
                  maxWidth: '100%',
                  overflowWrap: 'anywhere',
                  wordBreak: 'break-word',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {m.role === 'ai' ? (
                  <div dangerouslySetInnerHTML={renderMarkdown(m.text)} />
                ) : (
                  <div>{m.text}</div>
                )}

                {/* Grounded Sources (Collapsible) */}
                {m.sources && m.sources.length > 0 && (
                  <GroundedSourcesBlock sources={m.sources} />
                )}

                {/* Metadata & Action Bar */}
                <div
                  className="message-meta-bar"
                  style={{
                    display: 'flex',
                    flexWrap: 'wrap',
                    gap: 6,
                    alignItems: 'center',
                    marginTop: 6,
                  }}
                >
                  {m.role === 'ai' && (
                    <>
                      <span className="meta-pill">🎯 Top-K: {m.topK != null ? m.topK : 8}</span>
                      <span className="meta-pill">
                        🌡️ Temp: {m.temperature != null ? Number(m.temperature).toFixed(2) : '0.00'}
                      </span>
                      {m.sources && <span className="meta-pill">📄 {m.sources.length} sources</span>}
                      <button
                        type="button"
                        onClick={() => handleCopy(m.id, m.text)}
                        className="copy-answer-btn"
                        title="Copy response to clipboard"
                        aria-label="Copy response"
                      >
                        {copiedId === m.id ? '✓ Copied' : '📋 Copy'}
                      </button>
                    </>
                  )}

                  {m.role === 'user' && (
                    <>
                      <button
                        type="button"
                        onClick={() => handleEdit(m.text)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: 'var(--text-muted)',
                          fontSize: '0.72rem',
                          cursor: 'pointer',
                          padding: '2px 6px',
                        }}
                        title="Edit question in composer"
                        aria-label="Edit question"
                      >
                        ✏️ Edit
                      </button>
                      <button
                        type="button"
                        onClick={() => handleCopy(m.id, m.text)}
                        style={{
                          background: 'transparent',
                          border: 'none',
                          color: copiedId === m.id ? '#22c55e' : 'var(--text-muted)',
                          fontSize: '0.72rem',
                          cursor: 'pointer',
                          padding: '2px 6px',
                          fontWeight: copiedId === m.id ? 700 : 400,
                        }}
                        title="Copy question"
                        aria-label="Copy question"
                      >
                        {copiedId === m.id ? '✓ Copied' : '📋 Copy'}
                      </button>
                    </>
                  )}
                </div>
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

      <div className="input-bar-container">
        <form onSubmit={handleSubmit} className="input-bar-pill">
          <textarea
            ref={textareaRef}
            className="query-input-field"
            placeholder={isThinking ? 'Generating answer (you can still type your next question)…' : 'Ask a question (Enter to send, Shift+Enter for newline)…'}
            value={input}
            onChange={handleTextareaChange}
            onKeyDown={handleKeyDown}
            rows={1}
            style={{
              outline: 'none',
              border: 'none',
              boxShadow: 'none',
              background: 'transparent',
              resize: 'none',
            }}
            aria-label="Ask a question about your documents"
          />

          {isThinking ? (
            <button
              type="button"
              onClick={onStop}
              className="stop-pill-btn"
              title="Stop generation"
              aria-label="Stop generation"
            >
              <span>■</span>
              <span>Stop</span>
            </button>
          ) : (
            <button
              type="submit"
              className="send-pill-btn"
              disabled={!input.trim()}
              aria-label="Send question"
            >
              ➤
            </button>
          )}
        </form>
      </div>
    </main>
  );
};
