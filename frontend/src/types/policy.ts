// frontend/src/types/policy.ts — TypeScript Interfaces for HR Policy Assistant

export interface EmployeeRecord {
  employee_id: string;
  name: string;
  job_title: string;
  department: string;
  duty_station: string;
  jurisdiction: "Kenya" | "Ireland" | "Cote d'Ivoire" | "Rwanda" | "Global";
  tenure_months: number;
  employment_status: "Confirmed" | "Probation";
  annual_leave_balance: number;
  basic_salary_monthly: number;
  separation_reason?: string | null;
}

export interface PolicyQueryRequest {
  employee_id: string;
  question: string;
  case_id?: string;
  top_k?: number;
  temperature?: number;
  model?: string;
}

export interface OllamaModelListResponse {
  default_model: string;
  models: string[];
  agent_models: string[];
}

export interface ToolCallRecord {
  step: number;
  tool_name: string;
  arguments: Record<string, any>;
  output: any;
  latency_ms: number;
}

export interface RetryRecord {
  attempt: number;
  status: "SUCCESS" | "RETRY" | "FAILED" | "BUDGET_EXHAUSTED";
  retry_reason?: string | null;
  retryable: boolean;
  latency_ms: number;
  input_tokens: number;
  output_tokens: number;
  total_tokens: number;
  estimated_cost: number;
  is_retry: boolean;
}

export interface RoutingDecision {
  mode: "workflow" | "agent";
  complexity: "SIMPLE" | "MODERATE" | "COMPLEX";
  reason: string;
  requires_agent: boolean;
  routing_ms: number;
  routing_id: string;
  matched_signals: string[];
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
  iterations: number;

  // Token accounting
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  token_source?: string; // "ollama_live" | "proxy_estimate" | "unavailable"
  llm_calls?: any[];

  // Cost
  cost_usd: number;
  provider_cost?: string; // "N/A" for local Ollama

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

export interface BenchmarkCase {
  case_id: string;
  employee_id: string;
  question: string;
  source_section: string;
  expected_value: string;
  tenure_dependency?: string;
  deterministic_pass_criteria: string[];
}

export interface ExecutionSummary {
  pass_rate_pct: number;
  passed_count: number;
  total_cases: number;
  p50_latency_ms: number;
  total_tokens: number;
  cost_per_question_usd: number;
}

export interface PolicyBenchmarkResponse {
  summary: {
    agent: ExecutionSummary;
    workflow: ExecutionSummary;
  };
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
  status: "WAITING" | "RUNNING" | "PASS" | "FAIL" | "ERROR";
  agent_status: "WAITING" | "RUNNING" | "PASS" | "FAIL" | "ERROR";
  workflow_status: "WAITING" | "RUNNING" | "PASS" | "FAIL" | "ERROR";
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
  agent_result?: PolicyOutputContract | null;
  workflow_result?: PolicyOutputContract | null;
}

export interface PolicyBenchmarkRunStateResponse {
  run_id: string;
  status: "RUNNING" | "COMPLETED" | "CANCELLED" | "ERROR";
  top_k: number;
  temperature: number;
  model: string;
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
  summary?: {
    agent: ExecutionSummary;
    workflow: ExecutionSummary;
  } | null;
  error_message?: string | null;
  agent_results?: PolicyOutputContract[];
  workflow_results?: PolicyOutputContract[];
}

export interface ActiveBenchmarkRunResponse {
  active: boolean;
  run: PolicyBenchmarkRunStateResponse | null;
}
