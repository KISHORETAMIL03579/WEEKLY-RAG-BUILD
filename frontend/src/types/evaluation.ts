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

export interface JudgeAssertions {
  policy_section_reference_present: boolean;
  policy_section_reference_resolves: boolean;
  handbook_version_present: boolean;
  numeric_policy_value_present: boolean;
  out_of_jurisdiction_refusal: boolean;
}

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
  assertions?: JudgeAssertions;
  judge_v1_verdict: number;
  judge_v1_agreed?: boolean;
  judge_v1_raw?: string;
  judge_v2_verdict: number;
  judge_v2_agreed?: boolean;
  judge_v2_raw?: string;
  failure_category?: string;
  failure_type?: string;
  failure_reason?: string;
  resolution?: string;
}

export interface JudgeEvalResponse {
  total_cases: number;
  judge_v1_agreement_pct: number;
  judge_v2_agreement_pct: number;
  v1_agreements: number;
  v2_agreements: number;
  results: JudgeCaseResult[];
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
