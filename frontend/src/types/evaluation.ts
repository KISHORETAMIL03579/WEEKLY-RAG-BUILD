export interface EvalQuestionInput {
  id: string;
  question: string;
  expected: string;
}

export interface EvalRunPayload {
  questions: Array<{
    id: string;
    question: string;
    expected: string;
  }>;
  top_k: number;
  presets: string[];
  strategy_filter?: string;
}

export interface EvalQuestionResult {
  id: string;
  question: string;
  expected?: string;
  expected_doc?: string;
  expected_section?: string;
  hit: boolean;
  rank: number | null;
}

export interface EvalModeResult {
  hit_rate: number;
  mrr: number;
  hits: number;
  total: number;
  results: EvalQuestionResult[];
}

export interface EvalRunResponse {
  k: number;
  modes: Record<string, EvalModeResult>;
  error?: string;
}

export interface ParseQaResponse {
  pairs?: Array<{
    question: string;
    expected: string;
  }>;
  error?: string;
}

export interface BenchmarkCase {
  case_id: string;
  trace_id?: string;
  question: string;
  answer: string;
  retrieved_context?: string;
  handbook_version?: string;
  section_info?: string;
  taxonomy_mode?: string;
  human_label?: number;
  expected_numeric?: string;
  out_of_jurisdiction?: boolean;
}

export interface JudgeAssertions {
  policy_section_reference_present: boolean;
  policy_section_reference_resolves: boolean;
  handbook_version_present: boolean;
  numeric_policy_value_present: boolean;
  out_of_jurisdiction_refusal: boolean;
}

export type EvaluationCaseStatus = 'PENDING' | 'RUNNING' | 'COMPLETED' | 'ERROR';
export type EvaluationVerdictSource = 'LLM' | 'DETERMINISTIC' | 'FALLBACK' | 'CACHE' | 'ERROR';

export interface JudgeCaseResult {
  case_id: string;
  trace_id?: string;
  question: string;
  answer: string;
  retrieved_context?: string;
  handbook_version?: string;
  section_info?: string;
  taxonomy_mode?: string;
  human_label?: number;
  expected_numeric?: string;
  out_of_jurisdiction?: boolean;
  
  // Evaluation Lifecycle & Run Association
  evaluation_run_id?: string | null;
  status?: EvaluationCaseStatus;

  // Verdicts (null when PENDING / un-evaluated)
  judge_v1_verdict?: number | null;
  judge_v1_agreed?: boolean | null;
  judge_v1_raw?: string | null;
  judge_v1_source?: EvaluationVerdictSource | null;
  judge_v1_latency_ms?: number | null;
  judge_v1_llm_completed?: boolean | null;

  judge_v2_verdict?: number | null;
  judge_v2_agreed?: boolean | null;
  judge_v2_raw?: string | null;
  judge_v2_source?: EvaluationVerdictSource | null;
  judge_v2_latency_ms?: number | null;
  judge_v2_llm_completed?: boolean | null;

  // Canonical Provenance & Telemetry
  source?: EvaluationVerdictSource | null;
  latency_ms?: number | null;
  llm_completed?: boolean | null;

  // Provenance & Telemetry
  top_k?: number;
  requested_top_k?: number;
  temperature?: number;
  requested_temperature?: number;
  actual_temperature?: number;
  applied_temperature?: number;
  model?: string;
  retrieval_mode?: string;
  retrieved_count?: number;
  retrieved_chunk_ids?: string[];
  retrieved_scores?: Record<string, number> | number[];
  final_context_chunk_ids?: string[];
  final_context_token_count?: number;
  benchmark_taxonomy?: string | null;
  actual_run_diagnosis?: string | null;
  expected_answer?: string;

  // Assertions & Diagnosis
  assertions?: JudgeAssertions | null;
  failure_category?: 'pipeline' | 'llm_model' | 'code_issue' | 'pass' | string | null;
  failure_type?: string | null;
  failure_reason?: string | null;
  resolution?: string | null;
}

export interface JudgeEvalResponse {
  evaluation_run_id?: string;
  total_cases: number;
  judge_v1_agreement_pct?: number;
  judge_v2_agreement_pct?: number;
  v1_agreements?: number;
  v2_agreements?: number;
  cases?: JudgeCaseResult[];
  results: JudgeCaseResult[];
}

export interface EvaluationRunStateResponse {
  evaluation_run_id: string;
  status: 'PENDING' | 'RUNNING' | 'COMPLETED' | 'CANCELLED' | 'ERROR';
  eval_engine: 'deterministic' | 'llm';
  total_cases: number;
  completed_cases: number;
  current_case_id?: string | null;
  current_question?: string | null;
  created_at: number;
  updated_at: number;
  elapsed_seconds: number;
  top_k?: number;
  temperature?: number;
  model?: string;
  v1_agreements?: number;
  v2_agreements?: number;
  judge_v1_agreement_pct?: number | null;
  judge_v2_agreement_pct?: number | null;
  error_message?: string | null;
  cases: JudgeCaseResult[];
  results: JudgeCaseResult[];
}

export interface ActiveEvaluationRunResponse {
  active_run_id: string | null;
  run: EvaluationRunStateResponse | null;
}

export interface JudgeEvalPayload {
  cases?: JudgeCaseResult[];
  run_llm?: boolean;
}

// Backward-compatibility aliases
export type Week6Assertions = JudgeAssertions;
export type Week6CaseResult = JudgeCaseResult;
export type Week6EvalResponse = JudgeEvalResponse;
export type Week6EvalPayload = JudgeEvalPayload;
