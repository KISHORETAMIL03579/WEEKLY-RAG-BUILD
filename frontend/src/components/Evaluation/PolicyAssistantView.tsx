// frontend/src/components/Evaluation/PolicyAssistantView.tsx
// HR Policy benchmark dashboard: ReAct agent vs fixed-sequence workflow over the
// documents the user uploaded, with per-case traces and the Week 8 trajectory report.
import React, {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
} from "react";
import { api } from "../../services/api";
import { ApiError, describeError, isAbortError } from "../../services/apiError";
import {
  BenchmarkCase,
  BenchmarkCaseLiveStatus,
  BenchmarkSuite,
  CustomBenchmarkCase,
  ExecutionSummary,
  PolicyBenchmarkRunStateResponse,
  PolicyOutputContract,
  TrajectoryCaseRecord,
} from "../../types/policy";
import { QADataSetCase, DatasetMode } from "../../types/dataset";
import { useGenerationConfig } from "../../hooks/useGenerationConfig";
import { usePolicyReadiness } from "../../hooks/usePolicyReadiness";
import { formatInt, formatMs, formatPct, formatUsd } from "../../utils/helpers";
import { Banner } from "../common/Banner";
import { CancelButton } from "../common/CancelButton";
import { DataTable, DataColumn } from "../common/DataTable";
import { GenerationControls } from "../common/GenerationControls";
import { MetricCard } from "../common/MetricCard";
import { Modal } from "../common/Modal";
import { ProgressBar, ProgressTone } from "../common/ProgressBar";
import { StatusBadge, VerdictBadge } from "../common/StatusBadge";
import { EmployeePicker } from "../Policy/EmployeePicker";
import { ReadinessBanner } from "../Policy/ReadinessBanner";
import { PathSequence, ToolTrace } from "../Policy/ToolTrace";
import { TrajectoryPanel } from "../Policy/TrajectoryPanel";
import { EvaluationDatasetManager } from "./EvaluationDatasetManager";

interface PolicyAssistantViewProps {
  onNotify: (msg: string, type?: "info" | "success" | "error") => void;
}

const SUITES: Array<{ id: BenchmarkSuite; label: string; hint: string }> = [
  {
    id: "canonical",
    label: "Canonical",
    hint: "Single-path cases: the same tools every time.",
  },
  {
    id: "branching",
    label: "Branching",
    hint: "The tool path depends on what earlier tools return.",
  },
  { id: "all", label: "All", hint: "Canonical and branching together." },
];

const POLL_INTERVAL_MS = 500;

const isLive = (status?: string) =>
  status === "RUNNING" || status === "CANCELLING";
const isTerminal = (status?: string) =>
  status === "COMPLETED" || status === "CANCELLED" || status === "ERROR";

const RUN_STATUS_LABEL: Record<string, string> = {
  RUNNING: "Benchmark running",
  CANCELLING: "Cancelling after the current step…",
  COMPLETED: "Benchmark complete",
  CANCELLED: "Benchmark cancelled",
  ERROR: "Benchmark error",
};

function progressTone(status: string): ProgressTone {
  switch (status) {
    case "COMPLETED":
      return "success";
    case "CANCELLED":
    case "CANCELLING":
      return "warning";
    case "ERROR":
      return "danger";
    default:
      return "accent";
  }
}

/** Backend reads `source_section`/`expected_value`; the dataset manager uses other names. */
function toBackendCase(c: QADataSetCase): CustomBenchmarkCase {
  return {
    case_id: c.case_id,
    employee_id: (c.employee_id || "").trim(),
    question: c.question,
    expected_value: c.expected_answer || c.expected_entitlement || "",
    source_section: c.expected_section || "",
  };
}

/**
 * A case the server still lists as RUNNING inside a run that ended (ERROR/CANCELLED) was
 * cut off, not running: say so instead of showing a live spinner-state forever.
 */
function displayStatus(status: string, runStatus: string | undefined): string {
  if (
    status === "RUNNING" &&
    (runStatus === "ERROR" || runStatus === "CANCELLED")
  ) {
    return "INTERRUPTED";
  }
  return status;
}

const pair = (
  agent: string | number | null | undefined,
  workflow: string | number | null | undefined,
) => (
  <span className="u-mono">
    {agent ?? "—"} <span className="u-muted">/</span> {workflow ?? "—"}
  </span>
);

interface ScorecardRow {
  key: string;
  metric: string;
  hint?: string;
  agent: React.ReactNode;
  workflow: React.ReactNode;
}

function scorecardRows(
  agent: ExecutionSummary,
  workflow: ExecutionSummary,
): ScorecardRow[] {
  const terminations = (summary: ExecutionSummary) => {
    const entries = Object.entries(summary.terminations || {});
    return entries.length === 0 ? (
      "—"
    ) : (
      <span className="chip-list">
        {entries.map(([reason, count]) => (
          <span key={reason} className="u-row" style={{ gap: 4 }}>
            <StatusBadge status={reason} />
            <span className="u-tiny u-muted">×{count}</span>
          </span>
        ))}
      </span>
    );
  };
  return [
    {
      key: "pass",
      metric: "Pass rate",
      hint: "normalised scorer (aliases, number words)",
      agent: `${formatPct(agent.pass_rate_pct)} (${agent.passed_count}/${agent.total_cases})`,
      workflow: `${formatPct(workflow.pass_rate_pct)} (${workflow.passed_count}/${workflow.total_cases})`,
    },
    {
      key: "strict",
      metric: "Strict pass rate",
      hint: "legacy literal-substring check",
      agent: formatPct(agent.strict_pass_rate_pct),
      workflow: formatPct(workflow.strict_pass_rate_pct),
    },
    {
      key: "lat50",
      metric: "Latency p50",
      agent: formatMs(agent.p50_latency_ms, 0),
      workflow: formatMs(workflow.p50_latency_ms, 0),
    },
    {
      key: "latmax",
      metric: "Latency max",
      agent: formatMs(agent.max_latency_ms, 0),
      workflow: formatMs(workflow.max_latency_ms, 0),
    },
    {
      key: "cost50",
      metric: "Estimated cost p50",
      hint: "token-cost proxy, not billing",
      agent: formatUsd(agent.p50_cost_usd),
      workflow: formatUsd(workflow.p50_cost_usd),
    },
    {
      key: "costmax",
      metric: "Estimated cost max",
      hint: "token-cost proxy, not billing",
      agent: formatUsd(agent.max_cost_usd),
      workflow: formatUsd(workflow.max_cost_usd),
    },
    {
      key: "costq",
      metric: "Estimated cost / question",
      hint: "token-cost proxy, not billing",
      agent: formatUsd(agent.cost_per_question_usd),
      workflow: formatUsd(workflow.cost_per_question_usd),
    },
    {
      key: "tok50",
      metric: "Tokens p50",
      agent: formatInt(agent.p50_tokens),
      workflow: formatInt(workflow.p50_tokens),
    },
    {
      key: "tokmax",
      metric: "Tokens max",
      agent: formatInt(agent.max_tokens),
      workflow: formatInt(workflow.max_tokens),
    },
    {
      key: "toktotal",
      metric: "Tokens total",
      agent: formatInt(agent.total_tokens),
      workflow: formatInt(workflow.total_tokens),
    },
    {
      key: "term",
      metric: "Terminations",
      agent: terminations(agent),
      workflow: terminations(workflow),
    },
  ];
}

export const PolicyAssistantView: React.FC<PolicyAssistantViewProps> = ({
  onNotify,
}) => {
  const readiness = usePolicyReadiness();
  const { employees, hasDocuments } = readiness;
  const gen = useGenerationConfig({
    capability: "agent",
    defaults: { topK: 5, temperature: 0.3 },
    emptyModelsMessage:
      "No tool-enabled model is available from the configured provider for the agent.",
  });

  // Suite / cases
  const [suite, setSuite] = useState<BenchmarkSuite>("canonical");
  const [cases, setCases] = useState<BenchmarkCase[]>([]);
  const [casesError, setCasesError] = useState<string | null>(null);
  const [isLoadingCases, setIsLoadingCases] = useState(true);

  // Custom dataset (optional)
  const [datasetMode, setDatasetMode] = useState<DatasetMode>("builtin");
  const [customDatasetCases, setCustomDatasetCases] = useState<QADataSetCase[]>(
    [],
  );

  // Run state
  const [runState, setRunState] =
    useState<PolicyBenchmarkRunStateResponse | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [history, setHistory] = useState<PolicyBenchmarkRunStateResponse[]>([]);
  const [inspectCaseId, setInspectCaseId] = useState<string | null>(null);
  const [showMethodology, setShowMethodology] = useState(false);
  const [loadRunId, setLoadRunId] = useState("");
  const [isLoadingRun, setIsLoadingRun] = useState(false);

  // Single-case playground
  const [showPlayground, setShowPlayground] = useState(false);
  const [selectedEmpId, setSelectedEmpId] = useState("");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [queryText, setQueryText] = useState("");
  const [isRunningSingle, setIsRunningSingle] = useState(false);
  const [agentSingle, setAgentSingle] = useState<PolicyOutputContract | null>(
    null,
  );
  const [workflowSingle, setWorkflowSingle] =
    useState<PolicyOutputContract | null>(null);
  const [singleError, setSingleError] = useState<string | null>(null);
  const queryId = useId();

  const pollTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const pollBusyRef = useRef(false);
  const notifyRef = useRef(onNotify);
  notifyRef.current = onNotify;
  const notifiedModelErrorRef = useRef<string | null>(null);

  const isRunning = isLive(runState?.status);
  const customMode = datasetMode === "custom";
  const activeCasesCount = customMode
    ? customDatasetCases.length
    : cases.length;

  // ── data loading ───────────────────────────────────────────────────────────

  useEffect(() => {
    const controller = new AbortController();
    setIsLoadingCases(true);
    setCasesError(null);
    api
      .getPolicyCases(suite, controller.signal)
      .then((list) => setCases(Array.isArray(list) ? list : []))
      .catch((e: unknown) => {
        if (isAbortError(e)) return;
        setCases([]);
        setCasesError(describeError(e));
      })
      .finally(() => {
        if (!controller.signal.aborted) setIsLoadingCases(false);
      });
    return () => controller.abort();
  }, [suite]);

  useEffect(() => {
    if (gen.modelsError && notifiedModelErrorRef.current !== gen.modelsError) {
      notifiedModelErrorRef.current = gen.modelsError;
      onNotify(gen.modelsError, "error");
    }
  }, [gen.modelsError, onNotify]);

  // Follow the roster for the playground.
  useEffect(() => {
    if (employees.length === 0) return;
    if (!employees.some((e) => e.employee_id === selectedEmpId)) {
      setSelectedEmpId(employees[0].employee_id);
    }
  }, [employees, selectedEmpId]);

  const stopPolling = useCallback(() => {
    if (pollTimerRef.current) {
      clearInterval(pollTimerRef.current);
      pollTimerRef.current = null;
    }
  }, []);

  const applyRunState = useCallback(
    (state: PolicyBenchmarkRunStateResponse) => {
      setRunState(state);
      if (!isTerminal(state.status)) return;
      stopPolling();
      if (state.status === "COMPLETED") {
        notifyRef.current(
          `Benchmark run ${state.run_id} completed.`,
          "success",
        );
        setHistory((prev) => [
          state,
          ...prev.filter((p) => p.run_id !== state.run_id),
        ]);
      } else if (state.status === "CANCELLED") {
        notifyRef.current(`Benchmark run ${state.run_id} cancelled.`, "info");
      } else {
        notifyRef.current(
          `Benchmark run failed: ${state.error_message || "unknown error"}`,
          "error",
        );
      }
    },
    [stopPolling],
  );

  const startPolling = useCallback(
    (runId: string) => {
      stopPolling();
      pollTimerRef.current = setInterval(async () => {
        if (pollBusyRef.current) return;
        pollBusyRef.current = true;
        try {
          applyRunState(await api.getPolicyBenchmarkRun(runId));
        } catch (e: unknown) {
          if (e instanceof ApiError && e.code === "RUN_NOT_FOUND") {
            stopPolling();
            notifyRef.current(describeError(e), "error");
          } else {
            console.warn("Error polling benchmark state:", e);
          }
        } finally {
          pollBusyRef.current = false;
        }
      }, POLL_INTERVAL_MS);
    },
    [applyRunState, stopPolling],
  );

  // Resume a run that is already active on the server (survives a page reload).
  useEffect(() => {
    let cancelled = false;
    api
      .getActivePolicyBenchmarkRun()
      .then((active) => {
        if (cancelled || !active.active || !active.run) return;
        setRunState(active.run);
        if (isLive(active.run.status)) startPolling(active.run.run_id);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
      stopPolling();
    };
  }, [startPolling, stopPolling]);

  // ── actions ────────────────────────────────────────────────────────────────

  const runBlockers: string[] = [];
  if (!hasDocuments) runBlockers.push("upload documents on the Chat page");
  if (gen.isLoadingModels) runBlockers.push("wait for the model list");
  else if (!gen.modelReady) runBlockers.push("select a tool-capable model");
  if (!customMode && isLoadingCases) runBlockers.push("wait for the case list");
  if (activeCasesCount === 0 && !isLoadingCases)
    runBlockers.push(
      customMode ? "add custom cases" : "load a suite with at least one case",
    );
  if (isRunning) runBlockers.push("wait for the current run");
  if (isRunningSingle) runBlockers.push("wait for the playground run");
  const canRun = runBlockers.length === 0 && !isStarting;

  const handleStartBenchmark = async () => {
    if (!canRun) return;
    if (
      customMode &&
      customDatasetCases.some((c) => !(c.employee_id || "").trim())
    ) {
      onNotify("Every custom case needs an employee ID.", "error");
      return;
    }
    setIsStarting(true);
    setRunState(null);
    try {
      const res = await api.startPolicyBenchmark({
        suite,
        top_k: gen.topK,
        temperature: gen.temperature,
        model: gen.model,
        cases: customMode ? customDatasetCases.map(toBackendCase) : undefined,
      });
      setRunState(res);
      startPolling(res.run_id);
      onNotify(
        `Started benchmark ${res.run_id} (${res.total_cases} cases, suite: ${customMode ? "custom" : suite}).`,
        "info",
      );
    } catch (e: unknown) {
      onNotify("Failed to start benchmark: " + describeError(e), "error");
      if (e instanceof ApiError && e.action === "upload-documents") {
        void readiness.refresh();
      }
    } finally {
      setIsStarting(false);
    }
  };

  const handleCancelBenchmark = async () => {
    if (!runState || runState.status !== "RUNNING") return;
    try {
      await api.cancelPolicyBenchmarkRun(runState.run_id);
      setRunState((prev) =>
        prev
          ? { ...prev, status: "CANCELLING", cancellation_requested: true }
          : prev,
      );
      onNotify(
        `Cancelling ${runState.run_id}; the current case will finish first.`,
        "info",
      );
    } catch (e: unknown) {
      onNotify("Failed to cancel benchmark: " + describeError(e), "error");
    }
  };

  const handleLoadRun = async (runId: string) => {
    const id = runId.trim();
    if (!id) return;
    setIsLoadingRun(true);
    try {
      const loaded = await api.getPolicyBenchmarkRun(id);
      setRunState(loaded);
      gen.setTopK(loaded.top_k);
      gen.setTemperature(loaded.temperature);
      if (loaded.model && gen.models.includes(loaded.model)) {
        gen.setModel(loaded.model);
      }
      if (isLive(loaded.status)) startPolling(loaded.run_id);
      else stopPolling();
      if (loaded.status === "COMPLETED") {
        setHistory((prev) => [
          loaded,
          ...prev.filter((p) => p.run_id !== loaded.run_id),
        ]);
      }
      onNotify(`Loaded benchmark run ${loaded.run_id}.`, "success");
    } catch (e: unknown) {
      onNotify("Could not load that run: " + describeError(e), "error");
    } finally {
      setIsLoadingRun(false);
    }
  };

  const handleSelectCase = (c: BenchmarkCase) => {
    setSelectedCaseId(c.case_id);
    setSelectedEmpId(c.employee_id);
    setQueryText(c.question);
  };

  const singleBlockers: string[] = [];
  if (!hasDocuments) singleBlockers.push("upload documents on the Chat page");
  if (!selectedEmpId.trim()) singleBlockers.push("choose an employee");
  if (!queryText.trim()) singleBlockers.push("enter a question");
  if (isRunning) singleBlockers.push("wait for the benchmark");
  const agentBlockers = [
    ...singleBlockers,
    ...(gen.isLoadingModels
      ? ["wait for the model list"]
      : gen.modelReady
        ? []
        : ["select a tool-capable model"]),
  ];

  const handleRunSingle = async (mode: "both" | "agent" | "workflow") => {
    const blockers = mode === "workflow" ? singleBlockers : agentBlockers;
    if (blockers.length > 0 || isRunningSingle) return;
    setIsRunningSingle(true);
    setAgentSingle(null);
    setWorkflowSingle(null);
    setSingleError(null);
    const payload = {
      employee_id: selectedEmpId.trim(),
      question: queryText.trim(),
      ...(selectedCaseId ? { case_id: selectedCaseId } : {}),
      top_k: gen.topK,
      temperature: gen.temperature,
      model: gen.model,
    };
    const results: PolicyOutputContract[] = [];
    try {
      if (mode === "both" || mode === "agent") {
        const res = await api.runPolicyAgent(payload);
        setAgentSingle(res);
        results.push(res);
      }
      if (mode === "both" || mode === "workflow") {
        const res = await api.runPolicyWorkflow(payload);
        setWorkflowSingle(res);
        results.push(res);
      }
      const failed = results.find((r) => r.termination_reason !== "SUCCESS");
      if (failed) {
        onNotify(
          `Policy execution ended with ${failed.termination_reason}.`,
          "error",
        );
      } else {
        onNotify("Policy query evaluated.", "success");
      }
    } catch (e: unknown) {
      setSingleError(describeError(e));
      onNotify("Execution error: " + describeError(e), "error");
      if (e instanceof ApiError && e.action === "upload-documents") {
        void readiness.refresh();
      }
    } finally {
      setIsRunningSingle(false);
    }
  };

  // ── derived ────────────────────────────────────────────────────────────────

  const inspectCase: BenchmarkCaseLiveStatus | null =
    runState?.cases_status.find((c) => c.case_id === inspectCaseId) ?? null;
  const trajectoryByCase = useMemo(() => {
    const map = new Map<string, TrajectoryCaseRecord>();
    runState?.trajectory?.cases.forEach((c) => map.set(c.case_id, c));
    return map;
  }, [runState?.trajectory]);
  const skippedCount =
    runState?.cases_status.filter((c) => c.status === "SKIPPED").length ?? 0;
  const baselineCandidates = history
    .filter((h) => h.run_id !== runState?.run_id)
    .map((h) => ({
      run_id: h.run_id,
      label: `${h.run_id} · K=${h.top_k} T=${h.temperature} · ${formatPct(h.summary?.agent.pass_rate_pct)} agent`,
    }));

  const caseColumns: DataColumn<BenchmarkCaseLiveStatus>[] = [
    {
      key: "case",
      header: "Case",
      render: (cs) => <strong>{cs.case_id.toUpperCase()}</strong>,
    },
    {
      key: "emp",
      header: "Employee",
      render: (cs) => (
        <span style={{ color: "var(--accent-hover)" }}>{cs.employee_id}</span>
      ),
    },
    {
      key: "question",
      header: "Question",
      clip: true,
      render: (cs) => (
        <div>
          <div className="u-clip" style={{ maxWidth: 240 }} title={cs.question}>
            {cs.question}
          </div>
          {cs.status === "SKIPPED" && cs.skip_reason && (
            <div
              className="u-tiny"
              style={{ color: "var(--amber)", whiteSpace: "normal" }}
            >
              {cs.skip_reason}
            </div>
          )}
        </div>
      ),
    },
    {
      key: "expected",
      header: "Expected",
      clip: true,
      render: (cs) => (
        <span className="u-muted u-tiny" title={cs.ground_truth}>
          {cs.ground_truth || "—"}
        </span>
      ),
    },
    {
      key: "agent",
      header: "Agent",
      render: (cs) =>
        cs.status === "SKIPPED" ? (
          <StatusBadge status="SKIPPED" title={cs.skip_reason || undefined} />
        ) : (
          <VerdictBadge
            passed={cs.agent_passed}
            fallback={displayStatus(cs.agent_status, runState?.status)}
          />
        ),
    },
    {
      key: "workflow",
      header: "Workflow",
      render: (cs) =>
        cs.status === "SKIPPED" ? (
          <StatusBadge status="SKIPPED" title={cs.skip_reason || undefined} />
        ) : (
          <VerdictBadge
            passed={cs.workflow_passed}
            fallback={displayStatus(cs.workflow_status, runState?.status)}
          />
        ),
    },
    {
      key: "tools",
      header: "Agent tool sequence",
      render: (cs) => <PathSequence sequence={cs.agent_tool_sequence} />,
    },
    {
      key: "toolRetries",
      header: "Tool retries",
      align: "right",
      render: (cs) => cs.agent_tool_retries ?? "—",
    },
    {
      key: "modelRetries",
      header: "Model retries",
      align: "right",
      render: (cs) => cs.agent_model_retries ?? "—",
    },
    {
      key: "rejected",
      header: "Rejected calls",
      align: "right",
      render: (cs) =>
        cs.agent_rejected_calls ? (
          <span className="chip tone-danger">{cs.agent_rejected_calls}</span>
        ) : (
          (cs.agent_rejected_calls ?? "—")
        ),
    },
    {
      key: "selection",
      header: "Selection ok",
      align: "center",
      render: (cs) =>
        cs.agent_selection_ok === true ? (
          <StatusBadge status="PASS" label="OK" />
        ) : cs.agent_selection_ok === false ? (
          <StatusBadge status="FAIL" label="NOT OK" />
        ) : (
          <span
            className="u-muted"
            title="Not judged (run ended early, skipped or not run yet)"
          >
            —
          </span>
        ),
    },
    {
      key: "tokens",
      header: "Tokens (A / W)",
      align: "right",
      render: (cs) =>
        pair(
          cs.agent_tokens != null ? formatInt(cs.agent_tokens) : null,
          cs.workflow_tokens != null ? formatInt(cs.workflow_tokens) : null,
        ),
    },
    {
      key: "latency",
      header: "Latency (A / W)",
      align: "right",
      render: (cs) =>
        pair(
          cs.agent_latency_ms != null ? formatMs(cs.agent_latency_ms, 0) : null,
          cs.workflow_latency_ms != null
            ? formatMs(cs.workflow_latency_ms, 0)
            : null,
        ),
    },
    {
      key: "cost",
      header: "Est. cost (A / W)",
      headerTitle: "Estimated token cost (proxy, not billing)",
      align: "right",
      render: (cs) =>
        pair(
          cs.agent_cost_usd != null ? formatUsd(cs.agent_cost_usd) : null,
          cs.workflow_cost_usd != null ? formatUsd(cs.workflow_cost_usd) : null,
        ),
    },
    {
      key: "inspect",
      header: "Inspect",
      align: "center",
      render: (cs) => (
        <button
          type="button"
          className="btn-secondary btn-small"
          onClick={() => setInspectCaseId(cs.case_id)}
          aria-label={`Inspect ${cs.case_id}`}
        >
          Inspect
        </button>
      ),
    },
  ];

  // ── render ─────────────────────────────────────────────────────────────────

  const renderCaseDetail = (cs: BenchmarkCaseLiveStatus) => {
    const trajectory = trajectoryByCase.get(cs.case_id);
    const side = (
      label: string,
      result: PolicyOutputContract | null | undefined,
      fallbackStatus: string,
    ) => (
      <div className="panel-inset u-stack" style={{ minWidth: 0 }}>
        <div className="u-row">
          <h3 className="panel-title" style={{ fontSize: "0.95rem" }}>
            {label}
          </h3>
          <span className="u-right">
            <StatusBadge
              status={
                result ? (result.passed ? "PASS" : "FAIL") : fallbackStatus
              }
            />
          </span>
        </div>
        {result ? (
          <ToolTrace result={result} showCriteria showRouting={false} />
        ) : (
          <div className="u-small u-muted">
            {cs.status === "SKIPPED"
              ? `Skipped: ${cs.skip_reason || "required tools are not connected"}.`
              : "No result recorded for this case yet."}
          </div>
        )}
      </div>
    );
    return (
      <>
        <dl className="kv-grid panel-inset">
          <dt>Question</dt>
          <dd>{cs.question}</dd>
          <dt>Expected</dt>
          <dd>{cs.ground_truth || "N/A"}</dd>
          {cs.pass_criteria && cs.pass_criteria.length > 0 && (
            <>
              <dt>Pass criteria</dt>
              <dd>{cs.pass_criteria.map((c) => `"${c}"`).join(", ")}</dd>
            </>
          )}
          {cs.path_dependency && (
            <>
              <dt>Path dependency</dt>
              <dd>{cs.path_dependency}</dd>
            </>
          )}
          {cs.requires_tools && cs.requires_tools.length > 0 && (
            <>
              <dt>Requires tools</dt>
              <dd className="u-mono">{cs.requires_tools.join(", ")}</dd>
            </>
          )}
          {cs.status === "SKIPPED" && (
            <>
              <dt>Skipped because</dt>
              <dd style={{ color: "var(--amber)" }}>{cs.skip_reason}</dd>
            </>
          )}
        </dl>

        {trajectory && (
          <div className="panel-inset u-stack" style={{ gap: 8 }}>
            <div className="u-row">
              <span className="section-label">Trajectory for this case</span>
              <StatusBadge
                status={trajectory.trajectory_passed ? "PASS" : "FAIL"}
                label={trajectory.trajectory_passed ? "PATH OK" : "PATH WRONG"}
              />
              {trajectory.right_answer_wrong_path && (
                <span className="chip tone-warning">
                  right answer, wrong path
                </span>
              )}
            </div>
            <div className="u-small">
              <span className="u-muted">Allowed: </span>
              <span className="u-stack" style={{ gap: 2 }}>
                {trajectory.expected_paths.map((p, i) => (
                  <PathSequence key={i} sequence={p} />
                ))}
              </span>
            </div>
            <div className="u-small">
              <span className="u-muted">Observed: </span>
              <PathSequence
                sequence={trajectory.observed_sequence}
                tone={trajectory.path_exact ? "match" : "miss"}
              />
            </div>
            {trajectory.path_notes && (
              <div className="u-tiny u-muted">{trajectory.path_notes}</div>
            )}
            {trajectory.failure_modes.length > 0 && (
              <div className="chip-list">
                {trajectory.failure_modes.map((mode) => (
                  <span key={mode} className="chip is-mono tone-danger">
                    {mode}
                  </span>
                ))}
              </div>
            )}
          </div>
        )}

        <div
          style={{
            display: "grid",
            gap: 16,
            gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
          }}
        >
          {side("Agent", cs.agent_result, cs.agent_status)}
          {side("Workflow", cs.workflow_result, cs.workflow_status)}
        </div>
      </>
    );
  };

  return (
    <div
      className="u-stack"
      style={{ gap: 20, maxWidth: 1200, margin: "0 auto", width: "100%" }}
    >
      {/* 1. Header + run controls */}
      <div
        className="panel"
        style={{
          flexDirection: "row",
          alignItems: "center",
          flexWrap: "wrap",
          justifyContent: "space-between",
        }}
      >
        <div style={{ minWidth: 0, flex: "1 1 360px" }}>
          <h2 className="panel-title" style={{ fontSize: "1.4rem" }}>
            <span aria-hidden="true">🤖</span> HR Policy Assistant
          </h2>
          <div
            style={{
              color: "var(--accent-hover)",
              fontWeight: 600,
              marginTop: 4,
            }}
          >
            Dynamic ReAct agent vs fixed-sequence LLM workflow
          </div>
          <p className="panel-subtitle" style={{ maxWidth: 650 }}>
            Runs each case through a tool-calling agent and a fixed workflow
            over the documents you uploaded, then scores the answers and, for
            the agent, the tool path.
          </p>
        </div>
        <div className="u-row" style={{ gap: 10 }}>
          {isRunning ? (
            <>
              <StatusBadge
                status={runState?.status}
                size="lg"
                label={RUN_STATUS_LABEL[runState?.status || ""]}
              />
              {runState?.status === "RUNNING" && (
                <CancelButton
                  className="btn-danger"
                  onClick={() => void handleCancelBenchmark()}
                >
                  ■ Cancel
                </CancelButton>
              )}
            </>
          ) : (
            <button
              type="button"
              className="btn-primary btn-inline"
              disabled={!canRun}
              aria-disabled={!canRun}
              onClick={() => void handleStartBenchmark()}
              title={
                canRun
                  ? "Start the benchmark"
                  : `To run: ${runBlockers.join(", ")}`
              }
            >
              {isStarting
                ? "Starting…"
                : `▶ Run ${activeCasesCount || ""}-case benchmark`}
            </button>
          )}
        </div>
        {!isRunning && !canRun && !isStarting && (
          <div
            className="field-hint"
            style={{ flexBasis: "100%" }}
            role="status"
          >
            To run: {runBlockers.join(", ")}.
          </div>
        )}
      </div>

      <ReadinessBanner state={readiness} />

      {/* 2. Suite + dataset */}
      <div className="panel">
        <div className="u-row" style={{ justifyContent: "space-between" }}>
          <fieldset
            style={{ border: "none", padding: 0, minWidth: 0 }}
            disabled={isRunning || customMode}
          >
            <legend className="section-label" style={{ marginBottom: 6 }}>
              Case suite
            </legend>
            <div
              className="u-row"
              role="radiogroup"
              aria-label="Benchmark suite"
            >
              {SUITES.map((option) => (
                <label
                  key={option.id}
                  className={`suite-option${suite === option.id ? " active" : ""}`}
                  title={option.hint}
                >
                  <input
                    type="radio"
                    name="policy-suite"
                    value={option.id}
                    checked={suite === option.id}
                    onChange={() => setSuite(option.id)}
                  />
                  <span>{option.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          <span className="u-small u-muted" style={{ maxWidth: 520 }}>
            {customMode
              ? "A custom dataset is active, so the suite selection is ignored."
              : SUITES.find((s) => s.id === suite)?.hint}
          </span>
        </div>

        {casesError ? (
          <Banner
            tone="danger"
            icon="⚠"
            title="Could not load the case list"
            live="alert"
          >
            {casesError}
          </Banner>
        ) : (
          !customMode && (
            <details className="disclosure">
              <summary>
                {isLoadingCases
                  ? "Loading cases…"
                  : `${cases.length} case${cases.length === 1 ? "" : "s"} in the “${suite}” suite`}
              </summary>
              <div className="disclosure-body">
                <DataTable
                  ariaLabel={`Cases in the ${suite} suite`}
                  rows={cases}
                  rowKey={(c) => c.case_id}
                  empty="This suite has no cases."
                  columns={[
                    {
                      key: "id",
                      header: "Case",
                      render: (c) => <strong>{c.case_id}</strong>,
                    },
                    {
                      key: "emp",
                      header: "Employee",
                      render: (c) => c.employee_id,
                    },
                    { key: "q", header: "Question", render: (c) => c.question },
                    {
                      key: "tools",
                      header: "Requires tools",
                      render: (c) =>
                        c.requires_tools && c.requires_tools.length > 0 ? (
                          <span className="u-mono u-tiny">
                            {c.requires_tools.join(", ")}
                          </span>
                        ) : (
                          <span className="u-muted">—</span>
                        ),
                    },
                    {
                      key: "dep",
                      header: "Path dependency",
                      render: (c) => (
                        <span className="u-tiny u-muted">
                          {c.path_dependency || "—"}
                        </span>
                      ),
                    },
                  ]}
                />
                <div className="u-tiny u-muted" style={{ marginTop: 6 }}>
                  A case that requires a tool no connected MCP server provides
                  is reported as SKIPPED with the reason, not silently dropped.
                </div>
              </div>
            </details>
          )
        )}
      </div>

      <EvaluationDatasetManager
        evaluatorType="policy"
        title="HR Policy Assistant"
        builtinCount={cases.length}
        builtinLabel={`${SUITES.find((s) => s.id === suite)?.label ?? "Canonical"} HR Policy Benchmark`}
        datasetMode={datasetMode}
        customCases={customDatasetCases}
        isRunning={isRunning}
        onModeChange={(mode) => {
          setDatasetMode(mode);
          onNotify(
            mode === "builtin"
              ? "Switched to the built-in HR Policy benchmark suite."
              : `Switched to Custom Dataset (${customDatasetCases.length} cases loaded).`,
            "info",
          );
        }}
        onCustomCasesChange={(updated) => setCustomDatasetCases(updated)}
        onResetToBuiltin={() => {
          setDatasetMode("builtin");
          onNotify("Reset to the built-in HR Policy benchmark suite.", "info");
        }}
        onNotify={onNotify}
        storageKey="policy_custom_dataset"
      />

      {/* 3. Configuration */}
      <div className="panel">
        <div className="u-row" style={{ justifyContent: "space-between" }}>
          <h3 className="panel-title" style={{ fontSize: "0.95rem" }}>
            <span aria-hidden="true">⚙️</span> Benchmark configuration
          </h3>
          {isRunning && (
            <span className="chip tone-warning">
              🔒 Configuration frozen while running
            </span>
          )}
        </div>
        <div className="panel-inset">
          <GenerationControls
            config={gen}
            showModel
            disabled={isRunning}
            onPresetApplied={(preset) =>
              onNotify(
                `Loaded ${preset.label}: Top-K = ${preset.topK}, Temperature = ${preset.temperature.toFixed(1)}`,
                "info",
              )
            }
          />
        </div>
        <div className="field-hint">
          The workflow uses the same model and temperature as the agent: a fixed
          sequence (employee lookup, policy search, optional jurisdiction rules)
          followed by one model call.
        </div>
      </div>

      {/* 4. Empty state */}
      {!runState && (
        <div className="empty-state">
          <div style={{ fontSize: "2rem" }} aria-hidden="true">
            🏁
          </div>
          <div className="empty-state-title">No benchmark results yet</div>
          <p className="empty-state-text">
            Run the {activeCasesCount || ""}-case benchmark to compare the
            tool-calling agent with the fixed workflow under the same budgets,
            or load a finished run by its id below.
          </p>
          <button
            type="button"
            className="btn-primary btn-inline"
            disabled={!canRun}
            onClick={() => void handleStartBenchmark()}
            title={
              canRun
                ? "Start the benchmark"
                : `To run: ${runBlockers.join(", ")}`
            }
          >
            ▶ Run {activeCasesCount || ""}-case benchmark
          </button>
        </div>
      )}

      {/* 5. Error */}
      {runState?.status === "ERROR" && (
        <Banner
          tone="danger"
          icon="❌"
          title="Benchmark failed"
          live="alert"
          actions={
            <button
              type="button"
              className="btn-secondary btn-small"
              disabled={!canRun}
              onClick={() => void handleStartBenchmark()}
            >
              Retry benchmark
            </button>
          }
        >
          {runState.completed_cases} / {runState.total_cases} cases finished.{" "}
          {runState.error_message ||
            "An unexpected execution failure occurred."}
        </Banner>
      )}

      {/* 6. Live progress */}
      {runState && (
        <div
          className={`panel${isRunning ? " is-accent" : ""}`}
          aria-live="polite"
        >
          <div className="u-row" style={{ justifyContent: "space-between" }}>
            <div className="u-row" style={{ gap: 12 }}>
              <StatusBadge
                status={runState.status}
                size="lg"
                label={RUN_STATUS_LABEL[runState.status] || runState.status}
              />
              <strong>
                {runState.completed_cases} / {runState.total_cases} cases
                evaluated
              </strong>
              {skippedCount > 0 && (
                <span className="chip tone-warning">
                  {skippedCount} skipped
                </span>
              )}
              <span className="chip is-mono" title="Run id">
                {runState.run_id}
              </span>
            </div>
            <div className="u-row" style={{ gap: 14 }}>
              <strong style={{ fontSize: "1.1rem" }}>
                {runState.progress_pct}%
              </strong>
              {runState.status === "RUNNING" && (
                <CancelButton
                  className="btn-secondary btn-danger btn-small"
                  onClick={() => void handleCancelBenchmark()}
                >
                  Cancel benchmark
                </CancelButton>
              )}
              {runState.status === "CANCELLING" && (
                <span className="u-row" style={{ gap: 6 }}>
                  <span className="spinner" style={{ width: 14, height: 14 }} />
                  <span className="u-small">Finishing the current case…</span>
                </span>
              )}
            </div>
          </div>

          <ProgressBar
            ariaLabel="Policy benchmark progress"
            percentage={runState.progress_pct}
            tone={progressTone(runState.status)}
            size="lg"
          />

          <div className="metric-grid">
            <MetricCard
              label="Current case"
              value={
                runState.current_case_id && isRunning
                  ? `${runState.current_case_id.toUpperCase()} · ${
                      runState.cases_status.find(
                        (c) => c.case_id === runState.current_case_id,
                      )?.employee_id || ""
                    }`
                  : "—"
              }
              hint={isRunning ? runState.current_question : undefined}
              tone="info"
            />
            <MetricCard
              label="Elapsed"
              value={`${runState.elapsed_seconds.toFixed(1)} s`}
              tone="info"
            />
            <MetricCard
              label="Agent"
              value={`${runState.agent_completed_count} / ${runState.total_cases}`}
              hint={isRunning ? runState.current_agent_stage : "runs completed"}
              tone="neutral"
            />
            <MetricCard
              label="Workflow"
              value={`${runState.workflow_completed_count} / ${runState.total_cases}`}
              hint={
                isRunning ? runState.current_workflow_stage : "runs completed"
              }
              tone="neutral"
            />
          </div>

          <div>
            <div className="section-label" style={{ marginBottom: 8 }}>
              Case progress
            </div>
            <div className="case-grid">
              {runState.cases_status.map((cs) => {
                const current =
                  cs.case_id === runState.current_case_id &&
                  runState.status === "RUNNING";
                const open = () => setInspectCaseId(cs.case_id);
                return (
                  <div
                    key={cs.case_id}
                    className={`case-tile${current ? " is-current" : ""}`}
                    role="button"
                    tabIndex={0}
                    aria-label={`Inspect ${cs.case_id}, status ${displayStatus(cs.status, runState.status)}`}
                    title={cs.skip_reason || cs.question}
                    onClick={open}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        open();
                      }
                    }}
                  >
                    <div className="case-tile-id">
                      {cs.case_id.replace("_", " ").toUpperCase()}
                    </div>
                    <div className="case-tile-status">
                      <StatusBadge
                        status={displayStatus(cs.status, runState.status)}
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {runState.status === "COMPLETED" && (
            <div
              className="u-row"
              style={{
                justifyContent: "flex-end",
                borderTop: "1px solid var(--border)",
                paddingTop: 14,
              }}
            >
              <button
                type="button"
                className="btn-primary btn-inline"
                disabled={!canRun}
                onClick={() => void handleStartBenchmark()}
              >
                🔄 Run benchmark again
              </button>
            </div>
          )}
        </div>
      )}

      {/* 7. Scorecard */}
      {runState?.summary && (
        <div className="panel is-accent">
          <h3 className="panel-title">
            <span aria-hidden="true">🏁</span> Benchmark scorecard
          </h3>
          <div className="metric-grid">
            <MetricCard
              label="Agent pass rate"
              value={formatPct(runState.summary.agent.pass_rate_pct)}
              hint={`strict ${formatPct(runState.summary.agent.strict_pass_rate_pct)} · ${runState.summary.agent.passed_count}/${runState.summary.agent.total_cases} cases`}
              tone="success"
            />
            <MetricCard
              label="Workflow pass rate"
              value={formatPct(runState.summary.workflow.pass_rate_pct)}
              hint={`strict ${formatPct(runState.summary.workflow.strict_pass_rate_pct)} · ${runState.summary.workflow.passed_count}/${runState.summary.workflow.total_cases} cases`}
              tone="success"
            />
            <MetricCard
              label="Skipped cases"
              value={skippedCount}
              hint="Needed tools no connected MCP server provides"
              tone={skippedCount > 0 ? "warning" : "neutral"}
            />
          </div>
          <DataTable
            ariaLabel="Benchmark scorecard: agent versus workflow"
            caption="Agent vs workflow (scored cases only; skipped cases are excluded)"
            rows={scorecardRows(
              runState.summary.agent,
              runState.summary.workflow,
            )}
            rowKey={(row) => row.key}
            columns={[
              {
                key: "metric",
                header: "Metric",
                render: (row) => (
                  <div>
                    <strong>{row.metric}</strong>
                    {row.hint && (
                      <div className="u-tiny u-muted">{row.hint}</div>
                    )}
                  </div>
                ),
              },
              { key: "agent", header: "Agent", render: (row) => row.agent },
              {
                key: "workflow",
                header: "Workflow",
                render: (row) => row.workflow,
              },
            ]}
          />
        </div>
      )}

      {/* 8. Trajectory */}
      {runState?.status === "COMPLETED" && runState.trajectory && (
        <TrajectoryPanel
          run={runState}
          report={runState.trajectory}
          baselineCandidates={baselineCandidates}
        />
      )}
      {runState?.status === "COMPLETED" && !runState.trajectory && (
        <Banner
          tone="warning"
          icon="🧭"
          title="No trajectory report"
          live="status"
        >
          This run finished without a trajectory report (scoring failed on the
          server or the run predates it).
        </Banner>
      )}

      {/* 9. Results table */}
      {runState && runState.cases_status.length > 0 && (
        <div className="panel">
          <h3 className="panel-title">
            <span aria-hidden="true">📋</span> {runState.total_cases}-case
            benchmark results
          </h3>
          <DataTable
            ariaLabel="Benchmark results per case"
            rows={runState.cases_status}
            rowKey={(cs) => cs.case_id}
            columns={caseColumns}
          />
        </div>
      )}

      {/* 10. Case inspector */}
      {inspectCase && (
        <Modal
          title={`${inspectCase.case_id.toUpperCase()} · ${inspectCase.employee_id}`}
          onClose={() => setInspectCaseId(null)}
          size="xl"
        >
          {renderCaseDetail(inspectCase)}
        </Modal>
      )}

      {/* 11. History / load a run */}
      <div className="panel">
        <h3 className="panel-title">
          <span aria-hidden="true">📜</span> Experiment history
          <span className="chip">{history.length} this session</span>
        </h3>
        <form
          className="u-row"
          onSubmit={(event) => {
            event.preventDefault();
            void handleLoadRun(loadRunId);
          }}
        >
          <label className="field-label" htmlFor="policy-load-run">
            Load a run by id
          </label>
          <input
            id="policy-load-run"
            className="field-input"
            style={{ width: 260 }}
            value={loadRunId}
            placeholder="bench_…"
            spellCheck={false}
            autoComplete="off"
            onChange={(event) => setLoadRunId(event.target.value)}
          />
          <button
            type="submit"
            className="btn-secondary btn-small"
            disabled={!loadRunId.trim() || isLoadingRun || isRunning}
          >
            {isLoadingRun ? "Loading…" : "Load run"}
          </button>
        </form>
        {history.length > 0 && (
          <DataTable
            ariaLabel="Benchmark run history"
            rows={history}
            rowKey={(h) => h.run_id}
            columns={[
              {
                key: "id",
                header: "Run",
                render: (h) => <code>{h.run_id}</code>,
              },
              { key: "k", header: "Top-K", render: (h) => `K=${h.top_k}` },
              { key: "t", header: "Temp", render: (h) => `T=${h.temperature}` },
              { key: "m", header: "Model", render: (h) => h.model || "—" },
              {
                key: "ap",
                header: "Agent pass",
                render: (h) => formatPct(h.summary?.agent.pass_rate_pct),
              },
              {
                key: "wp",
                header: "Workflow pass",
                render: (h) => formatPct(h.summary?.workflow.pass_rate_pct),
              },
              {
                key: "al",
                header: "Agent p50 / max",
                render: (h) =>
                  pair(
                    formatMs(h.summary?.agent.p50_latency_ms, 0),
                    formatMs(h.summary?.agent.max_latency_ms, 0),
                  ),
              },
              {
                key: "wl",
                header: "Workflow p50 / max",
                render: (h) =>
                  pair(
                    formatMs(h.summary?.workflow.p50_latency_ms, 0),
                    formatMs(h.summary?.workflow.max_latency_ms, 0),
                  ),
              },
              {
                key: "tp",
                header: "Trajectory pass",
                render: (h) =>
                  formatPct(h.trajectory?.summary.trajectory_pass_rate_pct),
              },
              {
                key: "load",
                header: "Load",
                align: "center",
                render: (h) => (
                  <button
                    type="button"
                    className="btn-secondary btn-small"
                    disabled={isRunning}
                    onClick={() => void handleLoadRun(h.run_id)}
                  >
                    Load
                  </button>
                ),
              },
            ]}
          />
        )}
      </div>

      {/* 12. Methodology */}
      <div className="panel">
        <button
          type="button"
          className="btn-secondary"
          style={{
            display: "flex",
            justifyContent: "space-between",
            width: "100%",
          }}
          aria-expanded={showMethodology}
          onClick={() => setShowMethodology((v) => !v)}
        >
          <span>Benchmark methodology</span>
          <span aria-hidden="true">{showMethodology ? "▴" : "▾"}</span>
        </button>
        {showMethodology && (
          <div
            className="u-small u-stack"
            style={{ color: "var(--text-secondary)", lineHeight: 1.5 }}
          >
            <p>
              <strong>Documents:</strong> every tool reads only the chunks you
              uploaded in this session; nothing is answered from built-in data.
            </p>
            <p>
              <strong>Agent:</strong> live ReAct loop. The model picks tools
              from the MCP registry, the host validates and runs each call (with
              bounded retries), and the model writes the final structured
              answer.
            </p>
            <p>
              <strong>Workflow:</strong> fixed employee lookup and policy search
              (plus jurisdiction rules when the question names one), then one
              model call.
            </p>
            <p>
              <strong>Scoring:</strong> pass rate uses a normalised comparison
              with explicit per-case aliases; strict pass rate is the older
              literal-substring check, kept so historical numbers stay
              comparable. Trajectory scoring compares the agent's tool path with
              every allowed path for the case.
            </p>
            <p>
              <strong>Cost:</strong> an estimated token-cost proxy from recorded
              usage, never provider billing.
            </p>
          </div>
        )}
      </div>

      {/* 13. Playground */}
      <div className="panel">
        <div className="u-row" style={{ justifyContent: "space-between" }}>
          <div>
            <h3 className="panel-title">
              <span aria-hidden="true">🧪</span> Single case playground
            </h3>
            <p className="panel-subtitle">
              Ad-hoc runs isolated from the benchmark. Uses the configuration
              above.
            </p>
          </div>
          <button
            type="button"
            className="btn-secondary btn-small"
            aria-expanded={showPlayground}
            onClick={() => setShowPlayground((v) => !v)}
          >
            {showPlayground ? "Hide playground ▴" : "Open playground ▾"}
          </button>
        </div>

        {showPlayground && (
          <div className="u-stack">
            {isRunning && (
              <Banner tone="warning" icon="🔒" live="status">
                A benchmark is running, so single-case runs are disabled until
                it finishes.
              </Banner>
            )}
            <div
              style={{
                display: "grid",
                gap: 16,
                gridTemplateColumns: "minmax(260px, 340px) minmax(0, 1fr)",
              }}
            >
              <div className="panel-inset u-stack" style={{ minWidth: 0 }}>
                <div className="section-label">
                  Preset cases ({cases.length})
                </div>
                <div
                  className="u-stack"
                  style={{ gap: 6, maxHeight: 240, overflowY: "auto" }}
                >
                  {cases.map((c) => (
                    <button
                      key={c.case_id}
                      type="button"
                      className={`gen-preset${selectedCaseId === c.case_id ? " active" : ""}`}
                      style={{ textAlign: "left" }}
                      disabled={isRunning || isRunningSingle}
                      aria-pressed={selectedCaseId === c.case_id}
                      onClick={() => handleSelectCase(c)}
                    >
                      <strong>
                        {c.case_id.toUpperCase()} ({c.employee_id})
                      </strong>
                      <div className="u-tiny u-muted u-clip">{c.question}</div>
                    </button>
                  ))}
                  {cases.length === 0 && (
                    <div className="u-small u-muted">No cases loaded.</div>
                  )}
                </div>
              </div>

              <div className="panel-inset u-stack" style={{ minWidth: 0 }}>
                <EmployeePicker
                  employees={employees}
                  value={selectedEmpId}
                  onChange={(id) => {
                    setSelectedEmpId(id);
                    setSelectedCaseId("");
                  }}
                  disabled={isRunning || isRunningSingle || !hasDocuments}
                  hasDocuments={hasDocuments}
                  employeesError={readiness.employeesError}
                />
                <div className="field">
                  <label className="field-label" htmlFor={queryId}>
                    Policy question
                  </label>
                  <textarea
                    id={queryId}
                    className="field-textarea"
                    rows={2}
                    value={queryText}
                    disabled={isRunning || isRunningSingle}
                    placeholder="Ask a policy question about the selected employee…"
                    onChange={(event) => {
                      setQueryText(event.target.value);
                      setSelectedCaseId("");
                    }}
                  />
                </div>
                <div className="u-row" style={{ justifyContent: "flex-end" }}>
                  <button
                    type="button"
                    className="btn-secondary btn-small"
                    disabled={agentBlockers.length > 0 || isRunningSingle}
                    title={
                      agentBlockers.length
                        ? `To run: ${agentBlockers.join(", ")}`
                        : undefined
                    }
                    onClick={() => void handleRunSingle("agent")}
                  >
                    Run agent
                  </button>
                  <button
                    type="button"
                    className="btn-secondary btn-small"
                    disabled={singleBlockers.length > 0 || isRunningSingle}
                    title={
                      singleBlockers.length
                        ? `To run: ${singleBlockers.join(", ")}`
                        : undefined
                    }
                    onClick={() => void handleRunSingle("workflow")}
                  >
                    Run workflow
                  </button>
                  <button
                    type="button"
                    className="btn-primary btn-inline"
                    disabled={agentBlockers.length > 0 || isRunningSingle}
                    title={
                      agentBlockers.length
                        ? `To run: ${agentBlockers.join(", ")}`
                        : undefined
                    }
                    onClick={() => void handleRunSingle("both")}
                  >
                    {isRunningSingle ? "Running…" : "Compare agent vs workflow"}
                  </button>
                </div>
                {agentBlockers.length > 0 && !isRunningSingle && (
                  <div className="field-hint">
                    To run: {agentBlockers.join(", ")}.
                  </div>
                )}
              </div>
            </div>

            {singleError && (
              <Banner
                tone="danger"
                icon="⚠"
                title="The run failed"
                live="alert"
              >
                {singleError}
              </Banner>
            )}

            {(agentSingle || workflowSingle) && (
              <div
                style={{
                  display: "grid",
                  gap: 16,
                  gridTemplateColumns: "repeat(auto-fit, minmax(340px, 1fr))",
                }}
              >
                {agentSingle && (
                  <div className="panel-inset u-stack" style={{ minWidth: 0 }}>
                    <h4 className="panel-title" style={{ fontSize: "0.92rem" }}>
                      🤖 Agent
                    </h4>
                    <ToolTrace result={agentSingle} showRouting={false} />
                  </div>
                )}
                {workflowSingle && (
                  <div className="panel-inset u-stack" style={{ minWidth: 0 }}>
                    <h4 className="panel-title" style={{ fontSize: "0.92rem" }}>
                      ⚡ Workflow
                    </h4>
                    <ToolTrace result={workflowSingle} showRouting={false} />
                  </div>
                )}
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
};
