import React from "react";
import { PolicyReadinessState } from "../../hooks/usePolicyReadiness";
import { Banner } from "../common/Banner";

interface ReadinessBannerProps {
  state: PolicyReadinessState;
}

/** The link users follow to upload documents (the Chat page owns the upload control). */
export const UploadDocumentsLink: React.FC<{ label?: string }> = ({
  label = "Go to Chat and upload documents",
}) => (
  <a className="btn-link" href="/">
    {label}
  </a>
);

/**
 * Tells the user, before they run anything, which documents the policy tools will
 * read: file names + chunk counts, retrieval mode and tool count. With nothing
 * indexed it becomes an actionable empty state.
 */
export const ReadinessBanner: React.FC<ReadinessBannerProps> = ({ state }) => {
  const { readiness, isLoading, isRefreshing, error, hasDocuments, refresh } =
    state;

  const refreshButton = (
    <button
      type="button"
      className="btn-secondary btn-small"
      onClick={() => void refresh()}
      disabled={isRefreshing}
    >
      {isRefreshing ? "Checking…" : "↻ Refresh"}
    </button>
  );

  if (isLoading && !readiness) {
    return (
      <Banner tone="neutral" icon={<span className="spinner" />} live="status">
        Checking which documents are indexed…
      </Banner>
    );
  }

  if (error && !readiness) {
    return (
      <Banner
        tone="danger"
        icon="⚠"
        title="Could not read the document status"
        live="alert"
        actions={refreshButton}
      >
        {error}
      </Banner>
    );
  }

  if (!readiness) return null;

  if (!hasDocuments) {
    return (
      <Banner
        tone="warning"
        icon="📄"
        title="No documents are indexed yet"
        live="status"
        actions={
          <>
            <UploadDocumentsLink />
            {refreshButton}
          </>
        }
      >
        Upload the HR policy document and the employee records on the Chat page
        first. The policy tools read only the documents you upload in this
        browser session, so Search and Run stay disabled until something is
        indexed. Come back here afterwards: this page re-checks automatically
        when you return.
      </Banner>
    );
  }

  const notes: string[] = [];
  if (!readiness.groq_configured) {
    notes.push(
      "No model API key is configured on the server, so answers cannot be generated.",
    );
  }
  if (readiness.tools.tool_count === 0) {
    notes.push(
      "No MCP tools were discovered, so the agent and workflow have nothing to call.",
    );
  }

  return (
    <Banner
      tone={notes.length > 0 ? "warning" : "success"}
      icon={notes.length > 0 ? "⚠" : "✓"}
      title={`${readiness.document_count} document${readiness.document_count === 1 ? "" : "s"} indexed · ${readiness.chunk_count.toLocaleString()} chunks searched`}
      live="status"
      actions={refreshButton}
    >
      <div className="u-stack" style={{ gap: 8 }}>
        <div className="chip-list" aria-label="Indexed documents">
          {readiness.documents.map((doc) => (
            <span
              key={doc.doc_id}
              className="chip"
              title={`doc id ${doc.doc_id}`}
            >
              📄 {doc.filename} · {doc.chunks.toLocaleString()} chunk
              {doc.chunks === 1 ? "" : "s"}
            </span>
          ))}
        </div>
        <div className="chip-list">
          <span
            className="chip is-mono tone-info"
            title={
              readiness.retrieval_mode === "hybrid"
                ? "Lexical + embedding retrieval"
                : "Lexical (keyword) retrieval only; no embedding backend is configured"
            }
          >
            retrieval: {readiness.retrieval_mode}
          </span>
          <span
            className="chip is-mono"
            title={readiness.tools.tool_names.join(", ") || "no tools"}
          >
            {readiness.tools.tool_count} tool
            {readiness.tools.tool_count === 1 ? "" : "s"}
          </span>
          <span className="chip is-mono">
            chat backend: {readiness.chat_backend}
          </span>
        </div>
        {notes.map((note) => (
          <div key={note} style={{ color: "var(--amber)" }}>
            {note}
          </div>
        ))}
      </div>
    </Banner>
  );
};
