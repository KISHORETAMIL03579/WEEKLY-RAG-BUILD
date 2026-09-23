import {
  StatusResponse,
  AskResponse,
  UploadResponse,
  LoadUrlResponse,
  RemoveResponse,
  ClearResponse,
  PagesResponse,
} from '../types/api';
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
} from '../types/evaluation';
import { TracesResponse, ReplayResponse } from '../types/trace';

const API_BASE = import.meta.env.VITE_API_BASE_URL || '';

async function handleResponse<T>(res: Response): Promise<T> {
  const data = await res.json().catch(() => ({}));
  if (!res.ok) {
    const errorMsg =
      data.error || data.message || (typeof data.detail === 'string' ? data.detail : null) || `Request failed with status ${res.status}`;
    throw new Error(errorMsg);
  }
  return data as T;
}

export const api = {
  async getStatus(signal?: AbortSignal): Promise<StatusResponse> {
    const res = await fetch(`${API_BASE}/status`, { signal });
    return handleResponse<StatusResponse>(res);
  },

  async uploadFiles(formData: FormData, signal?: AbortSignal): Promise<UploadResponse> {
    const res = await fetch(`${API_BASE}/upload`, {
      method: 'POST',
      body: formData,
      signal,
    });
    return handleResponse<UploadResponse>(res);
  },

  async cancelUpload(uploadId: string): Promise<{ ok: boolean }> {
    const res = await fetch(`${API_BASE}/upload-cancel`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ upload_id: uploadId }),
    });
    return handleResponse<{ ok: boolean }>(res);
  },

  async askQuestion(
    query: string,
    chunk_mode: string = 'structured',
    top_k: number = 8,
    temperature: number = 0.0,
    signal?: AbortSignal
  ): Promise<AskResponse> {
    const res = await fetch(`${API_BASE}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ query, chunk_mode, top_k, temperature }),
      signal,
    });
    return handleResponse<AskResponse>(res);
  },

  async loadUrl(url: string, chunk_mode: string = 'structured', signal?: AbortSignal): Promise<LoadUrlResponse> {
    const res = await fetch(`${API_BASE}/load-url`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ url, chunk_mode }),
      signal,
    });
    return handleResponse<LoadUrlResponse>(res);
  },

  async removeDoc(doc_id: string, signal?: AbortSignal): Promise<RemoveResponse> {
    const res = await fetch(`${API_BASE}/remove`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ doc_id }),
      signal,
    });
    return handleResponse<RemoveResponse>(res);
  },

  async clearSession(signal?: AbortSignal): Promise<ClearResponse> {
    const res = await fetch(`${API_BASE}/clear`, {
      method: 'POST',
      signal,
    });
    return handleResponse<ClearResponse>(res);
  },

  async getTraces(signal?: AbortSignal): Promise<TracesResponse> {
    const res = await fetch(`${API_BASE}/traces`, { signal });
    return handleResponse<TracesResponse>(res);
  },

  async replayTrace(traceId: string, signal?: AbortSignal): Promise<ReplayResponse> {
    const res = await fetch(`${API_BASE}/replay/${encodeURIComponent(traceId)}`, {
      method: 'POST',
      signal,
    });
    return handleResponse<ReplayResponse>(res);
  },

  async getFilePages(docId: string, signal?: AbortSignal): Promise<PagesResponse> {
    const res = await fetch(`${API_BASE}/file/${encodeURIComponent(docId)}/pages`, {
      signal,
    });
    return handleResponse<PagesResponse>(res);
  },

  async runEvaluation(payload: EvalRunPayload, signal?: AbortSignal): Promise<EvalRunResponse> {
    const res = await fetch(`${API_BASE}/eval/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
      signal,
    });
    return handleResponse<EvalRunResponse>(res);
  },

  async parseEvaluationFile(file: File, signal?: AbortSignal): Promise<ParseQaResponse> {
    const fd = new FormData();
    fd.append('file', file);
    const res = await fetch(`${API_BASE}/eval/parse-qa-pdf`, {
      method: 'POST',
      body: fd,
      signal,
    });
    return handleResponse<ParseQaResponse>(res);
  },

  async getOrphans(adminKey?: string, signal?: AbortSignal): Promise<unknown> {
    const headers: Record<string, string> = {};
    if (adminKey) {
      headers['X-Admin-Key'] = adminKey;
    }
    const res = await fetch(`${API_BASE}/orphans`, { headers, signal });
    return handleResponse(res);
  },

  async startEvaluationRun(
    cases?: JudgeCaseResult[],
    runLlm: boolean = true,
    signal?: AbortSignal
  ): Promise<EvaluationRunStateResponse> {
    const payload = JSON.stringify({ cases, run_llm: runLlm });
    let res = await fetch(`${API_BASE}/api/evaluation/runs`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: payload,
      signal,
    }).catch(() => null);

    if (!res || !res.ok) {
      const fallbackRes = await fetch(`${API_BASE}/api/week6/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
        signal,
      }).catch(() => null);

      if (fallbackRes && fallbackRes.ok) {
        return handleResponse<EvaluationRunStateResponse>(fallbackRes);
      }

      // Synchronous evaluate fallback if backend background runner is unavailable
      if (!res || res.status === 404) {
        const syncData = await this.evaluateJudges(cases, runLlm, signal);
        const results = syncData.results || [];
        return {
          evaluation_run_id: syncData.evaluation_run_id || `eval_${Date.now()}`,
          status: 'COMPLETED',
          eval_engine: runLlm ? 'llm' : 'deterministic',
          total_cases: syncData.total_cases || results.length,
          completed_cases: syncData.total_cases || results.length,
          judge_v1_agreement_pct: syncData.judge_v1_agreement_pct ?? 0,
          judge_v2_agreement_pct: syncData.judge_v2_agreement_pct ?? 0,
          v1_agreements: syncData.v1_agreements ?? 0,
          v2_agreements: syncData.v2_agreements ?? 0,
          created_at: Date.now() / 1000,
          updated_at: Date.now() / 1000,
          elapsed_seconds: 0.1,
          cases: results,
          results,
        };
      }
    }

    return handleResponse<EvaluationRunStateResponse>(res);
  },

  async getActiveEvaluationRun(signal?: AbortSignal): Promise<ActiveEvaluationRunResponse> {
    try {
      const res = await fetch(`${API_BASE}/api/evaluation/runs/active`, { signal });
      if (res.status === 404) {
        const fallbackRes = await fetch(`${API_BASE}/api/week6/runs/active`, { signal });
        if (fallbackRes && fallbackRes.ok) return await fallbackRes.json();
        return { active_run_id: null, run: null };
      }
      return handleResponse<ActiveEvaluationRunResponse>(res);
    } catch {
      return { active_run_id: null, run: null };
    }
  },

  async getEvaluationRun(runId: string, signal?: AbortSignal): Promise<EvaluationRunStateResponse> {
    let res = await fetch(`${API_BASE}/api/evaluation/runs/${encodeURIComponent(runId)}`, { signal }).catch(() => null);
    if (!res || !res.ok) {
      const fallbackRes = await fetch(`${API_BASE}/api/week6/runs/${encodeURIComponent(runId)}`, { signal }).catch(() => null);
      if (fallbackRes && fallbackRes.ok) {
        return handleResponse<EvaluationRunStateResponse>(fallbackRes);
      }
    }
    if (!res) {
      throw new Error(`Failed to fetch evaluation run ${runId}`);
    }
    return handleResponse<EvaluationRunStateResponse>(res);
  },

  async cancelEvaluationRun(runId: string, signal?: AbortSignal): Promise<{ ok: boolean; status: string }> {
    let res = await fetch(`${API_BASE}/api/evaluation/runs/${encodeURIComponent(runId)}/cancel`, {
      method: 'POST',
      signal,
    }).catch(() => null);
    if (!res || !res.ok) {
      const fallbackRes = await fetch(`${API_BASE}/api/week6/runs/${encodeURIComponent(runId)}/cancel`, {
        method: 'POST',
        signal,
      }).catch(() => null);
      if (fallbackRes) return handleResponse<{ ok: boolean; status: string }>(fallbackRes);
    }
    if (!res) {
      return { ok: false, status: 'UNKNOWN' };
    }
    return handleResponse<{ ok: boolean; status: string }>(res);
  },

  async getBenchmarkCases(signal?: AbortSignal): Promise<JudgeEvalResponse> {
    const res = await fetch(`${API_BASE}/api/evaluation/benchmark`, { signal }).catch(async () => {
      return fetch(`${API_BASE}/api/week6/benchmark`, { signal });
    });
    return handleResponse<JudgeEvalResponse>(res);
  },

  async getJudgeResults(includeHistory: boolean = false, signal?: AbortSignal): Promise<JudgeEvalResponse> {
    const query = includeHistory ? '?include_history=true' : '';
    const res = await fetch(`${API_BASE}/api/evaluation/judges${query}`, { signal }).catch(async () => {
      // Fallback to legacy path if needed
      return fetch(`${API_BASE}/api/week6/results${query}`, { signal });
    });
    return handleResponse<JudgeEvalResponse>(res);
  },

  async evaluateJudges(
    cases?: JudgeCaseResult[],
    runLlm: boolean = true,
    signal?: AbortSignal
  ): Promise<JudgeEvalResponse> {
    const res = await fetch(`${API_BASE}/api/evaluation/judges`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ cases, run_llm: runLlm }),
      signal,
    }).catch(async () => {
      // Fallback to legacy path if needed
      return fetch(`${API_BASE}/api/week6/evaluate`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cases, run_llm: runLlm }),
        signal,
      });
    });
    return handleResponse<JudgeEvalResponse>(res);
  },

  // Backward compatibility methods
  async getWeek6Results(signal?: AbortSignal): Promise<Week6EvalResponse> {
    return this.getJudgeResults(false, signal);
  },

  async evaluateWeek6(cases?: Week6CaseResult[], runLlm: boolean = true, signal?: AbortSignal): Promise<Week6EvalResponse> {
    return this.evaluateJudges(cases, runLlm, signal);
  },
};
