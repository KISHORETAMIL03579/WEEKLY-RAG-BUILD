// Full, honest execution trace of one policy run: routing decision, every tool call
// (arguments, result summary, attempts/retries, rationale), rejected calls, the tool
// audit, retry summary, citation check, answer criteria and measured telemetry.
// Used by Policy Search and by the benchmark case drawer.
import React from "react";
import {
  AnswerCriterion,
  CitationCheck,
  LlmCallRecord,
  PolicyOutputContract,
  RejectedToolCall,
  RetryRecord,
  RoutingDecision,
  ToolAudit,
  ToolCallRecord,
} from "../../types/policy";
import {
  clipText,
  formatInt,
  formatMs,
  formatUsd,
  prettyJson,
} from "../../utils/helpers";
import { CopyJsonButton } from "../common/CopyJsonButton";
import { DataTable } from "../common/DataTable";
import { StatusBadge } from "../common/StatusBadge";

// ── helpers ───────────────────────────────────────────────────────────────────

type Rec = Record<string, unknown>;

function asRecord(value: unknown): Rec | null {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Rec)
    : null;
}

function isScalar(value: unknown): value is string | number | boolean | null {
  return (
    value === null ||
    typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
  );
}

function scalarText(value: unknown): string {
  if (value === null || value === undefined) return "—";
  return String(value);
}

const TERMINATION_HELP: Record<string, string> = {
  NO_EVIDENCE:
    "The uploaded documents do not say anything about this request, so no answer was invented.",
  EMPLOYEE_NOT_FOUND:
    "The employee id is not in the uploaded employee records.",
  TOOL_ERROR: "A tool call failed and the run could not recover.",
  MODEL_ERROR: "The model produced an unusable response.",
  GROQ_UNAVAILABLE: "The model provider was unreachable.",
  PROVIDER_TRANSIENT: "The model provider kept failing after retries.",
  BUDGET_TOKENS: "The token budget was used up before an answer was reached.",
  BUDGET_COST:
    "The estimated cost budget was used up before an answer was reached.",
  BUDGET_WALL_CLOCK:
    "The wall-clock budget ran out before an answer was reached.",
  BUDGET_ITERATIONS:
    "The iteration limit was reached before an answer was reached.",
  ERROR: "The run failed unexpectedly.",
};

export const PathSequence: React.FC<{
  sequence: readonly string[] | null | undefined;
  tone?: "match" | "miss" | "plain";
}> = ({ sequence, tone = "plain" }) => {
  if (!sequence || sequence.length === 0) {
    return <span className="path-seq is-empty">(no tool calls)</span>;
  }
  return (
    <span
      className={`path-seq${tone === "match" ? " is-match" : tone === "miss" ? " is-miss" : ""}`}
    >
      {sequence.map((name, index) => (
        <React.Fragment key={`${name}-${index}`}>
          {index > 0 && (
            <span className="path-arrow" aria-hidden="true">
              →
            </span>
          )}
          <span>{name}</span>
        </React.Fragment>
      ))}
    </span>
  );
};

const Section: React.FC<{
  title: React.ReactNode;
  aside?: React.ReactNode;
  children: React.ReactNode;
}> = ({ title, aside, children }) => (
  <section className="trace-section">
    <div className="trace-section-title">
      <span>{title}</span>
      {aside}
    </div>
    {children}
  </section>
);

// ── routing ───────────────────────────────────────────────────────────────────

export const RoutingCard: React.FC<{
  result: PolicyOutputContract;
  routing?: RoutingDecision | null;
}> = ({ result, routing }) => {
  const decision = routing || result.routing || null;
  const mode =
    result.execution_mode ||
    decision?.mode ||
    result.implementation ||
    "workflow";
  const complexity = decision?.complexity || result.complexity;
  const reason = decision?.reason || result.routing_reason || "";
  const history = result.mode_history || [];
  const routingMs = decision?.routing_ms ?? result.routing_ms;

  return (
    <div className={`routing-card mode-${mode}`}>
      <div className="u-row">
        <span className="section-label">Routing decision</span>
        <StatusBadge
          status={mode.toUpperCase()}
          label={mode === "agent" ? "AGENT" : "WORKFLOW"}
          plain
        />
        {complexity && (
          <span className="chip" title="Router complexity estimate">
            {complexity}
          </span>
        )}
        {history.length > 1 && (
          <span className="chip tone-warning">
            mode switch: {history.join(" → ")}
          </span>
        )}
        {typeof routingMs === "number" && (
          <span className="chip is-mono" title="Time spent routing">
            routed in {formatMs(routingMs, 2)}
          </span>
        )}
        {result.run_id && (
          <span className="chip is-mono u-right" title="Run id">
            {result.run_id}
          </span>
        )}
      </div>
      {reason && (
        <div className="u-small" style={{ color: "var(--text-secondary)" }}>
          <strong>Why:</strong> {reason}
        </div>
      )}
      {decision && decision.matched_signals.length > 0 && (
        <div className="chip-list" aria-label="Matched routing signals">
          {decision.matched_signals.map((signal) => (
            <span key={signal} className="chip is-mono">
              {signal}
            </span>
          ))}
        </div>
      )}
    </div>
  );
};

// ── tool calls ────────────────────────────────────────────────────────────────

interface Passage {
  chunk_id?: string;
  filename?: string;
  page?: number | null;
  section?: string | null;
  score?: number;
  text?: string;
  truncated?: boolean;
}

const PassageRow: React.FC<{ passage: Passage; rank: number }> = ({
  passage,
  rank,
}) => {
  const text = String(passage.text || "");
  const clipped = clipText(text, 240);
  const isClipped = clipped.length < text.replace(/\s+/g, " ").trim().length;
  return (
    <div className="passage">
      <div className="passage-meta">
        <span className="u-muted">#{rank}</span>
        <strong>{passage.filename || "unknown file"}</strong>
        {passage.page != null && (
          <span className="chip">page {passage.page}</span>
        )}
        {passage.section && (
          <span className="chip" title="Section label">
            {passage.section}
          </span>
        )}
        {typeof passage.score === "number" && (
          <span className="chip is-mono tone-info">
            score {passage.score.toFixed(3)}
          </span>
        )}
      </div>
      <div className="passage-text">{clipped}</div>
      {isClipped && (
        <details className="disclosure">
          <summary>Full passage text</summary>
          <div className="disclosure-body passage-text">{text}</div>
        </details>
      )}
    </div>
  );
};

export const ToolOutputSummary: React.FC<{ call: ToolCallRecord }> = ({
  call,
}) => {
  const output = asRecord(call.output);
  const errorPayload = call.error || asRecord(output?.error);
  if (call.is_error || errorPayload) {
    const err = asRecord(errorPayload) || {};
    return (
      <div className="tool-error-box" role="group" aria-label="Tool error">
        <div>
          <span className="tool-error-code">
            {scalarText(err.code || "TOOL_ERROR")}
          </span>
          {err.retryable === true && (
            <span className="chip tone-warning" style={{ marginLeft: 8 }}>
              retryable
            </span>
          )}
        </div>
        <div>{scalarText(err.message || "The tool reported an error.")}</div>
        {typeof err.hint === "string" && err.hint && (
          <div className="tool-error-hint">
            <strong>Hint:</strong> {err.hint}
          </div>
        )}
      </div>
    );
  }
  if (!output) {
    return (
      <div className="u-small u-muted">Result: {scalarText(call.output)}</div>
    );
  }

  const results = Array.isArray(output.results)
    ? (output.results as Passage[])
    : null;
  if (results) {
    const searched = Array.isArray(output.documents_searched)
      ? (output.documents_searched as string[])
      : [];
    return (
      <div className="u-stack" style={{ gap: 6 }}>
        <div className="u-row" style={{ gap: 6 }}>
          <span className="u-small">
            <strong>{results.length}</strong> passage
            {results.length === 1 ? "" : "s"}
            {output.no_match === true ? " (no match)" : ""}
          </span>
          {typeof output.retrieval_mode === "string" && (
            <span className="chip is-mono">{output.retrieval_mode}</span>
          )}
          {typeof output.jurisdiction === "string" && (
            <span className="chip tone-info">
              jurisdiction: {output.jurisdiction}
            </span>
          )}
          {typeof output.policy_category === "string" && (
            <span className="chip">category: {output.policy_category}</span>
          )}
          {searched.map((name) => (
            <span key={name} className="chip" title="Document searched">
              {name}
            </span>
          ))}
        </div>
        {results.length === 0 ? (
          <div className="u-small" style={{ color: "var(--amber)" }}>
            No passage in the uploaded documents matched this request.
          </div>
        ) : (
          results.map((passage, index) => (
            <PassageRow
              key={passage.chunk_id || index}
              passage={passage}
              rank={index + 1}
            />
          ))
        )}
      </div>
    );
  }

  const fields = asRecord(output.fields);
  const flat: Array<[string, unknown]> = fields
    ? Object.entries(fields)
    : Object.entries(output).filter(
        ([key, value]) => isScalar(value) && key !== "found",
      );
  const source = asRecord(output.source);
  return (
    <div className="u-stack" style={{ gap: 6 }}>
      {flat.length > 0 ? (
        <dl className="kv-grid">
          {flat.map(([key, value]) => (
            <React.Fragment key={key}>
              <dt>{key}</dt>
              <dd>{isScalar(value) ? scalarText(value) : prettyJson(value)}</dd>
            </React.Fragment>
          ))}
        </dl>
      ) : (
        <pre className="json-block">{prettyJson(call.output)}</pre>
      )}
      {source && (
        <div className="u-tiny u-muted">
          source: {scalarText(source.filename)}
          {source.page != null ? `, page ${scalarText(source.page)}` : ""}
        </div>
      )}
    </div>
  );
};

export const ToolCallCard: React.FC<{ call: ToolCallRecord }> = ({ call }) => {
  const attempts = call.attempts ?? 1;
  const retries = call.retries ?? Math.max(0, attempts - 1);
  const rationale = call.selection?.rationale;
  const attemptLog = call.attempt_log || [];
  const failed = Boolean(call.is_error || call.error);
  return (
    <div className={`tool-card${failed ? " is-error" : ""}`}>
      <div className="tool-card-head">
        <span className="tool-step" title={`Step ${call.step}`}>
          {call.step}
        </span>
        <span className="tool-name">{call.tool_name}</span>
        {call.server && (
          <span
            className="chip is-mono"
            title="MCP server that provided this tool"
          >
            {call.server}
          </span>
        )}
        {(call.roles || []).map((role) => (
          <span key={role} className="chip" title="Tool role">
            {role}
          </span>
        ))}
        <span className="u-right u-row" style={{ gap: 6 }}>
          <span
            className={`chip ${retries > 0 ? "tone-warning" : ""}`}
            title="Tool attempts and retries"
          >
            {attempts} attempt{attempts === 1 ? "" : "s"}
            {retries > 0
              ? ` · ${retries} retr${retries === 1 ? "y" : "ies"}`
              : ""}
          </span>
          <span className="chip is-mono">{formatMs(call.latency_ms, 1)}</span>
          <StatusBadge
            status={failed ? "ERROR" : "PASS"}
            label={failed ? "ERROR" : "OK"}
          />
        </span>
      </div>

      {rationale && (
        <div className="tool-rationale">
          <strong style={{ fontStyle: "normal" }}>Why this tool:</strong>{" "}
          {rationale}
        </div>
      )}

      <div>
        <div className="section-label" style={{ marginBottom: 4 }}>
          Arguments
        </div>
        <pre className="json-block">{prettyJson(call.arguments)}</pre>
      </div>

      <div>
        <div className="section-label" style={{ marginBottom: 4 }}>
          Result
        </div>
        <ToolOutputSummary call={call} />
      </div>

      {attemptLog.length > 0 && (
        <details className="disclosure">
          <summary>Attempt log ({attemptLog.length})</summary>
          <div className="disclosure-body">
            <DataTable
              ariaLabel={`Attempt log for ${call.tool_name}`}
              rows={attemptLog}
              rowKey={(row) => String(row.attempt)}
              columns={[
                { key: "n", header: "#", render: (row) => row.attempt },
                {
                  key: "status",
                  header: "Status",
                  render: (row) => (
                    <StatusBadge
                      status={row.status === "ok" ? "PASS" : "ERROR"}
                      label={row.status}
                    />
                  ),
                },
                {
                  key: "detail",
                  header: "Detail",
                  render: (row) => row.detail || "—",
                },
                {
                  key: "retry",
                  header: "Retryable",
                  render: (row) => (row.retryable ? "yes" : "no"),
                },
                {
                  key: "lat",
                  header: "Latency",
                  align: "right",
                  render: (row) => formatMs(row.latency_ms, 1),
                },
              ]}
            />
          </div>
        </details>
      )}

      <details className="disclosure">
        <summary>Raw tool output (JSON)</summary>
        <div className="disclosure-body">
          <pre className="json-block">{prettyJson(call.output)}</pre>
        </div>
      </details>
    </div>
  );
};

const RejectedCalls: React.FC<{ calls: RejectedToolCall[] }> = ({ calls }) => (
  <Section
    title="Rejected tool calls"
    aside={<span className="chip tone-danger">{calls.length}</span>}
  >
    <div className="u-small u-muted">
      The model asked for these calls but the host refused to run them.
    </div>
    {calls.map((call, index) => (
      <div key={index} className="tool-card is-error">
        <div className="tool-card-head">
          {call.step != null && <span className="tool-step">{call.step}</span>}
          <span className="tool-name">{call.tool_name}</span>
          <StatusBadge status="ERROR" label="REJECTED" />
        </div>
        <div className="u-small">
          <strong>Reason:</strong> {call.reason}
        </div>
        {call.arguments !== undefined && (
          <pre className="json-block">{prettyJson(call.arguments)}</pre>
        )}
      </div>
    ))}
  </Section>
);

// ── audit / retries / citation / criteria / telemetry ─────────────────────────

const Chips: React.FC<{
  label: string;
  values: readonly string[] | undefined;
  tone?: "warning" | "danger" | "info";
}> = ({ label, values, tone }) =>
  values && values.length > 0 ? (
    <div className="u-row" style={{ gap: 6 }}>
      <span className="u-small u-muted">{label}</span>
      {values.map((value) => (
        <span
          key={value}
          className={`chip is-mono${tone ? ` tone-${tone}` : ""}`}
        >
          {value}
        </span>
      ))}
    </div>
  ) : null;

export const ToolAuditCard: React.FC<{ audit: ToolAudit }> = ({ audit }) => {
  const ok = audit.selection_ok;
  const extra = audit.extra_tools ?? audit.unexpected_tools ?? [];
  const missing = audit.missing_tools ?? [];
  const duplicates = audit.duplicate_tools ?? [];
  const required = audit.required ?? [];
  return (
    <Section
      title="Tool-selection audit"
      aside={
        ok === true ? (
          <StatusBadge status="PASS" label="SELECTION OK" />
        ) : ok === false ? (
          <StatusBadge status="FAIL" label="SELECTION NOT OK" />
        ) : (
          <StatusBadge status="WAITING" label="NOT JUDGED" plain />
        )
      }
    >
      <div className="panel-inset u-stack" style={{ gap: 8 }}>
        <div className="u-row" style={{ gap: 6 }}>
          <span className="u-small u-muted">Tools selected</span>
          <PathSequence sequence={audit.tools_selected} />
        </div>
        {required.length > 0 && (
          <ul className="check-list" aria-label="Tools the question needs">
            {required.map((group) => (
              <li
                key={group.rule}
                className={`check-item ${group.satisfied ? "is-ok" : "is-bad"}`}
              >
                <span className="check-mark" aria-hidden="true">
                  {group.satisfied ? "✓" : "✗"}
                </span>
                <span>
                  <strong>{group.rule}</strong> needs one of{" "}
                  <span className="u-mono">
                    {group.requires_any.join(", ")}
                  </span>
                  {" — "}
                  {group.reason}
                </span>
              </li>
            ))}
          </ul>
        )}
        <Chips label="Missing" values={missing} tone="danger" />
        <Chips label="Extra" values={extra} tone="warning" />
        <Chips label="Duplicate" values={duplicates} tone="warning" />
        <div className="u-small">
          <span className="u-muted">Rejected calls: </span>
          {audit.rejected_calls ?? 0}
        </div>
        {(audit.reasons || []).length > 0 && (
          <ul className="check-list" aria-label="Audit reasons">
            {(audit.reasons || []).map((reason, index) => (
              <li key={index} className="check-item is-warn">
                <span className="check-mark" aria-hidden="true">
                  !
                </span>
                <span>{reason}</span>
              </li>
            ))}
          </ul>
        )}
        {ok === null || ok === undefined ? (
          <div className="u-tiny u-muted">
            Selection is only judged for runs that completed; a run that stopped
            early never got the chance to call every tool.
          </div>
        ) : null}
      </div>
    </Section>
  );
};

const RetrySummary: React.FC<{
  audit?: ToolAudit;
  history: RetryRecord[];
  maxRetries?: number;
}> = ({ audit, history, maxRetries }) => {
  const retries = audit?.retries;
  const perTool = Object.keys({
    ...(retries?.tool_attempts || {}),
    ...(retries?.tool_retries || {}),
  });
  if (!retries && history.length === 0) return null;
  return (
    <Section title="Retries">
      <div className="stat-strip">
        <div className="panel-inset">
          <div className="u-tiny u-muted">Run attempts</div>
          <strong>{retries?.run_attempts ?? (history.length || 1)}</strong>
          <span className="u-tiny u-muted">
            {" "}
            · {retries?.run_retries ?? Math.max(0, history.length - 1)} retries
            {maxRetries != null ? ` (max ${maxRetries})` : ""}
          </span>
        </div>
        <div className="panel-inset">
          <div className="u-tiny u-muted">Tool retries</div>
          <strong>{retries?.total_tool_retries ?? 0}</strong>
        </div>
        <div className="panel-inset">
          <div className="u-tiny u-muted">Model-call retries</div>
          <strong>{retries?.model_call_retries ?? 0}</strong>
          <span className="u-tiny u-muted">
            {" "}
            of {retries?.model_calls ?? 0} calls
          </span>
        </div>
      </div>
      {perTool.length > 0 && (
        <DataTable
          ariaLabel="Attempts and retries per tool"
          rows={perTool}
          rowKey={(name) => name}
          columns={[
            {
              key: "tool",
              header: "Tool",
              render: (name) => <span className="u-mono">{name}</span>,
            },
            {
              key: "attempts",
              header: "Attempts",
              align: "right",
              render: (name) => retries?.tool_attempts?.[name] ?? 0,
            },
            {
              key: "retries",
              header: "Retries",
              align: "right",
              render: (name) => retries?.tool_retries?.[name] ?? 0,
            },
          ]}
        />
      )}
      {history.length > 0 && (
        <DataTable
          ariaLabel="Run attempts"
          caption="Every run attempt (the final attempt's tool trace is shown above)"
          rows={history}
          rowKey={(row) => String(row.attempt)}
          columns={[
            { key: "n", header: "Attempt", render: (row) => row.attempt },
            {
              key: "status",
              header: "Status",
              render: (row) => <StatusBadge status={row.status} />,
            },
            {
              key: "reason",
              header: "Retry reason",
              render: (row) =>
                row.retry_reason ? (
                  <span>
                    {row.retry_reason}
                    {row.retryable === false ? " (not retryable)" : ""}
                  </span>
                ) : (
                  "—"
                ),
            },
            {
              key: "tools",
              header: "Tools",
              render: (row) => <PathSequence sequence={row.tool_sequence} />,
            },
            {
              key: "tr",
              header: "Tool retries",
              align: "right",
              render: (row) =>
                Object.values(row.tool_retries || {}).reduce(
                  (a, b) => a + b,
                  0,
                ),
            },
            {
              key: "mr",
              header: "Model retries",
              align: "right",
              render: (row) => row.model_call_retries ?? 0,
            },
            {
              key: "tok",
              header: "Tokens",
              align: "right",
              render: (row) => formatInt(row.total_tokens),
            },
            {
              key: "lat",
              header: "Latency",
              align: "right",
              render: (row) => formatMs(row.latency_ms, 0),
            },
          ]}
        />
      )}
    </Section>
  );
};

export const CitationCard: React.FC<{ citation: CitationCheck }> = ({
  citation,
}) => {
  const cited = citation.cited_sections || [];
  const resolved = new Set(citation.resolved_sections || []);
  const unresolved = new Set(citation.unresolved_sections || []);
  return (
    <Section
      title="Citation check"
      aside={
        !citation.has_citation ? (
          <StatusBadge status="WAITING" label="NO SECTION CITED" plain />
        ) : citation.all_resolve ? (
          <StatusBadge status="PASS" label="ALL SECTIONS RESOLVE" />
        ) : (
          <StatusBadge status="FAIL" label="UNRESOLVED SECTION" />
        )
      }
    >
      {cited.length === 0 ? (
        <div className="u-small u-muted">
          The answer's rule text names no numbered handbook section.
        </div>
      ) : (
        <div className="chip-list">
          {cited.map((section) => (
            <span
              key={section}
              className={`chip is-mono ${
                resolved.has(section)
                  ? "tone-success"
                  : unresolved.has(section)
                    ? "tone-danger"
                    : ""
              }`}
              title={
                resolved.has(section)
                  ? "Found as a heading in the uploaded document"
                  : unresolved.has(section)
                    ? "Not found as a heading in the uploaded document"
                    : ""
              }
            >
              {resolved.has(section)
                ? "✓"
                : unresolved.has(section)
                  ? "✗"
                  : "•"}{" "}
              §{section}
            </span>
          ))}
        </div>
      )}
      <div className="u-tiny u-muted">
        Sections are checked against the numbered headings found in the uploaded
        document chunks.
      </div>
    </Section>
  );
};

const CriteriaCard: React.FC<{
  criteria: AnswerCriterion[];
  passed: boolean;
  strictPassed?: boolean;
}> = ({ criteria, passed, strictPassed }) => (
  <Section
    title="Answer criteria"
    aside={
      <>
        <StatusBadge
          status={passed ? "PASS" : "FAIL"}
          label={passed ? "PASS" : "FAIL"}
        />
        {strictPassed !== undefined && (
          <span className="chip" title="Legacy literal-substring verdict">
            strict: {strictPassed ? "pass" : "fail"}
          </span>
        )}
      </>
    }
  >
    <ul className="check-list">
      {criteria.map((criterion) => (
        <li
          key={criterion.criterion}
          className={`check-item ${criterion.satisfied ? "is-ok" : "is-bad"}`}
        >
          <span className="check-mark" aria-hidden="true">
            {criterion.satisfied ? "✓" : "✗"}
          </span>
          <span>
            <strong>{criterion.criterion}</strong>
            {criterion.matched_by ? (
              <span className="u-muted">
                {" "}
                — matched by {criterion.matched_by}
              </span>
            ) : (
              <span className="u-muted"> — not found in the answer</span>
            )}
          </span>
        </li>
      ))}
    </ul>
  </Section>
);

const TOKEN_SOURCE_LABEL: Record<string, string> = {
  groq_live: "Live from Groq",
  proxy_estimate: "Proxy estimate",
  unavailable: "Unavailable",
};

const Telemetry: React.FC<{ result: PolicyOutputContract }> = ({ result }) => {
  const source = result.token_source || "unavailable";
  const calls: LlmCallRecord[] = result.llm_calls || [];
  return (
    <Section title="Telemetry (measured)">
      <div className="stat-strip">
        <div className="panel-inset">
          <div className="u-tiny u-muted">Latency</div>
          <strong>{formatMs(result.latency_ms, 1)}</strong>
          {/* The backend leaves the split at 0 when it does not measure it; show only real values. */}
          {result.router_latency_ms || result.execution_latency_ms ? (
            <div className="u-tiny u-muted">
              {result.router_latency_ms
                ? `router ${formatMs(result.router_latency_ms, 1)}`
                : ""}
              {result.execution_latency_ms
                ? ` · execution ${formatMs(result.execution_latency_ms, 1)}`
                : ""}
            </div>
          ) : null}
          {typeof result.routing_ms === "number" && result.routing_ms > 0 ? (
            <div className="u-tiny u-muted">
              routing {formatMs(result.routing_ms, 2)}
            </div>
          ) : null}
        </div>
        <div className="panel-inset">
          <div className="u-tiny u-muted">Tokens</div>
          <strong>{formatInt(result.total_tokens)}</strong>
          <div className="u-tiny u-muted">
            in {formatInt(result.prompt_tokens)} · out{" "}
            {formatInt(result.completion_tokens)} ·{" "}
            {TOKEN_SOURCE_LABEL[source] || source}
          </div>
        </div>
        <div className="panel-inset">
          <div className="u-tiny u-muted">
            Estimated token cost (proxy, not billing)
          </div>
          <strong>{formatUsd(result.cost_usd)}</strong>
          <div className="u-tiny u-muted">
            Provider billing: {result.provider_cost || "N/A"}
          </div>
        </div>
        <div className="panel-inset">
          <div className="u-tiny u-muted">Iterations</div>
          <strong>{result.iterations}</strong>
          <div className="u-tiny u-muted">
            {result.model ? `model ${result.model}` : ""}
            {result.top_k != null ? ` · K=${result.top_k}` : ""}
            {result.temperature != null ? ` · T=${result.temperature}` : ""}
          </div>
        </div>
      </div>
      {calls.length > 0 && (
        <details className="disclosure">
          <summary>Model calls ({calls.length})</summary>
          <div className="disclosure-body">
            <DataTable
              ariaLabel="Model calls"
              rows={calls}
              rowKey={(row) => String(row.call_index)}
              columns={[
                { key: "i", header: "#", render: (row) => row.call_index },
                {
                  key: "a",
                  header: "Run attempt",
                  render: (row) => row.attempt,
                },
                {
                  key: "pa",
                  header: "Provider attempts",
                  align: "right",
                  render: (row) => row.provider_attempts ?? 1,
                },
                {
                  key: "pr",
                  header: "Provider retries",
                  align: "right",
                  render: (row) => row.provider_retries ?? 0,
                },
                {
                  key: "tok",
                  header: "Tokens",
                  align: "right",
                  render: (row) => formatInt(row.total_tokens),
                },
                {
                  key: "lat",
                  header: "Latency",
                  align: "right",
                  render: (row) => formatMs(row.latency_ms, 0),
                },
                {
                  key: "st",
                  header: "Status",
                  render: (row) => (
                    <StatusBadge status={row.status || "SUCCESS"} />
                  ),
                },
              ]}
            />
          </div>
        </details>
      )}
    </Section>
  );
};

// ── the trace ─────────────────────────────────────────────────────────────────

interface ToolTraceProps {
  result: PolicyOutputContract;
  /** Overrides result.routing (e.g. a routing decision fetched separately). */
  routing?: RoutingDecision | null;
  /** Show the answer card at the top (default true). */
  showAnswer?: boolean;
  /** Show a PASS/FAIL verdict + criteria (benchmark cases; ad-hoc questions have none). */
  showCriteria?: boolean;
  /** Hide the routing card (benchmark drawer shows the mode in its own heading). */
  showRouting?: boolean;
  showCopy?: boolean;
}

export const ToolTrace: React.FC<ToolTraceProps> = ({
  result,
  routing,
  showAnswer = true,
  showCriteria = false,
  showRouting = true,
  showCopy = true,
}) => {
  const toolCalls = result.tool_calls || [];
  const rejected = result.rejected_tool_calls || [];
  const history = result.retry_history || [];
  const criteria = result.answer_criteria || [];
  const failed = result.termination_reason !== "SUCCESS";
  const mode = result.execution_mode || result.implementation;

  return (
    <div className="trace">
      {failed && (
        <div className="tool-error-box" role="alert">
          <div>
            <StatusBadge status={result.termination_reason} />
          </div>
          <div>
            {TERMINATION_HELP[result.termination_reason] ||
              "The run ended before it produced a complete answer."}
          </div>
        </div>
      )}

      {showAnswer && (
        <div
          className={`answer-card${failed || (showCriteria && !result.passed) ? " is-fail" : ""}`}
        >
          <div className="u-row">
            <span className="section-label">Answer</span>
            <StatusBadge status={result.termination_reason} />
            {showCriteria && (
              <StatusBadge status={result.passed ? "PASS" : "FAIL"} />
            )}
          </div>
          <div className="answer-card-value">
            {result.entitlement_value || "— (no entitlement value returned)"}
          </div>
          {result.rule_cited && (
            <div className="answer-card-rule">
              <strong>Rule cited:</strong> {result.rule_cited}
            </div>
          )}
          {result.explanation && (
            <div className="answer-card-explanation">{result.explanation}</div>
          )}
        </div>
      )}

      {showRouting && <RoutingCard result={result} routing={routing} />}

      <Section
        title={mode === "agent" ? "Agent tool calls" : "Workflow tool calls"}
        aside={<span className="chip">{toolCalls.length}</span>}
      >
        {toolCalls.length === 0 ? (
          <div className="panel-inset u-small u-muted">
            No tool was called in this run, so there is nothing to trace.
            {failed ? ` The run ended with ${result.termination_reason}.` : ""}
          </div>
        ) : (
          toolCalls.map((call) => (
            <ToolCallCard key={`${call.step}-${call.tool_name}`} call={call} />
          ))
        )}
      </Section>

      {rejected.length > 0 && <RejectedCalls calls={rejected} />}

      {result.tool_audit && Object.keys(result.tool_audit).length > 0 && (
        <ToolAuditCard audit={result.tool_audit} />
      )}

      <RetrySummary
        audit={result.tool_audit}
        history={history}
        maxRetries={result.max_retries}
      />

      {result.citation && Object.keys(result.citation).length > 0 && (
        <CitationCard citation={result.citation} />
      )}

      {showCriteria && criteria.length > 0 && (
        <CriteriaCard
          criteria={criteria}
          passed={result.passed}
          strictPassed={result.strict_passed}
        />
      )}

      <Telemetry result={result} />

      {showCopy && (
        <div className="u-row">
          <CopyJsonButton value={result} label="Copy JSON" />
          <span className="u-tiny u-muted">
            Copies the raw response exactly as the API returned it.
          </span>
        </div>
      )}
    </div>
  );
};
