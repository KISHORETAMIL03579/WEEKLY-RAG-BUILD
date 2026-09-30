// frontend/src/types/policy.ts — TypeScript contracts for the HR Policy Assistant.
// Mirrors backend/schemas/policy.py, backend/services/policy_trajectory.py,
// backend/services/policy_benchmark_runner.py and backend/routes/policy.py.

// ── Readiness / roster / models ──────────────────────────────────────────────

export interface PolicyReadinessDocument {
  doc_id: string;
  filename: string;
  chunks: number;
}

export interface PolicyReadiness {
  chat_backend: string;
  groq_configured: boolean;
  retrieval_mode: "lexical" | "hybrid" | string;
  documents: PolicyReadinessDocument[];
  document_count: number;
  chunk_count: number;
  ready: boolean;
  tools: {
    tool_count: number;
    tool_names: string[];
  };
}

/** One roster row parsed by the backend from the uploaded employee records. */
export interface EmployeeRecord {
  employee_id: string;
  filename?: string | null;
  name?: string;
  job_title?: string;
  department?: string;
  duty_station?: string;
  jurisdiction?: string;
  tenure_months?: number;
  employment_status?: string;
  annual_leave_balance_days?: number;
  basic_monthly_salary_usd?: number;
  separation_reason?: string | null;
  [field: string]: unknown;
}

export interface ChatModelListResponse {
  provider: string;
  default_model: string;
  models: string[];
  agent_models: string[];
}

// ── Requests ─────────────────────────────────────────────────────────────────

export interface PolicyQueryRequest {
  employee_id: string;
  question: string;
  case_id?: string;
  top_k?: number;
  temperature?: number;
  model?: string;
  document_ids?: string[];
}

export interface PolicySearchRequest extends PolicyQueryRequest {
  max_retries?: number;
  force_mode?: "workflow" | "agent";
}

export type BenchmarkSuite = "canonical" | "branching" | "all";

/** Case shape the benchmark endpoints accept when a custom dataset is used. */
export interface CustomBenchmarkCase {
  case_id: string;
  employee_id: string;
  question: string;
  expected_value: string;
  /** Backend reads `source_section` (not `expected_section`). */
  source_section: string;
  deterministic_pass_criteria?: string[];
}

export interface PolicyBenchmarkStartRequest {
  suite?: BenchmarkSuite;
  top_k?: number;
  temperature?: number;
  model?: string;
  cases?: CustomBenchmarkCase[];
  document_ids?: string[];
}

// ── Execution trace ──────────────────────────────────────────────────────────

export interface RoutingDecision {
  mode: "workflow" | "agent";
  complexity: "SIMPLE" | "MODERATE" | "COMPLEX";
  reason: string;
  requires_agent: boolean;
  routing_ms: number;
  routing_id: string;
  matched_signals: string[];
}

export interface ToolErrorPayload {
  code: string;
  message: string;
  retryable?: boolean;
  hint?: string | null;
}

export interface ToolAttemptLogEntry {
  attempt: number;
  status: string;
  detail?: string | null;
  retryable?: boolean;
  latency_ms?: number;
}

export interface ToolCallRecord {
  step: number;
  tool_name: string;
  server?: string | null;
  roles?: string[];
  arguments: Record<string, unknown>;
  /** Compact tool observation; shape depends on the tool (see ToolTrace). */
  output: unknown;
  is_error?: boolean;
  error?: ToolErrorPayload | null;
  attempts?: number;
  retries?: number;
  attempt_log?: ToolAttemptLogEntry[];
  latency_ms: number;
  selection?: {
    rationale?: string | null;
    call_id?: string | null;
  } | null;
}

export interface RejectedToolCall {
  step?: number;
  tool_name: string;
  arguments?: unknown;
  reason: string;
}

export interface RequiredToolGroup {
  rule: string;
  requires_any: string[];
  satisfied: boolean;
  reason: string;
}

export interface ToolRetryStats {
  tool_attempts?: Record<string, number>;
  tool_retries?: Record<string, number>;
  total_tool_retries?: number;
  model_call_retries?: number;
  model_calls?: number;
  run_attempts?: number;
  run_retries?: number;
}

export interface ToolAudit {
  tools_selected?: string[];
  call_counts?: Record<string, number>;
  required?: RequiredToolGroup[];
  missing_tools?: string[];
  extra_tools?: string[];
  /** Older backend builds named `extra_tools` this way. */
  unexpected_tools?: string[];
  duplicate_tools?: string[];
  rejected_calls?: number;
  /** true/false, or null when the run ended early and selection was not judged. */
  selection_ok?: boolean | null;
  termination_reason?: string | null;
  reasons?: string[];
  retries?: ToolRetryStats;
}

export interface CitationCheck {
  cited_sections?: string[];
  resolved_sections?: string[];
  unresolved_sections?: string[];
  has_citation?: boolean;
  all_resolve?: boolean;
}

export interface AnswerCriterion {
  criterion: string;
  /** Literal substring match (legacy scorer). */
  strict_satisfied?: boolean;
  /** Normalised / alias match (current scorer). */
  satisfied?: boolean;
  /** "literal" | "normalized" | "alias:<text>" | null */
  matched_by?: string | null;
}

export interface RetryRecord {
  attempt: number;
  status: "SUCCESS" | "RETRY" | "FAILED" | "BUDGET_EXHAUSTED" | string;
  retry_reason?: string | null;
  retryable?: boolean;
  latency_ms?: number;
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  estimated_cost?: number;
  tool_sequence?: string[];
  tool_retries?: Record<string, number>;
  model_call_retries?: number;
  is_retry?: boolean;
}

export interface ProviderAttemptLogEntry {
  attempt: number;
  outcome: string;
  [field: string]: unknown;
}

export interface LlmCallRecord {
  call_index: number;
  attempt: number;
  is_retry?: boolean;
  provider_attempts?: number;
  provider_retries?: number;
  provider_attempt_log?: ProviderAttemptLogEntry[];
  input_tokens?: number;
  output_tokens?: number;
  total_tokens?: number;
  latency_ms?: number;
  token_source?: string;
  status?: string;
  retry_reason?: string | null;
  retryable?: boolean;
}

export interface PolicyOutputContract {
  // Identification
  case_id: string;
  employee_id: string;
  question: string;
  run_id?: string;
  evaluation_type?: string;

  // Result
  entitlement_value: string;
  rule_cited: string;
  explanation: string;
  passed: boolean;
  strict_passed?: boolean;
  answer_criteria?: AnswerCriterion[];
  citation?: CitationCheck;
  implementation: "agent" | "workflow";

  // Routing metadata
  execution_mode?: "workflow" | "agent";
  routing_reason?: string;
  complexity?: "SIMPLE" | "MODERATE" | "COMPLEX";
  routing_ms?: number;
  mode_history?: string[];
  routing?: RoutingDecision;

  // Execution telemetry
  tool_calls: ToolCallRecord[];
  rejected_tool_calls?: RejectedToolCall[];
  tool_audit?: ToolAudit;
  iterations: number;

  // Token accounting
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  token_source?: string; // "groq_live" | "proxy_estimate" | "unavailable"
  llm_calls?: LlmCallRecord[];

  // Cost (estimated token-cost proxy, never billing)
  cost_usd: number;
  provider_cost?: string;

  // Latency
  latency_ms: number;
  router_latency_ms?: number;
  execution_latency_ms?: number;

  // Retry metadata
  attempt?: number;
  max_retries?: number;
  total_attempts?: number;
  retry_history?: RetryRecord[];

  // Termination
  termination_reason: string;

  // Config provenance
  top_k?: number | null;
  temperature?: number | null;
  model?: string | null;
}

// ── Benchmark ────────────────────────────────────────────────────────────────

export interface BenchmarkCase {
  case_id: string;
  employee_id: string;
  question: string;
  source_section: string;
  expected_value: string;
  tenure_dependency?: string | null;
  deterministic_pass_criteria?: string[];
  requires_tools?: string[];
  path_dependency?: string | null;
}

export type CaseStatus =
  "WAITING" | "RUNNING" | "PASS" | "FAIL" | "ERROR" | "SKIPPED";

export interface ExecutionSummary {
  pass_rate_pct: number;
  strict_pass_rate_pct?: number;
  passed_count: number;
  total_cases: number;
  p50_latency_ms: number;
  max_latency_ms?: number;
  total_tokens: number;
  p50_tokens?: number;
  max_tokens?: number;
  cost_per_question_usd: number;
  p50_cost_usd?: number;
  max_cost_usd?: number;
  terminations?: Record<string, number>;
}

export interface BenchmarkSummary {
  agent: ExecutionSummary;
  workflow: ExecutionSummary;
}

export interface PolicyBenchmarkResponse {
  summary: BenchmarkSummary;
  agent_results: PolicyOutputContract[];
  workflow_results: PolicyOutputContract[];
}

export interface BenchmarkCaseLiveStatus {
  case_id: string;
  employee_id: string;
  question: string;
  ground_truth?: string;
  source_section?: string;
  pass_criteria?: string[];
  requires_tools?: string[];
  path_dependency?: string | null;
  status: CaseStatus;
  skip_reason?: string | null;
  agent_status: CaseStatus;
  workflow_status: CaseStatus;
  agent_entitlement?: string | null;
  workflow_entitlement?: string | null;
  agent_rule?: string | null;
  workflow_rule?: string | null;
  agent_explanation?: string | null;
  workflow_explanation?: string | null;
  agent_passed?: boolean | null;
  workflow_passed?: boolean | null;
  agent_latency_ms?: number | null;
  workflow_latency_ms?: number | null;
  agent_tokens?: number | null;
  workflow_tokens?: number | null;
  agent_cost_usd?: number | null;
  workflow_cost_usd?: number | null;
  agent_tool_sequence?: string[] | null;
  workflow_tool_sequence?: string[] | null;
  agent_tool_retries?: number | null;
  agent_model_retries?: number | null;
  agent_rejected_calls?: number | null;
  agent_selection_ok?: boolean | null;
  agent_result?: PolicyOutputContract | null;
  workflow_result?: PolicyOutputContract | null;
}

export type BenchmarkRunStatus =
  "RUNNING" | "CANCELLING" | "COMPLETED" | "CANCELLED" | "ERROR";

export interface PolicyBenchmarkRunStateResponse {
  run_id: string;
  status: BenchmarkRunStatus;
  cancellation_requested?: boolean;
  top_k: number;
  temperature: number;
  model: string | null;
  total_cases: number;
  completed_cases: number;
  progress_pct: number;
  current_case_id?: string | null;
  current_question?: string | null;
  current_agent_stage?: string | null;
  current_workflow_stage?: string | null;
  agent_completed_count: number;
  workflow_completed_count: number;
  elapsed_seconds: number;
  cases_status: BenchmarkCaseLiveStatus[];
  summary?: BenchmarkSummary | null;
  trajectory?: TrajectoryReport | null;
  error_message?: string | null;
  agent_results?: PolicyOutputContract[];
  workflow_results?: PolicyOutputContract[];
}

export interface ActiveBenchmarkRunResponse {
  active: boolean;
  run: PolicyBenchmarkRunStateResponse | null;
}

export interface CancelBenchmarkResponse {
  cancelled: boolean;
  run_id: string;
}

export interface LatestBenchmarkResults {
  rows: Array<Record<string, string>>;
}

// ── Trajectory (Week 8) ──────────────────────────────────────────────────────

export type FailureMode =
  | "provider_error"
  | "budget_exhausted"
  | "tool_error"
  | "invalid_tool_call"
  | "skipped_required_tool"
  | "wrong_tool_selection"
  | "bad_arguments"
  | "redundant_calls"
  | "answer_wrong";

export interface ArgumentCheck {
  check: string;
  tool?: string | null;
  step?: number | null;
  ok: boolean;
  detail?: string | null;
}

export interface TrajectoryToolTraceEntry {
  step?: number | null;
  tool: string;
  server?: string | null;
  arguments?: Record<string, unknown> | null;
  is_error?: boolean;
  attempts?: number;
  retries?: number;
  rationale?: string | null;
}

export interface TrajectoryCaseRecord {
  case_id: string;
  employee_id: string;
  question?: string | null;
  expected_paths: string[][];
  accepts_alternate_paths: boolean;
  path_notes?: string | null;
  observed_sequence: string[];
  matched_path: string[];
  path_exact: boolean;
  missing_tools: string[];
  extra_tools: string[];
  duplicate_tools: string[];
  tool_choice_score: number;
  argument_checks: ArgumentCheck[];
  argument_validity: number | null;
  steps_taken: number;
  steps_needed: number;
  step_efficiency: number;
  outcome_passed: boolean;
  strict_passed?: boolean;
  trajectory_passed: boolean;
  right_answer_wrong_path: boolean;
  failure_modes: FailureMode[] | string[];
  primary_failure_mode: FailureMode | string | null;
  termination_reason: string;
  tool_trace: TrajectoryToolTraceEntry[];
  rejected_tool_calls: RejectedToolCall[];
  retries: ToolRetryStats;
  latency_ms: number;
  total_tokens: number;
  cost_usd: number;
  answer?: {
    entitlement_value?: string | null;
    rule_cited?: string | null;
    explanation?: string | null;
  };
}

export interface P50Max {
  p50: number;
  max: number;
}

export interface RightAnswerWrongPath {
  case_id: string;
  question?: string | null;
  observed_sequence: string[];
  expected_paths: string[][];
  why?: string;
}

export interface TrajectorySummary {
  case_count?: number;
  outcome_pass_rate_pct: number;
  outcome_strict_pass_rate_pct?: number;
  trajectory_pass_rate_pct: number;
  outcome_vs_trajectory_gap_pct: number;
  tool_choice_accuracy: number;
  exact_tool_set_rate_pct?: number;
  argument_validity_rate: number | null;
  argument_checks_total?: number;
  argument_checks_failed?: number;
  step_efficiency_mean: number;
  step_efficiency_worst: number;
  cost_usd: P50Max;
  latency_ms: P50Max;
  total_tokens: P50Max;
  failure_mode_counts: Record<string, number>;
  failure_mode_any_counts?: Record<string, number>;
  right_answer_wrong_path: RightAnswerWrongPath[];
  retries: {
    tool_attempts?: Record<string, number>;
    tool_retries?: Record<string, number>;
    model_call_retries?: number;
  };
}

export interface TrajectoryReport {
  run_id?: string;
  model?: string | null;
  summary: TrajectorySummary;
  cases: TrajectoryCaseRecord[];
}

export interface ExpectedTrajectory {
  case_id: string;
  employee_id: string;
  question: string;
  paths: string[][];
  steps_needed?: number;
  notes?: string;
  allowed_extra_tools?: string[];
}

export interface TrajectoryComparison {
  baseline_run_id: string;
  per_mode: Array<{
    mode: string;
    before: number;
    after: number;
    delta: number;
  }>;
  regressions: string[];
  modes_checked?: string[];
  price: Record<string, number>;
  outcome_pass_rate_delta_pct?: number;
  trajectory_pass_rate_delta_pct?: number;
}

export interface TrajectoryEvaluateResponse extends TrajectoryReport {
  comparison?: TrajectoryComparison;
}

export interface TrajectoryEvaluateRequest {
  run_id: string;
  baseline_run_id?: string;
}
