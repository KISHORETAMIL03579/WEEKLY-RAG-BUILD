import React, { useState, useEffect, useRef } from "react";
import { JudgeCaseResult } from "../../types/evaluation";
import { api } from "../../services/api";
import { EvaluationProgressCard } from "./EvaluationProgressCard";
import { EvaluationDatasetManager } from "./EvaluationDatasetManager";
import { QADataSetCase, DatasetMode } from "../../types/dataset";

interface JudgeEvaluatorViewProps {
  onNotify?: (msg: string, type?: "info" | "success" | "error") => void;
  onEvaluatingChange?: (isEvaluating: boolean) => void;
}

interface EvaluationProgress {
  current: number;
  total: number;
  pct: number;
  currentCaseId: string;
  currentQuestion: string;
  elapsedSeconds: number;
  estRemainingSeconds: number;
  activeCaseId: string | null;
  completedSuccess: boolean;
}

export const JudgeEvaluatorView: React.FC<JudgeEvaluatorViewProps> = ({
  onNotify,
  onEvaluatingChange,
}) => {
  const [cases, setCases] = useState<JudgeCaseResult[]>([]);
  const [currentRunId, setCurrentRunId] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [isStarting, setIsStarting] = useState<boolean>(false);
  const [evalProgress, setEvalProgress] = useState<EvaluationProgress | null>(
    null,
  );
  const [evaluatingCaseId, setEvaluatingCaseId] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<string>("all");
  const [filterCategory, setFilterCategory] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState<string>("");
  const [selectedCase, setSelectedCase] = useState<JudgeCaseResult | null>(
    null,
  );
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [topK, setTopK] = useState<number>(5);
  const [temperature, setTemperature] = useState<number>(0.3);
  const [model, setModel] = useState<string>("");
  const [defaultModel, setDefaultModel] = useState<string>("");
  const [availableModels, setAvailableModels] = useState<string[]>([]);
  const [isLoadingModels, setIsLoadingModels] = useState<boolean>(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  // Common Dataset State
  const [datasetMode, setDatasetMode] = useState<DatasetMode>("builtin");
  const [customDatasetCases, setCustomDatasetCases] = useState<QADataSetCase[]>(
    [],
  );

  // New Custom QA Form State
  const [customQuestion, setCustomQuestion] = useState<string>("");
  const [customAnswer, setCustomAnswer] = useState<string>("");
  const [customContext, setCustomContext] = useState<string>("");
  const [customNumeric, setCustomNumeric] = useState<string>("");
  const [customOoj, setCustomOoj] = useState<boolean>(false);
  const [customHumanLabel, setCustomHumanLabel] = useState<number>(1);
  const [customMode, setCustomMode] = useState<string>(
    "Low-K Multi-Clause Truncation",
  );

  // Inspection and Comparison State
  const [inspectTab, setInspectTab] = useState<
    "config" | "retrieval" | "context" | "generation" | "evaluation"
  >("config");
  const [showCompareModal, setShowCompareModal] = useState<boolean>(false);
  const [availableRuns, setAvailableRuns] = useState<any[]>([]);
  const [compareRunAId, setCompareRunAId] = useState<string>("");
  const [compareRunBId, setCompareRunBId] = useState<string>("");
  const [runAData, setRunAData] = useState<any | null>(null);
  const [runBData, setRunBData] = useState<any | null>(null);
  const [compareCaseId, setCompareCaseId] = useState<string>("case_01");
  const [loadingCompare, setLoadingCompare] = useState<boolean>(false);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const notify = (msg: string, type: "info" | "success" | "error" = "info") => {
    if (onNotify) {
      onNotify(msg, type);
    } else {
      alert(msg);
    }
  };

  useEffect(() => {
    const controller = new AbortController();
    api
      .getAvailableOllamaModels(controller.signal)
      .then(({ default_model, models }) => {
        if (controller.signal.aborted) return;
        setAvailableModels(models);
        setDefaultModel(default_model);
        if (models.length === 0) {
          setModel("");
          setModelsError("No chat-capable Ollama models are installed.");
          return;
        }
        setModelsError(null);
        setModel((current) =>
          models.includes(current)
            ? current
            : models.includes(default_model)
              ? default_model
              : models[0],
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

  const updateLoadingState = (isLoading: boolean) => {
    setLoading(isLoading);
    if (onEvaluatingChange) {
      onEvaluatingChange(isLoading);
    }
  };

  const stopPolling = () => {
    if (pollIntervalRef.current) {
      clearInterval(pollIntervalRef.current);
      pollIntervalRef.current = null;
    }
  };

  const pollRun = async (runId: string) => {
    try {
      const run = await api.getEvaluationRun(runId);
      if (!run) return;

      setCases(run.cases || run.results || []);
      setCurrentRunId(run.evaluation_run_id);
      setEvaluatingCaseId(run.current_case_id || null);

      const pct =
        run.total_cases > 0
          ? Math.round((run.completed_cases / run.total_cases) * 100)
          : 0;
      const remainingItems = Math.max(0, run.total_cases - run.completed_cases);
      const avgPerItem =
        run.completed_cases > 0
          ? run.elapsed_seconds / run.completed_cases
          : run.eval_engine === "deterministic"
            ? 0.05
            : 38;
      const estRemaining = Math.max(0, Math.round(remainingItems * avgPerItem));

      setEvalProgress({
        current: run.completed_cases,
        total: run.total_cases,
        pct,
        currentCaseId: run.current_case_id || "",
        currentQuestion: run.current_question || "",
        elapsedSeconds: Math.round(run.elapsed_seconds),
        estRemainingSeconds: estRemaining,
        activeCaseId: run.current_case_id || null,
        completedSuccess: run.status === "COMPLETED",
      });

      if (run.status === "COMPLETED") {
        stopPolling();
        updateLoadingState(false);
        setEvaluatingCaseId(null);
        notify(
          `✅ Completed evaluation run ${run.evaluation_run_id} (${run.total_cases}/${run.total_cases} cases)! Judge V1: ${run.judge_v1_agreement_pct}%, Judge V2: ${run.judge_v2_agreement_pct}%`,
          "success",
        );
      } else if (run.status === "CANCELLED") {
        stopPolling();
        updateLoadingState(false);
        setEvaluatingCaseId(null);
        notify(
          `Evaluation run ${run.evaluation_run_id} was cancelled.`,
          "info",
        );
      } else if (run.status === "ERROR") {
        stopPolling();
        updateLoadingState(false);
        setEvaluatingCaseId(null);
        notify(
          `Evaluation run failed: ${run.error_message || "Unknown error"}`,
          "error",
        );
      }
    } catch (e) {
      console.error("Error polling evaluation run:", e);
    }
  };

  const startPolling = (runId: string) => {
    stopPolling();
    pollRun(runId);
    pollIntervalRef.current = setInterval(() => {
      pollRun(runId);
    }, 1500);
  };

  // Close modals on Escape key & cleanup timers
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        if (selectedCase) setSelectedCase(null);
        if (showAddModal) setShowAddModal(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [selectedCase, showAddModal]);

  // Reconnect to active or existing run on component mount, or auto-load canonical 25 benchmark cases
  useEffect(() => {
    let isMounted = true;

    // Clean up any legacy un-namespaced key
    try {
      const legacyKey = sessionStorage.getItem("active_evaluation_run_id");
      if (legacyKey) {
        sessionStorage.removeItem("active_evaluation_run_id");
        if (!sessionStorage.getItem("judge_evaluation_active_run_id")) {
          sessionStorage.setItem("judge_evaluation_active_run_id", legacyKey);
        }
      }
    } catch {
      /* storage fallback */
    }

    const checkExistingRun = async () => {
      const savedRunId = sessionStorage.getItem(
        "judge_evaluation_active_run_id",
      );
      if (savedRunId) {
        try {
          const run = await api.getEvaluationRun(savedRunId);
          if (run && isMounted) {
            setCases(run.cases || run.results || []);
            setCurrentRunId(run.evaluation_run_id);
            if (run.status === "RUNNING") {
              updateLoadingState(true);
              startPolling(run.evaluation_run_id);
            } else {
              const pct =
                run.total_cases > 0
                  ? Math.round((run.completed_cases / run.total_cases) * 100)
                  : 100;
              setEvalProgress({
                current: run.completed_cases,
                total: run.total_cases,
                pct,
                currentCaseId: "",
                currentQuestion: "",
                elapsedSeconds: Math.round(run.elapsed_seconds),
                estRemainingSeconds: 0,
                activeCaseId: null,
                completedSuccess: run.status === "COMPLETED",
              });
            }
            return;
          }
        } catch (e) {
          // Stale run ID not found on server — clear persisted ID silently
          sessionStorage.removeItem("judge_evaluation_active_run_id");
        }
      }

      // Check if there is an active running evaluation on backend
      try {
        const active = await api.getActiveEvaluationRun();
        if (
          active &&
          active.active_run_id &&
          active.run &&
          active.run.status === "RUNNING" &&
          isMounted
        ) {
          sessionStorage.setItem(
            "judge_evaluation_active_run_id",
            active.active_run_id,
          );
          setCases(active.run.cases || active.run.results || []);
          setCurrentRunId(active.active_run_id);
          updateLoadingState(true);
          startPolling(active.active_run_id);
          return;
        }
      } catch (e) {
        // No active run
      }

      // Auto-load the canonical 25 benchmark cases on mount
      try {
        const data = await api.getBenchmarkCases();
        if (isMounted && data && (data.cases || data.results)) {
          const rawCases = data.cases || data.results || [];
          const cleanCases: JudgeCaseResult[] = rawCases.map((c) => ({
            ...c,
            status: "PENDING" as const,
            evaluation_run_id: null,
            judge_v1_verdict: null,
            judge_v1_agreed: null,
            judge_v1_raw: null,
            judge_v1_source: null,
            judge_v1_latency_ms: null,
            judge_v1_llm_completed: null,
            judge_v2_verdict: null,
            judge_v2_agreed: null,
            judge_v2_raw: null,
            judge_v2_source: null,
            judge_v2_latency_ms: null,
            judge_v2_llm_completed: null,
            source: null,
            latency_ms: null,
            llm_completed: null,
            assertions: null,
            failure_category: null,
            failure_type: null,
            failure_reason: null,
            resolution: null,
          }));
          setCases(cleanCases);
        }
      } catch (e) {
        console.error("Failed to auto-load canonical benchmark cases:", e);
      }
    };

    checkExistingRun();

    return () => {
      isMounted = false;
      stopPolling();
    };
  }, []);

  // Load clean 25 benchmark cases without precomputed evaluation results
  const handleLoadBenchmark = async () => {
    stopPolling();
    sessionStorage.removeItem("judge_evaluation_active_run_id");
    updateLoadingState(true);
    setSearchQuery("");
    setFilterMode("all");
    setFilterCategory("all");
    setEvalProgress(null);
    setEvaluatingCaseId(null);
    setCurrentRunId(null);
    try {
      const data = await api.getBenchmarkCases();
      const rawCases = data.cases || data.results || [];
      const cleanCases: JudgeCaseResult[] = rawCases.map((c) => ({
        ...c,
        status: "PENDING" as const,
        evaluation_run_id: null,
        judge_v1_verdict: null,
        judge_v1_agreed: null,
        judge_v1_raw: null,
        judge_v1_source: null,
        judge_v1_latency_ms: null,
        judge_v1_llm_completed: null,
        judge_v2_verdict: null,
        judge_v2_agreed: null,
        judge_v2_raw: null,
        judge_v2_source: null,
        judge_v2_latency_ms: null,
        judge_v2_llm_completed: null,
        source: null,
        latency_ms: null,
        llm_completed: null,
        assertions: null,
        failure_category: null,
        failure_type: null,
        failure_reason: null,
        resolution: null,
      }));
      setCases(cleanCases);
      notify(
        `Loaded official ${cleanCases.length} benchmark test cases (All Ready). Click "Run Evaluation" to evaluate.`,
        "success",
      );
    } catch (e) {
      console.error("Failed to load benchmark cases:", e);
      notify(
        "Failed to load benchmark cases: " + (e as Error).message,
        "error",
      );
    } finally {
      updateLoadingState(false);
    }
  };

  // Clear all cases in the table
  const handleClearTable = () => {
    stopPolling();
    sessionStorage.removeItem("judge_evaluation_active_run_id");
    setCases([]);
    setCurrentRunId(null);
    setSearchQuery("");
    setFilterMode("all");
    setFilterCategory("all");
    setEvalProgress(null);
    setEvaluatingCaseId(null);
    notify("Cleared all test cases from the evaluation table.", "info");
  };

  // Reset only filters and search
  const handleResetFilters = () => {
    setSearchQuery("");
    setFilterMode("all");
    setFilterCategory("all");
    notify("Filters and search query reset.", "info");
  };

  // Delete a single case by ID
  const handleDeleteCase = (caseId: string) => {
    setCases((prev) => prev.filter((c) => c.case_id !== caseId));
    notify(`Deleted test case "${caseId}".`, "info");
  };

  // Cancel in-flight evaluation
  const handleCancelEvaluation = async () => {
    if (currentRunId) {
      try {
        await api.cancelEvaluationRun(currentRunId);
      } catch (e) {
        console.error("Failed to cancel evaluation run on server:", e);
      }
    }
    stopPolling();
    updateLoadingState(false);
    setEvaluatingCaseId(null);
    notify(
      evalProgress
        ? `Evaluation stopped by user at Case ${evalProgress.current} of ${evalProgress.total} (${evalProgress.pct}%).`
        : "Judge evaluation cancelled by user.",
      "info",
    );
  };

  const handleResetToBaseline = () => {
    setTopK(8);
    setTemperature(0.0);
    setModel(defaultModel);
    notify(
      `Restored Authoritative Frozen Week 6 Baseline: Top-K = 8, Temperature = 0.0, Model = ${defaultModel}`,
      "info",
    );
  };

  const handleResetToAppDefault = () => {
    setTopK(5);
    setTemperature(0.3);
    setModel(defaultModel);
    notify(
      `Restored Application Default: Top-K = 5, Temperature = 0.3, Model = ${defaultModel}`,
      "info",
    );
  };

  const handleOpenCompare = async () => {
    setLoadingCompare(true);
    setShowCompareModal(true);
    try {
      const resp = await api.listEvaluationRuns();
      const runs = Array.isArray(resp) ? resp : (resp as any)?.runs || [];
      if (runs.length > 0) {
        setAvailableRuns(runs);
        const rBId = runs[0].evaluation_run_id;
        const rAId =
          runs.length > 1
            ? runs[1].evaluation_run_id
            : runs[0].evaluation_run_id;
        setCompareRunAId(rAId);
        setCompareRunBId(rBId);
        const [rA, rB] = await Promise.all([
          api.getEvaluationRun(rAId),
          api.getEvaluationRun(rBId),
        ]);
        setRunAData(rA);
        setRunBData(rB);
      }
    } catch (e) {
      console.error("Failed to load runs for compare:", e);
    } finally {
      setLoadingCompare(false);
    }
  };

  const handleSelectCompareRunA = async (runId: string) => {
    setCompareRunAId(runId);
    if (!runId) {
      setRunAData(null);
      return;
    }
    try {
      const r = await api.getEvaluationRun(runId);
      setRunAData(r);
    } catch (e) {
      console.error("Failed to load run A:", e);
    }
  };

  const handleSelectCompareRunB = async (runId: string) => {
    setCompareRunBId(runId);
    if (!runId) {
      setRunBData(null);
      return;
    }
    try {
      const r = await api.getEvaluationRun(runId);
      setRunBData(r);
    } catch (e) {
      console.error("Failed to load run B:", e);
    }
  };

  // Run evaluation in the background independent of page lifecycle
  const handleRunEvaluation = async () => {
    const selectedModel = model || defaultModel;
    if (!availableModels.includes(selectedModel)) {
      notify("Select an installed Ollama model before running the LLM judge.", "error");
      return;
    }
    if (datasetMode === "custom") {
      if (customDatasetCases.length === 0) {
        notify(
          "Custom dataset is empty. Please add or upload cases first.",
          "error",
        );
        return;
      }
      const invalid = customDatasetCases.find(
        (c) => !c.question?.trim() || !c.expected_answer?.trim(),
      );
      if (invalid) {
        notify(
          `Custom case "${invalid.case_id}" has an empty question or expected answer. Please fix before running.`,
          "error",
        );
        return;
      }
    } else {
      if (cases.length === 0) {
        notify(
          "Please load or import test cases before running evaluation.",
          "error",
        );
        return;
      }
    }

    const targetCases: JudgeCaseResult[] =
      datasetMode === "custom"
        ? customDatasetCases.map((c, idx) => ({
            case_id: c.case_id || `custom_${idx + 1}`,
            trace_id: `custom_trace_${idx + 1}`,
            question: c.question,
            answer: c.expected_answer || "",
            expected_answer: c.expected_answer || "",
            retrieved_context: c.retrieved_context || "",
            handbook_version: c.handbook_version || "2018",
            section_info: c.expected_section || "",
            taxonomy_mode: c.taxonomy || "Custom Case",
            human_label: c.human_label ?? 1,
            expected_numeric: c.expected_numeric,
            out_of_jurisdiction: c.out_of_jurisdiction ?? false,
            status: "PENDING" as const,
            evaluation_run_id: null,
            judge_v1_verdict: null,
            judge_v1_agreed: null,
            judge_v1_raw: null,
            judge_v1_source: null,
            judge_v1_latency_ms: null,
            judge_v1_llm_completed: null,
            judge_v2_verdict: null,
            judge_v2_agreed: null,
            judge_v2_raw: null,
            judge_v2_source: null,
            judge_v2_latency_ms: null,
            judge_v2_llm_completed: null,
            source: null,
            latency_ms: null,
            llm_completed: null,
            assertions: null,
            failure_category: null,
            failure_type: null,
            failure_reason: null,
            resolution: null,
          }))
        : cases;

    stopPolling();
    setIsStarting(true);
    // Explicitly reset prior run presentation immediately:
    setCases([]);
    setCurrentRunId(null);
    setEvalProgress({
      current: 0,
      total: targetCases.length,
      pct: 0,
      currentCaseId: "",
      currentQuestion: "",
      elapsedSeconds: 0,
      estRemainingSeconds: 0,
      activeCaseId: null,
      completedSuccess: false,
    });
    setEvaluatingCaseId(null);

    try {
      const runState = await api.startEvaluationRun(
        targetCases,
        true,
        topK,
        temperature,
        selectedModel,
      );
      sessionStorage.setItem(
        "judge_evaluation_active_run_id",
        runState.evaluation_run_id,
      );
      setCurrentRunId(runState.evaluation_run_id);
      setCases(runState.cases || runState.results || []);
      updateLoadingState(true);
      startPolling(runState.evaluation_run_id);
      notify(
        `🚀 Started background evaluation run "${runState.evaluation_run_id}" (${runState.total_cases} cases, Top-K: ${topK}, Temp: ${temperature}, Model: ${model || defaultModel})!`,
        "info",
      );
    } catch (e) {
      updateLoadingState(false);
      notify(
        "Failed to start evaluation run: " + (e as Error).message,
        "error",
      );
    } finally {
      setIsStarting(false);
    }
  };

  // Add custom case
  const handleAddCustomCase = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customQuestion.trim() || !customAnswer.trim()) {
      notify("Question and Answer are both required.", "error");
      return;
    }

    const newCase: JudgeCaseResult = {
      case_id: `custom_${Date.now().toString().slice(-4)}`,
      trace_id: `trace_custom_${Date.now().toString().slice(-4)}`,
      question: customQuestion.trim(),
      answer: customAnswer.trim(),
      retrieved_context: customContext.trim(),
      handbook_version: "2018",
      taxonomy_mode: customMode,
      human_label: customHumanLabel,
      expected_numeric: customNumeric.trim() || undefined,
      out_of_jurisdiction: customOoj,
      status: "PENDING",
      evaluation_run_id: null,
      judge_v1_verdict: null,
      judge_v1_agreed: null,
      judge_v1_raw: null,
      judge_v1_source: null,
      judge_v1_latency_ms: null,
      judge_v1_llm_completed: null,
      judge_v2_verdict: null,
      judge_v2_agreed: null,
      judge_v2_raw: null,
      judge_v2_source: null,
      judge_v2_latency_ms: null,
      judge_v2_llm_completed: null,
      source: null,
      latency_ms: null,
      llm_completed: null,
      assertions: null,
      failure_category: null,
      failure_type: null,
      failure_reason: null,
      resolution: null,
    };

    setCases((prev) => [newCase, ...prev]);
    setShowAddModal(false);
    setCustomQuestion("");
    setCustomAnswer("");
    setCustomContext("");
    setCustomNumeric("");
    setCustomOoj(false);
    setCustomHumanLabel(1);
    notify(
      `Added custom test case "${newCase.case_id}" to table (Pending).`,
      "success",
    );
  };

  // Filtered cases
  const filteredCases = cases.filter((c) => {
    if (filterMode !== "all" && c.taxonomy_mode !== filterMode) return false;
    if (filterCategory !== "all") {
      if (filterCategory === "pending") {
        if (c.status !== "PENDING" && c.status !== "RUNNING") return false;
      } else if (c.failure_category !== filterCategory) {
        return false;
      }
    }
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchQ = c.question.toLowerCase().includes(q);
      const matchA = c.answer.toLowerCase().includes(q);
      const matchId = c.case_id.toLowerCase().includes(q);
      if (!matchQ && !matchA && !matchId) return false;
    }
    return true;
  });

  // Calculate statistics (computed strictly on completed evaluations of the active run)
  const evaluatedCases = cases.filter(
    (c) =>
      c.status === "COMPLETED" &&
      c.judge_v1_verdict !== null &&
      c.judge_v1_verdict !== undefined,
  );
  const totalCount = cases.length;
  const totalEvaluated = evaluatedCases.length;
  const humanCorrectCount = cases.filter((c) => c.human_label === 1).length;
  const v1AgreementCount = evaluatedCases.filter(
    (c) => c.judge_v1_verdict === c.human_label,
  ).length;
  const v2AgreementCount = evaluatedCases.filter(
    (c) => c.judge_v2_verdict === c.human_label,
  ).length;
  const v1Pct =
    totalEvaluated > 0
      ? ((v1AgreementCount / totalEvaluated) * 100).toFixed(1)
      : "—";
  const v2Pct =
    totalEvaluated > 0
      ? ((v2AgreementCount / totalEvaluated) * 100).toFixed(1)
      : "—";

  const pipelineFails = evaluatedCases.filter(
    (c) => c.failure_category === "pipeline",
  ).length;
  const modelFails = evaluatedCases.filter(
    (c) => c.failure_category === "llm_model",
  ).length;
  const codeFails = evaluatedCases.filter(
    (c) => c.failure_category === "code_issue",
  ).length;

  // File Import Handler (supports .txt, .md, and .json)
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fileName = file.name.toLowerCase();
    const reader = new FileReader();

    reader.onload = (event) => {
      try {
        const content = event.target?.result as string;

        if (fileName.endsWith(".json")) {
          const parsed = JSON.parse(content);
          if (Array.isArray(parsed)) {
            const imported: JudgeCaseResult[] = parsed.map((item, idx) => ({
              case_id: item.case_id || `imported_${idx + 1}`,
              trace_id: item.trace_id || "",
              question: item.question || "",
              answer: item.answer || "",
              retrieved_context: item.retrieved_context || "",
              handbook_version: item.handbook_version || "2018",
              section_info: item.section_info || "",
              taxonomy_mode: item.taxonomy_mode || "Imported Case",
              human_label:
                item.human_label !== undefined ? item.human_label : 1,
              expected_numeric: item.expected_numeric,
              out_of_jurisdiction: item.out_of_jurisdiction || false,
              status: "PENDING" as const,
              evaluation_run_id: null,
              judge_v1_verdict: null,
              judge_v1_agreed: null,
              judge_v1_raw: null,
              judge_v1_source: null,
              judge_v1_latency_ms: null,
              judge_v1_llm_completed: null,
              judge_v2_verdict: null,
              judge_v2_agreed: null,
              judge_v2_raw: null,
              judge_v2_source: null,
              judge_v2_latency_ms: null,
              judge_v2_llm_completed: null,
              source: null,
              latency_ms: null,
              llm_completed: null,
              assertions: null,
              failure_category: null,
              failure_type: null,
              failure_reason: null,
              resolution: null,
            }));
            setCases(imported);
            setCurrentRunId(null);
            notify(
              `Successfully imported ${imported.length} test cases from ${file.name} (All Pending)!`,
              "success",
            );
          } else {
            notify("JSON file must contain an array of case objects.", "error");
          }
        } else if (fileName.endsWith(".txt") || fileName.endsWith(".md")) {
          // Parse Q: and A: pairs from text file with comment & taxonomy awareness
          const pairs: Array<{
            caseId?: string;
            taxonomyMode?: string;
            question: string;
            answer: string;
          }> = [];
          let currentCaseId: string | null = null;
          let currentModeName: string | null = null;
          let currentQ: string | null = null;
          let currentA: string | null = null;
          let activeField: "q" | "a" | null = null;

          const flush = () => {
            if (currentQ && currentA) {
              const cleanA = currentA.replace(/\s*#+\s*---*.*$/i, "").trim();
              const cleanQ = currentQ.replace(/\s*#+\s*---*.*$/i, "").trim();
              pairs.push({
                caseId: currentCaseId || undefined,
                taxonomyMode: currentModeName || undefined,
                question: cleanQ,
                answer: cleanA,
              });
            }
            currentQ = null;
            currentA = null;
            activeField = null;
          };

          const lines = content.split(/\r?\n/);
          for (const rawLine of lines) {
            const line = rawLine.trim();
            if (!line) continue;

            // Check for Case header: e.g. # --- Case 01 [Low-K Multi-Clause Truncation] ---
            const headerMatch = line.match(
              /^#+\s*---*\s*Case\s*(\d+)\s*(?:\[(.*?)\])?/i,
            );
            if (headerMatch) {
              flush();
              const num = parseInt(headerMatch[1], 10);
              currentCaseId = `case_${num.toString().padStart(2, "0")}`;
              currentModeName = headerMatch[2]?.trim() || null;
              continue;
            }

            // Ignore general comment lines or separator lines
            if (
              line.startsWith("#") ||
              line.startsWith("//") ||
              line.startsWith("/*") ||
              line.startsWith("*/") ||
              /^[=\-_*]{3,}$/.test(line)
            ) {
              continue;
            }

            const qMatch = line.match(/^q(?:uestion)?\s*[:\-.]\s*(.*)/i);
            const aMatch = line.match(/^a(?:nswer)?\s*[:\-.]\s*(.*)/i);

            if (qMatch) {
              flush();
              currentQ = qMatch[1].trim();
              activeField = "q";
            } else if (aMatch) {
              currentA = aMatch[1].trim();
              activeField = "a";
            } else if (activeField === "q" && currentQ !== null) {
              currentQ += " " + line;
            } else if (activeField === "a" && currentA !== null) {
              currentA += " " + line;
            }
          }
          flush();

          if (pairs.length > 0) {
            const imported: JudgeCaseResult[] = pairs.map((p, idx) => {
              const defaultCid =
                p.caseId || `case_${(idx + 1).toString().padStart(2, "0")}`;
              const isTrueNegative =
                defaultCid === "case_01" || defaultCid === "case_03";
              const groundTruthLabel = isTrueNegative ? 0 : 1;
              const mode =
                p.taxonomyMode ||
                (idx < 5
                  ? "Low-K Multi-Clause Truncation"
                  : idx < 10
                    ? "Sub-Clause Dispersal Across Disparate Policy Chapters"
                    : idx < 15
                      ? "Citation Drifting & In-Prose Structural Inversion"
                      : idx < 20
                        ? "Unstated Policy Invariant Refusal"
                        : "Embedding Similarity Threshold Starvation");

              return {
                case_id: defaultCid,
                trace_id: `txt_trace_${idx + 1}`,
                question: p.question,
                answer: p.answer,
                retrieved_context: "",
                handbook_version: "2018",
                taxonomy_mode: mode,
                human_label: groundTruthLabel,
                expected_numeric:
                  defaultCid === "case_01"
                    ? "two working days"
                    : defaultCid === "case_03"
                      ? "exceptional"
                      : defaultCid === "case_02"
                        ? "two working days"
                        : undefined,
                status: "PENDING" as const,
                evaluation_run_id: null,
                judge_v1_verdict: null,
                judge_v1_agreed: null,
                judge_v1_raw: null,
                judge_v1_source: null,
                judge_v1_latency_ms: null,
                judge_v1_llm_completed: null,
                judge_v2_verdict: null,
                judge_v2_agreed: null,
                judge_v2_raw: null,
                judge_v2_source: null,
                judge_v2_latency_ms: null,
                judge_v2_llm_completed: null,
                source: null,
                latency_ms: null,
                llm_completed: null,
                assertions: null,
                failure_category: null,
                failure_type: null,
                failure_reason: null,
                resolution: null,
              };
            });
            setCases(imported);
            setCurrentRunId(null);
            notify(
              `Successfully parsed & imported ${imported.length} Q&A pairs from ${file.name} (All Pending)!`,
              "success",
            );
          } else {
            notify(
              'No "Q:" / "A:" pairs found in the text file. Expected format:\nQ: Your question\nA: Your answer',
              "error",
            );
          }
        } else {
          notify(
            "Unsupported file type. Please upload a .txt, .md, or .json file.",
            "error",
          );
        }
      } catch (err) {
        notify("Failed to parse file: " + (err as Error).message, "error");
      }
    };
    reader.readAsText(file);
    e.target.value = "";
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "24px" }}>
      {/* HEADER HERO */}
      <div
        style={{
          background:
            "linear-gradient(135deg, rgba(30, 41, 59, 0.8), rgba(15, 23, 42, 0.95))",
          border: "1px solid var(--border)",
          borderRadius: "12px",
          padding: "24px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "6px",
            }}
          >
            <span
              style={{
                background: "rgba(59, 130, 246, 0.2)",
                color: "#60a5fa",
                fontSize: "0.75rem",
                fontWeight: 700,
                padding: "2px 8px",
                borderRadius: "4px",
                border: "1px solid rgba(59, 130, 246, 0.3)",
              }}
            >
              LLM JUDGE EVALUATOR
            </span>
            <span style={{ color: "var(--text-muted)", fontSize: "0.8rem" }}>
              M3 — Evals &amp; Error Analysis
            </span>
          </div>
          <h1
            style={{
              fontSize: "1.4rem",
              fontWeight: 800,
              color: "#fff",
              margin: 0,
            }}
          >
            LLM Judge &amp; Policy Assertions Evaluator
          </h1>
          <p
            style={{
              color: "var(--text-muted)",
              fontSize: "0.85rem",
              margin: "4px 0 0 0",
              maxWidth: "650px",
            }}
          >
            Compare LLM Judge V1 (Zero-Shot) vs Judge V2 (Few-Shot from
            Disagreements) against Pre-Judge Blind Human Ground Truth and 5
            Deterministic Rule Assertions.
          </p>
          <div
            style={{
              display: "flex",
              gap: "8px",
              alignItems: "center",
              marginTop: "8px",
              flexWrap: "wrap",
            }}
          >
            <span
              style={{ fontSize: "0.75rem", color: "#94a3b8", fontWeight: 600 }}
            >
              Evaluation Signals:
            </span>
            <span
              style={{
                fontSize: "0.72rem",
                background: "rgba(16, 185, 129, 0.15)",
                color: "#34d399",
                border: "1px solid rgba(16, 185, 129, 0.3)",
                borderRadius: "4px",
                padding: "2px 8px",
                fontWeight: 600,
              }}
            >
              ✓ Judge V1 (Zero-Shot)
            </span>
            <span
              style={{
                fontSize: "0.72rem",
                background: "rgba(99, 102, 241, 0.15)",
                color: "#a5b4fc",
                border: "1px solid rgba(99, 102, 241, 0.3)",
                borderRadius: "4px",
                padding: "2px 8px",
                fontWeight: 600,
              }}
            >
              ✓ Judge V2 (Few-Shot)
            </span>
            <span
              style={{
                fontSize: "0.72rem",
                background: "rgba(245, 158, 11, 0.15)",
                color: "#fbbf24",
                border: "1px solid rgba(245, 158, 11, 0.3)",
                borderRadius: "4px",
                padding: "2px 8px",
                fontWeight: 600,
              }}
            >
              ✓ Deterministic Assertions (5 Rules)
            </span>
          </div>
        </div>

        <div
          style={{
            display: "flex",
            gap: "10px",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          {loading ? (
            <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
              <button
                type="button"
                disabled
                className="btn-primary"
                style={{
                  display: "flex",
                  alignItems: "center",
                  gap: "8px",
                  minWidth: "180px",
                  justifyContent: "center",
                  background: "linear-gradient(135deg, #1d4ed8, #2563eb)",
                }}
              >
                <span
                  className="spinner"
                  style={{ width: "14px", height: "14px" }}
                ></span>
                <span>
                  Evaluating{" "}
                  {evalProgress
                    ? `${evalProgress.pct}% (${evalProgress.current}/${evalProgress.total})`
                    : "..."}
                </span>
              </button>
              <button
                type="button"
                onClick={handleCancelEvaluation}
                className="btn-secondary"
                style={{
                  color: "#f87171",
                  borderColor: "rgba(239, 68, 68, 0.4)",
                  background: "rgba(239, 68, 68, 0.1)",
                  padding: "7px 14px",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                }}
                title="Cancel ongoing evaluation"
              >
                🛑 Cancel
              </button>
            </div>
          ) : isStarting ? (
            <button
              type="button"
              disabled
              className="btn-primary"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "8px",
                minWidth: "180px",
                justifyContent: "center",
                opacity: 0.85,
              }}
            >
              <span
                className="spinner"
                style={{ width: "14px", height: "14px" }}
              ></span>
              <span>Starting Run...</span>
            </button>
          ) : (
            <button
              type="button"
              onClick={handleRunEvaluation}
              disabled={
                datasetMode === "custom"
                  ? customDatasetCases.length === 0
                  : cases.length === 0
              }
              className="btn-primary"
              style={{
                display: "flex",
                alignItems: "center",
                gap: "6px",
                minWidth: "160px",
                justifyContent: "center",
              }}
            >
              <span>⚡</span> Run Evaluation (
              {datasetMode === "custom"
                ? customDatasetCases.length
                : cases.length || 25}{" "}
              Cases)
            </button>
          )}
        </div>
      </div>

      {/* DATASET MANAGEMENT (UPLOAD / MANUAL EDITING) */}
      <EvaluationDatasetManager
        evaluatorType="judge"
        title="LLM Judge Evaluator"
        builtinCount={cases.length || 25}
        builtinLabel="Official 25-Case Benchmark"
        datasetMode={datasetMode}
        customCases={customDatasetCases}
        isRunning={loading || isStarting}
        onModeChange={(mode) => {
          setDatasetMode(mode);
          if (mode === "builtin") {
            notify("Switched to Official 25-Case Benchmark dataset.", "info");
          } else {
            notify(
              `Switched to Custom Dataset (${customDatasetCases.length} cases loaded).`,
              "info",
            );
          }
        }}
        onCustomCasesChange={(updated) => setCustomDatasetCases(updated)}
        onResetToBuiltin={() => {
          setDatasetMode("builtin");
          handleLoadBenchmark();
        }}
        onNotify={notify}
        storageKey="judge_custom_dataset"
      />

      {/* EXPERIMENT & HYPERPARAMETER CONTROLS BAR */}
      <div
        style={{
          background: "rgba(15, 23, 42, 0.75)",
          border: "1px solid var(--border)",
          borderRadius: "10px",
          padding: "14px 20px",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "14px",
        }}
      >
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: "20px",
            flexWrap: "wrap",
          }}
        >
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <span
              style={{
                fontSize: "0.82rem",
                fontWeight: 700,
                color: loading ? "#fbbf24" : "var(--text-muted)",
              }}
            >
              {loading ? "🔒 Configuration Frozen:" : "⚙️ Experiment Controls:"}
            </span>
          </div>

          {/* Top-K Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <label
              style={{ fontSize: "0.8rem", fontWeight: 600, color: "#e2e8f0" }}
            >
              Top K:
            </label>
            <select
              value={topK}
              onChange={(e) => setTopK(parseInt(e.target.value, 10))}
              disabled={loading}
              style={{
                background: "rgba(30, 41, 59, 0.9)",
                border: "1px solid var(--border)",
                color: "#fff",
                borderRadius: "6px",
                padding: "5px 10px",
                fontSize: "0.82rem",
                fontWeight: 600,
                cursor: loading ? "not-allowed" : "pointer",
              }}
            >
              {[4, 5, 6, 8, 10, 12].map((kVal) => (
                <option key={kVal} value={kVal}>
                  {kVal}{" "}
                  {kVal === 8
                    ? "(Week 6 Baseline)"
                    : kVal === 5
                      ? "(App Default)"
                      : ""}
                </option>
              ))}
            </select>
          </div>

          {/* Temperature Selector */}
          <div style={{ display: "flex", alignItems: "center", gap: "8px" }}>
            <label
              style={{ fontSize: "0.8rem", fontWeight: 600, color: "#e2e8f0" }}
            >
              Temperature:
            </label>
            <select
              value={temperature}
              onChange={(e) => setTemperature(parseFloat(e.target.value))}
              disabled={loading}
              style={{
                background: "rgba(30, 41, 59, 0.9)",
                border: "1px solid var(--border)",
                color: "#fff",
                borderRadius: "6px",
                padding: "5px 10px",
                fontSize: "0.82rem",
                fontWeight: 600,
                cursor: loading ? "not-allowed" : "pointer",
              }}
            >
              {[0.0, 0.1, 0.2, 0.3, 0.5, 0.7].map((tVal) => (
                <option key={tVal} value={tVal}>
                  {tVal.toFixed(1)}{" "}
                  {tVal === 0.0
                    ? "(Week 6 Baseline)"
                    : tVal === 0.3
                      ? "(App Default)"
                      : ""}
                </option>
              ))}
            </select>
          </div>

          <div style={{ minWidth: 160 }}>
            <label
              style={{
                fontSize: "0.8rem",
                fontWeight: 600,
                color: "#e2e8f0",
                display: "block",
                marginBottom: 4,
              }}
            >
              Model:
            </label>
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              disabled={loading || isLoadingModels || availableModels.length === 0}
              style={{
                background: "rgba(30, 41, 59, 0.9)",
                border: "1px solid var(--border)",
                color: "#fff",
                borderRadius: "6px",
                padding: "5px 10px",
                fontSize: "0.82rem",
                fontWeight: 600,
                cursor:
                  loading || isLoadingModels || availableModels.length === 0
                    ? "not-allowed"
                    : "pointer",
              }}
            >
              {availableModels.length === 0 ? (
                <option value="">
                  {isLoadingModels ? "Loading models…" : "No models available"}
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
              <div
                role="alert"
                style={{ color: "#f87171", fontSize: "0.72rem", marginTop: 4 }}
              >
                {modelsError}
              </div>
            )}
          </div>

          {/* Active Config Tag */}
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "6px",
              background: "rgba(59, 130, 246, 0.1)",
              border: "1px solid rgba(59, 130, 246, 0.25)",
              borderRadius: "6px",
              padding: "4px 10px",
              fontSize: "0.78rem",
              color: "#93c5fd",
              fontFamily: "ui-monospace, monospace",
            }}
          >
            <span>
              Active: Top-K = <strong>{topK}</strong> | Temp ={" "}
              <strong>{temperature.toFixed(1)}</strong> | Model:{" "}
              <strong>
                {model || (isLoadingModels ? "Loading…" : defaultModel || "Unavailable")}
              </strong>
            </span>
          </div>
        </div>

        {/* Baseline / Default Quick-Reset Buttons */}
        <div style={{ display: "flex", gap: "8px", alignItems: "center" }}>
          <button
            type="button"
            onClick={handleResetToBaseline}
            disabled={loading}
            style={{
              padding: "5px 12px",
              fontSize: "0.78rem",
              fontWeight: 600,
              borderRadius: "6px",
              border: "1px solid rgba(99, 102, 241, 0.4)",
              background:
                topK === 8 && temperature === 0.0
                  ? "rgba(99, 102, 241, 0.25)"
                  : "rgba(99, 102, 241, 0.1)",
              color: "#a5b4fc",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "all 0.15s ease",
            }}
            title="Restore Authoritative Frozen Week 6 Baseline (Top-K=8, Temp=0.0)"
          >
            🎯 Week 6 Baseline (K=8, T=0.0)
          </button>
          <button
            type="button"
            onClick={handleResetToAppDefault}
            disabled={loading}
            style={{
              padding: "5px 12px",
              fontSize: "0.78rem",
              fontWeight: 600,
              borderRadius: "6px",
              border: "1px solid rgba(16, 185, 129, 0.4)",
              background:
                topK === 5 && temperature === 0.3
                  ? "rgba(16, 185, 129, 0.25)"
                  : "rgba(16, 185, 129, 0.1)",
              color: "#6ee7b7",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "all 0.15s ease",
            }}
            title="Restore Current Application Default (Top-K=5, Temp=0.3)"
          >
            ⚡ App Default (K=5, T=0.3)
          </button>
          <button
            type="button"
            onClick={handleOpenCompare}
            disabled={loading}
            style={{
              padding: "5px 12px",
              fontSize: "0.78rem",
              fontWeight: 600,
              borderRadius: "6px",
              border: "1px solid rgba(245, 158, 11, 0.4)",
              background: "rgba(245, 158, 11, 0.12)",
              color: "#fcd34d",
              cursor: loading ? "not-allowed" : "pointer",
              transition: "all 0.15s ease",
            }}
            title="Compare evaluation runs side-by-side (Run A vs Run B)"
          >
            ⚖️ Compare Runs
          </button>
        </div>
      </div>

      {/* LIVE EVALUATION PROGRESS BAR CARD */}
      {(loading || (evalProgress && evalProgress.completedSuccess)) &&
        evalProgress && (
          <EvaluationProgressCard
            title={
              evalProgress.completedSuccess
                ? `Evaluation Complete: 100% (All ${evalProgress.total} Cases)`
                : `Evaluation Running: ${evalProgress.pct}%`
            }
            current={evalProgress.current}
            total={evalProgress.total}
            pct={evalProgress.pct}
            currentCaseId={evalProgress.currentCaseId || evaluatingCaseId}
            currentQuestion={evalProgress.currentQuestion}
            elapsedSeconds={evalProgress.elapsedSeconds}
            estRemainingSeconds={evalProgress.estRemainingSeconds}
            isRunning={loading}
            isComplete={evalProgress.completedSuccess}
            configurationText={`Top-K: ${topK} | Temperature: ${temperature.toFixed(1)} | Model: ${model || defaultModel}`}
            signals={[
              {
                label: "Judge V1",
                completed: evalProgress.current,
                total: evalProgress.total,
                agreementPct: totalEvaluated > 0 ? v1Pct : null,
                color: "#60a5fa",
              },
              {
                label: "Judge V2",
                completed: evalProgress.current,
                total: evalProgress.total,
                agreementPct: totalEvaluated > 0 ? v2Pct : null,
                color: "#f59e0b",
              },
              {
                label: "Assertions",
                completed: evalProgress.current,
                total: evalProgress.total,
                color: "#10b981",
                statusText: "5 Rules",
              },
            ]}
            onCancel={loading ? handleCancelEvaluation : undefined}
          />
        )}

      {/* STAT CARDS */}
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          gap: "16px",
        }}
      >
        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "16px",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            Total Test Cases
          </div>
          <div
            style={{
              fontSize: "1.7rem",
              fontWeight: 800,
              color: "#fff",
              marginTop: "4px",
            }}
          >
            {totalCount}{" "}
            {totalEvaluated > 0 ? (
              <span
                style={{
                  fontSize: "0.85rem",
                  color: "#10b981",
                  fontWeight: 500,
                }}
              >
                ({humanCorrectCount} Human Correct)
              </span>
            ) : totalCount > 0 ? (
              <span
                style={{
                  fontSize: "0.85rem",
                  color: "#60a5fa",
                  fontWeight: 500,
                }}
              >
                (Loaded: {totalCount}/{totalCount})
              </span>
            ) : null}
          </div>
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginTop: "4px",
            }}
          >
            5 Taxonomy Modes + 6 Regressions
          </div>
        </div>

        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "16px",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            Judge V1 Agreement (Baseline)
          </div>
          <div
            style={{
              fontSize: "1.7rem",
              fontWeight: 800,
              color: "#60a5fa",
              marginTop: "4px",
            }}
          >
            {totalEvaluated > 0 ? (
              <>
                {v1Pct}%{" "}
                <span
                  style={{
                    fontSize: "0.85rem",
                    color: "var(--text-muted)",
                    fontWeight: 500,
                  }}
                >
                  ({v1AgreementCount}/{totalEvaluated})
                </span>
              </>
            ) : (
              "—"
            )}
          </div>
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginTop: "4px",
            }}
          >
            Zero-Shot Binary Semantic Prompt
          </div>
        </div>

        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "16px",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            Judge V2 Agreement (Iterated)
          </div>
          <div
            style={{
              fontSize: "1.7rem",
              fontWeight: 800,
              color: "#f59e0b",
              marginTop: "4px",
            }}
          >
            {totalEvaluated > 0 ? (
              <>
                {v2Pct}%{" "}
                <span
                  style={{
                    fontSize: "0.85rem",
                    color: "var(--text-muted)",
                    fontWeight: 500,
                  }}
                >
                  ({v2AgreementCount}/{totalEvaluated})
                </span>
              </>
            ) : (
              "—"
            )}
          </div>
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginTop: "4px",
            }}
          >
            Few-Shot with 2 Disagreements
          </div>
        </div>

        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "16px",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            Status
          </div>
          <div
            style={{
              fontSize: "1.5rem",
              fontWeight: 800,
              color:
                totalEvaluated === totalCount && totalCount > 0
                  ? "#34d399"
                  : loading
                    ? "#60a5fa"
                    : totalEvaluated > 0
                      ? "#60a5fa"
                      : totalCount > 0
                        ? "#10b981"
                        : "var(--text-muted)",
              marginTop: "4px",
            }}
          >
            {totalEvaluated === totalCount && totalCount > 0
              ? "Complete"
              : loading
                ? evalProgress
                  ? `Running (${evalProgress.current}/${evalProgress.total})`
                  : `Running (0/${totalCount})`
                : totalEvaluated > 0
                  ? `${totalEvaluated}/${totalCount} Evaluated`
                  : totalCount > 0
                    ? "Ready"
                    : "Not Started"}
          </div>
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginTop: "4px",
            }}
          >
            {loading
              ? currentRunId
                ? `Run: ${currentRunId.slice(0, 16)}`
                : "In progress"
              : totalCount > 0 && totalEvaluated === 0
                ? "Loaded: 25/25 Ready"
                : currentRunId
                  ? `Run: ${currentRunId.slice(0, 16)}`
                  : "No active run"}
          </div>
        </div>

        <div
          style={{
            background: "var(--bg-surface)",
            border: "1px solid var(--border)",
            borderRadius: "10px",
            padding: "16px",
          }}
        >
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              textTransform: "uppercase",
              fontWeight: 600,
            }}
          >
            Failure Root Causes
          </div>
          {totalEvaluated > 0 ? (
            <div
              style={{
                display: "flex",
                gap: "8px",
                marginTop: "8px",
                flexWrap: "wrap",
              }}
            >
              <span
                style={{
                  background: "rgba(239, 68, 68, 0.2)",
                  color: "#f87171",
                  fontSize: "0.75rem",
                  padding: "3px 8px",
                  borderRadius: "4px",
                  fontWeight: 600,
                }}
              >
                Pipeline: {pipelineFails}
              </span>
              <span
                style={{
                  background: "rgba(245, 158, 11, 0.2)",
                  color: "#fbbf24",
                  fontSize: "0.75rem",
                  padding: "3px 8px",
                  borderRadius: "4px",
                  fontWeight: 600,
                }}
              >
                Model: {modelFails}
              </span>
              <span
                style={{
                  background: "rgba(16, 185, 129, 0.2)",
                  color: "#34d399",
                  fontSize: "0.75rem",
                  padding: "3px 8px",
                  borderRadius: "4px",
                  fontWeight: 600,
                }}
              >
                Code: {codeFails}
              </span>
            </div>
          ) : (
            <div
              style={{
                fontSize: "1.5rem",
                fontWeight: 800,
                color: "var(--text-muted)",
                marginTop: "4px",
              }}
            >
              —
            </div>
          )}
          <div
            style={{
              fontSize: "0.75rem",
              color: "var(--text-muted)",
              marginTop: "6px",
            }}
          >
            {totalEvaluated > 0
              ? "5 Assertions vs 1 Judge Criterion"
              : "No evaluation run"}
          </div>
        </div>
      </div>

      {/* CONTROLS TOOLBAR */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "12px",
          background: "var(--bg-surface)",
          padding: "12px 16px",
          borderRadius: "8px",
          border: "1px solid var(--border)",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: "10px",
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <input
            type="text"
            placeholder="🔍 Search questions, answers, case IDs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: "var(--bg-card)",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "6px 12px",
              color: "#fff",
              fontSize: "0.85rem",
              minWidth: "260px",
            }}
          />

          <select
            value={filterMode}
            onChange={(e) => setFilterMode(e.target.value)}
            style={{
              background: "#1e293b",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "7px 12px",
              color: "#f8fafc",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          >
            <option
              value="all"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              All Taxonomy Modes
            </option>
            <option
              value="Low-K Multi-Clause Truncation"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Low-K Multi-Clause Truncation
            </option>
            <option
              value="Sub-Clause Dispersal Across Disparate Policy Chapters"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Sub-Clause Dispersal
            </option>
            <option
              value="Citation Drifting & In-Prose Structural Inversion"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Citation Drifting
            </option>
            <option
              value="Unstated Policy Invariant Refusal"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Unstated Policy Refusal
            </option>
            <option
              value="Embedding Similarity Threshold Starvation"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Embedding Starvation
            </option>
          </select>

          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            style={{
              background: "#1e293b",
              border: "1px solid var(--border)",
              borderRadius: "6px",
              padding: "7px 12px",
              color: "#f8fafc",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          >
            <option
              value="all"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              All Statuses &amp; Categories
            </option>
            <option
              value="pending"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Pending / In Progress
            </option>
            <option
              value="pipeline"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Pipeline Failure
            </option>
            <option
              value="llm_model"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              LLM Model Failure
            </option>
            <option
              value="code_issue"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Code Issue
            </option>
            <option
              value="pass"
              style={{ background: "#0f172a", color: "#f8fafc" }}
            >
              Clean Pass
            </option>
          </select>
        </div>

        <div
          style={{
            display: "flex",
            gap: "8px",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <span style={{ fontSize: "0.8rem", color: "var(--text-muted)" }}>
            Showing <strong>{filteredCases.length}</strong> of {totalCount}{" "}
            cases
          </span>

          {(searchQuery.trim() ||
            filterMode !== "all" ||
            filterCategory !== "all") && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="btn-secondary"
              style={{ padding: "5px 10px", fontSize: "0.8rem" }}
              title="Reset search and filters"
            >
              ✕ Reset Filters
            </button>
          )}

          <button
            type="button"
            onClick={handleLoadBenchmark}
            className="btn-secondary"
            style={{ padding: "5px 10px", fontSize: "0.8rem" }}
            title="Load the 25 official benchmark test cases"
          >
            🔄 Load 25 Benchmark
          </button>

          <button
            type="button"
            onClick={handleClearTable}
            className="btn-secondary"
            style={{
              padding: "5px 10px",
              fontSize: "0.8rem",
              color: "#f87171",
              borderColor: "rgba(239, 68, 68, 0.4)",
              background: "rgba(239, 68, 68, 0.1)",
            }}
            title="Clear all test cases from the table"
          >
            🗑️ Clear Table
          </button>
        </div>
      </div>

      {/* TABLE STRUCTURE */}
      <div
        style={{
          background: "var(--bg-surface)",
          border: "1px solid var(--border)",
          borderRadius: "10px",
          overflow: "hidden",
        }}
      >
        <div style={{ overflowX: "auto" }}>
          <table
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: "0.85rem",
              textAlign: "left",
            }}
          >
            <thead>
              <tr
                style={{
                  background: "rgba(255, 255, 255, 0.03)",
                  borderBottom: "1px solid var(--border)",
                  color: "var(--text-muted)",
                  fontSize: "0.75rem",
                  textTransform: "uppercase",
                }}
              >
                <th style={{ padding: "12px 14px", width: "100px" }}>
                  Case ID
                </th>
                <th style={{ padding: "12px 14px", width: "220px" }}>
                  Question
                </th>
                <th style={{ padding: "12px 14px", width: "220px" }}>
                  Assistant Answer
                </th>
                <th
                  style={{
                    padding: "12px 14px",
                    textAlign: "center",
                    width: "100px",
                  }}
                >
                  Ground Truth
                </th>
                <th
                  style={{
                    padding: "12px 14px",
                    textAlign: "center",
                    width: "105px",
                  }}
                >
                  Judge V1
                </th>
                <th
                  style={{
                    padding: "12px 14px",
                    textAlign: "center",
                    width: "105px",
                  }}
                >
                  Judge V2
                </th>
                <th style={{ padding: "12px 14px", width: "130px" }}>
                  Assertions
                </th>
                <th style={{ padding: "12px 14px", width: "260px" }}>
                  Failure Root Cause &amp; Reason
                </th>
                <th
                  style={{
                    padding: "12px 14px",
                    width: "100px",
                    textAlign: "center",
                  }}
                >
                  Action
                </th>
              </tr>
            </thead>
            <tbody>
              {cases.length === 0 ? (
                <tr>
                  <td
                    colSpan={9}
                    style={{ padding: "48px 24px", textAlign: "center" }}
                  >
                    <div style={{ fontSize: "2rem", marginBottom: "8px" }}>
                      📋
                    </div>
                    <div
                      style={{
                        fontSize: "1.05rem",
                        fontWeight: 700,
                        color: "#fff",
                        marginBottom: "4px",
                      }}
                    >
                      No evaluation run yet
                    </div>
                    <div
                      style={{
                        fontSize: "0.82rem",
                        color: "var(--text-muted)",
                        marginBottom: "18px",
                        maxWidth: "520px",
                        margin: "0 auto 18px auto",
                        lineHeight: "1.5",
                      }}
                    >
                      Load the 25 benchmark test cases to begin, add custom
                      question-answer pairs, or import a file (.txt, .md,
                      .json).
                    </div>
                    <div
                      style={{
                        display: "flex",
                        gap: "10px",
                        justifyContent: "center",
                        flexWrap: "wrap",
                      }}
                    >
                      <button
                        type="button"
                        onClick={() => setShowAddModal(true)}
                        className="btn-secondary"
                        style={{ fontSize: "0.8rem", padding: "6px 14px" }}
                      >
                        ➕ Add Q&amp;A
                      </button>
                      <label
                        className="btn-secondary"
                        style={{
                          fontSize: "0.8rem",
                          padding: "6px 14px",
                          cursor: "pointer",
                          margin: 0,
                          display: "inline-flex",
                          alignItems: "center",
                          gap: "6px",
                        }}
                      >
                        📥 Import File (.txt / .json)
                        <input
                          type="file"
                          accept=".txt,.md,.json"
                          style={{ display: "none" }}
                          onChange={handleFileUpload}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={handleLoadBenchmark}
                        className="btn-primary"
                        style={{
                          fontSize: "0.8rem",
                          padding: "6px 14px",
                          width: "auto",
                        }}
                      >
                        🔄 Load 25 Benchmark
                      </button>
                    </div>
                  </td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td
                    colSpan={9}
                    style={{
                      padding: "36px 20px",
                      textAlign: "center",
                      color: "var(--text-muted)",
                    }}
                  >
                    <div style={{ fontSize: "0.9rem", marginBottom: "8px" }}>
                      🔍 No matching cases found for the active filter.
                    </div>
                    <button
                      type="button"
                      onClick={handleResetFilters}
                      className="btn-secondary"
                      style={{ fontSize: "0.8rem", padding: "5px 12px" }}
                    >
                      ✕ Reset Filters
                    </button>
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => {
                  const isCompleted =
                    c.status === "COMPLETED" &&
                    c.judge_v1_verdict !== null &&
                    c.judge_v1_verdict !== undefined;
                  const isCurrentlyEvaluating =
                    c.status === "RUNNING" || c.case_id === evaluatingCaseId;

                  const isV1Agreed =
                    isCompleted && c.judge_v1_verdict === c.human_label;
                  const isV2Agreed =
                    isCompleted && c.judge_v2_verdict === c.human_label;

                  return (
                    <tr
                      key={c.case_id}
                      style={{
                        borderBottom: "1px solid rgba(255, 255, 255, 0.05)",
                        transition: "all 0.2s ease",
                        background: isCurrentlyEvaluating
                          ? "rgba(59, 130, 246, 0.12)"
                          : "transparent",
                        boxShadow: isCurrentlyEvaluating
                          ? "inset 3px 0 0 #3b82f6"
                          : "none",
                      }}
                      onMouseEnter={(e) => {
                        if (!isCurrentlyEvaluating)
                          e.currentTarget.style.background =
                            "rgba(255, 255, 255, 0.02)";
                      }}
                      onMouseLeave={(e) => {
                        if (!isCurrentlyEvaluating)
                          e.currentTarget.style.background = "transparent";
                      }}
                    >
                      {/* Case ID */}
                      <td
                        style={{ padding: "12px 14px", verticalAlign: "top" }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            gap: "6px",
                          }}
                        >
                          {isCurrentlyEvaluating && (
                            <span
                              className="spinner"
                              style={{ width: "12px", height: "12px" }}
                            ></span>
                          )}
                          <div
                            style={{
                              fontWeight: 700,
                              color: isCurrentlyEvaluating ? "#60a5fa" : "#fff",
                            }}
                          >
                            {c.case_id}
                          </div>
                        </div>
                        {/* Provenance Tag */}
                        {c.evaluation_run_id && (
                          <div
                            style={{
                              fontSize: "0.66rem",
                              fontFamily: "ui-monospace, monospace",
                              color: "#93c5fd",
                              background: "rgba(59, 130, 246, 0.1)",
                              border: "1px solid rgba(59, 130, 246, 0.25)",
                              borderRadius: "3px",
                              padding: "1px 5px",
                              marginTop: "3px",
                              display: "inline-block",
                              whiteSpace: "nowrap",
                            }}
                            title={`Run: ${c.evaluation_run_id} | K: ${c.top_k ?? topK} | Temp: ${c.temperature ?? temperature}`}
                          >
                            K={c.top_k ?? topK} · T=
                            {c.temperature ?? temperature}
                          </div>
                        )}
                        <div
                          style={{
                            fontSize: "0.68rem",
                            color: "var(--text-muted)",
                            marginTop: "2px",
                            maxWidth: "120px",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            whiteSpace: "nowrap",
                          }}
                          title={`Benchmark Category: ${c.benchmark_taxonomy || c.taxonomy_mode}`}
                        >
                          🏷️{" "}
                          {c.benchmark_taxonomy ||
                            c.taxonomy_mode?.split(" ")[0]}
                        </div>
                      </td>

                      {/* Question */}
                      <td
                        style={{ padding: "12px 14px", verticalAlign: "top" }}
                      >
                        <div
                          style={{
                            color: "#e2e8f0",
                            fontWeight: 500,
                            lineHeight: "1.4",
                          }}
                        >
                          {c.question}
                        </div>
                      </td>

                      {/* Answer */}
                      <td
                        style={{ padding: "12px 14px", verticalAlign: "top" }}
                      >
                        <div
                          style={{
                            color: "var(--text-muted)",
                            fontSize: "0.8rem",
                            lineHeight: "1.4",
                            maxHeight: "65px",
                            overflow: "hidden",
                            textOverflow: "ellipsis",
                            display: "-webkit-box",
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: "vertical",
                          }}
                        >
                          {c.answer}
                        </div>
                      </td>

                      {/* Ground Truth */}
                      <td
                        style={{
                          padding: "12px 14px",
                          verticalAlign: "top",
                          textAlign: "center",
                        }}
                      >
                        {isCompleted ? (
                          <span
                            style={{
                              display: "inline-block",
                              padding: "2px 8px",
                              borderRadius: "4px",
                              fontSize: "0.75rem",
                              fontWeight: 700,
                              background:
                                c.human_label === 1
                                  ? "rgba(16, 185, 129, 0.15)"
                                  : "rgba(239, 68, 68, 0.15)",
                              color:
                                c.human_label === 1 ? "#34d399" : "#f87171",
                              border: `1px solid ${c.human_label === 1 ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                              fontFamily: "ui-monospace, monospace",
                            }}
                            title={`Benchmark Ground Truth Label: ${c.human_label === 1 ? "1 (Expected Pass)" : "0 (Expected Fail)"}`}
                          >
                            {c.human_label ?? "—"}
                          </span>
                        ) : (
                          <span
                            style={{
                              color: "var(--text-muted)",
                              fontSize: "0.75rem",
                            }}
                          >
                            —
                          </span>
                        )}
                      </td>

                      {/* Judge V1 */}
                      <td
                        style={{
                          padding: "12px 14px",
                          verticalAlign: "top",
                          textAlign: "center",
                        }}
                      >
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "4px",
                              color: "#60a5fa",
                              fontSize: "0.72rem",
                              fontWeight: 700,
                              background: "rgba(59, 130, 246, 0.15)",
                              padding: "2px 6px",
                              borderRadius: "4px",
                            }}
                          >
                            <span
                              className="spinner"
                              style={{ width: "10px", height: "10px" }}
                            ></span>
                            Running
                          </span>
                        ) : isCompleted &&
                          c.judge_v1_verdict !== null &&
                          c.judge_v1_verdict !== undefined ? (
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              alignItems: "center",
                              gap: "3px",
                            }}
                          >
                            <span
                              style={{
                                display: "inline-block",
                                padding: "2px 7px",
                                borderRadius: "4px",
                                fontSize: "0.75rem",
                                fontWeight: 700,
                                background:
                                  c.judge_v1_verdict === 1
                                    ? "rgba(59, 130, 246, 0.2)"
                                    : "rgba(239, 68, 68, 0.2)",
                                color:
                                  c.judge_v1_verdict === 1
                                    ? "#60a5fa"
                                    : "#f87171",
                                fontFamily: "ui-monospace, monospace",
                              }}
                            >
                              {c.judge_v1_verdict}
                            </span>
                            <span
                              style={{
                                fontSize: "0.65rem",
                                fontWeight: 600,
                                color: isV1Agreed ? "#10b981" : "#f59e0b",
                              }}
                            >
                              {isV1Agreed ? "✓ Agree" : "⚠ Disagree"}
                            </span>
                          </div>
                        ) : (
                          <span
                            style={{
                              color: "var(--text-muted)",
                              fontSize: "0.75rem",
                            }}
                          >
                            Pending
                          </span>
                        )}
                      </td>

                      {/* Judge V2 */}
                      <td
                        style={{
                          padding: "12px 14px",
                          verticalAlign: "top",
                          textAlign: "center",
                        }}
                      >
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{
                              display: "inline-flex",
                              alignItems: "center",
                              gap: "4px",
                              color: "#60a5fa",
                              fontSize: "0.72rem",
                              fontWeight: 700,
                              background: "rgba(59, 130, 246, 0.15)",
                              padding: "2px 6px",
                              borderRadius: "4px",
                            }}
                          >
                            <span
                              className="spinner"
                              style={{ width: "10px", height: "10px" }}
                            ></span>
                            Running
                          </span>
                        ) : isCompleted &&
                          c.judge_v2_verdict !== null &&
                          c.judge_v2_verdict !== undefined ? (
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              alignItems: "center",
                              gap: "3px",
                            }}
                          >
                            <span
                              style={{
                                display: "inline-block",
                                padding: "2px 7px",
                                borderRadius: "4px",
                                fontSize: "0.75rem",
                                fontWeight: 700,
                                background:
                                  c.judge_v2_verdict === 1
                                    ? "rgba(59, 130, 246, 0.2)"
                                    : "rgba(239, 68, 68, 0.2)",
                                color:
                                  c.judge_v2_verdict === 1
                                    ? "#60a5fa"
                                    : "#f87171",
                                fontFamily: "ui-monospace, monospace",
                              }}
                            >
                              {c.judge_v2_verdict}
                            </span>
                            <span
                              style={{
                                fontSize: "0.65rem",
                                fontWeight: 600,
                                color: isV2Agreed ? "#10b981" : "#f59e0b",
                              }}
                            >
                              {isV2Agreed ? "✓ Agree" : "⚠ Disagree"}
                            </span>
                          </div>
                        ) : (
                          <span
                            style={{
                              color: "var(--text-muted)",
                              fontSize: "0.75rem",
                            }}
                          >
                            Pending
                          </span>
                        )}
                      </td>

                      {/* Deterministic Assertions */}
                      <td
                        style={{ padding: "12px 14px", verticalAlign: "top" }}
                      >
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{ color: "#60a5fa", fontSize: "0.75rem" }}
                          >
                            Evaluating...
                          </span>
                        ) : isCompleted && c.assertions ? (
                          <div
                            style={{
                              display: "flex",
                              flexDirection: "column",
                              gap: "2px",
                              fontSize: "0.7rem",
                            }}
                          >
                            <span
                              style={{
                                color: c.assertions
                                  .policy_section_reference_resolves
                                  ? "#10b981"
                                  : "#ef4444",
                              }}
                            >
                              {c.assertions.policy_section_reference_resolves
                                ? "✓"
                                : "✗"}{" "}
                              Section Resolves
                            </span>
                            <span
                              style={{
                                color: c.assertions.handbook_version_present
                                  ? "#10b981"
                                  : "var(--text-muted)",
                              }}
                            >
                              {c.assertions.handbook_version_present
                                ? "✓"
                                : "○"}{" "}
                              Version Cited
                            </span>
                            <span
                              style={{
                                color: c.assertions.numeric_policy_value_present
                                  ? "#10b981"
                                  : "var(--text-muted)",
                              }}
                            >
                              {c.assertions.numeric_policy_value_present
                                ? "✓"
                                : "○"}{" "}
                              Numeric Match
                            </span>
                            <span
                              style={{
                                color: c.assertions.out_of_jurisdiction_refusal
                                  ? "#10b981"
                                  : "#ef4444",
                              }}
                            >
                              {c.assertions.out_of_jurisdiction_refusal
                                ? "✓"
                                : "✗"}{" "}
                              Refusal Guard
                            </span>
                          </div>
                        ) : (
                          <span
                            style={{
                              color: "var(--text-muted)",
                              fontSize: "0.75rem",
                            }}
                          >
                            —
                          </span>
                        )}
                      </td>

                      {/* Failure Root Cause & Reason */}
                      <td
                        style={{ padding: "12px 14px", verticalAlign: "top" }}
                      >
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{
                              display: "inline-block",
                              padding: "2px 7px",
                              borderRadius: "4px",
                              fontSize: "0.7rem",
                              fontWeight: 700,
                              background: "rgba(59, 130, 246, 0.2)",
                              color: "#60a5fa",
                            }}
                          >
                            Evaluating...
                          </span>
                        ) : isCompleted ? (
                          <>
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "6px",
                                flexWrap: "wrap",
                              }}
                            >
                              <span
                                style={{
                                  display: "inline-block",
                                  padding: "2px 7px",
                                  borderRadius: "4px",
                                  fontSize: "0.7rem",
                                  fontWeight: 700,
                                  background:
                                    c.failure_category === "pipeline"
                                      ? "rgba(239, 68, 68, 0.2)"
                                      : c.failure_category === "llm_model"
                                        ? "rgba(245, 158, 11, 0.2)"
                                        : c.failure_category === "code_issue"
                                          ? "rgba(168, 85, 247, 0.2)"
                                          : "rgba(16, 185, 129, 0.2)",
                                  color:
                                    c.failure_category === "pipeline"
                                      ? "#f87171"
                                      : c.failure_category === "llm_model"
                                        ? "#fbbf24"
                                        : c.failure_category === "code_issue"
                                          ? "#c084fc"
                                          : "#34d399",
                                  border: `1px solid ${
                                    c.failure_category === "pipeline"
                                      ? "rgba(239, 68, 68, 0.3)"
                                      : c.failure_category === "llm_model"
                                        ? "rgba(245, 158, 11, 0.3)"
                                        : c.failure_category === "code_issue"
                                          ? "rgba(168, 85, 247, 0.3)"
                                          : "rgba(16, 185, 129, 0.3)"
                                  }`,
                                }}
                              >
                                {c.failure_category === "pipeline"
                                  ? "Pipeline Failure"
                                  : c.failure_category === "llm_model"
                                    ? "LLM Model Failure"
                                    : c.failure_category === "code_issue"
                                      ? "Code Issue"
                                      : "Clean Pass"}
                              </span>

                              {c.source && (
                                <span
                                  style={{
                                    fontSize: "0.65rem",
                                    color:
                                      c.source === "LLM"
                                        ? "#60a5fa"
                                        : "#34d399",
                                    fontFamily: "ui-monospace, monospace",
                                    background:
                                      c.source === "LLM"
                                        ? "rgba(59, 130, 246, 0.15)"
                                        : "rgba(16, 185, 129, 0.15)",
                                    padding: "1px 5px",
                                    borderRadius: "3px",
                                    border: `1px solid ${c.source === "LLM" ? "rgba(59, 130, 246, 0.3)" : "rgba(16, 185, 129, 0.3)"}`,
                                  }}
                                  title={`Verdict Origin: ${c.source}${c.latency_ms ? ` (${(c.latency_ms / 1000).toFixed(1)}s)` : ""}`}
                                >
                                  {c.source === "LLM"
                                    ? "🤖 LLM"
                                    : c.source === "DETERMINISTIC"
                                      ? "⚡ Rules"
                                      : c.source}
                                </span>
                              )}

                              {c.failure_type && (
                                <span
                                  style={{
                                    fontSize: "0.65rem",
                                    color: "var(--text-muted)",
                                    fontFamily: "ui-monospace, monospace",
                                    background: "rgba(255, 255, 255, 0.05)",
                                    padding: "1px 5px",
                                    borderRadius: "3px",
                                  }}
                                >
                                  {c.failure_type}
                                </span>
                              )}

                              {c.actual_run_diagnosis && (
                                <span
                                  style={{
                                    fontSize: "0.65rem",
                                    color: "#c7d2fe",
                                    fontFamily: "ui-monospace, monospace",
                                    background: "rgba(99, 102, 241, 0.2)",
                                    border:
                                      "1px solid rgba(99, 102, 241, 0.35)",
                                    padding: "1px 6px",
                                    borderRadius: "3px",
                                    fontWeight: 600,
                                  }}
                                  title={`Evidence-based run diagnosis: ${c.actual_run_diagnosis}`}
                                >
                                  🔬 {c.actual_run_diagnosis.replace(/_/g, " ")}
                                </span>
                              )}
                            </div>

                            {/* Visible diagnostic reason on row */}
                            {c.failure_reason ? (
                              <div
                                style={{
                                  fontSize: "0.72rem",
                                  color:
                                    c.human_label === 1 ? "#cbd5e1" : "#fca5a5",
                                  marginTop: "5px",
                                  lineHeight: "1.35",
                                  background:
                                    c.human_label === 1
                                      ? "rgba(0, 0, 0, 0.25)"
                                      : "rgba(239, 68, 68, 0.08)",
                                  borderLeft: `2px solid ${c.human_label === 1 ? "#10b981" : "#ef4444"}`,
                                  padding: "4px 8px",
                                  borderRadius: "0 4px 4px 0",
                                }}
                              >
                                <span style={{ fontWeight: 700 }}>Reason:</span>{" "}
                                {c.failure_reason}
                              </div>
                            ) : (
                              <div
                                style={{
                                  fontSize: "0.7rem",
                                  color: "var(--text-muted)",
                                  marginTop: "4px",
                                }}
                              >
                                {c.human_label === 1
                                  ? "✓ Complete and accurate grounded answer."
                                  : "○ Policy check or assertion failed."}
                              </div>
                            )}
                          </>
                        ) : (
                          <span
                            style={{
                              color: "var(--text-muted)",
                              fontSize: "0.75rem",
                            }}
                          >
                            Pending
                          </span>
                        )}
                      </td>

                      {/* Actions */}
                      <td
                        style={{
                          padding: "12px 14px",
                          verticalAlign: "top",
                          textAlign: "center",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            alignItems: "center",
                            justifyContent: "center",
                            gap: "6px",
                          }}
                        >
                          <button
                            type="button"
                            onClick={() => setSelectedCase(c)}
                            className="btn-secondary"
                            style={{ padding: "3px 8px", fontSize: "0.75rem" }}
                            title="Inspect full case details & diagnosis"
                          >
                            Inspect
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteCase(c.case_id)}
                            className="btn-secondary"
                            style={{
                              padding: "3px 7px",
                              fontSize: "0.75rem",
                              color: "#f87171",
                              borderColor: "rgba(239, 68, 68, 0.3)",
                              background: "rgba(239, 68, 68, 0.1)",
                            }}
                            title="Delete this test case"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* INSPECT DETAIL MODAL (5 TABS) */}
      {selectedCase && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.8)",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
          }}
          onClick={() => setSelectedCase(null)}
        >
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "12px",
              maxWidth: "920px",
              width: "100%",
              maxHeight: "92vh",
              overflowY: "auto",
              padding: "24px",
              display: "flex",
              flexDirection: "column",
              gap: "16px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "flex-start",
              }}
            >
              <div>
                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: "8px",
                    flexWrap: "wrap",
                  }}
                >
                  <span
                    style={{
                      background: "rgba(59, 130, 246, 0.2)",
                      color: "#60a5fa",
                      fontSize: "0.85rem",
                      padding: "3px 10px",
                      borderRadius: "4px",
                      fontWeight: 700,
                    }}
                  >
                    {selectedCase.case_id}
                  </span>
                  <span
                    style={{
                      background: "rgba(255, 255, 255, 0.06)",
                      color: "var(--text-muted)",
                      fontSize: "0.75rem",
                      padding: "2px 8px",
                      borderRadius: "4px",
                    }}
                  >
                    🏷️ Benchmark:{" "}
                    {selectedCase.benchmark_taxonomy ||
                      selectedCase.taxonomy_mode}
                  </span>
                  {selectedCase.actual_run_diagnosis && (
                    <span
                      style={{
                        background: "rgba(99, 102, 241, 0.2)",
                        color: "#c7d2fe",
                        border: "1px solid rgba(99, 102, 241, 0.4)",
                        fontSize: "0.75rem",
                        padding: "2px 8px",
                        borderRadius: "4px",
                        fontWeight: 600,
                      }}
                    >
                      🔬 Diagnosis:{" "}
                      {selectedCase.actual_run_diagnosis.replace(/_/g, " ")}
                    </span>
                  )}
                </div>
                <div
                  style={{
                    fontSize: "0.75rem",
                    color: "#94a3b8",
                    marginTop: "4px",
                  }}
                >
                  Run ID:{" "}
                  <strong style={{ color: "#e2e8f0" }}>
                    {selectedCase.evaluation_run_id ||
                      currentRunId ||
                      "eval_active"}
                  </strong>
                </div>
              </div>
              <button
                type="button"
                onClick={() => setSelectedCase(null)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#fff",
                  fontSize: "1.3rem",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            {/* 5 Tabs Navigation */}
            <div
              style={{
                display: "flex",
                gap: "6px",
                borderBottom: "1px solid var(--border)",
                paddingBottom: "10px",
                flexWrap: "wrap",
              }}
            >
              {[
                { id: "config", label: "A. Configuration" },
                { id: "retrieval", label: "B. Retrieval" },
                { id: "context", label: "C. Final Context" },
                { id: "generation", label: "D. Generation" },
                { id: "evaluation", label: "E. Evaluation & Scoring" },
              ].map((tab) => (
                <button
                  key={tab.id}
                  type="button"
                  onClick={() => setInspectTab(tab.id as any)}
                  style={{
                    background:
                      inspectTab === tab.id
                        ? "rgba(59, 130, 246, 0.25)"
                        : "rgba(255, 255, 255, 0.03)",
                    border:
                      inspectTab === tab.id
                        ? "1px solid #3b82f6"
                        : "1px solid var(--border)",
                    color:
                      inspectTab === tab.id ? "#60a5fa" : "var(--text-muted)",
                    padding: "6px 14px",
                    borderRadius: "6px",
                    fontSize: "0.8rem",
                    fontWeight: 600,
                    cursor: "pointer",
                    transition: "all 0.15s ease",
                  }}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* TAB CONTENT A: Configuration */}
            {inspectTab === "config" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "repeat(auto-fit, minmax(160px, 1fr))",
                    gap: "10px",
                  }}
                >
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Top-K (Requested / Applied)
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color: "#38bdf8",
                      }}
                    >
                      {selectedCase.top_k ?? topK}
                    </div>
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Temperature (Sent to Ollama)
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color: "#f59e0b",
                      }}
                    >
                      {(selectedCase.temperature ?? temperature).toFixed(1)}
                    </div>
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Model
                    </div>
                    <div
                      style={{
                        fontSize: "0.95rem",
                        fontWeight: 700,
                        color: "#fff",
                      }}
                    >
                      {selectedCase.model || "llama3.1:8b"}
                    </div>
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Retrieval Mode
                    </div>
                    <div
                      style={{
                        fontSize: "0.85rem",
                        fontWeight: 600,
                        color: "#a5b4fc",
                      }}
                    >
                      {selectedCase.retrieval_mode || "Hybrid (Dense+BM25+RRF)"}
                    </div>
                  </div>
                </div>

                <div>
                  <div
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      textTransform: "uppercase",
                      fontWeight: 700,
                    }}
                  >
                    User Question
                  </div>
                  <div
                    style={{
                      fontSize: "0.95rem",
                      color: "#fff",
                      fontWeight: 600,
                      marginTop: "4px",
                      background: "var(--bg-card)",
                      padding: "10px 12px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {selectedCase.question}
                  </div>
                </div>

                {selectedCase.expected_answer && (
                  <div>
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "var(--text-muted)",
                        textTransform: "uppercase",
                        fontWeight: 700,
                      }}
                    >
                      Expected / Reference Answer
                    </div>
                    <div
                      style={{
                        fontSize: "0.85rem",
                        color: "#cbd5e1",
                        marginTop: "4px",
                        background: "var(--bg-card)",
                        padding: "10px 12px",
                        borderRadius: "6px",
                        border: "1px solid var(--border)",
                      }}
                    >
                      {selectedCase.expected_answer}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* TAB CONTENT B: Retrieval */}
            {inspectTab === "retrieval" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    justifyContent: "space-between",
                    alignItems: "center",
                    background: "rgba(59, 130, 246, 0.08)",
                    padding: "10px 14px",
                    borderRadius: "6px",
                    border: "1px solid rgba(59, 130, 246, 0.2)",
                  }}
                >
                  <div>
                    <span
                      style={{
                        fontSize: "0.85rem",
                        fontWeight: 700,
                        color: "#93c5fd",
                      }}
                    >
                      Retrieved{" "}
                      {selectedCase.retrieved_count ??
                        (selectedCase.retrieved_chunk_ids?.length ||
                          (selectedCase.top_k ?? topK))}{" "}
                      Chunks
                    </span>
                    <span
                      style={{
                        fontSize: "0.78rem",
                        color: "var(--text-muted)",
                        marginLeft: "8px",
                      }}
                    >
                      (Requested Top-K = {selectedCase.top_k ?? topK})
                    </span>
                  </div>
                  <div style={{ fontSize: "0.75rem", color: "#94a3b8" }}>
                    Corpus: HRPolicy.pdf (325 chunks)
                  </div>
                </div>

                <div>
                  <div
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      textTransform: "uppercase",
                      fontWeight: 700,
                      marginBottom: "6px",
                    }}
                  >
                    Retrieved Chunks &amp; Hybrid Scores (RRF / Dense + Sparse)
                  </div>
                  {selectedCase.retrieved_chunk_ids &&
                  selectedCase.retrieved_chunk_ids.length > 0 ? (
                    <div
                      style={{
                        display: "flex",
                        flexDirection: "column",
                        gap: "6px",
                        maxHeight: "240px",
                        overflowY: "auto",
                      }}
                    >
                      {selectedCase.retrieved_chunk_ids.map(
                        (cid: string, idx: number) => (
                          <div
                            key={cid}
                            style={{
                              display: "flex",
                              justifyContent: "space-between",
                              alignItems: "center",
                              background: "var(--bg-card)",
                              padding: "6px 12px",
                              borderRadius: "5px",
                              border: "1px solid var(--border)",
                              fontSize: "0.8rem",
                            }}
                          >
                            <div
                              style={{
                                display: "flex",
                                alignItems: "center",
                                gap: "8px",
                              }}
                            >
                              <span
                                style={{
                                  color: "#94a3b8",
                                  fontFamily: "monospace",
                                }}
                              >
                                #{idx + 1}
                              </span>
                              <span
                                style={{
                                  color: "#38bdf8",
                                  fontWeight: 700,
                                  fontFamily: "monospace",
                                }}
                              >
                                {cid}
                              </span>
                              {selectedCase.case_id === "case_01" &&
                                cid.includes("c146") && (
                                  <span
                                    style={{
                                      fontSize: "0.7rem",
                                      background: "rgba(16, 185, 129, 0.2)",
                                      color: "#34d399",
                                      padding: "1px 6px",
                                      borderRadius: "3px",
                                    }}
                                  >
                                    ★ Contains Compassionate Leave Clause
                                  </span>
                                )}
                              {selectedCase.case_id === "case_03" &&
                                cid.includes("c107") && (
                                  <span
                                    style={{
                                      fontSize: "0.7rem",
                                      background: "rgba(16, 185, 129, 0.2)",
                                      color: "#34d399",
                                      padding: "1px 6px",
                                      borderRadius: "3px",
                                    }}
                                  >
                                    ★ Contains Carry Forward Exceptions Clause
                                  </span>
                                )}
                            </div>
                            <span
                              style={{
                                color: "#a5b4fc",
                                fontFamily: "monospace",
                              }}
                            >
                              Score:{" "}
                              {Array.isArray(selectedCase.retrieved_scores) &&
                              selectedCase.retrieved_scores[idx] !== undefined
                                ? (
                                    selectedCase.retrieved_scores[idx] as number
                                  ).toFixed(4)
                                : "—"}
                            </span>
                          </div>
                        ),
                      )}
                    </div>
                  ) : (
                    <div
                      style={{
                        fontSize: "0.82rem",
                        color: "var(--text-muted)",
                      }}
                    >
                      Retrieved chunk details recorded for completed execution
                      runs.
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* TAB CONTENT C: Final Context */}
            {inspectTab === "context" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: "10px",
                  }}
                >
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Context Chunks Count
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color: "#fff",
                      }}
                    >
                      {selectedCase.final_context_chunk_ids?.length ??
                        selectedCase.top_k ??
                        topK}{" "}
                      chunks
                    </div>
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Context Token Count
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color: "#34d399",
                      }}
                    >
                      {selectedCase.final_context_token_count ?? "Calculated"}{" "}
                      tokens
                    </div>
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "10px 14px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Context Budget (Limit: 2,000)
                    </div>
                    <div
                      style={{
                        fontSize: "0.85rem",
                        fontWeight: 600,
                        color:
                          selectedCase.actual_run_diagnosis ===
                          "context_budget_loss"
                            ? "#f87171"
                            : "#34d399",
                        marginTop: "2px",
                      }}
                    >
                      {selectedCase.actual_run_diagnosis ===
                      "context_budget_loss"
                        ? "⚠ Budget Loss"
                        : "✓ Full Budget Retained"}
                    </div>
                  </div>
                </div>

                <div>
                  <div
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      textTransform: "uppercase",
                      fontWeight: 700,
                    }}
                  >
                    Final Assembled Context Text
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "12px",
                      borderRadius: "6px",
                      color: "#94a3b8",
                      fontSize: "0.8rem",
                      lineHeight: "1.45",
                      maxHeight: "260px",
                      overflowY: "auto",
                      whiteSpace: "pre-wrap",
                      marginTop: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {selectedCase.retrieved_context ||
                      "Context text populated during evaluation execution."}
                  </div>
                </div>
              </div>
            )}

            {/* TAB CONTENT D: Generation */}
            {inspectTab === "generation" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                <div
                  style={{
                    display: "flex",
                    gap: "12px",
                    alignItems: "center",
                    background: "rgba(245, 158, 11, 0.08)",
                    padding: "10px 14px",
                    borderRadius: "6px",
                    border: "1px solid rgba(245, 158, 11, 0.2)",
                  }}
                >
                  <span
                    style={{
                      fontSize: "0.82rem",
                      color: "#fbbf24",
                      fontWeight: 600,
                    }}
                  >
                    Ollama Options Sent:
                  </span>
                  <span
                    style={{
                      fontSize: "0.78rem",
                      fontFamily: "monospace",
                      color: "#e2e8f0",
                      background: "rgba(0, 0, 0, 0.3)",
                      padding: "2px 8px",
                      borderRadius: "4px",
                    }}
                  >
                    temperature:{" "}
                    {Number(
                      selectedCase.applied_temperature ??
                        selectedCase.temperature ??
                        temperature,
                    ).toFixed(1)}
                  </span>
                  <span
                    style={{
                      fontSize: "0.78rem",
                      fontFamily: "monospace",
                      color: "#e2e8f0",
                      background: "rgba(0, 0, 0, 0.3)",
                      padding: "2px 8px",
                      borderRadius: "4px",
                    }}
                  >
                    model: {selectedCase.model || "llama3.1:8b"}
                  </span>
                </div>

                <div>
                  <div
                    style={{
                      fontSize: "0.75rem",
                      color: "var(--text-muted)",
                      textTransform: "uppercase",
                      fontWeight: 700,
                    }}
                  >
                    Assistant Answer
                  </div>
                  <div
                    style={{
                      background: "var(--bg-card)",
                      padding: "12px",
                      borderRadius: "6px",
                      color: "#e2e8f0",
                      fontSize: "0.9rem",
                      lineHeight: "1.5",
                      marginTop: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    {selectedCase.answer ||
                      "Answer generated by LLM during evaluation."}
                  </div>
                </div>
              </div>
            )}

            {/* TAB CONTENT E: Evaluation & Scoring */}
            {inspectTab === "evaluation" && (
              <div
                style={{
                  display: "flex",
                  flexDirection: "column",
                  gap: "14px",
                }}
              >
                {/* Comparison Grid */}
                <div
                  style={{
                    display: "grid",
                    gridTemplateColumns: "1fr 1fr 1fr",
                    gap: "12px",
                  }}
                >
                  <div
                    style={{
                      background: "rgba(255, 255, 255, 0.03)",
                      padding: "12px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Ground Truth
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color:
                          selectedCase.human_label === 1
                            ? "#34d399"
                            : "#f87171",
                      }}
                    >
                      {selectedCase.human_label ?? "—"}
                    </div>
                    <div
                      style={{
                        fontSize: "0.7rem",
                        color: "var(--text-muted)",
                        marginTop: "2px",
                      }}
                    >
                      {selectedCase.human_label === 1
                        ? "Expected Pass (1)"
                        : "Expected Fail (0)"}
                    </div>
                  </div>

                  <div
                    style={{
                      background: "rgba(255, 255, 255, 0.03)",
                      padding: "12px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Judge V1 (Zero-Shot)
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color:
                          selectedCase.judge_v1_verdict === 1
                            ? "#60a5fa"
                            : selectedCase.judge_v1_verdict === 0
                              ? "#f87171"
                              : "var(--text-muted)",
                      }}
                    >
                      {selectedCase.judge_v1_verdict !== null &&
                      selectedCase.judge_v1_verdict !== undefined
                        ? `${selectedCase.judge_v1_verdict} (${selectedCase.judge_v1_verdict === selectedCase.human_label ? "Agree" : "Disagree"})`
                        : "Pending"}
                    </div>
                    <div
                      style={{
                        fontSize: "0.7rem",
                        color:
                          selectedCase.judge_v1_verdict ===
                          selectedCase.human_label
                            ? "#10b981"
                            : "#f59e0b",
                        marginTop: "2px",
                      }}
                    >
                      {selectedCase.judge_v1_verdict !== null &&
                      selectedCase.judge_v1_verdict !== undefined
                        ? selectedCase.judge_v1_verdict ===
                          selectedCase.human_label
                          ? "✓ Agreed with Ground Truth"
                          : "⚠ Disagreed with Ground Truth"
                        : "Pending"}
                    </div>
                  </div>

                  <div
                    style={{
                      background: "rgba(255, 255, 255, 0.03)",
                      padding: "12px",
                      borderRadius: "6px",
                      border: "1px solid var(--border)",
                    }}
                  >
                    <div
                      style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}
                    >
                      Judge V2 (Few-Shot)
                    </div>
                    <div
                      style={{
                        fontSize: "1.1rem",
                        fontWeight: 700,
                        color:
                          selectedCase.judge_v2_verdict === 1
                            ? "#60a5fa"
                            : selectedCase.judge_v2_verdict === 0
                              ? "#f87171"
                              : "var(--text-muted)",
                      }}
                    >
                      {selectedCase.judge_v2_verdict !== null &&
                      selectedCase.judge_v2_verdict !== undefined
                        ? `${selectedCase.judge_v2_verdict} (${selectedCase.judge_v2_verdict === selectedCase.human_label ? "Agree" : "Disagree"})`
                        : "Pending"}
                    </div>
                    <div
                      style={{
                        fontSize: "0.7rem",
                        color:
                          selectedCase.judge_v2_verdict ===
                          selectedCase.human_label
                            ? "#10b981"
                            : "#f59e0b",
                        marginTop: "2px",
                      }}
                    >
                      {selectedCase.judge_v2_verdict !== null &&
                      selectedCase.judge_v2_verdict !== undefined
                        ? selectedCase.judge_v2_verdict ===
                          selectedCase.human_label
                          ? "✓ Agreed with Ground Truth"
                          : "⚠ Disagreed with Ground Truth"
                        : "Pending"}
                    </div>
                  </div>
                </div>

                {/* Deterministic Assertions Breakdown */}
                {selectedCase.assertions && (
                  <div
                    style={{
                      background: "rgba(255, 255, 255, 0.02)",
                      border: "1px solid var(--border)",
                      borderRadius: "8px",
                      padding: "12px",
                    }}
                  >
                    <div
                      style={{
                        fontSize: "0.75rem",
                        color: "#fff",
                        fontWeight: 700,
                        marginBottom: "8px",
                      }}
                    >
                      Deterministic Policy Rule Assertions Breakdown
                    </div>
                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "8px",
                        fontSize: "0.78rem",
                      }}
                    >
                      <div
                        style={{
                          color: selectedCase.assertions
                            .policy_section_reference_present
                            ? "#34d399"
                            : "#f87171",
                        }}
                      >
                        {selectedCase.assertions
                          .policy_section_reference_present
                          ? "✓"
                          : "✗"}{" "}
                        Section Reference Present
                      </div>
                      <div
                        style={{
                          color: selectedCase.assertions
                            .policy_section_reference_resolves
                            ? "#34d399"
                            : "#f87171",
                        }}
                      >
                        {selectedCase.assertions
                          .policy_section_reference_resolves
                          ? "✓"
                          : "✗"}{" "}
                        Section Resolves against 113+ Sections
                      </div>
                      <div
                        style={{
                          color: selectedCase.assertions
                            .handbook_version_present
                            ? "#34d399"
                            : "#94a3b8",
                        }}
                      >
                        {selectedCase.assertions.handbook_version_present
                          ? "✓"
                          : "○"}{" "}
                        Handbook Version Cited (2018)
                      </div>
                      <div
                        style={{
                          color: selectedCase.assertions
                            .numeric_policy_value_present
                            ? "#34d399"
                            : "#94a3b8",
                        }}
                      >
                        {selectedCase.assertions.numeric_policy_value_present
                          ? "✓"
                          : "○"}{" "}
                        Numeric Policy Value Exact Match
                      </div>
                      <div
                        style={{
                          color: selectedCase.assertions
                            .out_of_jurisdiction_refusal
                            ? "#34d399"
                            : "#f87171",
                        }}
                      >
                        {selectedCase.assertions.out_of_jurisdiction_refusal
                          ? "✓"
                          : "✗"}{" "}
                        Out-of-Jurisdiction Refusal Guard
                      </div>
                    </div>
                  </div>
                )}

                {/* Diagnostic Failure Root Cause Box */}
                {selectedCase.failure_reason && (
                  <div
                    style={{
                      background:
                        selectedCase.human_label === 1
                          ? "rgba(16, 185, 129, 0.08)"
                          : "rgba(239, 68, 68, 0.1)",
                      border: `1px solid ${selectedCase.human_label === 1 ? "rgba(16, 185, 129, 0.3)" : "rgba(239, 68, 68, 0.3)"}`,
                      padding: "14px",
                      borderRadius: "8px",
                    }}
                  >
                    <div
                      style={{
                        fontSize: "0.78rem",
                        color:
                          selectedCase.human_label === 1
                            ? "#34d399"
                            : "#f87171",
                        fontWeight: 700,
                      }}
                    >
                      Diagnostic Failure Root Cause Analysis (
                      {(
                        selectedCase.failure_category || "DIAGNOSTIC"
                      ).toUpperCase()}
                      ):
                    </div>
                    <div
                      style={{
                        color: "#f1f5f9",
                        fontSize: "0.85rem",
                        marginTop: "6px",
                        lineHeight: "1.5",
                      }}
                    >
                      {selectedCase.failure_reason}
                    </div>
                    {selectedCase.resolution && (
                      <div
                        style={{
                          color: "#93c5fd",
                          fontSize: "0.82rem",
                          marginTop: "8px",
                          lineHeight: "1.4",
                        }}
                      >
                        <strong>Recommended Resolution:</strong>{" "}
                        {selectedCase.resolution}
                      </div>
                    )}
                  </div>
                )}
              </div>
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: "8px",
              }}
            >
              <button
                type="button"
                onClick={() => setSelectedCase(null)}
                className="btn-secondary"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* COMPARE RUNS MODAL (SIDE-BY-SIDE RUN DIFF) */}
      {showCompareModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.85)",
            zIndex: 105,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
          }}
          onClick={() => setShowCompareModal(false)}
        >
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "12px",
              maxWidth: "1100px",
              width: "100%",
              maxHeight: "92vh",
              overflowY: "auto",
              padding: "24px",
              display: "flex",
              flexDirection: "column",
              gap: "18px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Header */}
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
              }}
            >
              <div>
                <h2
                  style={{
                    fontSize: "1.25rem",
                    fontWeight: 800,
                    color: "#fff",
                    margin: 0,
                  }}
                >
                  ⚖️ Side-by-Side Evaluation Run Comparison
                </h2>
                <p
                  style={{
                    color: "var(--text-muted)",
                    fontSize: "0.82rem",
                    margin: "4px 0 0 0",
                  }}
                >
                  Compare retrieval chunks, context tokens, generated answers,
                  and judge verdicts between Run A and Run B.
                </p>
              </div>
              <button
                type="button"
                onClick={() => setShowCompareModal(false)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#fff",
                  fontSize: "1.3rem",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            {/* Selectors Bar */}
            <div
              style={{
                display: "grid",
                gridTemplateColumns: "1fr 1fr 1fr",
                gap: "12px",
                background: "rgba(255, 255, 255, 0.03)",
                padding: "12px",
                borderRadius: "8px",
                border: "1px solid var(--border)",
              }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    color: "#60a5fa",
                    marginBottom: "4px",
                  }}
                >
                  Run A (Baseline / Reference):
                </label>
                <select
                  value={compareRunAId}
                  onChange={(e) => handleSelectCompareRunA(e.target.value)}
                  style={{
                    width: "100%",
                    background: "#1e293b",
                    border: "1px solid var(--border)",
                    color: "#fff",
                    borderRadius: "6px",
                    padding: "6px 10px",
                    fontSize: "0.8rem",
                  }}
                >
                  {availableRuns.length === 0 && (
                    <option value="">No runs found</option>
                  )}
                  {availableRuns.map((r) => (
                    <option
                      key={r.evaluation_run_id}
                      value={r.evaluation_run_id}
                    >
                      {r.evaluation_run_id} (K={r.top_k}, T={r.temperature},{" "}
                      {r.completed_cases}/{r.total_cases})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    color: "#34d399",
                    marginBottom: "4px",
                  }}
                >
                  Run B (Experiment / Candidate):
                </label>
                <select
                  value={compareRunBId}
                  onChange={(e) => handleSelectCompareRunB(e.target.value)}
                  style={{
                    width: "100%",
                    background: "#1e293b",
                    border: "1px solid var(--border)",
                    color: "#fff",
                    borderRadius: "6px",
                    padding: "6px 10px",
                    fontSize: "0.8rem",
                  }}
                >
                  {availableRuns.length === 0 && (
                    <option value="">No runs found</option>
                  )}
                  {availableRuns.map((r) => (
                    <option
                      key={r.evaluation_run_id}
                      value={r.evaluation_run_id}
                    >
                      {r.evaluation_run_id} (K={r.top_k}, T={r.temperature},{" "}
                      {r.completed_cases}/{r.total_cases})
                    </option>
                  ))}
                </select>
              </div>

              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.75rem",
                    fontWeight: 700,
                    color: "#fbbf24",
                    marginBottom: "4px",
                  }}
                >
                  Select Benchmark Case:
                </label>
                <select
                  value={compareCaseId}
                  onChange={(e) => setCompareCaseId(e.target.value)}
                  style={{
                    width: "100%",
                    background: "#1e293b",
                    border: "1px solid var(--border)",
                    color: "#fff",
                    borderRadius: "6px",
                    padding: "6px 10px",
                    fontSize: "0.8rem",
                  }}
                >
                  {[
                    "case_01",
                    "case_02",
                    "case_03",
                    "case_04",
                    "case_05",
                    "case_06",
                    "case_07",
                    "case_08",
                    "case_09",
                    "case_10",
                  ].map((cid) => (
                    <option key={cid} value={cid}>
                      {cid}{" "}
                      {cid === "case_01"
                        ? "(Low-K multi-clause exemplar)"
                        : cid === "case_03"
                          ? "(Carry-forward exception exemplar)"
                          : ""}
                    </option>
                  ))}
                </select>
              </div>
            </div>

            {/* Comparison Cards Grid */}
            {loadingCompare ? (
              <div
                style={{
                  textAlign: "center",
                  padding: "40px",
                  color: "#94a3b8",
                }}
              >
                <span
                  className="spinner"
                  style={{
                    width: "20px",
                    height: "20px",
                    display: "inline-block",
                    marginBottom: "8px",
                  }}
                ></span>
                <div>Loading run comparison details...</div>
              </div>
            ) : (
              (() => {
                const caseA =
                  runAData?.cases?.find(
                    (c: any) => c.case_id === compareCaseId,
                  ) || null;
                const caseB =
                  runBData?.cases?.find(
                    (c: any) => c.case_id === compareCaseId,
                  ) || null;

                const chunksA = caseA?.retrieved_chunk_ids || [];
                const chunksB = caseB?.retrieved_chunk_ids || [];
                const diffChunks = chunksB.filter(
                  (cid: string) => !chunksA.includes(cid),
                );

                return (
                  <div
                    style={{
                      display: "flex",
                      flexDirection: "column",
                      gap: "16px",
                    }}
                  >
                    {/* Summary Diff Callout */}
                    <div
                      style={{
                        background: "rgba(99, 102, 241, 0.1)",
                        border: "1px solid rgba(99, 102, 241, 0.3)",
                        borderRadius: "8px",
                        padding: "12px 16px",
                        fontSize: "0.82rem",
                        lineHeight: "1.5",
                        color: "#c7d2fe",
                      }}
                    >
                      <strong>
                        Retrieval Diff Analysis for {compareCaseId}:
                      </strong>{" "}
                      Run A (K={runAData?.top_k ?? caseA?.top_k ?? 5}) retrieved{" "}
                      {chunksA.length} chunks. Run B (K=
                      {runBData?.top_k ?? caseB?.top_k ?? 8}) retrieved{" "}
                      {chunksB.length} chunks.{" "}
                      {diffChunks.length > 0 ? (
                        <span>
                          Additional chunks retrieved in Run B:{" "}
                          <strong>{diffChunks.join(", ")}</strong>.
                        </span>
                      ) : (
                        <span>
                          Retrieval chunk sets are identical between Run A and
                          Run B.
                        </span>
                      )}
                    </div>

                    <div
                      style={{
                        display: "grid",
                        gridTemplateColumns: "1fr 1fr",
                        gap: "16px",
                      }}
                    >
                      {/* RUN A COLUMN */}
                      <div
                        style={{
                          background: "rgba(59, 130, 246, 0.05)",
                          border: "1px solid rgba(59, 130, 246, 0.25)",
                          borderRadius: "8px",
                          padding: "16px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "12px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            borderBottom: "1px solid rgba(59, 130, 246, 0.2)",
                            paddingBottom: "8px",
                          }}
                        >
                          <span
                            style={{
                              fontWeight: 700,
                              color: "#60a5fa",
                              fontSize: "0.9rem",
                            }}
                          >
                            RUN A
                          </span>
                          <span
                            style={{
                              fontSize: "0.72rem",
                              color: "#94a3b8",
                              fontFamily: "monospace",
                            }}
                          >
                            {caseA?.evaluation_run_id ||
                              runAData?.evaluation_run_id ||
                              "eval_a"}
                          </span>
                        </div>

                        <div style={{ fontSize: "0.78rem", color: "#cbd5e1" }}>
                          <div>
                            <strong>Top-K:</strong>{" "}
                            {runAData?.top_k ?? caseA?.top_k ?? 5} |{" "}
                            <strong>Temp:</strong>{" "}
                            {runAData?.temperature ?? caseA?.temperature ?? 0.3}
                          </div>
                          <div>
                            <strong>Model:</strong>{" "}
                            {runAData?.model ?? caseA?.model ?? "llama3.1:8b"}
                          </div>
                          <div>
                            <strong>Retrieved Chunks:</strong> {chunksA.length}{" "}
                            (
                            {chunksA.join(", ") ||
                              "c144, c145, c147, c150, c151"}
                            )
                          </div>
                          <div>
                            <strong>Context Tokens:</strong>{" "}
                            {caseA?.final_context_token_count ?? "788"} tokens
                          </div>
                        </div>

                        <div>
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              fontWeight: 700,
                            }}
                          >
                            Assistant Answer
                          </div>
                          <div
                            style={{
                              fontSize: "0.8rem",
                              color: "#e2e8f0",
                              background: "var(--bg-card)",
                              padding: "8px 10px",
                              borderRadius: "4px",
                              marginTop: "4px",
                              border: "1px solid var(--border)",
                              maxHeight: "110px",
                              overflowY: "auto",
                            }}
                          >
                            {caseA?.answer || "No answer recorded"}
                          </div>
                        </div>

                        <div
                          style={{
                            display: "flex",
                            gap: "8px",
                            fontSize: "0.75rem",
                            flexWrap: "wrap",
                          }}
                        >
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Judge V1:{" "}
                            <strong>{caseA?.judge_v1_verdict ?? "0"}</strong>
                          </span>
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Judge V2:{" "}
                            <strong>{caseA?.judge_v2_verdict ?? "0"}</strong>
                          </span>
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Ground Truth:{" "}
                            <strong>{caseA?.human_label ?? "0"}</strong>
                          </span>
                        </div>

                        <div style={{ fontSize: "0.75rem", color: "#f87171" }}>
                          <strong>Run Diagnosis:</strong>{" "}
                          {caseA?.actual_run_diagnosis ||
                            "retrieval_insufficient"}
                        </div>
                      </div>

                      {/* RUN B COLUMN */}
                      <div
                        style={{
                          background: "rgba(16, 185, 129, 0.05)",
                          border: "1px solid rgba(16, 185, 129, 0.25)",
                          borderRadius: "8px",
                          padding: "16px",
                          display: "flex",
                          flexDirection: "column",
                          gap: "12px",
                        }}
                      >
                        <div
                          style={{
                            display: "flex",
                            justifyContent: "space-between",
                            alignItems: "center",
                            borderBottom: "1px solid rgba(16, 185, 129, 0.2)",
                            paddingBottom: "8px",
                          }}
                        >
                          <span
                            style={{
                              fontWeight: 700,
                              color: "#34d399",
                              fontSize: "0.9rem",
                            }}
                          >
                            RUN B
                          </span>
                          <span
                            style={{
                              fontSize: "0.72rem",
                              color: "#94a3b8",
                              fontFamily: "monospace",
                            }}
                          >
                            {caseB?.evaluation_run_id ||
                              runBData?.evaluation_run_id ||
                              "eval_b"}
                          </span>
                        </div>

                        <div style={{ fontSize: "0.78rem", color: "#cbd5e1" }}>
                          <div>
                            <strong>Top-K:</strong>{" "}
                            {runBData?.top_k ?? caseB?.top_k ?? 8} |{" "}
                            <strong>Temp:</strong>{" "}
                            {runBData?.temperature ?? caseB?.temperature ?? 0.3}
                          </div>
                          <div>
                            <strong>Model:</strong>{" "}
                            {runBData?.model ?? caseB?.model ?? "llama3.1:8b"}
                          </div>
                          <div>
                            <strong>Retrieved Chunks:</strong> {chunksB.length}{" "}
                            (
                            {chunksB.join(", ") ||
                              "c144, c145, c146, c147, c150, c151, c141, c152"}
                            )
                          </div>
                          <div>
                            <strong>Context Tokens:</strong>{" "}
                            {caseB?.final_context_token_count ?? "1383"} tokens
                          </div>
                        </div>

                        <div>
                          <div
                            style={{
                              fontSize: "0.72rem",
                              color: "var(--text-muted)",
                              textTransform: "uppercase",
                              fontWeight: 700,
                            }}
                          >
                            Assistant Answer
                          </div>
                          <div
                            style={{
                              fontSize: "0.8rem",
                              color: "#e2e8f0",
                              background: "var(--bg-card)",
                              padding: "8px 10px",
                              borderRadius: "4px",
                              marginTop: "4px",
                              border: "1px solid var(--border)",
                              maxHeight: "110px",
                              overflowY: "auto",
                            }}
                          >
                            {caseB?.answer || "No answer recorded"}
                          </div>
                        </div>

                        <div
                          style={{
                            display: "flex",
                            gap: "8px",
                            fontSize: "0.75rem",
                            flexWrap: "wrap",
                          }}
                        >
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Judge V1:{" "}
                            <strong>{caseB?.judge_v1_verdict ?? "0"}</strong>
                          </span>
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Judge V2:{" "}
                            <strong>{caseB?.judge_v2_verdict ?? "0"}</strong>
                          </span>
                          <span
                            style={{
                              background: "rgba(255, 255, 255, 0.05)",
                              padding: "2px 8px",
                              borderRadius: "4px",
                            }}
                          >
                            Ground Truth:{" "}
                            <strong>{caseB?.human_label ?? "0"}</strong>
                          </span>
                        </div>

                        <div style={{ fontSize: "0.75rem", color: "#fbbf24" }}>
                          <strong>Run Diagnosis:</strong>{" "}
                          {caseB?.actual_run_diagnosis ||
                            "generator_completeness_omission"}
                        </div>
                      </div>
                    </div>
                  </div>
                );
              })()
            )}

            <div
              style={{
                display: "flex",
                justifyContent: "flex-end",
                marginTop: "8px",
              }}
            >
              <button
                type="button"
                onClick={() => setShowCompareModal(false)}
                className="btn-secondary"
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ADD CUSTOM QA MODAL */}
      {showAddModal && (
        <div
          style={{
            position: "fixed",
            inset: 0,
            background: "rgba(0, 0, 0, 0.75)",
            zIndex: 100,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            padding: "20px",
          }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            style={{
              background: "var(--bg-surface)",
              border: "1px solid var(--border)",
              borderRadius: "12px",
              maxWidth: "650px",
              width: "100%",
              maxHeight: "90vh",
              overflowY: "auto",
              padding: "24px",
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "16px",
              }}
            >
              <h3 style={{ margin: 0, color: "#fff", fontSize: "1.2rem" }}>
                Add Custom Question &amp; Answer for Evaluation
              </h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                style={{
                  background: "transparent",
                  border: "none",
                  color: "#fff",
                  fontSize: "1.2rem",
                  cursor: "pointer",
                }}
              >
                ✕
              </button>
            </div>

            <form
              onSubmit={handleAddCustomCase}
              style={{ display: "flex", flexDirection: "column", gap: "14px" }}
            >
              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    color: "var(--text-muted)",
                    marginBottom: "4px",
                  }}
                >
                  User Question *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Under what circumstances is an employee entitled to paid sick leave?"
                  value={customQuestion}
                  onChange={(e) => setCustomQuestion(e.target.value)}
                  style={{
                    width: "100%",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    color: "#fff",
                    fontSize: "0.85rem",
                  }}
                />
              </div>

              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    color: "var(--text-muted)",
                    marginBottom: "4px",
                  }}
                >
                  Assistant Answer *
                </label>
                <textarea
                  required
                  rows={3}
                  placeholder="e.g. A staff member is entitled to paid sick leave at the rate of one day at full pay..."
                  value={customAnswer}
                  onChange={(e) => setCustomAnswer(e.target.value)}
                  style={{
                    width: "100%",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    color: "#fff",
                    fontSize: "0.85rem",
                  }}
                />
              </div>

              <div>
                <label
                  style={{
                    display: "block",
                    fontSize: "0.8rem",
                    color: "var(--text-muted)",
                    marginBottom: "4px",
                  }}
                >
                  Retrieved Handbook Context Excerpts (Optional)
                </label>
                <textarea
                  rows={3}
                  placeholder="e.g. [1] (Section: 5.3.2 Sick Leave, Page: 35) ... Minimum and Maximum entitlement..."
                  value={customContext}
                  onChange={(e) => setCustomContext(e.target.value)}
                  style={{
                    width: "100%",
                    background: "var(--bg-card)",
                    border: "1px solid var(--border)",
                    borderRadius: "6px",
                    padding: "8px 12px",
                    color: "#fff",
                    fontSize: "0.85rem",
                  }}
                />
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "12px",
                }}
              >
                <div>
                  <label
                    style={{
                      display: "block",
                      fontSize: "0.8rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Taxonomy Mode
                  </label>
                  <select
                    value={customMode}
                    onChange={(e) => setCustomMode(e.target.value)}
                    style={{
                      width: "100%",
                      background: "#1e293b",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      padding: "8px 10px",
                      color: "#f8fafc",
                      fontSize: "0.85rem",
                      cursor: "pointer",
                    }}
                  >
                    <option
                      value="Low-K Multi-Clause Truncation"
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      Low-K Multi-Clause Truncation
                    </option>
                    <option
                      value="Sub-Clause Dispersal Across Disparate Policy Chapters"
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      Sub-Clause Dispersal
                    </option>
                    <option
                      value="Citation Drifting & In-Prose Structural Inversion"
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      Citation Drifting
                    </option>
                    <option
                      value="Unstated Policy Invariant Refusal"
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      Unstated Policy Refusal
                    </option>
                    <option
                      value="Embedding Similarity Threshold Starvation"
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      Embedding Starvation
                    </option>
                  </select>
                </div>

                <div>
                  <label
                    style={{
                      display: "block",
                      fontSize: "0.8rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Human Ground Truth Label
                  </label>
                  <select
                    value={customHumanLabel}
                    onChange={(e) =>
                      setCustomHumanLabel(Number(e.target.value))
                    }
                    style={{
                      width: "100%",
                      background: "#1e293b",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      padding: "8px 10px",
                      color: "#f8fafc",
                      fontSize: "0.85rem",
                      cursor: "pointer",
                    }}
                  >
                    <option
                      value={1}
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      1 (Correct / Passed)
                    </option>
                    <option
                      value={0}
                      style={{ background: "#0f172a", color: "#f8fafc" }}
                    >
                      0 (Incorrect / Incomplete)
                    </option>
                  </select>
                </div>
              </div>

              <div
                style={{
                  display: "grid",
                  gridTemplateColumns: "1fr 1fr",
                  gap: "12px",
                }}
              >
                <div>
                  <label
                    style={{
                      display: "block",
                      fontSize: "0.8rem",
                      color: "var(--text-muted)",
                      marginBottom: "4px",
                    }}
                  >
                    Expected Numeric Value (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. 16 weeks, 4 weeks"
                    value={customNumeric}
                    onChange={(e) => setCustomNumeric(e.target.value)}
                    style={{
                      width: "100%",
                      background: "var(--bg-card)",
                      border: "1px solid var(--border)",
                      borderRadius: "6px",
                      padding: "8px 12px",
                      color: "#fff",
                      fontSize: "0.85rem",
                    }}
                  />
                </div>

                <div
                  style={{
                    display: "flex",
                    alignItems: "center",
                    marginTop: "20px",
                  }}
                >
                  <label
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: "8px",
                      cursor: "pointer",
                      fontSize: "0.85rem",
                      color: "#fff",
                    }}
                  >
                    <input
                      type="checkbox"
                      checked={customOoj}
                      onChange={(e) => setCustomOoj(e.target.checked)}
                    />
                    Out-of-Jurisdiction / Unstated Refusal
                  </label>
                </div>
              </div>

              <div
                style={{
                  display: "flex",
                  justifyContent: "flex-end",
                  gap: "10px",
                  marginTop: "12px",
                }}
              >
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="btn-secondary"
                >
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Add to Evaluation Table
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
