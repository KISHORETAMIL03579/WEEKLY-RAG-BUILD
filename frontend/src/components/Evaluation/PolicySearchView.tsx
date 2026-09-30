// frontend/src/components/Evaluation/PolicySearchView.tsx
// Production HR Policy Search with automatic routing.
//
// Flow: question -> router -> fixed workflow or ReAct agent -> answer + full trace.
// Everything shown comes from the API response; nothing is fabricated client-side.
import React, { useEffect, useId, useMemo, useRef, useState } from "react";
import { api } from "../../services/api";
import { ApiError, describeError, isAbortError } from "../../services/apiError";
import {
  BenchmarkCase,
  PolicyOutputContract,
  RoutingDecision,
} from "../../types/policy";
import { useGenerationConfig } from "../../hooks/useGenerationConfig";
import { usePolicyReadiness } from "../../hooks/usePolicyReadiness";
import { Banner } from "../common/Banner";
import { GenerationControls } from "../common/GenerationControls";
import { StatusBadge } from "../common/StatusBadge";
import { EmployeePicker } from "../Policy/EmployeePicker";
import {
  ReadinessBanner,
  UploadDocumentsLink,
} from "../Policy/ReadinessBanner";
import { ToolTrace } from "../Policy/ToolTrace";

interface PolicySearchViewProps {
  onNotify: (msg: string, type?: "info" | "success" | "error") => void;
}

const EXAMPLES_COLLAPSED = 6;

export const PolicySearchView: React.FC<PolicySearchViewProps> = ({
  onNotify,
}) => {
  const readiness = usePolicyReadiness();
  const gen = useGenerationConfig({
    capability: "agent",
    defaults: { topK: 5, temperature: 0.3 },
  });

  const [empId, setEmpId] = useState("");
  const [question, setQuestion] = useState("");
  const [isSearching, setIsSearching] = useState(false);
  const [result, setResult] = useState<PolicyOutputContract | null>(null);
  const [searchError, setSearchError] = useState<ApiError | Error | null>(null);
  const [previewRouting, setPreviewRouting] = useState<RoutingDecision | null>(
    null,
  );
  const [isPreviewingRoute, setIsPreviewingRoute] = useState(false);
  const [exampleCases, setExampleCases] = useState<BenchmarkCase[]>([]);
  const [showAllExamples, setShowAllExamples] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const questionId = useId();

  const { employees, hasDocuments, hasRoster } = readiness;

  // Follow the roster: default to its first employee, and drop ids it does not contain.
  useEffect(() => {
    if (employees.length === 0) return;
    if (!employees.some((e) => e.employee_id === empId)) {
      setEmpId(employees[0].employee_id);
    }
  }, [employees, empId]);

  // Example questions come from the benchmark case files served by the backend
  // (no ids are baked into the frontend).
  useEffect(() => {
    const controller = new AbortController();
    api
      .getPolicyCases("all", controller.signal)
      .then((cases) => setExampleCases(Array.isArray(cases) ? cases : []))
      .catch(() => setExampleCases([]));
    return () => controller.abort();
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  const examples = useMemo(() => {
    const known = new Set(employees.map((e) => e.employee_id));
    return exampleCases.filter((c) => !hasRoster || known.has(c.employee_id));
  }, [exampleCases, employees, hasRoster]);
  const visibleExamples = showAllExamples
    ? examples
    : examples.slice(0, EXAMPLES_COLLAPSED);

  const missing: string[] = [];
  if (!hasDocuments) missing.push("upload documents on the Chat page");
  if (!empId.trim()) missing.push("choose an employee");
  if (!question.trim()) missing.push("enter a question");
  if (gen.isLoadingModels) missing.push("wait for the model list");
  else if (!gen.modelReady) missing.push("select a tool-capable model");
  const canSearch = missing.length === 0 && !isSearching;

  const handlePreviewRoute = async () => {
    if (!question.trim()) return;
    setIsPreviewingRoute(true);
    try {
      setPreviewRouting(
        await api.classifyPolicyQuestion(question.trim(), empId || undefined),
      );
    } catch (e: unknown) {
      onNotify("Routing preview failed: " + describeError(e), "error");
    } finally {
      setIsPreviewingRoute(false);
    }
  };

  const handleSearch = async () => {
    if (!canSearch) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setIsSearching(true);
    setResult(null);
    setSearchError(null);
    setPreviewRouting(null);
    try {
      const res = await api.runPolicySearch(
        {
          employee_id: empId.trim(),
          question: question.trim(),
          top_k: gen.topK,
          temperature: gen.temperature,
          model: gen.model,
        },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setResult(res);
      const mode = res.execution_mode || res.implementation;
      if (res.termination_reason === "SUCCESS") {
        onNotify(
          `Search complete. Mode: ${mode}. Run: ${res.run_id}`,
          "success",
        );
      } else {
        onNotify(
          `Policy search ended with ${res.termination_reason}. Mode: ${mode}. Run: ${res.run_id}`,
          "error",
        );
      }
    } catch (e: unknown) {
      if (isAbortError(e) || controller.signal.aborted) return;
      const error = e instanceof Error ? e : new Error(describeError(e));
      setSearchError(error);
      onNotify("Search failed: " + describeError(e), "error");
      if (e instanceof ApiError && e.action === "upload-documents") {
        void readiness.refresh(); // the index is empty now: re-check and show the empty state
      }
    } finally {
      if (abortRef.current === controller) {
        abortRef.current = null;
        setIsSearching(false);
      }
    }
  };

  const handleStop = () => {
    const controller = abortRef.current;
    if (!controller) return;
    abortRef.current = null;
    controller.abort();
    setIsSearching(false);
    onNotify(
      "Stopped waiting for the answer. The server may still finish the run in the background.",
      "info",
    );
  };

  const handleLoadExample = (example: BenchmarkCase) => {
    setEmpId(example.employee_id);
    setQuestion(example.question);
    setResult(null);
    setSearchError(null);
    setPreviewRouting(null);
  };

  const errorNeedsUpload =
    searchError instanceof ApiError &&
    searchError.action === "upload-documents";

  return (
    <div className="u-stack" style={{ gap: 18, maxWidth: 980 }}>
      <div>
        <h2 className="panel-title" style={{ fontSize: "1.1rem" }}>
          <span aria-hidden="true">🔍</span> HR Policy Search
          <span className="chip tone-info">Auto-routed</span>
        </h2>
        <p className="panel-subtitle" style={{ maxWidth: 720 }}>
          Ask an HR policy question about an employee. The router picks the
          fixed <strong style={{ color: "var(--green)" }}>workflow</strong> or
          the <strong style={{ color: "var(--amber)" }}>agent</strong> from how
          variable the tool path is, and the full trace of what it read and
          called is shown below the answer.
        </p>
      </div>

      <ReadinessBanner state={readiness} />

      {examples.length > 0 && (
        <div>
          <div className="section-label" style={{ marginBottom: 6 }}>
            Example questions
            <span
              className="u-muted"
              style={{ textTransform: "none", letterSpacing: 0 }}
            >
              {" "}
              (from the benchmark case files)
            </span>
          </div>
          <div
            className="chip-list"
            role="group"
            aria-label="Example questions"
          >
            {visibleExamples.map((example) => (
              <button
                key={example.case_id}
                type="button"
                className="btn-secondary btn-small"
                style={{ textAlign: "left", maxWidth: 300 }}
                title={example.question}
                disabled={isSearching}
                onClick={() => handleLoadExample(example)}
              >
                <strong>{example.employee_id}</strong>:{" "}
                {example.question.length > 52
                  ? `${example.question.slice(0, 52)}…`
                  : example.question}
              </button>
            ))}
            {examples.length > EXAMPLES_COLLAPSED && (
              <button
                type="button"
                className="btn-secondary btn-small"
                onClick={() => setShowAllExamples((v) => !v)}
              >
                {showAllExamples ? "Show fewer" : `Show all ${examples.length}`}
              </button>
            )}
          </div>
        </div>
      )}

      <div className="panel">
        <div
          className="u-row"
          style={{ alignItems: "flex-start", flexWrap: "nowrap" }}
        >
          <EmployeePicker
            employees={employees}
            value={empId}
            onChange={setEmpId}
            disabled={isSearching || !hasDocuments}
            hasDocuments={hasDocuments}
            employeesError={readiness.employeesError}
            className="u-grow"
          />
        </div>

        <div className="field">
          <label className="field-label" htmlFor={questionId}>
            Question
          </label>
          <textarea
            id={questionId}
            className="field-textarea"
            value={question}
            rows={3}
            disabled={isSearching}
            placeholder="Ask a policy question about the selected employee…"
            onChange={(event) => setQuestion(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
                event.preventDefault();
                void handleSearch();
              }
            }}
          />
          <div className="field-hint">Ctrl+Enter runs the search.</div>
        </div>

        <GenerationControls
          config={gen}
          showModel
          disabled={isSearching}
          onPresetApplied={(preset) =>
            onNotify(
              `Loaded ${preset.label}: Top-K = ${preset.topK}, Temperature = ${preset.temperature.toFixed(1)}`,
              "info",
            )
          }
        />
        <div className="field-hint">
          Top-K controls how many passages each retrieval returns. The selected
          model and temperature are used for answer synthesis in both execution
          modes.
        </div>

        <div className="u-row">
          <button
            type="button"
            className="btn-secondary"
            disabled={isPreviewingRoute || isSearching || !question.trim()}
            onClick={() => void handlePreviewRoute()}
          >
            {isPreviewingRoute ? "Previewing…" : "🔀 Preview route"}
          </button>
          <span className="u-right u-row">
            {isSearching && (
              <button
                type="button"
                className="btn-danger"
                onClick={handleStop}
                aria-label="Stop waiting for the search result"
              >
                ■ Stop
              </button>
            )}
            <button
              type="button"
              className="btn-primary btn-inline"
              disabled={!canSearch}
              aria-disabled={!canSearch}
              onClick={() => void handleSearch()}
              title={
                canSearch
                  ? "Run the search"
                  : `To search: ${missing.join(", ")}`
              }
            >
              {isSearching ? (
                <span className="u-row" style={{ gap: 8, flexWrap: "nowrap" }}>
                  <span className="spinner" style={{ width: 14, height: 14 }} />
                  Searching…
                </span>
              ) : (
                "🔍 Search"
              )}
            </button>
          </span>
        </div>
        {!canSearch && !isSearching && (
          <div className="field-hint" role="status">
            To search: {missing.join(", ")}.
          </div>
        )}

        {previewRouting && (
          <div className="banner tone-info" role="status">
            <div className="banner-body">
              <div className="banner-title">
                Routing preview (nothing was executed)
              </div>
              <div className="u-row" style={{ gap: 8 }}>
                <StatusBadge status={previewRouting.mode.toUpperCase()} plain />
                <span className="chip">{previewRouting.complexity}</span>
                {previewRouting.matched_signals.map((signal) => (
                  <span key={signal} className="chip is-mono">
                    {signal}
                  </span>
                ))}
              </div>
              <div className="banner-text">{previewRouting.reason}</div>
            </div>
          </div>
        )}
      </div>

      {searchError && (
        <Banner
          tone="danger"
          icon="⚠"
          title={
            errorNeedsUpload ? "No documents to search" : "The search failed"
          }
          live="alert"
          actions={errorNeedsUpload ? <UploadDocumentsLink /> : undefined}
        >
          {describeError(searchError)}
        </Banner>
      )}

      {isSearching && (
        <div className="panel-inset u-row" role="status">
          <span className="spinner" />
          <span className="u-small">
            Routing, calling tools and generating the answer. This can take up
            to a minute.
          </span>
        </div>
      )}

      {result && (
        <div className="panel">
          <h3 className="panel-title" style={{ fontSize: "0.95rem" }}>
            HR policy search result
            <StatusBadge
              status={(
                result.execution_mode ||
                result.implementation ||
                "workflow"
              ).toUpperCase()}
              plain
            />
          </h3>
          <ToolTrace result={result} />
        </div>
      )}
    </div>
  );
};
