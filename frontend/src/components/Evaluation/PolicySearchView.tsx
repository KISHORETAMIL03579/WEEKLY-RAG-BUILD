// frontend/src/components/Evaluation/PolicySearchView.tsx
// Week 7 — Production HR Policy Search with Automatic Routing
//
// Flow: User Question → Auto Router → Workflow / Agent → Answer + Full Telemetry
//
// The UI shows routing decision immediately, then execution progress,
// then tokens / latency / cost without fabricating any values.
import React, { useEffect, useState, useRef } from "react";
import { api } from "../../services/api";
import {
  PolicyOutputContract,
  RoutingDecision,
  RetryRecord,
} from "../../types/policy";

interface PolicySearchViewProps {
  onNotify: (msg: string, type?: "info" | "success" | "error") => void;
}

const MODE_COLORS: Record<string, string> = {
  workflow: "#22c55e",
  agent: "#f59e0b",
};

const COMPLEXITY_COLORS: Record<string, string> = {
  SIMPLE: "#22c55e",
  MODERATE: "#f59e0b",
  COMPLEX: "#ef4444",
};

const EXAMPLE_QUESTIONS: { empId: string; question: string }[] = [
  {
    empId: "EMP001",
    question:
      "What is the standard annual leave entitlement and monthly accrual rate for EMP001?",
  },
  {
    empId: "EMP003",
    question:
      "How much written notice must EMP003 provide if they decide to resign while on probation?",
  },
  {
    empId: "EMP007",
    question:
      "What severance payment and notice period is EMP007 entitled to upon separation due to redundancy with 4 completed years of service?",
  },
  {
    empId: "EMP009",
    question:
      "Is EMP009 currently eligible to receive the 10% pension contribution allowance while on probation?",
  },
  {
    empId: "EMP005",
    question:
      "Compare the statutory minimum sick leave days in Ireland versus the organisational policy for EMP005.",
  },
];

function TokenPanel({ result }: { result: PolicyOutputContract }) {
  const [expanded, setExpanded] = useState(false);
  const src = result.token_source || "unavailable";
  const srcLabel =
    src === "ollama_live"
      ? "🟢 Live Ollama"
      : src === "proxy_estimate"
        ? "🟡 Proxy Estimate"
        : "⚪ Unavailable";

  if (result.total_tokens === 0 && src === "unavailable") {
    return (
      <div
        style={{
          padding: "8px 12px",
          background: "rgba(255,255,255,0.04)",
          borderRadius: 6,
          fontSize: "0.82rem",
          color: "var(--text-muted)",
        }}
      >
        Token usage: <strong>Unavailable</strong> — token_source: unavailable
      </div>
    );
  }

  return (
    <div
      style={{
        background: "rgba(255,255,255,0.04)",
        borderRadius: 6,
        overflow: "hidden",
      }}
    >
      <button
        onClick={() => setExpanded((e) => !e)}
        style={{
          width: "100%",
          textAlign: "left",
          padding: "8px 12px",
          background: "none",
          border: "none",
          cursor: "pointer",
          color: "var(--text-primary)",
          fontSize: "0.83rem",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <span>
          🪙 Token Usage &nbsp;
          <span style={{ color: "var(--text-muted)", fontWeight: 400 }}>
            ({srcLabel})
          </span>
          &nbsp;·&nbsp;
          <strong>Total: {result.total_tokens.toLocaleString()}</strong>
        </span>
        <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
          {expanded ? "▲ collapse" : "▼ details"}
        </span>
      </button>
      {expanded && (
        <div
          style={{
            padding: "0 12px 12px",
            display: "flex",
            flexDirection: "column",
            gap: 6,
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "1fr 1fr 1fr",
              gap: 8,
            }}
          >
            {[
              { label: "Input Tokens", val: result.prompt_tokens },
              { label: "Output Tokens", val: result.completion_tokens },
              { label: "Total Tokens", val: result.total_tokens },
            ].map(({ label, val }) => (
              <div
                key={label}
                style={{
                  background: "rgba(255,255,255,0.06)",
                  borderRadius: 4,
                  padding: "6px 10px",
                  textAlign: "center",
                }}
              >
                <div
                  style={{ fontSize: "0.72rem", color: "var(--text-muted)" }}
                >
                  {label}
                </div>
                <div style={{ fontSize: "1rem", fontWeight: 700 }}>
                  {val.toLocaleString()}
                </div>
              </div>
            ))}
          </div>
          {result.retry_history && result.retry_history.length > 1 && (
            <div style={{ marginTop: 6 }}>
              <div
                style={{
                  fontSize: "0.75rem",
                  color: "var(--text-muted)",
                  marginBottom: 4,
                }}
              >
                Per-Attempt Breakdown (tokens accumulate across retries):
              </div>
              {result.retry_history.map((r: RetryRecord, i: number) => (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    gap: 12,
                    fontSize: "0.78rem",
                    padding: "3px 0",
                    borderBottom: "1px solid rgba(255,255,255,0.05)",
                  }}
                >
                  <span
                    style={{
                      color: r.is_retry ? "#f59e0b" : "var(--text-muted)",
                      minWidth: 90,
                    }}
                  >
                    {r.is_retry ? `🔄 Retry ${r.attempt - 1}` : "▶ Attempt 1"}
                  </span>
                  <span>In: {r.input_tokens}</span>
                  <span>Out: {r.output_tokens}</span>
                  <span>Total: {r.total_tokens}</span>
                  <span
                    style={{
                      color: r.status === "SUCCESS" ? "#22c55e" : "#ef4444",
                    }}
                  >
                    {r.status}
                  </span>
                  {r.retry_reason && (
                    <span style={{ color: "#f59e0b" }}>{r.retry_reason}</span>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function RoutingBadge({ result }: { result: PolicyOutputContract }) {
  const mode = result.execution_mode || result.implementation || "workflow";
  const complexity = result.complexity || "SIMPLE";
  const reason = result.routing_reason || result.routing?.reason || "";
  const runId = result.run_id || "";
  const modeHistory = result.mode_history || [mode];

  return (
    <div
      style={{
        background: "rgba(255,255,255,0.04)",
        borderRadius: 8,
        border: "1px solid rgba(255,255,255,0.08)",
        padding: "12px 16px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      <div
        style={{
          display: "flex",
          gap: 10,
          flexWrap: "wrap",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: "0.72rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Execution Mode
          </span>
          {modeHistory.length > 1 ? (
            <div style={{ display: "flex", alignItems: "center", gap: 4 }}>
              {modeHistory.map((m, i) => (
                <React.Fragment key={i}>
                  <span
                    style={{
                      background: `${MODE_COLORS[m]}22`,
                      color: MODE_COLORS[m],
                      padding: "2px 8px",
                      borderRadius: 4,
                      fontSize: "0.8rem",
                      fontWeight: 700,
                    }}
                  >
                    {m.toUpperCase()}
                  </span>
                  {i < modeHistory.length - 1 && (
                    <span style={{ color: "var(--text-muted)" }}>→</span>
                  )}
                </React.Fragment>
              ))}
              <span
                style={{ fontSize: "0.72rem", color: "#f59e0b", marginLeft: 4 }}
              >
                MODE SWITCH
              </span>
            </div>
          ) : (
            <span
              style={{
                background: `${MODE_COLORS[mode]}22`,
                color: MODE_COLORS[mode],
                padding: "2px 8px",
                borderRadius: 4,
                fontSize: "0.8rem",
                fontWeight: 700,
              }}
            >
              {mode.toUpperCase()}
            </span>
          )}
        </div>
        <div style={{ display: "flex", alignItems: "center", gap: 6 }}>
          <span
            style={{
              fontSize: "0.72rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              letterSpacing: "0.05em",
            }}
          >
            Complexity
          </span>
          <span
            style={{
              background: `${COMPLEXITY_COLORS[complexity]}22`,
              color: COMPLEXITY_COLORS[complexity],
              padding: "2px 8px",
              borderRadius: 4,
              fontSize: "0.8rem",
              fontWeight: 700,
            }}
          >
            {complexity}
          </span>
        </div>
        {runId && (
          <div
            style={{
              fontSize: "0.72rem",
              color: "var(--text-muted)",
              fontFamily: "monospace",
            }}
          >
            Run ID:{" "}
            <span style={{ color: "var(--text-primary)" }}>{runId}</span>
          </div>
        )}
      </div>
      {reason && (
        <div
          style={{
            fontSize: "0.82rem",
            color: "var(--text-muted)",
            borderLeft: `3px solid ${MODE_COLORS[mode]}`,
            paddingLeft: 8,
          }}
        >
          <em>Why: "{reason}"</em>
        </div>
      )}
    </div>
  );
}

function ExecutionSteps({ result }: { result: PolicyOutputContract }) {
  const mode = result.execution_mode || result.implementation || "workflow";
  const toolCalls = result.tool_calls || [];
  const retryHistory = result.retry_history || [];
  const hasRetries = retryHistory.some((r) => r.is_retry);

  const steps: {
    icon: string;
    label: string;
    detail?: string;
    color?: string;
  }[] = [
    {
      icon: "🔀",
      label: "Route",
      detail: `${mode === "agent" ? "AGENT" : "NORMAL WORKFLOW"} • ${result.routing_ms?.toFixed(1) || 0}ms`,
    },
    ...toolCalls.map((tc) => ({
      icon:
        tc.tool_name === "get_employee_record"
          ? "👤"
          : tc.tool_name === "search_handbook"
            ? "📖"
            : "⚖️",
      label: tc.tool_name,
      detail: `${tc.latency_ms?.toFixed(2) || 0}ms`,
    })),
    ...(hasRetries
      ? retryHistory
          .filter((r) => r.is_retry)
          .map((r) => ({
            icon: "🔄",
            label: `Retry ${r.attempt - 1}/${result.max_retries || 2}`,
            detail: `${r.retry_reason || "transient error"} • ${r.latency_ms.toFixed(1)}ms`,
            color: "#f59e0b",
          }))
      : []),
    {
      icon: "✅",
      label: "Final Answer",
      detail: result.termination_reason,
      color: result.termination_reason === "SUCCESS" ? "#22c55e" : "#ef4444",
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      {steps.map((step, i) => (
        <div
          key={i}
          style={{
            display: "flex",
            alignItems: "center",
            gap: 10,
            padding: "5px 10px",
            background: "rgba(255,255,255,0.03)",
            borderRadius: 5,
          }}
        >
          <span style={{ minWidth: 20, textAlign: "center" }}>{step.icon}</span>
          <span
            style={{
              fontSize: "0.83rem",
              fontWeight: 600,
              color: step.color || "var(--text-primary)",
              minWidth: 180,
            }}
          >
            [{i + 1}] {step.label}
          </span>
          {step.detail && (
            <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>
              {step.detail}
            </span>
          )}
        </div>
      ))}
    </div>
  );
}

function ResultCard({ result }: { result: PolicyOutputContract }) {
  const mode = result.execution_mode || result.implementation || "workflow";
  const totalAttempts = result.total_attempts || 1;
  const maxRetries = result.max_retries ?? 2;

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      {/* Routing Decision */}
      <RoutingBadge result={result} />

      {/* Answer */}
      <div
        style={{
          background: "rgba(34,197,94,0.06)",
          border: "1px solid rgba(34,197,94,0.2)",
          borderRadius: 8,
          padding: "12px 16px",
        }}
      >
        <div
          style={{
            fontSize: "0.75rem",
            color: "#22c55e",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            marginBottom: 4,
          }}
        >
          Answer
        </div>
        <div style={{ fontSize: "0.92rem", fontWeight: 600 }}>
          {result.entitlement_value || "—"}
        </div>
        {result.rule_cited && (
          <div
            style={{
              fontSize: "0.78rem",
              color: "var(--text-muted)",
              marginTop: 4,
            }}
          >
            Rule: {result.rule_cited}
          </div>
        )}
        {result.explanation && (
          <div
            style={{
              fontSize: "0.82rem",
              color: "var(--text-muted)",
              marginTop: 6,
            }}
          >
            {result.explanation}
          </div>
        )}
      </div>

      {/* Execution Steps */}
      <div>
        <div
          style={{
            fontSize: "0.75rem",
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            marginBottom: 6,
          }}
        >
          {mode === "agent" ? "AGENT EXECUTION" : "WORKFLOW EXECUTION"}
        </div>
        <ExecutionSteps result={result} />
      </div>

      {/* Retry status */}
      {totalAttempts > 1 && (
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            fontSize: "0.82rem",
          }}
        >
          <span style={{ color: "#f59e0b" }}>🔄 Retried</span>
          <span style={{ color: "var(--text-muted)" }}>
            Attempt {totalAttempts} / {1 + maxRetries} max
          </span>
        </div>
      )}

      {/* Metrics row */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, 1fr)",
          gap: 8,
        }}
      >
        {[
          {
            label: "Latency",
            val: `${result.latency_ms?.toFixed(1) || 0} ms`,
            sub: "time.perf_counter()",
          },
          {
            label: "Estimated Token Cost",
            val: `$${result.cost_usd?.toFixed(6) || "0.000000"}`,
            sub: "Provider Cost: N/A (local Ollama)",
          },
          {
            label: "Status",
            val: result.termination_reason || "SUCCESS",
            sub: `Iterations: ${result.iterations}`,
          },
        ].map(({ label, val, sub }) => (
          <div
            key={label}
            style={{
              background: "rgba(255,255,255,0.04)",
              borderRadius: 6,
              padding: "8px 10px",
            }}
          >
            <div
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                textTransform: "uppercase",
                marginBottom: 2,
              }}
            >
              {label}
            </div>
            <div style={{ fontSize: "0.9rem", fontWeight: 700 }}>{val}</div>
            <div style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
              {sub}
            </div>
          </div>
        ))}
      </div>

      {/* Token Panel */}
      <TokenPanel result={result} />
    </div>
  );
}

export const PolicySearchView: React.FC<PolicySearchViewProps> = ({
  onNotify,
}) => {
  const [empId, setEmpId] = useState("EMP001");
  const [question, setQuestion] = useState(EXAMPLE_QUESTIONS[0].question);
  const [topK, setTopK] = useState(5);
  const [temperature, setTemperature] = useState(0.3);
  const [model, setModel] = useState("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<PolicyOutputContract | null>(null);
  const [previewRouting, setPreviewRouting] = useState<RoutingDecision | null>(
    null,
  );
  const [isPreviewingRoute, setIsPreviewingRoute] = useState(false);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAvailableOllamaModels(controller.signal)
      .then(({ default_model, agent_models }) => {
        if (controller.signal.aborted) return;
        setAvailableModels(agent_models);
        if (agent_models.length === 0) {
          setModel("");
          setModelsError(
            "No tool-capable Ollama models are installed for Agent execution.",
          );
          return;
        }
        setModelsError(null);
        setModel((current) =>
          agent_models.includes(current)
            ? current
            : agent_models.includes(default_model)
              ? default_model
              : agent_models[0],
        );
      })
      .catch((error: Error) => {
        if (!controller.signal.aborted) {
          setModel("");
          setModelsError(`Could not load installed Ollama models: ${error.message}`);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingModels(false);
      });
    return () => controller.abort();
  }, []);

  const handlePreviewRoute = async () => {
    if (!question.trim()) return;
    setIsPreviewingRoute(true);
    try {
      const decision = await api.classifyPolicyQuestion(
        question.trim(),
        empId || undefined,
      );
      setPreviewRouting(decision);
    } catch (e: any) {
      onNotify("Routing preview failed: " + e.message, "error");
    } finally {
      setIsPreviewingRoute(false);
    }
  };

  const handleSearch = async () => {
    if (!empId.trim() || !question.trim()) {
      onNotify("Please provide both Employee ID and question", "error");
      return;
    }
    if (abortRef.current) abortRef.current.abort();
    abortRef.current = new AbortController();
    setIsSearching(true);
    setResult(null);
    setPreviewRouting(null);
    try {
      const res = await api.runPolicySearch(
        {
          employee_id: empId.trim(),
          question: question.trim(),
          top_k: topK,
          temperature,
          model,
        },
        abortRef.current.signal,
      );
      setResult(res);
      const mode = res.execution_mode || res.implementation;
      if (res.termination_reason === "SUCCESS") {
        onNotify(`Search complete. Mode: ${mode}. Run: ${res.run_id}`, "success");
      } else {
        onNotify(
          `Policy search failed (${res.termination_reason}). Mode: ${mode}. Run: ${res.run_id}`,
          "error",
        );
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        onNotify("Search failed: " + e.message, "error");
      }
    } finally {
      setIsSearching(false);
    }
  };

  const handleLoadExample = (ex: (typeof EXAMPLE_QUESTIONS)[0]) => {
    setEmpId(ex.empId);
    setQuestion(ex.question);
    setResult(null);
    setPreviewRouting(null);
  };

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 20,
        maxWidth: 900,
      }}
    >
      {/* Header */}
      <div>
        <div
          style={{
            fontSize: "1.1rem",
            fontWeight: 700,
            color: "#fff",
            display: "flex",
            alignItems: "center",
            gap: 8,
          }}
        >
          🔍 HR Policy Search
          <span
            style={{
              fontSize: "0.72rem",
              background: "rgba(59,130,246,0.15)",
              color: "#60a5fa",
              padding: "2px 8px",
              borderRadius: 4,
              fontWeight: 600,
            }}
          >
            Auto-Routed
          </span>
        </div>
        <p
          style={{
            fontSize: "0.82rem",
            color: "var(--text-muted)",
            marginTop: 4,
          }}
        >
          Ask any HR policy question. The system automatically decides whether
          to use
          <strong style={{ color: "#22c55e" }}> Normal Workflow</strong> or
          <strong style={{ color: "#f59e0b" }}> Agent</strong> based on the
          question's execution-path complexity.
        </p>
      </div>

      {/* Example questions */}
      <div>
        <div
          style={{
            fontSize: "0.75rem",
            color: "var(--text-muted)",
            textTransform: "uppercase",
            marginBottom: 6,
          }}
        >
          Example Questions
        </div>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6 }}>
          {EXAMPLE_QUESTIONS.map((ex, i) => (
            <button
              key={i}
              onClick={() => handleLoadExample(ex)}
              style={{
                padding: "4px 10px",
                borderRadius: 5,
                fontSize: "0.75rem",
                cursor: "pointer",
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-muted)",
                textAlign: "left",
                maxWidth: 260,
              }}
            >
              {ex.empId}: {ex.question.slice(0, 55)}…
            </button>
          ))}
        </div>
      </div>

      {/* Search Form */}
      <div
        style={{
          background: "rgba(255,255,255,0.03)",
          border: "1px solid var(--border)",
          borderRadius: 10,
          padding: "16px 20px",
          display: "flex",
          flexDirection: "column",
          gap: 12,
        }}
      >
        <div
          style={{ display: "grid", gridTemplateColumns: "140px 1fr", gap: 10 }}
        >
          <div>
            <label
              style={{
                fontSize: "0.75rem",
                color: "var(--text-muted)",
                display: "block",
                marginBottom: 4,
              }}
            >
              Employee ID
            </label>
            <input
              value={empId}
              onChange={(e) => setEmpId(e.target.value)}
              placeholder="EMP001"
              style={{
                width: "100%",
                padding: "7px 10px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                fontSize: "0.85rem",
                boxSizing: "border-box",
              }}
            />
          </div>
          <div>
            <label
              style={{
                fontSize: "0.75rem",
                color: "var(--text-muted)",
                display: "block",
                marginBottom: 4,
              }}
            >
              Question
            </label>
            <textarea
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              rows={2}
              style={{
                width: "100%",
                padding: "7px 10px",
                borderRadius: 6,
                border: "1px solid var(--border)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                fontSize: "0.85rem",
                resize: "vertical",
                boxSizing: "border-box",
              }}
            />
          </div>
        </div>

        {/* Config Row */}
        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "flex-end",
          }}
        >
          {[
            {
              label: "Top-K",
              value: topK,
              setter: (v: number) => setTopK(v),
              min: 1,
              max: 20,
              step: 1,
            },
            {
              label: "Temperature",
              value: temperature,
              setter: (v: number) => setTemperature(v),
              min: 0,
              max: 1,
              step: 0.05,
            },
          ].map(({ label, value, setter, min, max, step }) => (
            <div key={label} style={{ minWidth: 120 }}>
              <label
                style={{
                  fontSize: "0.72rem",
                  color: "var(--text-muted)",
                  display: "block",
                  marginBottom: 3,
                }}
              >
                {label}: <strong>{value}</strong>
              </label>
              <input
                type="range"
                min={min}
                max={max}
                step={step}
                value={value}
                onChange={(e) => setter(Number(e.target.value))}
                style={{ width: "100%" }}
              />
            </div>
          ))}
          <div style={{ minWidth: 160 }}>
            <label
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                display: "block",
                marginBottom: 3,
              }}
            >
              Model
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={isLoadingModels || availableModels.length === 0}
              style={{
                width: "100%",
                padding: "5px 8px",
                borderRadius: 5,
                border: "1px solid var(--border)",
                background: "var(--bg-surface)",
                color: "var(--text-primary)",
                fontSize: "0.82rem",
              }}
            >
              {availableModels.length === 0 ? (
                <option value="">
                  {isLoadingModels
                    ? "Loading Agent models…"
                    : "No tool-capable models"}
                </option>
              ) : (
                availableModels.map((availableModel) => (
                  <option key={availableModel} value={availableModel}>
                    {availableModel}
                  </option>
                ))
              )}
            </select>
            {modelsError && (
              <div role="alert" style={{ color: "#f87171", fontSize: "0.72rem" }}>
                {modelsError}
              </div>
            )}
          </div>

          <div style={{ display: "flex", gap: 8, marginLeft: "auto" }}>
            <button
              type="button"
              disabled={isPreviewingRoute || !question.trim()}
              onClick={handlePreviewRoute}
              style={{
                padding: "7px 14px",
                borderRadius: 6,
                fontSize: "0.82rem",
                fontWeight: 600,
                cursor: "pointer",
                border: "1px solid var(--border)",
                background: "transparent",
                color: "var(--text-muted)",
                opacity: isPreviewingRoute ? 0.6 : 1,
              }}
            >
              {isPreviewingRoute ? "…" : "🔀 Preview Route"}
            </button>
            <button
              type="button"
              disabled={isSearching}
              onClick={handleSearch}
              style={{
                padding: "7px 18px",
                borderRadius: 6,
                fontSize: "0.85rem",
                fontWeight: 700,
                cursor: "pointer",
                border: "none",
                background: isSearching ? "#1e3a5f" : "var(--accent)",
                color: "#fff",
                opacity: isSearching ? 0.7 : 1,
              }}
            >
              {isSearching ? "⏳ Searching…" : "🔍 Search"}
            </button>
          </div>
        </div>
        <div style={{ color: "var(--text-muted)", fontSize: "0.72rem" }}>
          Top-K controls handbook retrieval. Temperature and model are used only
          when routing selects Agent mode; Workflow execution is deterministic.
        </div>

        {/* Route Preview */}
        {previewRouting && (
          <div
            style={{
              background: "rgba(59,130,246,0.06)",
              border: "1px solid rgba(59,130,246,0.15)",
              borderRadius: 6,
              padding: "8px 12px",
            }}
          >
            <div
              style={{
                fontSize: "0.75rem",
                color: "#60a5fa",
                marginBottom: 4,
                fontWeight: 600,
              }}
            >
              🔀 Routing Preview (no execution)
            </div>
            <div style={{ display: "flex", gap: 10, fontSize: "0.82rem" }}>
              <span
                style={{
                  color: MODE_COLORS[previewRouting.mode] || "#fff",
                  fontWeight: 700,
                }}
              >
                {previewRouting.mode.toUpperCase()}
              </span>
              <span
                style={{
                  color: COMPLEXITY_COLORS[previewRouting.complexity] || "#fff",
                }}
              >
                {previewRouting.complexity}
              </span>
              <span style={{ color: "var(--text-muted)", fontSize: "0.78rem" }}>
                {previewRouting.reason}
              </span>
            </div>
          </div>
        )}
      </div>

      {/* Result */}
      {result && (
        <div
          style={{
            background: "rgba(255,255,255,0.03)",
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "16px 20px",
          }}
        >
          <div
            style={{
              fontSize: "0.85rem",
              fontWeight: 700,
              color: "#fff",
              marginBottom: 12,
            }}
          >
            HR POLICY SEARCH —{" "}
            {(
              result.execution_mode ||
              result.implementation ||
              "workflow"
            ).toUpperCase()}
          </div>
          <ResultCard result={result} />
        </div>
      )}
    </div>
  );
};
