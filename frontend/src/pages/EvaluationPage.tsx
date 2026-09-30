import React, { useState, useEffect, useRef, useCallback } from "react";
import { EvalQuestionInput, EvalRunResponse } from "../types/evaluation";
import { FormView } from "../components/Evaluation/FormView";
import { ResultsView } from "../components/Evaluation/ResultsView";
import { JudgeEvaluatorView } from "../components/Evaluation/JudgeEvaluatorView";
import { PolicyAssistantView } from "../components/Evaluation/PolicyAssistantView";
import { PolicySearchView } from "../components/Evaluation/PolicySearchView";
import { McpView } from "../components/Evaluation/McpView";
import { ToastContainer, ToastItem } from "../components/common/ToastContainer";
import { TabItem, TabPanel, Tabs } from "../components/common/Tabs";
import { useGenerationConfig } from "../hooks/useGenerationConfig";
import { PRESETS } from "../components/Evaluation/KeyTakeaways";
import { CANONICAL_RETRIEVAL_QUESTIONS } from "../data/canonicalRetrievalQuestions";
import { api } from "../services/api";
import { generateId } from "../utils/helpers";

type EvalTab = "policy" | "judge" | "retrieval" | "mcp";
type PolicySubTab = "search" | "benchmark";

const EVAL_TABS: readonly EvalTab[] = ["policy", "judge", "retrieval", "mcp"];

// URL scheme: /eval/<tab> picks the top-level tab; /eval/policy?view=benchmark picks the
// Policy sub-tab. The legacy ?tab=<tab> query is still understood.
function readLocation(): { tab: EvalTab; sub: PolicySubTab } {
  if (typeof window === "undefined") return { tab: "policy", sub: "search" };
  const pathname = window.location.pathname.toLowerCase();
  const params = new URLSearchParams(window.location.search);
  const fromPath = EVAL_TABS.find((tab) => pathname.includes(`/eval/${tab}`));
  const queryTab = params.get("tab");
  const fromQuery = EVAL_TABS.find((tab) => tab === queryTab);
  return {
    tab: fromPath ?? fromQuery ?? "policy",
    sub: params.get("view") === "benchmark" ? "benchmark" : "search",
  };
}

export const EvaluationPage: React.FC = () => {
  const [activeTab, setActiveTabState] = useState<EvalTab>(
    () => readLocation().tab,
  );
  const [policySubTab, setPolicySubTabState] = useState<PolicySubTab>(
    () => readLocation().sub,
  );
  const [isJudgeEvaluating, setIsJudgeEvaluating] = useState<boolean>(false);

  const setActiveTab = (tab: EvalTab) => {
    setActiveTabState(tab);
    if (typeof window !== "undefined" && window.history) {
      const target =
        tab === "policy" && policySubTab === "benchmark"
          ? "/eval/policy?view=benchmark"
          : `/eval/${tab}`;
      if (window.location.pathname + window.location.search !== target) {
        window.history.pushState(null, "", target);
      }
    }
  };

  const setPolicySubTab = (sub: PolicySubTab) => {
    setPolicySubTabState(sub);
    if (typeof window !== "undefined" && window.history) {
      const target =
        sub === "benchmark" ? "/eval/policy?view=benchmark" : "/eval/policy";
      if (window.location.pathname + window.location.search !== target) {
        window.history.pushState(null, "", target);
      }
    }
  };

  useEffect(() => {
    const handlePopState = () => {
      const next = readLocation();
      setActiveTabState(next.tab);
      setPolicySubTabState(next.sub);
    };
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  // Retrieval Benchmark State: Auto-load canonical 25 questions on mount with default Top-K = 5
  const [questions, setQuestions] = useState<EvalQuestionInput[]>(() => [
    ...CANONICAL_RETRIEVAL_QUESTIONS,
  ]);
  const retrievalGen = useGenerationConfig({
    capability: null,
    defaults: { topK: 5, temperature: 0 },
  });
  const [strategyFilter, setStrategyFilter] = useState<string>("");
  const [presets, setPresets] = useState<Record<string, boolean>>({
    tfidf: true,
    "bm25-qdrant-blend": true,
    "bm25-qdrant-rrf": true,
    "rrf-rerank": true,
    "rrf-rerank-rewrite": true,
  });
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [results, setResults] = useState<EvalRunResponse | null>(null);
  const [view, setView] = useState<"form" | "results">("form");
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const abortControllerRef = useRef<AbortController | null>(null);
  const toastTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(
    new Map(),
  );

  const dismissToast = useCallback((id: string) => {
    if (toastTimersRef.current.has(id)) {
      clearTimeout(toastTimersRef.current.get(id));
      toastTimersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (
      message: string,
      type: "info" | "success" | "error" = "info",
      duration = 5000,
    ) => {
      const id = generateId("toast");
      setToasts((prev) => [...prev, { id, message, type }]);
      if (duration > 0) {
        const timer = setTimeout(() => {
          dismissToast(id);
        }, duration);
        toastTimersRef.current.set(id, timer);
      }
    },
    [dismissToast],
  );

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      toastTimersRef.current.forEach((timer) => clearTimeout(timer));
      toastTimersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: "smooth" });
  }, [view, activeTab]);

  const handleCancel = () => {
    const controller = abortControllerRef.current;
    if (controller) {
      controller.abort();
      abortControllerRef.current = null;
      setIsRunning(false);
      showToast("Retrieval benchmark cancelled by user.", "info");
    }
  };

  const handleRun = async () => {
    // Validate both question AND expected ground truth
    const invalidEmptyExpected = questions.filter(
      (q) => q.question.trim() && !q.expected.trim(),
    );
    if (invalidEmptyExpected.length > 0) {
      showToast(
        "Please provide an expected section/filename substring for all entered questions.",
        "error",
      );
      return;
    }

    const validQ = questions.filter(
      (q) => q.question.trim() && q.expected.trim(),
    );
    if (!validQ.length) {
      showToast(
        "Please enter at least one question and its expected target substring.",
        "error",
      );
      return;
    }

    const active = Object.keys(presets).filter((k) => presets[k]);
    if (!active.length) {
      showToast(
        "Please select at least one retrieval strategy to compare.",
        "error",
      );
      return;
    }

    const kVal = Math.max(1, Math.min(20, Math.round(retrievalGen.topK)));

    setIsRunning(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const data = await api.runEvaluation(
        {
          questions: validQ.map((q) => ({
            id: q.id,
            question: q.question.trim(),
            expected: q.expected.trim(),
          })),
          top_k: kVal,
          presets: active,
          strategy_filter: strategyFilter,
        },
        controller.signal,
      );

      // Response schema and result integrity validation
      if (
        !data ||
        typeof data !== "object" ||
        !data.modes ||
        typeof data.modes !== "object"
      ) {
        throw new Error(
          "Malformed evaluation response: missing modes dictionary.",
        );
      }

      const submittedIds = new Set(validQ.map((q) => q.id));
      for (const mk of active) {
        const modeData = data.modes[mk];
        if (
          !modeData ||
          typeof modeData !== "object" ||
          !Array.isArray(modeData.results)
        ) {
          throw new Error(
            `Strategy "${PRESETS[mk]?.label || mk}" missing results array in server response.`,
          );
        }

        modeData.hit_rate =
          typeof modeData.hit_rate === "number" && !isNaN(modeData.hit_rate)
            ? modeData.hit_rate
            : Number(modeData.hit_rate) || 0;
        modeData.mrr =
          typeof modeData.mrr === "number" && !isNaN(modeData.mrr)
            ? modeData.mrr
            : Number(modeData.mrr) || 0;
        modeData.hits =
          typeof modeData.hits === "number" && !isNaN(modeData.hits)
            ? modeData.hits
            : Number(modeData.hits) || 0;
        modeData.total =
          typeof modeData.total === "number" && !isNaN(modeData.total)
            ? modeData.total
            : Number(modeData.total) || 0;

        const resultIds: string[] = [];
        for (const r of modeData.results) {
          if (!r || typeof r !== "object" || typeof r.id !== "string") {
            throw new Error(
              `Strategy "${PRESETS[mk]?.label || mk}" returned an invalid result item structure.`,
            );
          }
          // Strict boolean hit normalization
          if (typeof r.hit === "boolean") {
            // Valid boolean
          } else if (
            (r.hit as unknown) === 1 ||
            (r.hit as unknown) === "1" ||
            (r.hit as unknown) === "true"
          ) {
            r.hit = true;
          } else if (
            (r.hit as unknown) === 0 ||
            (r.hit as unknown) === "0" ||
            (r.hit as unknown) === "false"
          ) {
            r.hit = false;
          } else {
            throw new Error(
              `Strategy "${PRESETS[mk]?.label || mk}" returned invalid hit value for question ID "${r.id}".`,
            );
          }

          if (r.rank !== null && r.rank !== undefined) {
            const parsedRank = Number(r.rank);
            r.rank =
              isNaN(parsedRank) || parsedRank <= 0
                ? null
                : Math.floor(parsedRank);
          } else {
            r.rank = null;
          }
          resultIds.push(r.id);
        }

        const uniqueIds = new Set(resultIds);
        if (uniqueIds.size !== resultIds.length) {
          throw new Error(
            `Strategy "${PRESETS[mk]?.label || mk}" returned duplicate question IDs.`,
          );
        }
        for (const qId of submittedIds) {
          if (!uniqueIds.has(qId)) {
            throw new Error(
              `Strategy "${PRESETS[mk]?.label || mk}" did not return a result for question ID "${qId}".`,
            );
          }
        }
        for (const resultId of resultIds) {
          if (!submittedIds.has(resultId)) {
            throw new Error(
              `Strategy "${PRESETS[mk]?.label || mk}" returned unexpected question ID "${resultId}".`,
            );
          }
        }
      }

      setResults(data);
      setView("results");
      showToast(
        `Retrieval benchmark evaluated across ${active.length} strategies!`,
        "success",
      );
    } catch (e: unknown) {
      const err = e as Error;
      if (err.name !== "AbortError") {
        showToast("Evaluation Integrity Error: " + err.message, "error");
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setIsRunning(false);
      }
    }
  };

  const goToForm = () => {
    setView("form");
  };

  const goToResults = () => {
    setView("results");
  };

  const handleClear = () => {
    setResults(null);
    setView("form");
    showToast("Evaluation results cleared.", "info");
  };

  const topTabs: TabItem[] = [
    { id: "policy", label: "👔 Policy Assistant" },
    {
      id: "judge",
      label: "⚖️ Judge Evaluator",
      badge: isJudgeEvaluating ? "⚡ Running..." : undefined,
      badgeLive: true,
    },
    {
      id: "retrieval",
      label: "📊 Retrieval Benchmark",
      badge: isRunning ? "⚡ Running..." : undefined,
      badgeLive: true,
    },
    { id: "mcp", label: "🔌 MCP Tools" },
  ];

  const policyTabs: TabItem[] = [
    { id: "search", label: "🔍 Policy Search (Auto-Routed)" },
    { id: "benchmark", label: "📊 Agent vs Workflow Benchmark" },
  ];

  return (
    <div className="eval-root">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* TOPBAR */}
      <header className="evaluation-page-header">
        <div className="evaluation-page-heading">
          <div className="evaluation-page-title">Evaluation Hub</div>
          <div className="evaluation-page-subtitle">
            LLM Judges (V1 vs V2), Deterministic Assertions &amp; Retrieval
            Benchmarks, HR Policy Agent and MCP Tools
          </div>
        </div>

        <Tabs
          className="evaluation-page-tabs"
          tabs={topTabs}
          active={activeTab}
          onChange={(id) => setActiveTab(id as EvalTab)}
          ariaLabel="Evaluation sections"
          idPrefix="eval"
        />

        <div className="evaluation-page-actions">
          {activeTab === "retrieval" && view === "form" && results && (
            <button
              type="button"
              onClick={goToResults}
              className="btn-secondary"
              style={{ borderColor: "var(--accent)", color: "var(--accent)" }}
            >
              View Results →
            </button>
          )}

          <a href="/" className="btn-secondary">
            ← Back to chat
          </a>
        </div>
      </header>

      {/* MAIN CONTENT — ONLY THE ACTIVE TAB IS MOUNTED */}
      <main className="evaluation-page-main">
        {/* TAB 1: POLICY ASSISTANT */}
        <TabPanel idPrefix="eval" id="policy" active={activeTab}>
          <div className="u-stack" style={{ gap: 16 }}>
            <Tabs
              tabs={policyTabs}
              active={policySubTab}
              onChange={(id) => setPolicySubTab(id as PolicySubTab)}
              ariaLabel="Policy assistant views"
              idPrefix="policy"
              variant="underline"
              tone={policySubTab === "search" ? "green" : "amber"}
            />
            <TabPanel idPrefix="policy" id="search" active={policySubTab}>
              <PolicySearchView onNotify={showToast} />
            </TabPanel>
            <TabPanel idPrefix="policy" id="benchmark" active={policySubTab}>
              <PolicyAssistantView onNotify={showToast} />
            </TabPanel>
          </div>
        </TabPanel>

        {/* TAB 2: JUDGE EVALUATOR */}
        <TabPanel idPrefix="eval" id="judge" active={activeTab}>
          <JudgeEvaluatorView
            onNotify={showToast}
            onEvaluatingChange={setIsJudgeEvaluating}
          />
        </TabPanel>

        {/* TAB 3: RETRIEVAL BENCHMARK */}
        <TabPanel idPrefix="eval" id="retrieval" active={activeTab}>
          <div style={{ maxWidth: "1000px", margin: "0 auto" }}>
            {view === "form" ? (
              <FormView
                questions={questions}
                setQuestions={setQuestions}
                generation={retrievalGen}
                strategyFilter={strategyFilter}
                setStrategyFilter={setStrategyFilter}
                presets={presets}
                setPresets={setPresets}
                onRun={handleRun}
                onCancel={handleCancel}
                isRunning={isRunning}
                onNotify={showToast}
              />
            ) : (
              <ResultsView
                results={results}
                onBack={goToForm}
                onClear={handleClear}
              />
            )}
          </div>
        </TabPanel>

        {/* TAB 4: MCP */}
        <TabPanel idPrefix="eval" id="mcp" active={activeTab}>
          <McpView onNotify={showToast} />
        </TabPanel>
      </main>
    </div>
  );
};
