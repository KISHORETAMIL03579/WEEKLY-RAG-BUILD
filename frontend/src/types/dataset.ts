// frontend/src/types/dataset.ts — Common Dataset Types for All Three Evaluators

export interface QADataSetCase {
  case_id: string;
  question: string;
  expected_answer?: string;
  employee_id?: string;
  expected_section?: string;
  expected_entitlement?: string;
  taxonomy?: string;
  metadata?: Record<string, any>;
  [key: string]: any;
}

export interface DatasetInvalidCase {
  row: number;
  raw: any;
  reason: string;
}

export interface DatasetParseResult {
  ok: boolean;
  filename: string;
  evaluator_type: string;
  total_found: number;
  valid_count: number;
  invalid_count: number;
  duplicate_count: number;
  valid_cases: QADataSetCase[];
  invalid_cases: DatasetInvalidCase[];
  errors: string[];
  warnings: string[];
  pairs?: Array<{ question: string; expected: string }>;
}

export type DatasetMode = "builtin" | "custom";
