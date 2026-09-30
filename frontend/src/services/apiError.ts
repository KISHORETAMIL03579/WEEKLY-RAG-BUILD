// Structured API errors. The backend answers with
//   { success:false, error:{ code, message, request_id, retryable, details? }, message }
// (backend/errors.py). Some legacy routes answer { error: "text" }.

export interface ApiErrorInit {
  status: number;
  code?: string | null;
  backendMessage?: string | null;
  retryable?: boolean;
  requestId?: string | null;
  details?: unknown;
}

/** Where a user should go to fix the problem behind an error code. */
export type ApiErrorAction = "upload-documents" | "retry" | "none";

interface Friendly {
  message: string;
  action: ApiErrorAction;
}

function friendly(init: ApiErrorInit): Friendly {
  const backend = (init.backendMessage || "").trim();
  switch (init.code) {
    case "NO_INDEXED_DOCUMENTS":
      return {
        message:
          "No documents are indexed for this session. Upload the HR policy document and the employee records on the Chat page first.",
        action: "upload-documents",
      };
    case "LLM_GENERATION_FAILED":
    case "SERVICE_UNAVAILABLE":
      return {
        message:
          backend || "A backing service is unavailable. Please try again.",
        action: "retry",
      };
    case "BENCHMARK_ACTIVE": {
      const details = init.details as { active_run_id?: string } | undefined;
      const active = details?.active_run_id
        ? ` (run ${details.active_run_id})`
        : "";
      return {
        message: `A policy benchmark is already running${active}. Wait for it to finish or cancel it first.`,
        action: "none",
      };
    }
    case "RATE_LIMIT_EXCEEDED":
      return {
        message:
          backend ||
          "The request budget was exceeded. Wait a moment and retry.",
        action: "retry",
      };
    case "RUN_NOT_FOUND":
      return {
        message:
          backend || "That benchmark run no longer exists on the server.",
        action: "none",
      };
    case "VALIDATION_ERROR":
      return {
        message: backend || "The request was not valid.",
        action: "none",
      };
    default:
      break;
  }
  if (init.status === 400 && /no active session/i.test(backend)) {
    return {
      message:
        "There is no active session yet. Upload your documents on the Chat page first.",
      action: "upload-documents",
    };
  }
  if (init.status >= 500) {
    return {
      message:
        backend ||
        `The server failed to handle the request (HTTP ${init.status}).`,
      action: "retry",
    };
  }
  return {
    message: backend || `Request failed with status ${init.status}`,
    action: "none",
  };
}

export class ApiError extends Error {
  readonly status: number;
  readonly code: string | null;
  readonly backendMessage: string;
  readonly retryable: boolean;
  readonly requestId: string | null;
  readonly details: unknown;
  readonly action: ApiErrorAction;

  constructor(init: ApiErrorInit) {
    const { message, action } = friendly(init);
    super(message);
    this.name = "ApiError";
    this.status = init.status;
    this.code = init.code ?? null;
    this.backendMessage = init.backendMessage ?? "";
    this.retryable = Boolean(init.retryable);
    this.requestId = init.requestId ?? null;
    this.details = init.details;
    this.action = action;
  }
}

/** Human-readable text for anything thrown by an API call (never raw JSON). */
export function describeError(error: unknown): string {
  if (error instanceof ApiError) return error.message;
  if (error instanceof DOMException && error.name === "AbortError") {
    return "The request was cancelled.";
  }
  if (error instanceof TypeError) {
    return "Cannot reach the backend server. Check that it is running and try again.";
  }
  if (error instanceof Error && error.message) return error.message;
  return "Something went wrong.";
}

export function isAbortError(error: unknown): boolean {
  return (
    (error instanceof DOMException && error.name === "AbortError") ||
    (error instanceof Error && error.name === "AbortError")
  );
}

/** True when the failure means "nothing is uploaded yet". */
export function isNoDocumentsError(error: unknown): boolean {
  return error instanceof ApiError && error.action === "upload-documents";
}
