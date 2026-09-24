// frontend/src/types/policy.ts — TypeScript Interfaces for HR Policy Assistant

export interface EmployeeRecord {
  employee_id: string;
  name: string;
  job_title: string;
  department: string;
  duty_station: string;
  jurisdiction: 'Kenya' | 'Ireland' | "Cote d'Ivoire" | 'Rwanda' | 'Global';
  tenure_months: number;
  employment_status: 'Confirmed' | 'Probation';
  annual_leave_balance: number;
  basic_salary_monthly: number;
  separation_reason?: string | null;
}

export interface PolicyQueryRequest {
  employee_id: string;
  question: string;
  case_id?: string;
}

export interface ToolCallRecord {
  step: number;
  tool_name: string;
  arguments: Record<string, any>;
  output: any;
  latency_ms: number;
}

export interface PolicyOutputContract {
  case_id: string;
  employee_id: string;
  question: string;
  entitlement_value: string;
  rule_cited: string;
  explanation: string;
  passed: boolean;
  implementation: 'agent' | 'workflow';
  tool_calls: ToolCallRecord[];
  iterations: number;
  prompt_tokens: number;
  completion_tokens: number;
  total_tokens: number;
  cost_usd: number;
  latency_ms: number;
  termination_reason: string;
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
