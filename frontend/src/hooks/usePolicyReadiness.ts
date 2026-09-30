import { useCallback, useEffect, useRef, useState } from "react";
import { api, DOCUMENTS_CHANGED_EVENT } from "../services/api";
import { describeError, isNoDocumentsError } from "../services/apiError";
import { EmployeeRecord, PolicyReadiness } from "../types/policy";

const MIN_REFETCH_GAP_MS = 800;

/**
 * What the policy features can use right now: indexed documents (names + chunk
 * counts), retrieval mode, tool count, and the employee roster parsed from the
 * uploaded records. Refreshes on mount, when the window regains focus or becomes
 * visible again, after any upload/remove/clear on the Chat page, and on demand.
 */
export function usePolicyReadiness() {
  const [readiness, setReadiness] = useState<PolicyReadiness | null>(null);
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshing, setIsRefreshing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [employeesError, setEmployeesError] = useState<string | null>(null);
  const [checkedAt, setCheckedAt] = useState<number | null>(null);

  const sequenceRef = useRef(0);
  const lastRunRef = useRef(0);
  const mountedRef = useRef(true);

  const refresh = useCallback(async () => {
    const sequence = ++sequenceRef.current;
    lastRunRef.current = Date.now();
    setIsRefreshing(true);
    try {
      const status = await api.getPolicyReadiness();
      if (!mountedRef.current || sequence !== sequenceRef.current) return;
      setReadiness(status);
      setError(null);
      if (status.document_count > 0) {
        try {
          const roster = await api.getPolicyEmployees();
          if (!mountedRef.current || sequence !== sequenceRef.current) return;
          setEmployees(Array.isArray(roster) ? roster : []);
          setEmployeesError(null);
        } catch (rosterError) {
          if (!mountedRef.current || sequence !== sequenceRef.current) return;
          setEmployees([]);
          setEmployeesError(
            isNoDocumentsError(rosterError)
              ? null
              : `Could not read the employee roster: ${describeError(rosterError)}`,
          );
        }
      } else {
        setEmployees([]);
        setEmployeesError(null);
      }
    } catch (statusError) {
      if (!mountedRef.current || sequence !== sequenceRef.current) return;
      setError(describeError(statusError));
    } finally {
      if (mountedRef.current && sequence === sequenceRef.current) {
        setIsLoading(false);
        setIsRefreshing(false);
        setCheckedAt(Date.now());
      }
    }
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    void refresh();

    const refreshIfStale = () => {
      if (Date.now() - lastRunRef.current > MIN_REFETCH_GAP_MS) void refresh();
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") refreshIfStale();
    };
    const onDocumentsChanged = () => void refresh();

    window.addEventListener("focus", refreshIfStale);
    document.addEventListener("visibilitychange", onVisibility);
    window.addEventListener(DOCUMENTS_CHANGED_EVENT, onDocumentsChanged);
    return () => {
      mountedRef.current = false;
      window.removeEventListener("focus", refreshIfStale);
      document.removeEventListener("visibilitychange", onVisibility);
      window.removeEventListener(DOCUMENTS_CHANGED_EVENT, onDocumentsChanged);
    };
  }, [refresh]);

  const hasDocuments = (readiness?.document_count ?? 0) > 0;

  return {
    readiness,
    employees,
    hasDocuments,
    hasRoster: employees.length > 0,
    isLoading,
    isRefreshing,
    error,
    employeesError,
    checkedAt,
    refresh,
  };
}

export type PolicyReadinessState = ReturnType<typeof usePolicyReadiness>;
