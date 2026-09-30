import {
  StatusResponse,
  AskResponse,
  UploadResponse,
  LoadUrlResponse,
  RemoveResponse,
  ClearResponse,
  PagesResponse,
} from "../types/api";
import {
  EvalRunPayload,
  EvalRunResponse,
  ParseQaResponse,
  JudgeEvalResponse,
  JudgeCaseResult,
  EvaluationRunStateResponse,
  ActiveEvaluationRunResponse,
  Week6EvalResponse,
  Week6CaseResult,
} from "../types/evaluation";
import { TracesResponse, ReplayResponse } from "../types/trace";
import { DatasetParseResult } from "../types/dataset";
import {
  ActiveBenchmarkRunResponse,
  BenchmarkCase,
  BenchmarkSuite,
  CancelBenchmarkResponse,
  ChatModelListResponse,
  EmployeeRecord,
  ExpectedTrajectory,
  PolicyBenchmarkRunStateResponse,
  PolicyBenchmarkStartRequest,
  PolicyOutputContract,
  PolicyQueryRequest,
  PolicyReadiness,
  PolicySearchRequest,
  RoutingDecision,
  TrajectoryEvaluateRequest,
  TrajectoryEvaluateResponse,
} from "../types/policy";
import { McpStatusResponse, McpWireResponse } from "../types/mcp";
import { ApiError } from "./apiError";

const API_BASE = import.meta.env.VITE_API_BASE_URL || "";

/** Fired after the set of indexed documents may have changed (upload, remove, clear). */
export const DOCUMENTS_CHANGED_EVENT = "amd:documents-changed";

function notifyDocumentsChanged(): void {
  if (typeof window !== "undefined") {
    window.dispatchEvent(new Event(DOCUMENTS_CHANGED_EVENT));
  }
}

function pickString(value: unknown): string | null {
  return typeof value === "string" && value.trim() ? value : null;
}

async function handleResponse<T>(res: Response): Promise<T> {
  const payload: unknown = await res.json().catch(() => ({}));
  const data =
    payload && typeof payload === "object" && !Array.isArray(payload)
      ? (payload as Record<string, unknown>)
      : {};
  if (!res.ok) {
    const structured =
      data.error && typeof data.error === "object" && !Array.isArray(data.error)
        ? (data.error as Record<string, unknown>)
        : null;
    throw new ApiError({
      status: res.status,
      code: pickString(structured?.code),
      backendMessage:
        pickString(data.error) ||
        pickString(structured?.message) ||
        pickString(data.message) ||
        pickString(data.detail),
      retryable: Boolean(structured?.retryable),
      requestId:
        pickString(structured?.request_id) || res.headers.get("X-Request-ID"),
      details: structured?.details,
    });
  }
  return payload as T;
}

function postJson(
  url: string,
  body: unknown,
  signal?: AbortSignal,
): Promise<Response> {
  return fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    signal,
  });
}

export const api = {
  async getStatus(signal?: AbortSignal): Promise<StatusResponse> {
    const res = await fetch(`${API_BASE}/status`, { signal });
    return handleResponse<StatusResponse>(res);
  },

  async uploadFiles(
    formData: FormData,
    signal?: AbortSignal,
  ): Promise<UploadResponse> {
    const res = await fetch(`${API_BASE}/upload`, {
      method: "POST",
      body: formData,
      signal,
    });
    try {
      return await handleResponse<UploadResponse>(res);
    } finally {
      notifyDocumentsChanged();
    }
  },

  async cancelUpload(uploadId: string): Promise<{ ok: boolean }> {
    const res = await postJson(`${API_BASE}/upload-cancel`, {
      upload_id: uploadId,
    });
    return handleResponse<{ ok: boolean }>(res);
  },

  async askQuestion(
    query: string,
    chunk_mode: string = "structured",
    top_k: number = 8,
    temperature: number = 0.0,
    signal?: AbortSignal,
    turn_id?: string,
    run_id?: string,
  ): Promise<AskResponse> {
    const res = await postJson(
      `${API_BASE}/ask`,
      {
        query,
        chunk_mode,
        top_k,
        temperature,
        ...(turn_id ? { turn_id } : {}),
        ...(run_id ? { run_id } : {}),
      },
      signal,
    );
    return handleResponse<AskResponse>(res);
  },

  async cancelAsk(runId: string): Promise<{ ok: boolean; run_id: string }> {
    const res = await fetch(
      `${API_BASE}/ask/${encodeURIComponent(runId)}/cancel`,
      {
        method: "POST",
      },
    );
    if (res.status === 404) return { ok: false, run_id: runId };
    return handleResponse<{ ok: boolean; run_id: string }>(res);
  },

  async loadUrl(
    url: string,
    chunk_mode: string = "structured",
    signal?: AbortSignal,
  ): Promise<LoadUrlResponse> {
    const res = await postJson(
      `${API_BASE}/load-url`,
      { url, chunk_mode },
      signal,
    );
    try {
      return await handleResponse<LoadUrlResponse>(res);
    } finally {
      notifyDocumentsChanged();
    }
  },

  async removeDoc(
    doc_id: string,
    signal?: AbortSignal,
  ): Promise<RemoveResponse> {
    const res = await postJson(`${API_BASE}/remove`, { doc_id }, signal);
    try {
      return await handleResponse<RemoveResponse>(res);
    } finally {
      notifyDocumentsChanged();
    }
  },

  async clearSession(signal?: AbortSignal): Promise<ClearResponse> {
    const res = await fetch(`${API_BASE}/clear`, {
      method: "POST",
      signal,
    });
    try {
      return await handleResponse<ClearResponse>(res);
    } finally {
      notifyDocumentsChanged();
    }
  },

  async getTraces(signal?: AbortSignal): Promise<TracesResponse> {
    const res = await fetch(`${API_BASE}/traces`, { signal });
    return handleResponse<TracesResponse>(res);
  },

  async replayTrace(
    traceId: string,
    signal?: AbortSignal,
  ): Promise<ReplayResponse> {
    const res = await fetch(
      `${API_BASE}/replay/${encodeURIComponent(traceId)}`,
      {
        method: "POST",
        signal,
      },
    );
    return handleResponse<ReplayResponse>(res);
  },

  async getFilePages(
    docId: string,
    signal?: AbortSignal,
  ): Promise<PagesResponse> {
    const res = await fetch(
      `${API_BASE}/file/${encodeURIComponent(docId)}/pages`,
      {
        signal,
      },
    );
    return handleResponse<PagesResponse>(res);
  },

  async runEvaluation(
    payload: EvalRunPayload,
    signal?: AbortSignal,
  ): Promise<EvalRunResponse> {
    const res = await postJson(`${API_BASE}/eval/run`, payload, signal);
    return handleResponse<EvalRunResponse>(res);
  },

  async parseEvaluationFile(
    file: File,
    signal?: AbortSignal,
  ): Promise<ParseQaResponse> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(`${API_BASE}/eval/parse-qa-pdf`, {
      method: "POST",
      body: fd,
      signal,
    });
    return handleResponse<ParseQaResponse>(res);
  },

  async parseEvaluationDataset(
    file: File,
    evaluatorType: string = "general",
    signal?: AbortSignal,
  ): Promise<DatasetParseResult> {
    const fd = new FormData();
    fd.append("file", file);
    const res = await fetch(
      `${API_BASE}/api/evaluation/dataset/parse?evaluator_type=${encodeURIComponent(evaluatorType)}`,
      {
        method: "POST",
        body: fd,
        signal,
      },
    );
    return handleResponse<DatasetParseResult>(res);
  },

  async getOrphans(adminKey?: string, signal?: AbortSignal): Promise<unknown> {
    const headers: Record<string, string> = {};
    if (adminKey) {
      headers["X-Admin-Key"] = adminKey;
    }
    const res = await fetch(`${API_BASE}/orphans`, { headers, signal });
    return handleResponse(res);
  },

  async startEvaluationRun(
    cases?: JudgeCaseResult[],
    runLlm: boolean = true,
    top_k: number = 5,
    temperature: number = 0.3,
    model: string = "llama3.1:8b",
    signal?: AbortSignal,
  ): Promise<EvaluationRunStateResponse> {
    const res = await postJson(
      `${API_BASE}/api/evaluation/runs`,
      {
        cases,
        run_llm: runLlm,
        top_k,
        temperature,
        model,
      },
      signal,
    );
    return handleResponse<EvaluationRunStateResponse>(res);
  },

  async getActiveEvaluationRun(
    signal?: AbortSignal,
  ): Promise<ActiveEvaluationRunResponse> {
    try {
      const res = await fetch(`${API_BASE}/api/evaluation/runs/active`, {
        signal,
      });
      if (!res.ok) {
        return { active_run_id: null, run: null };
      }
      return handleResponse<ActiveEvaluationRunResponse>(res);
    } catch {
      return { active_run_id: null, run: null };
    }
  },

  async getEvaluationRun(
    runId: string,
    signal?: AbortSignal,
  ): Promise<EvaluationRunStateResponse> {
    const res = await fetch(
      `${API_BASE}/api/evaluation/runs/${encodeURIComponent(runId)}`,
      { signal },
    );
    return handleResponse<EvaluationRunStateResponse>(res);
  },

  async listEvaluationRuns(
    signal?: AbortSignal,
  ): Promise<{ runs: EvaluationRunStateResponse[] }> {
    const res = await fetch(`${API_BASE}/api/evaluation/runs`, { signal });
    return handleResponse<{ runs: EvaluationRunStateResponse[] }>(res);
  },

  async cancelEvaluationRun(
    runId: string,
    signal?: AbortSignal,
  ): Promise<{ ok: boolean; status: string }> {
    const res = await fetch(
      `${API_BASE}/api/evaluation/runs/${encodeURIComponent(runId)}/cancel`,
      {
        method: "POST",
        signal,
      },
    );
    return handleResponse<{ ok: boolean; status: string }>(res);
  },

  async getBenchmarkCases(signal?: AbortSignal): Promise<JudgeEvalResponse> {
    const res = await fetch(`${API_BASE}/api/evaluation/benchmark`, { signal });
    return handleResponse<JudgeEvalResponse>(res);
  },

  async getJudgeResults(
    includeHistory: boolean = false,
    signal?: AbortSignal,
  ): Promise<JudgeEvalResponse> {
    const query = includeHistory ? "?include_history=true" : "";
    const res = await fetch(`${API_BASE}/api/evaluation/judges${query}`, {
      signal,
    });
    return handleResponse<JudgeEvalResponse>(res);
  },

  async evaluateJudges(
    cases?: JudgeCaseResult[],
    runLlm: boolean = true,
    signal?: AbortSignal,
  ): Promise<JudgeEvalResponse> {
    const res = await postJson(
      `${API_BASE}/api/evaluation/judges`,
      { cases, run_llm: runLlm },
      signal,
    );
    return handleResponse<JudgeEvalResponse>(res);
  },

  // Backward compatibility methods
  async getWeek6Results(signal?: AbortSignal): Promise<Week6EvalResponse> {
    return this.getJudgeResults(false, signal);
  },

  async evaluateWeek6(
    cases?: Week6CaseResult[],
    runLlm: boolean = true,
    signal?: AbortSignal,
  ): Promise<Week6EvalResponse> {
    return this.evaluateJudges(cases, runLlm, signal);
  },

  // ── HR Policy Assistant ────────────────────────────────────────────────
  // Every policy call runs against the documents uploaded in the current
  // browser session; a 409 NO_INDEXED_DOCUMENTS means nothing is indexed yet.

  async getPolicyReadiness(signal?: AbortSignal): Promise<PolicyReadiness> {
    const res = await fetch(`${API_BASE}/api/policy/readiness`, { signal });
    return handleResponse<PolicyReadiness>(res);
  },

  async getPolicyCases(
    suite: BenchmarkSuite = "canonical",
    signal?: AbortSignal,
  ): Promise<BenchmarkCase[]> {
    const res = await fetch(
      `${API_BASE}/api/policy/cases?suite=${encodeURIComponent(suite)}`,
      { signal },
    );
    return handleResponse<BenchmarkCase[]>(res);
  },

  /** Roster rows parsed from the uploaded employee records (409 when nothing is uploaded). */
  async getPolicyEmployees(signal?: AbortSignal): Promise<EmployeeRecord[]> {
    const res = await fetch(`${API_BASE}/api/policy/employees`, { signal });
    return handleResponse<EmployeeRecord[]>(res);
  },

  async getExpectedTrajectories(
    suite: BenchmarkSuite = "all",
    signal?: AbortSignal,
  ): Promise<ExpectedTrajectory[]> {
    const res = await fetch(
      `${API_BASE}/api/policy/trajectory/expected?suite=${encodeURIComponent(suite)}`,
      { signal },
    );
    return handleResponse<ExpectedTrajectory[]>(res);
  },

  async evaluateTrajectory(
    payload: TrajectoryEvaluateRequest,
    signal?: AbortSignal,
  ): Promise<TrajectoryEvaluateResponse> {
    const res = await postJson(
      `${API_BASE}/api/policy/trajectory/evaluate`,
      payload,
      signal,
    );
    return handleResponse<TrajectoryEvaluateResponse>(res);
  },

  async runPolicyAgent(
    payload: PolicyQueryRequest,
    signal?: AbortSignal,
  ): Promise<PolicyOutputContract> {
    const res = await postJson(`${API_BASE}/api/policy/agent`, payload, signal);
    return handleResponse<PolicyOutputContract>(res);
  },

  async runPolicyWorkflow(
    payload: PolicyQueryRequest,
    signal?: AbortSignal,
  ): Promise<PolicyOutputContract> {
    const res = await postJson(
      `${API_BASE}/api/policy/workflow`,
      payload,
      signal,
    );
    return handleResponse<PolicyOutputContract>(res);
  },

  async startPolicyBenchmark(
    payload: PolicyBenchmarkStartRequest = {},
    signal?: AbortSignal,
  ): Promise<PolicyBenchmarkRunStateResponse> {
    const res = await postJson(
      `${API_BASE}/api/policy/benchmark/start`,
      payload,
      signal,
    );
    return handleResponse<PolicyBenchmarkRunStateResponse>(res);
  },

  async getPolicyBenchmarkRun(
    runId: string,
    signal?: AbortSignal,
  ): Promise<PolicyBenchmarkRunStateResponse> {
    const res = await fetch(
      `${API_BASE}/api/policy/benchmark/runs/${encodeURIComponent(runId)}`,
      { signal },
    );
    return handleResponse<PolicyBenchmarkRunStateResponse>(res);
  },

  async getActivePolicyBenchmarkRun(
    signal?: AbortSignal,
  ): Promise<ActiveBenchmarkRunResponse> {
    const res = await fetch(`${API_BASE}/api/policy/benchmark/runs/active`, {
      signal,
    });
    return handleResponse<ActiveBenchmarkRunResponse>(res);
  },

  async cancelPolicyBenchmarkRun(
    runId: string,
    signal?: AbortSignal,
  ): Promise<CancelBenchmarkResponse> {
    const res = await fetch(
      `${API_BASE}/api/policy/benchmark/runs/${encodeURIComponent(runId)}/cancel`,
      { method: "POST", signal },
    );
    return handleResponse<CancelBenchmarkResponse>(res);
  },

  // Auto-routed HR Policy Search
  async getAvailableChatModels(
    signal?: AbortSignal,
  ): Promise<ChatModelListResponse> {
    const res = await fetch(`${API_BASE}/api/policy/models`, { signal });
    return handleResponse<ChatModelListResponse>(res);
  },

  async runPolicySearch(
    payload: PolicySearchRequest,
    signal?: AbortSignal,
  ): Promise<PolicyOutputContract> {
    const res = await postJson(
      `${API_BASE}/api/policy/search`,
      payload,
      signal,
    );
    return handleResponse<PolicyOutputContract>(res);
  },

  // Preview routing decision without executing
  async classifyPolicyQuestion(
    question: string,
    employeeId?: string,
    signal?: AbortSignal,
  ): Promise<RoutingDecision> {
    const params = new URLSearchParams({ question });
    if (employeeId) params.append("employee_id", employeeId);
    const res = await fetch(
      `${API_BASE}/api/policy/router/classify?${params.toString()}`,
      { signal },
    );
    return handleResponse<RoutingDecision>(res);
  },

  // ── MCP visibility (Week 9) ────────────────────────────────────────────
  async getMcpStatus(signal?: AbortSignal): Promise<McpStatusResponse> {
    const res = await fetch(`${API_BASE}/api/mcp/status`, { signal });
    return handleResponse<McpStatusResponse>(res);
  },

  async getMcpWire(
    options: { server?: string; limit?: number } = {},
    signal?: AbortSignal,
  ): Promise<McpWireResponse> {
    const params = new URLSearchParams();
    if (options.server) params.set("server", options.server);
    if (options.limit) params.set("limit", String(options.limit));
    const query = params.toString();
    const res = await fetch(
      `${API_BASE}/api/mcp/wire${query ? `?${query}` : ""}`,
      { signal },
    );
    return handleResponse<McpWireResponse>(res);
  },

  async reloadMcp(signal?: AbortSignal): Promise<McpStatusResponse> {
    const res = await fetch(`${API_BASE}/api/mcp/reload`, {
      method: "POST",
      signal,
    });
    return handleResponse<McpStatusResponse>(res);
  },
};
