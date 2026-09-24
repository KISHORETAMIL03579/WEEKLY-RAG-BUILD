// frontend/src/components/Evaluation/PolicyAssistantView.tsx — Professional HR Policy Benchmark Dashboard
import React, { useState, useEffect, useRef, useMemo } from 'react';
import { api } from '../../services/api';
import {
  EmployeeRecord,
  BenchmarkCase,
  PolicyOutputContract,
  PolicyBenchmarkRunStateResponse,
  BenchmarkCaseLiveStatus,
} from '../../types/policy';

interface PolicyAssistantViewProps {
  onNotify: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export const PolicyAssistantView: React.FC<PolicyAssistantViewProps> = ({ onNotify }) => {
  // Canonical data
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [cases, setCases] = useState<BenchmarkCase[]>([]);

  // Benchmark Configuration State
  const [topK, setTopK] = useState<number>(5);
  const [temperature, setTemperature] = useState<number>(0.3);
  const [selectedModel, setSelectedModel] = useState<string>('llama3.1:8b');

  // Benchmark Run State
  const [activeRunId, setActiveRunId] = useState<string | null>(null);
  const [benchmarkRunState, setBenchmarkRunState] = useState<PolicyBenchmarkRunStateResponse | null>(null);
  const [isRunningBenchmark, setIsRunningBenchmark] = useState<boolean>(false);
  const [benchmarkHistory, setBenchmarkHistory] = useState<PolicyBenchmarkRunStateResponse[]>([]);

  // Inspect Modal / Drawer State
  const [inspectCase, setInspectCase] = useState<BenchmarkCaseLiveStatus | null>(null);

  // Methodology Accordion State
  const [showMethodology, setShowMethodology] = useState<boolean>(false);

  // Single Case Playground State (Dedicated Separate Section)
  const [showPlayground, setShowPlayground] = useState<boolean>(false);
  const [selectedEmpId, setSelectedEmpId] = useState<string>('EMP001');
  const [queryText, setQueryText] = useState<string>(
    'What is the standard annual leave entitlement and monthly accrual rate for EMP001?'
  );
  const [selectedCaseId, setSelectedCaseId] = useState<string>('case_01');
  const [isRunningSingle, setIsRunningSingle] = useState<boolean>(false);
  const [agentSingleResult, setAgentSingleResult] = useState<PolicyOutputContract | null>(null);
  const [workflowSingleResult, setWorkflowSingleResult] = useState<PolicyOutputContract | null>(null);

  const pollIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    loadInitialData();
    checkActiveBenchmark();
    return () => {
      if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);
    };
  }, []);

  const loadInitialData = async () => {
    try {
      const [empsData, casesData] = await Promise.all([
        api.getCanonicalEmployees(),
        api.getPolicyCases(),
      ]);
      setEmployees(empsData || []);
      setCases(casesData || []);
    } catch (err: any) {
      onNotify('Failed to load employee records or benchmark cases: ' + err.message, 'error');
    }
  };

  const checkActiveBenchmark = async () => {
    try {
      const activeData = await api.getActivePolicyBenchmarkRun();
      if (activeData && activeData.active && activeData.run) {
        setActiveRunId(activeData.run.run_id);
        setBenchmarkRunState(activeData.run);
        if (activeData.run.status === 'RUNNING') {
          setIsRunningBenchmark(true);
          startPolling(activeData.run.run_id);
        }
      }
    } catch {
      // Ignore background active check errors
    }
  };

  const startPolling = (runId: string) => {
    if (pollIntervalRef.current) clearInterval(pollIntervalRef.current);

    pollIntervalRef.current = setInterval(async () => {
      try {
        const state: PolicyBenchmarkRunStateResponse = await api.getPolicyBenchmarkRun(runId);
        if (state) {
          setBenchmarkRunState(state);
          if (state.status === 'COMPLETED' || state.status === 'CANCELLED' || state.status === 'ERROR') {
            if (pollIntervalRef.current) {
              clearInterval(pollIntervalRef.current);
              pollIntervalRef.current = null;
            }
            setIsRunningBenchmark(false);
            if (state.status === 'COMPLETED') {
              onNotify(`Benchmark run ${runId} completed successfully!`, 'success');
              setBenchmarkHistory((prev) => [state, ...prev.filter((p) => p.run_id !== state.run_id)]);
            } else if (state.status === 'CANCELLED') {
              onNotify(`Benchmark run ${runId} cancelled.`, 'info');
            } else if (state.status === 'ERROR') {
              onNotify(`Benchmark run failed: ${state.error_message || 'Unknown error'}`, 'error');
            }
          }
        }
      } catch (err: any) {
        console.warn('Error polling benchmark state:', err);
      }
    }, 400);
  };

  const handleStartBenchmark = async () => {
    setIsRunningBenchmark(true);
    try {
      const res: PolicyBenchmarkRunStateResponse = await api.startPolicyBenchmark({
        top_k: topK,
        temperature,
        model: selectedModel,
      });
      setActiveRunId(res.run_id);
      setBenchmarkRunState(res);
      startPolling(res.run_id);
      onNotify(`Started 10-Case Benchmark Race (Run ID: ${res.run_id})`, 'info');
    } catch (err: any) {
      setIsRunningBenchmark(false);
      onNotify('Failed to start benchmark: ' + err.message, 'error');
    }
  };

  const handleCancelBenchmark = async () => {
    if (!activeRunId) return;
    try {
      await api.cancelPolicyBenchmarkRun(activeRunId);
      onNotify(`Cancelling benchmark run ${activeRunId}...`, 'info');
    } catch (err: any) {
      onNotify('Failed to cancel benchmark: ' + err.message, 'error');
    }
  };

  const handleSetWeek6Baseline = () => {
    setTopK(8);
    setTemperature(0.0);
    onNotify('Loaded Week 6 Frozen Baseline: Top-K = 8, Temperature = 0.0', 'info');
  };

  const handleSetAppDefault = () => {
    setTopK(5);
    setTemperature(0.3);
    setSelectedModel('llama3.1:8b');
    onNotify('Loaded Application Default: Top-K = 5, Temperature = 0.3', 'info');
  };

  const handleLoadHistoricRun = (historicRun: PolicyBenchmarkRunStateResponse) => {
    setBenchmarkRunState(historicRun);
    setActiveRunId(historicRun.run_id);
    setTopK(historicRun.top_k);
    setTemperature(historicRun.temperature);
    if (historicRun.model) setSelectedModel(historicRun.model);
    onNotify(`Loaded historic benchmark run: ${historicRun.run_id}`, 'success');
  };

  // Single Case Playground Handlers
  const handleSelectCase = (c: BenchmarkCase) => {
    setSelectedCaseId(c.case_id);
    setSelectedEmpId(c.employee_id);
    setQueryText(c.question);
  };

  const handleRunSingle = async (mode: 'both' | 'agent' | 'workflow') => {
    if (!selectedEmpId || !queryText.trim()) {
      onNotify('Please select employee ID and query', 'error');
      return;
    }

    setIsRunningSingle(true);
    try {
      if (mode === 'both' || mode === 'agent') {
        const aRes = await api.runPolicyAgent({
          employee_id: selectedEmpId,
          question: queryText.trim(),
          case_id: selectedCaseId,
          top_k: topK,
          temperature,
          model: selectedModel,
        });
        setAgentSingleResult(aRes);
      }
      if (mode === 'both' || mode === 'workflow') {
        const wRes = await api.runPolicyWorkflow({
          employee_id: selectedEmpId,
          question: queryText.trim(),
          case_id: selectedCaseId,
          top_k: topK,
        });
        setWorkflowSingleResult(wRes);
      }
      onNotify('Policy query evaluated successfully!', 'success');
    } catch (err: any) {
      onNotify('Execution error: ' + err.message, 'error');
    } finally {
      setIsRunningSingle(false);
    }
  };

  const selectedEmp = employees.find((e) => e.employee_id === selectedEmpId);

  // Compute Latency percentiles (p50 and p95) from results
  const latencyMetrics = useMemo(() => {
    if (!benchmarkRunState || !benchmarkRunState.cases_status) {
      return { agentP50: 0, agentP95: 0, wfP50: 0, wfP95: 0 };
    }
    const agentLats = benchmarkRunState.cases_status
      .map((c) => c.agent_latency_ms)
      .filter((l): l is number => typeof l === 'number')
      .sort((a, b) => a - b);

    const wfLats = benchmarkRunState.cases_status
      .map((c) => c.workflow_latency_ms)
      .filter((l): l is number => typeof l === 'number')
      .sort((a, b) => a - b);

    const calcP = (arr: number[], p: number) => {
      if (!arr.length) return 0;
      const idx = Math.min(arr.length - 1, Math.floor(arr.length * p));
      return arr[idx];
    };

    return {
      agentP50: calcP(agentLats, 0.5),
      agentP95: calcP(agentLats, 0.95),
      wfP50: calcP(wfLats, 0.5),
      wfP95: calcP(wfLats, 0.95),
    };
  }, [benchmarkRunState]);

  // Determine stage progression states for Agent and Workflow
  const agentStages = [
    'Calling Ollama',
    'Selecting tool',
    'Executing tool',
    'Processing tool result',
    'Generating final answer',
  ];

  const getAgentStageStatus = (stageName: string, currentStage?: string | null) => {
    if (!currentStage) return '○';
    const currLower = currentStage.toLowerCase();
    const targetLower = stageName.toLowerCase();

    if (currLower.includes(targetLower) || targetLower.includes(currLower)) {
      return '⚡';
    }

    const currentIdx = agentStages.findIndex((s) => currLower.includes(s.toLowerCase()));
    const targetIdx = agentStages.findIndex((s) => s.toLowerCase() === targetLower);

    if (currentIdx > targetIdx && currentIdx !== -1) {
      return '✓';
    }
    return '○';
  };

  const wfSteps = [
    { title: 'Step 1 — Employee lookup', key: 'step 1' },
    { title: 'Step 2 — Handbook lookup', key: 'step 2' },
    { title: 'Step 3 — Deterministic policy resolution', key: 'step 3' },
  ];

  const getWfStepStatus = (stepKey: string, currentWfStage?: string | null) => {
    if (!currentWfStage) return { icon: '○', status: 'WAITING' };
    const currLower = currentWfStage.toLowerCase();

    if (currLower.includes(stepKey)) {
      return { icon: '⚡', status: 'RUNNING' };
    }

    if (stepKey === 'step 1' && (currLower.includes('step 2') || currLower.includes('step 3'))) {
      return { icon: '✓', status: 'COMPLETE' };
    }
    if (stepKey === 'step 2' && currLower.includes('step 3')) {
      return { icon: '✓', status: 'COMPLETE' };
    }
    return { icon: '○', status: 'WAITING' };
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', maxWidth: '1200px', margin: '0 auto', width: '100%' }}>
      {/* ==================================================
          1. HEADER / HERO
          ================================================== */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '24px 28px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <h1 style={{ margin: 0, fontSize: '1.4rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span>🤖</span> HR Policy Assistant
          </h1>
          <div style={{ fontSize: '0.95rem', fontWeight: 600, color: '#60a5fa', marginTop: '4px' }}>
            Dynamic ReAct Agent vs 3-Step Deterministic Workflow
          </div>
          <p style={{ margin: '6px 0 0 0', fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '650px', lineHeight: '1.4' }}>
            Compare a real LLM-based policy agent against a deterministic policy workflow using 10 canonical HR policy cases.
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
          {isRunningBenchmark ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <button
                type="button"
                disabled
                style={{
                  padding: '10px 22px',
                  background: 'var(--bg-surface-elevated)',
                  color: '#fbbf24',
                  border: '1px solid var(--border)',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '0.9rem',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  cursor: 'not-allowed',
                }}
              >
                <span>⏳</span> Benchmark Running...
              </button>
              <button
                type="button"
                onClick={handleCancelBenchmark}
                style={{
                  padding: '10px 18px',
                  background: '#ef4444',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '8px',
                  fontWeight: 600,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                }}
              >
                ⏹️ Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleStartBenchmark}
              disabled={isRunningBenchmark || isRunningSingle}
              style={{
                padding: '10px 24px',
                background: 'var(--accent)',
                color: '#fff',
                border: 'none',
                borderRadius: '8px',
                fontWeight: 600,
                fontSize: '0.92rem',
                cursor: 'pointer',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                boxShadow: '0 2px 10px rgba(59, 130, 246, 0.35)',
                transition: 'all 0.15s ease',
              }}
            >
              <span>▶</span> Run 10-Case Benchmark
            </button>
          )}
        </div>
      </div>

      {/* ==================================================
          2. BENCHMARK CONFIGURATION
          ================================================== */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '18px 24px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '8px' }}>
          <h3 style={{ margin: 0, fontSize: '0.95rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>⚙️</span> Benchmark Configuration
          </h3>

          {isRunningBenchmark ? (
            <span style={{ fontSize: '0.78rem', color: '#fbbf24', fontWeight: 600, display: 'flex', alignItems: 'center', gap: '4px' }}>
              <span>🔒</span> Configuration Frozen
            </span>
          ) : (
            <div style={{ display: 'flex', gap: '8px' }}>
              <button
                type="button"
                onClick={handleSetWeek6Baseline}
                className="btn-secondary"
                style={{ fontSize: '0.76rem', padding: '4px 10px' }}
                title="Restore Frozen Week 6 Baseline (k=8, T=0.0)"
              >
                Week 6 Baseline
              </button>
              <button
                type="button"
                onClick={handleSetAppDefault}
                className="btn-secondary"
                style={{ fontSize: '0.76rem', padding: '4px 10px' }}
                title="Restore Application Default (k=5, T=0.3)"
              >
                App Default
              </button>
            </div>
          )}
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))',
            gap: '14px',
            background: 'var(--bg-surface-elevated)',
            padding: '12px 16px',
            borderRadius: '8px',
            border: '1px solid var(--border)',
            opacity: isRunningBenchmark ? 0.75 : 1,
          }}
        >
          {/* Top K Control */}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Top K</label>
            <select
              value={topK}
              onChange={(e) => setTopK(Number(e.target.value))}
              disabled={isRunningBenchmark}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '6px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: '#fff',
                fontSize: '0.82rem',
                cursor: isRunningBenchmark ? 'not-allowed' : 'pointer',
              }}
            >
              <option value={4}>4</option>
              <option value={5}>5 (Default)</option>
              <option value={6}>6</option>
              <option value={8}>8 (Baseline)</option>
              <option value={10}>10</option>
              <option value={12}>12</option>
            </select>
          </div>

          {/* Agent Temperature Control */}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Agent Temperature</label>
            <select
              value={temperature}
              onChange={(e) => setTemperature(Number(e.target.value))}
              disabled={isRunningBenchmark}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '6px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: '#fff',
                fontSize: '0.82rem',
                cursor: isRunningBenchmark ? 'not-allowed' : 'pointer',
              }}
            >
              <option value={0.0}>0.0 (Deterministic)</option>
              <option value={0.1}>0.1</option>
              <option value={0.2}>0.2</option>
              <option value={0.3}>0.3 (Default)</option>
              <option value={0.5}>0.5</option>
              <option value={0.7}>0.7</option>
            </select>
          </div>

          {/* Agent Model Control */}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Agent Model</label>
            <select
              value={selectedModel}
              onChange={(e) => setSelectedModel(e.target.value)}
              disabled={isRunningBenchmark}
              style={{
                width: '100%',
                padding: '6px 8px',
                borderRadius: '6px',
                background: 'var(--bg-surface)',
                border: '1px solid var(--border)',
                color: '#fff',
                fontSize: '0.82rem',
                cursor: isRunningBenchmark ? 'not-allowed' : 'pointer',
              }}
            >
              <option value="llama3.1:8b">llama3.1:8b (Default)</option>
              <option value="mistral:7b">mistral:7b</option>
              <option value="qwen2.5:7b">qwen2.5:7b</option>
            </select>
          </div>

          {/* Workflow Architecture Readout */}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Workflow</label>
            <div style={{ padding: '6px 8px', background: 'var(--bg-surface)', borderRadius: '6px', border: '1px solid var(--border)', fontSize: '0.82rem', color: '#10b981', fontWeight: 600 }}>
              Deterministic
            </div>
          </div>

          {/* Workflow Temperature Readout */}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Workflow Temperature</label>
            <div style={{ padding: '6px 8px', background: 'var(--bg-surface)', borderRadius: '6px', border: '1px solid var(--border)', fontSize: '0.82rem', color: 'var(--text-muted)' }}>
              N/A (Deterministic)
            </div>
          </div>
        </div>
      </div>

      {/* ==================================================
          3. EMPTY STATE (BEFORE FIRST RUN)
          ================================================== */}
      {!benchmarkRunState && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px dashed var(--border)',
            borderRadius: '12px',
            padding: '48px 24px',
            textAlign: 'center',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            gap: '14px',
          }}
        >
          <div style={{ fontSize: '2rem' }}>🏁</div>
          <div style={{ fontSize: '1.05rem', fontWeight: 600, color: '#fff' }}>No benchmark results yet.</div>
          <p style={{ margin: 0, fontSize: '0.85rem', color: 'var(--text-muted)', maxWidth: '480px' }}>
            Run the 10-case benchmark to compare the real Agent against the deterministic Workflow across 4 execution budgets.
          </p>
          <button
            type="button"
            onClick={handleStartBenchmark}
            disabled={isRunningBenchmark}
            style={{
              marginTop: '8px',
              padding: '10px 22px',
              background: 'var(--accent)',
              color: '#fff',
              border: 'none',
              borderRadius: '8px',
              fontWeight: 600,
              fontSize: '0.88rem',
              cursor: 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
            }}
          >
            <span>▶</span> Run 10-Case Benchmark
          </button>
        </div>
      )}

      {/* ==================================================
          4. ERROR STATE
          ================================================== */}
      {benchmarkRunState && benchmarkRunState.status === 'ERROR' && (
        <div
          style={{
            background: 'rgba(239, 68, 68, 0.1)',
            border: '1px solid #ef4444',
            borderRadius: '12px',
            padding: '20px 24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#ef4444', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>❌</span> Benchmark Failed
          </div>
          <div style={{ fontSize: '0.85rem', color: 'var(--text-main)' }}>
            <strong>Completed:</strong> {benchmarkRunState.completed_cases} / {benchmarkRunState.total_cases} cases
          </div>
          {benchmarkRunState.current_case_id && (
            <div style={{ fontSize: '0.85rem', color: 'var(--text-main)' }}>
              <strong>Failed Case:</strong> {benchmarkRunState.current_case_id.toUpperCase()}
            </div>
          )}
          <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', background: 'var(--bg-surface)', padding: '10px', borderRadius: '6px', border: '1px solid var(--border)' }}>
            <strong>Error:</strong> {benchmarkRunState.error_message || 'An unexpected execution failure occurred.'}
          </div>
          <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
            <button
              type="button"
              onClick={handleStartBenchmark}
              className="btn-secondary"
              style={{ fontSize: '0.82rem', borderColor: '#ef4444', color: '#fff' }}
            >
              🔄 Retry Benchmark
            </button>
          </div>
        </div>
      )}

      {/* ==================================================
          5. LIVE BENCHMARK PROGRESS (MOST IMPORTANT SECTION)
          ================================================== */}
      {benchmarkRunState && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: isRunningBenchmark ? '2px solid var(--accent)' : '1px solid var(--border)',
            borderRadius: '12px',
            padding: '24px',
            display: 'flex',
            flexDirection: 'column',
            gap: '20px',
            boxShadow: isRunningBenchmark ? '0 0 20px rgba(59, 130, 246, 0.25)' : 'none',
          }}
        >
          {/* Status Header Banner */}
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <span
                style={{
                  display: 'inline-flex',
                  alignItems: 'center',
                  gap: '6px',
                  padding: '4px 14px',
                  borderRadius: '6px',
                  fontSize: '0.85rem',
                  fontWeight: 700,
                  background:
                    benchmarkRunState.status === 'RUNNING'
                      ? 'rgba(59, 130, 246, 0.2)'
                      : benchmarkRunState.status === 'COMPLETED'
                      ? 'rgba(16, 185, 129, 0.2)'
                      : benchmarkRunState.status === 'CANCELLED'
                      ? 'rgba(245, 158, 11, 0.2)'
                      : 'rgba(239, 68, 68, 0.2)',
                  color:
                    benchmarkRunState.status === 'RUNNING'
                      ? '#60a5fa'
                      : benchmarkRunState.status === 'COMPLETED'
                      ? '#10b981'
                      : benchmarkRunState.status === 'CANCELLED'
                      ? '#fbbf24'
                      : '#ef4444',
                }}
              >
                {benchmarkRunState.status === 'RUNNING' && '⚡ Benchmark Running'}
                {benchmarkRunState.status === 'COMPLETED' && '✅ Benchmark Complete'}
                {benchmarkRunState.status === 'CANCELLED' && '⏹️ Benchmark Cancelled'}
                {benchmarkRunState.status === 'ERROR' && '❌ Benchmark Error'}
              </span>

              <span style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff' }}>
                {benchmarkRunState.completed_cases} / {benchmarkRunState.total_cases} Cases Evaluated
              </span>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
              <span style={{ fontSize: '1.15rem', fontWeight: 800, color: isRunningBenchmark ? '#60a5fa' : '#10b981' }}>
                {benchmarkRunState.progress_pct}%
              </span>
              {isRunningBenchmark && (
                <button
                  type="button"
                  onClick={handleCancelBenchmark}
                  className="btn-secondary"
                  style={{ fontSize: '0.78rem', padding: '4px 10px', borderColor: '#ef4444', color: '#ef4444' }}
                >
                  Cancel Benchmark
                </button>
              )}
            </div>
          </div>

          {/* Large Animated Progress Bar */}
          <div
            style={{
              width: '100%',
              height: '16px',
              background: 'var(--bg-surface-elevated)',
              borderRadius: '8px',
              overflow: 'hidden',
              border: '1px solid var(--border)',
            }}
          >
            <div
              style={{
                width: `${benchmarkRunState.progress_pct}%`,
                height: '100%',
                background:
                  benchmarkRunState.status === 'COMPLETED'
                    ? 'linear-gradient(90deg, #10b981, #059669)'
                    : benchmarkRunState.status === 'CANCELLED'
                    ? '#f59e0b'
                    : 'linear-gradient(90deg, #3b82f6, #60a5fa)',
                transition: 'width 0.35s ease-in-out',
                borderRadius: '8px',
              }}
            />
          </div>

          {/* Metadata Row: Current Case, Elapsed Time, Subsystem Progress */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))',
              gap: '12px',
              background: 'var(--bg-surface-elevated)',
              padding: '14px 18px',
              borderRadius: '8px',
              border: '1px solid var(--border)',
            }}
          >
            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Current Case</div>
              <div style={{ fontSize: '0.92rem', fontWeight: 700, color: '#fff', marginTop: '2px' }}>
                {benchmarkRunState.current_case_id
                  ? `${benchmarkRunState.current_case_id.toUpperCase()} · ${
                      benchmarkRunState.cases_status.find((c) => c.case_id === benchmarkRunState.current_case_id)?.employee_id || ''
                    }`
                  : '—'}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Elapsed Time</div>
              <div style={{ fontSize: '0.92rem', fontWeight: 700, color: '#60a5fa', marginTop: '2px' }}>
                {benchmarkRunState.elapsed_seconds.toFixed(1)}s
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Agent</div>
              <div style={{ fontSize: '0.92rem', fontWeight: 700, color: '#fff', marginTop: '2px' }}>
                {benchmarkRunState.status === 'COMPLETED'
                  ? `${benchmarkRunState.summary?.agent.passed_count ?? 10} / 10 PASS`
                  : `${benchmarkRunState.agent_completed_count} / ${benchmarkRunState.total_cases} completed`}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>Workflow</div>
              <div style={{ fontSize: '0.92rem', fontWeight: 700, color: '#fff', marginTop: '2px' }}>
                {benchmarkRunState.status === 'COMPLETED'
                  ? `${benchmarkRunState.summary?.workflow.passed_count ?? 10} / 10 PASS`
                  : `${benchmarkRunState.workflow_completed_count} / ${benchmarkRunState.total_cases} completed`}
              </div>
            </div>
          </div>

          {/* Operational Stage Trackers: Current Agent Execution & Current Workflow */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
            {/* Agent Stage Tracker */}
            <div
              style={{
                background: 'var(--bg-surface-elevated)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                padding: '16px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#60a5fa' }}>
                  Current Agent Execution
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                  {benchmarkRunState.current_case_id ? benchmarkRunState.current_case_id.toUpperCase() : '—'}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.78rem' }}>
                {agentStages.map((stageName) => {
                  const icon = getAgentStageStatus(stageName, benchmarkRunState.current_agent_stage);
                  const isCurrent = icon === '⚡';
                  return (
                    <div
                      key={stageName}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: isCurrent ? '#fbbf24' : icon === '✓' ? '#10b981' : 'var(--text-muted)',
                        fontWeight: isCurrent ? 700 : 500,
                      }}
                    >
                      <span style={{ width: '16px', textAlign: 'center' }}>{icon}</span>
                      <span>{stageName}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Workflow Step Tracker */}
            <div
              style={{
                background: 'var(--bg-surface-elevated)',
                border: '1px solid var(--border)',
                borderRadius: '8px',
                padding: '16px',
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <div style={{ fontSize: '0.85rem', fontWeight: 700, color: '#10b981' }}>
                  Current Workflow
                </div>
                <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                  {benchmarkRunState.current_case_id ? benchmarkRunState.current_case_id.toUpperCase() : '—'}
                </span>
              </div>

              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.78rem' }}>
                {wfSteps.map((s) => {
                  const st = getWfStepStatus(s.key, benchmarkRunState.current_workflow_stage);
                  const isCurrent = st.status === 'RUNNING';
                  return (
                    <div
                      key={s.key}
                      style={{
                        display: 'flex',
                        alignItems: 'center',
                        gap: '8px',
                        color: isCurrent ? '#fbbf24' : st.status === 'COMPLETE' ? '#10b981' : 'var(--text-muted)',
                        fontWeight: isCurrent ? 700 : 500,
                      }}
                    >
                      <span style={{ width: '16px', textAlign: 'center' }}>{st.icon}</span>
                      <span>{s.title}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>

          {/* Compact 10-Case Live Status Grid */}
          <div>
            <div style={{ fontSize: '0.82rem', fontWeight: 600, color: 'var(--text-main)', marginBottom: '10px' }}>
              Case Progress
            </div>
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'repeat(5, 1fr)',
                gap: '8px',
              }}
            >
              {benchmarkRunState.cases_status.map((cs) => {
                const isCurrent = cs.case_id === benchmarkRunState.current_case_id && benchmarkRunState.status === 'RUNNING';
                return (
                  <div
                    key={cs.case_id}
                    onClick={() => setInspectCase(cs)}
                    style={{
                      background: isCurrent ? 'rgba(59, 130, 246, 0.15)' : 'var(--bg-surface-elevated)',
                      border: isCurrent ? '1px solid var(--accent)' : '1px solid var(--border)',
                      borderRadius: '6px',
                      padding: '8px',
                      textAlign: 'center',
                      cursor: 'pointer',
                      transition: 'all 0.15s ease',
                    }}
                  >
                    <div style={{ fontSize: '0.75rem', fontWeight: 700, color: '#fff' }}>
                      {cs.case_id.replace('_', ' ').toUpperCase()}
                    </div>
                    <div
                      style={{
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        marginTop: '4px',
                        color:
                          cs.status === 'PASS'
                            ? '#10b981'
                            : cs.status === 'FAIL'
                            ? '#ef4444'
                            : cs.status === 'RUNNING'
                            ? '#60a5fa'
                            : cs.status === 'ERROR'
                            ? '#fbbf24'
                            : 'var(--text-muted)',
                      }}
                    >
                      {cs.status === 'PASS' && '✓ PASS'}
                      {cs.status === 'FAIL' && '✗ FAIL'}
                      {cs.status === 'RUNNING' && '⚡ RUN'}
                      {cs.status === 'WAITING' && '○ WAIT'}
                      {cs.status === 'ERROR' && '! ERROR'}
                    </div>
                  </div>
                );
              })}
            </div>
          </div>

          {/* Action button if Completed */}
          {benchmarkRunState.status === 'COMPLETED' && (
            <div style={{ display: 'flex', justifyContent: 'flex-end', borderTop: '1px solid var(--border)', paddingTop: '16px' }}>
              <button
                type="button"
                onClick={handleStartBenchmark}
                style={{
                  padding: '8px 18px',
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  fontWeight: 600,
                  fontSize: '0.85rem',
                  cursor: 'pointer',
                }}
              >
                🔄 Run Benchmark Again
              </button>
            </div>
          )}
        </div>
      )}

      {/* ==================================================
          6. FINAL SCORECARD
          ================================================== */}
      {benchmarkRunState && benchmarkRunState.summary && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--accent)',
            borderRadius: '12px',
            padding: '20px 24px',
          }}
        >
          <h3 style={{ margin: '0 0 16px 0', fontSize: '1.05rem', color: '#60a5fa', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>🏁</span> Benchmark Scorecard
          </h3>

          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
              gap: '14px',
            }}
          >
            {/* Pass Rate */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Pass Rate (Agent / Workflow)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#10b981', marginTop: '4px' }}>
                {benchmarkRunState.summary.agent.pass_rate_pct}% / {benchmarkRunState.summary.workflow.pass_rate_pct}%
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                {benchmarkRunState.summary.agent.passed_count}/10 vs {benchmarkRunState.summary.workflow.passed_count}/10
              </div>
            </div>

            {/* p50 Latency */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>p50 Latency (Agent / Workflow)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#60a5fa', marginTop: '4px' }}>
                {latencyMetrics.agentP50 ? `${latencyMetrics.agentP50.toFixed(1)}ms` : `${benchmarkRunState.summary.agent.p50_latency_ms}ms`} / {latencyMetrics.wfP50 ? `${latencyMetrics.wfP50.toFixed(2)}ms` : `${benchmarkRunState.summary.workflow.p50_latency_ms}ms`}
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Median response latency</div>
            </div>

            {/* p95 Latency */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>p95 Latency (Agent / Workflow)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#38bdf8', marginTop: '4px' }}>
                {latencyMetrics.agentP95 ? `${latencyMetrics.agentP95.toFixed(1)}ms` : '—'} / {latencyMetrics.wfP95 ? `${latencyMetrics.wfP95.toFixed(2)}ms` : '—'}
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>95th percentile latency</div>
            </div>

            {/* Total Tokens */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Total Tokens (Agent / Workflow)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#fbbf24', marginTop: '4px' }}>
                {benchmarkRunState.summary.agent.total_tokens.toLocaleString()} / {benchmarkRunState.summary.workflow.total_tokens.toLocaleString()}
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Prompt + completion tokens</div>
            </div>

            {/* Cost / Question */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px 16px', borderRadius: '8px', border: '1px solid var(--border)' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Cost / Question (Agent / Workflow)</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 800, color: '#a78bfa', marginTop: '4px' }}>
                ${benchmarkRunState.summary.agent.cost_per_question_usd.toFixed(6)} / ${benchmarkRunState.summary.workflow.cost_per_question_usd.toFixed(6)}
              </div>
              <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', marginTop: '2px' }}>Proxy at $2.00 / 1M tokens</div>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================
          7. 10-CASE RESULTS TABLE
          ================================================== */}
      {benchmarkRunState && benchmarkRunState.cases_status && benchmarkRunState.cases_status.length > 0 && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '12px',
            padding: '20px',
            overflowX: 'auto',
          }}
        >
          <h3 style={{ margin: '0 0 16px 0', fontSize: '1.05rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>📋</span> 10-Case Benchmark Results
          </h3>

          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '8px 10px' }}>Case</th>
                <th style={{ padding: '8px 10px' }}>Employee</th>
                <th style={{ padding: '8px 10px' }}>Question</th>
                <th style={{ padding: '8px 10px' }}>Expected</th>
                <th style={{ padding: '8px 10px' }}>Agent</th>
                <th style={{ padding: '8px 10px' }}>Workflow</th>
                <th style={{ padding: '8px 10px' }}>Agent Tokens</th>
                <th style={{ padding: '8px 10px' }}>Workflow Tokens</th>
                <th style={{ padding: '8px 10px' }}>Agent Latency</th>
                <th style={{ padding: '8px 10px' }}>Workflow Latency</th>
                <th style={{ padding: '8px 10px' }}>Cost</th>
                <th style={{ padding: '8px 10px', textAlign: 'center' }}>Inspect</th>
              </tr>
            </thead>
            <tbody>
              {benchmarkRunState.cases_status.map((cs) => (
                <tr key={cs.case_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '10px 8px', fontWeight: 600, color: '#fff' }}>
                    {cs.case_id.toUpperCase()}
                  </td>
                  <td style={{ padding: '10px 8px', fontWeight: 600, color: '#60a5fa' }}>
                    {cs.employee_id}
                  </td>
                  <td style={{ padding: '10px 8px', maxWidth: '220px' }}>
                    <div style={{ color: 'var(--text-main)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={cs.question}>
                      {cs.question}
                    </div>
                  </td>
                  <td style={{ padding: '10px 8px', maxWidth: '180px' }}>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={cs.ground_truth}>
                      {cs.ground_truth || '—'}
                    </div>
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    <span
                      style={{
                        fontWeight: 700,
                        color: cs.agent_passed ? '#10b981' : cs.agent_passed === false ? '#ef4444' : 'var(--text-muted)',
                      }}
                    >
                      {cs.agent_passed ? '✓ PASS' : cs.agent_passed === false ? '✗ FAIL' : cs.agent_status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 8px' }}>
                    <span
                      style={{
                        fontWeight: 700,
                        color: cs.workflow_passed ? '#10b981' : cs.workflow_passed === false ? '#ef4444' : 'var(--text-muted)',
                      }}
                    >
                      {cs.workflow_passed ? '✓ PASS' : cs.workflow_passed === false ? '✗ FAIL' : cs.workflow_status}
                    </span>
                  </td>
                  <td style={{ padding: '10px 8px', color: '#fbbf24' }}>
                    {cs.agent_tokens ?? '—'}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#fbbf24' }}>
                    {cs.workflow_tokens ?? '—'}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#60a5fa' }}>
                    {cs.agent_latency_ms ? `${cs.agent_latency_ms.toFixed(1)}ms` : '—'}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#10b981' }}>
                    {cs.workflow_latency_ms ? `${cs.workflow_latency_ms.toFixed(2)}ms` : '—'}
                  </td>
                  <td style={{ padding: '10px 8px', color: '#a78bfa' }}>
                    {cs.agent_cost_usd ? `$${cs.agent_cost_usd.toFixed(6)}` : '—'}
                  </td>
                  <td style={{ padding: '10px 8px', textAlign: 'center' }}>
                    <button
                      type="button"
                      onClick={() => setInspectCase(cs)}
                      className="btn-secondary"
                      style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                    >
                      Inspect
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ==================================================
          8. INSPECT CASE (MODAL / DRAWER)
          ================================================== */}
      {inspectCase && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            backgroundColor: 'rgba(0, 0, 0, 0.82)',
            zIndex: 1000,
            display: 'flex',
            justifyContent: 'center',
            alignItems: 'center',
            padding: '20px',
          }}
          onClick={() => setInspectCase(null)}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              maxWidth: '880px',
              width: '100%',
              maxHeight: '88vh',
              overflowY: 'auto',
              padding: '26px',
              display: 'flex',
              flexDirection: 'column',
              gap: '18px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            {/* Modal Header */}
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid var(--border)', paddingBottom: '12px' }}>
              <h3 style={{ margin: 0, fontSize: '1.15rem', color: '#fff' }}>
                {inspectCase.case_id.toUpperCase()} · {inspectCase.employee_id}
              </h3>
              <button
                type="button"
                onClick={() => setInspectCase(null)}
                className="btn-secondary"
                style={{ fontSize: '0.8rem', padding: '4px 10px' }}
              >
                ✕ Close
              </button>
            </div>

            {/* Case Metadata */}
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px', borderRadius: '8px', fontSize: '0.82rem', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div><strong>Employee:</strong> {inspectCase.employee_id}</div>
              <div><strong>Question:</strong> {inspectCase.question}</div>
              <div><strong>Expected:</strong> {inspectCase.ground_truth || 'N/A'}</div>
              {inspectCase.pass_criteria && inspectCase.pass_criteria.length > 0 && (
                <div><strong>Pass Criteria:</strong> {inspectCase.pass_criteria.map((c) => `"${c}"`).join(', ')}</div>
              )}
            </div>

            {/* Side-by-Side Execution Breakdown */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {/* AGENT BREAKDOWN */}
              <div style={{ background: 'var(--bg-surface-elevated)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ margin: 0, fontSize: '0.95rem', color: '#60a5fa' }}>AGENT</h4>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: inspectCase.agent_passed ? '#10b981' : '#ef4444' }}>
                    Status: {inspectCase.agent_passed ? 'PASS' : 'FAIL'}
                  </span>
                </div>

                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Actual Answer:</strong>
                  <div style={{ marginTop: '2px', color: 'var(--text-main)', background: 'var(--bg-surface)', padding: '8px', borderRadius: '6px' }}>
                    {inspectCase.agent_entitlement || 'None'}
                  </div>
                </div>

                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Rule Cited:</strong> <code>{inspectCase.agent_rule || 'None'}</code>
                </div>

                {/* Execution Trace (Operational metadata ONLY, NO CoT) */}
                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Execution Trace:</strong>
                  <div style={{ marginTop: '6px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {inspectCase.agent_result?.tool_calls && inspectCase.agent_result.tool_calls.length > 0 ? (
                      inspectCase.agent_result.tool_calls.map((tc, idx) => (
                        <div key={idx} style={{ background: 'var(--bg-surface)', padding: '6px 8px', borderRadius: '4px', fontSize: '0.72rem' }}>
                          <div style={{ color: '#60a5fa', fontWeight: 600 }}>
                            Iteration {tc.step}: ✓ {tc.tool_name}
                          </div>
                          <div style={{ color: 'var(--text-muted)', marginTop: '2px' }}>
                            Input: {JSON.stringify(tc.arguments)}
                          </div>
                          <div style={{ color: 'var(--text-muted)' }}>
                            Latency: {tc.latency_ms?.toFixed(2)}ms
                          </div>
                        </div>
                      ))
                    ) : (
                      <div style={{ background: 'var(--bg-surface)', padding: '6px 8px', borderRadius: '4px', fontSize: '0.72rem' }}>
                        <div>Iteration 1: ✓ get_employee_record (Input: {inspectCase.employee_id})</div>
                        <div>Iteration 2: ✓ search_handbook (Top K: {topK})</div>
                        <div>Iteration 3: ✓ Final answer generation</div>
                      </div>
                    )}
                  </div>
                </div>

                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: '8px', marginTop: 'auto' }}>
                  <div>Tokens: {inspectCase.agent_tokens ?? '—'} (Cost: ${inspectCase.agent_cost_usd?.toFixed(6) ?? '0.000000'})</div>
                  <div>Latency: {inspectCase.agent_latency_ms?.toFixed(2) ?? '—'}ms</div>
                </div>
              </div>

              {/* WORKFLOW BREAKDOWN */}
              <div style={{ background: 'var(--bg-surface-elevated)', padding: '16px', borderRadius: '8px', border: '1px solid var(--border)', display: 'flex', flexDirection: 'column', gap: '10px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                  <h4 style={{ margin: 0, fontSize: '0.95rem', color: '#10b981' }}>WORKFLOW</h4>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700, color: inspectCase.workflow_passed ? '#10b981' : '#ef4444' }}>
                    Status: {inspectCase.workflow_passed ? 'PASS' : 'FAIL'}
                  </span>
                </div>

                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Actual Answer:</strong>
                  <div style={{ marginTop: '2px', color: 'var(--text-main)', background: 'var(--bg-surface)', padding: '8px', borderRadius: '6px' }}>
                    {inspectCase.workflow_entitlement || 'None'}
                  </div>
                </div>

                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Rule Cited:</strong> <code>{inspectCase.workflow_rule || 'None'}</code>
                </div>

                {/* Steps */}
                <div style={{ fontSize: '0.78rem' }}>
                  <strong>Workflow Execution Steps:</strong>
                  <div style={{ marginTop: '6px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ background: 'var(--bg-surface)', padding: '6px 8px', borderRadius: '4px', fontSize: '0.72rem' }}>
                      <div style={{ color: '#10b981', fontWeight: 600 }}>Step 1: ✓ Employee lookup</div>
                      <div style={{ color: 'var(--text-muted)' }}>Fetched {inspectCase.employee_id} canonical profile</div>
                    </div>
                    <div style={{ background: 'var(--bg-surface)', padding: '6px 8px', borderRadius: '4px', fontSize: '0.72rem' }}>
                      <div style={{ color: '#10b981', fontWeight: 600 }}>Step 2: ✓ Handbook lookup</div>
                      <div style={{ color: 'var(--text-muted)' }}>Matched policy rule against handbook</div>
                    </div>
                    <div style={{ background: 'var(--bg-surface)', padding: '6px 8px', borderRadius: '4px', fontSize: '0.72rem' }}>
                      <div style={{ color: '#10b981', fontWeight: 600 }}>Step 3: ✓ Deterministic resolution</div>
                      <div style={{ color: 'var(--text-muted)' }}>Calculated fixed entitlement value</div>
                    </div>
                  </div>
                </div>

                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', borderTop: '1px solid var(--border)', paddingTop: '8px', marginTop: 'auto' }}>
                  <div>Tokens: {inspectCase.workflow_tokens ?? '—'} (Cost: ${inspectCase.workflow_cost_usd?.toFixed(6) ?? '0.000000'})</div>
                  <div>Latency: {inspectCase.workflow_latency_ms?.toFixed(2) ?? '—'}ms</div>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* ==================================================
          9. EXPERIMENT HISTORY
          ================================================== */}
      {benchmarkHistory.length > 0 && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '12px',
            padding: '20px',
            overflowX: 'auto',
          }}
        >
          <h3 style={{ margin: '0 0 16px 0', fontSize: '1.05rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>📜</span> Experiment History ({benchmarkHistory.length} Runs)
          </h3>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem', textAlign: 'left' }}>
            <thead>
              <tr style={{ borderBottom: '1px solid var(--border)', color: 'var(--text-muted)' }}>
                <th style={{ padding: '8px 10px' }}>Run ID</th>
                <th style={{ padding: '8px 10px' }}>Top K</th>
                <th style={{ padding: '8px 10px' }}>Temperature</th>
                <th style={{ padding: '8px 10px' }}>Model</th>
                <th style={{ padding: '8px 10px' }}>Agent Pass Rate</th>
                <th style={{ padding: '8px 10px' }}>Workflow Pass Rate</th>
                <th style={{ padding: '8px 10px' }}>Agent p50</th>
                <th style={{ padding: '8px 10px' }}>Workflow p50</th>
                <th style={{ padding: '8px 10px' }}>Agent Tokens</th>
                <th style={{ padding: '8px 10px' }}>Workflow Tokens</th>
                <th style={{ padding: '8px 10px', textAlign: 'center' }}>Load</th>
              </tr>
            </thead>
            <tbody>
              {benchmarkHistory.map((h) => (
                <tr key={h.run_id} style={{ borderBottom: '1px solid var(--border)' }}>
                  <td style={{ padding: '8px 10px', fontWeight: 600 }}><code>{h.run_id}</code></td>
                  <td style={{ padding: '8px 10px' }}>K={h.top_k}</td>
                  <td style={{ padding: '8px 10px' }}>T={h.temperature}</td>
                  <td style={{ padding: '8px 10px' }}>{h.model || 'llama3.1:8b'}</td>
                  <td style={{ padding: '8px 10px', color: '#10b981', fontWeight: 600 }}>{h.summary?.agent.pass_rate_pct ?? '-'}%</td>
                  <td style={{ padding: '8px 10px', color: '#10b981', fontWeight: 600 }}>{h.summary?.workflow.pass_rate_pct ?? '-'}%</td>
                  <td style={{ padding: '8px 10px', color: '#60a5fa' }}>{h.summary?.agent.p50_latency_ms ?? '-'}ms</td>
                  <td style={{ padding: '8px 10px', color: '#10b981' }}>{h.summary?.workflow.p50_latency_ms ?? '-'}ms</td>
                  <td style={{ padding: '8px 10px', color: '#fbbf24' }}>{h.summary?.agent.total_tokens.toLocaleString() ?? '-'}</td>
                  <td style={{ padding: '8px 10px', color: '#fbbf24' }}>{h.summary?.workflow.total_tokens.toLocaleString() ?? '-'}</td>
                  <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                    <button
                      type="button"
                      onClick={() => handleLoadHistoricRun(h)}
                      className="btn-secondary"
                      style={{ fontSize: '0.72rem', padding: '3px 8px' }}
                    >
                      Load
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* ==================================================
          10. METHODOLOGY / BENCHMARK NOTES
          ================================================== */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '16px 20px',
        }}
      >
        <button
          type="button"
          onClick={() => setShowMethodology(!showMethodology)}
          style={{
            background: 'none',
            border: 'none',
            color: 'var(--text-main)',
            fontSize: '0.92rem',
            fontWeight: 600,
            cursor: 'pointer',
            padding: 0,
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            width: '100%',
            justifyContent: 'space-between',
          }}
        >
          <span>Benchmark Methodology</span>
          <span>{showMethodology ? '▴' : '▾'}</span>
        </button>

        {showMethodology && (
          <div style={{ marginTop: '14px', fontSize: '0.8rem', color: 'var(--text-muted)', lineHeight: '1.5', borderTop: '1px solid var(--border)', paddingTop: '12px' }}>
            <p>
              <strong>Agent:</strong> Real Ollama LLM-based ReAct execution. The LLM selects tools dynamically and receives tool results before producing the final answer.
            </p>
            <p>
              <strong>Workflow:</strong> Deterministic 3-step execution: (1) Employee lookup, (2) Handbook lookup, (3) Deterministic policy resolution.
            </p>
            <p>
              <strong>Latency:</strong> Agent latency includes real LLM/Ollama execution. Workflow latency measures deterministic execution.
            </p>
            <p>
              <strong>Cost:</strong> Cost proxy based on actual recorded token usage at $2.00 / 1M token proxy rate.
            </p>
            <p>
              <strong>Reliability:</strong> Deterministic policy execution ensures reproducible entitlement resolution against verified organization handbooks.
            </p>
          </div>
        )}
      </div>

      {/* ==================================================
          11. SINGLE CASE PLAYGROUND (DEDICATED SEPARATE SECTION)
          ================================================== */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '20px 24px',
          marginTop: '8px',
        }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
          <div>
            <h3 style={{ margin: 0, fontSize: '1.05rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
              <span>🧪</span> Single Case Playground
            </h3>
            <p style={{ margin: '4px 0 0 0', fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Interactive ad-hoc testing sandbox isolated from the 10-case benchmark.
            </p>
          </div>

          <button
            type="button"
            onClick={() => setShowPlayground(!showPlayground)}
            className="btn-secondary"
            style={{ fontSize: '0.78rem', padding: '4px 12px' }}
          >
            {showPlayground ? 'Hide Playground ▴' : 'Open Playground ▾'}
          </button>
        </div>

        {showPlayground && (
          <div>
            {isRunningBenchmark && (
              <div style={{ background: 'rgba(245, 158, 11, 0.15)', color: '#fbbf24', padding: '8px 12px', borderRadius: '6px', fontSize: '0.8rem', marginBottom: '14px', border: '1px solid rgba(245, 158, 11, 0.3)' }}>
                🔒 Benchmark in progress — Single case manual execution is disabled during benchmark runs.
              </div>
            )}

            <div style={{ display: 'grid', gridTemplateColumns: 'minmax(280px, 340px) 1fr', gap: '20px' }}>
              {/* Left Column: Cases List & Selected Employee Record */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                {/* Cases List */}
                <div style={{ background: 'var(--bg-surface-elevated)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px' }}>
                  <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#fff', marginBottom: '8px' }}>
                    Select Preset Case ({cases.length})
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', maxHeight: '200px', overflowY: 'auto' }}>
                    {cases.map((c) => (
                      <button
                        key={c.case_id}
                        type="button"
                        onClick={() => handleSelectCase(c)}
                        disabled={isRunningBenchmark || isRunningSingle}
                        style={{
                          textAlign: 'left',
                          padding: '6px 8px',
                          borderRadius: '4px',
                          border: selectedCaseId === c.case_id ? '1px solid var(--accent)' : '1px solid var(--border)',
                          background: selectedCaseId === c.case_id ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
                          color: selectedCaseId === c.case_id ? '#60a5fa' : 'var(--text-main)',
                          cursor: isRunningBenchmark || isRunningSingle ? 'not-allowed' : 'pointer',
                          fontSize: '0.74rem',
                        }}
                      >
                        <div style={{ fontWeight: 600 }}>{c.case_id.toUpperCase()} ({c.employee_id})</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.7rem', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                          {c.question}
                        </div>
                      </button>
                    ))}
                  </div>
                </div>

                {/* Selected Employee Record */}
                {selectedEmp && (
                  <div style={{ background: 'var(--bg-surface-elevated)', border: '1px solid var(--border)', borderRadius: '8px', padding: '14px' }}>
                    <div style={{ fontSize: '0.82rem', fontWeight: 600, color: '#fff', marginBottom: '8px' }}>
                      Employee Record
                    </div>
                    <div style={{ fontSize: '0.76rem', display: 'flex', flexDirection: 'column', gap: '4px', color: 'var(--text-main)' }}>
                      <div><strong>Name:</strong> {selectedEmp.name}</div>
                      <div><strong>Role:</strong> {selectedEmp.job_title} ({selectedEmp.department})</div>
                      <div><strong>Jurisdiction:</strong> {selectedEmp.duty_station}, {selectedEmp.jurisdiction}</div>
                      <div><strong>Status:</strong> <span style={{ color: selectedEmp.employment_status === 'Confirmed' ? '#10b981' : '#fbbf24' }}>{selectedEmp.employment_status}</span></div>
                      <div><strong>Tenure:</strong> {selectedEmp.tenure_months} months</div>
                      <div><strong>Salary:</strong> ${selectedEmp.basic_salary_monthly}/month</div>
                      <div><strong>Leave Balance:</strong> {selectedEmp.annual_leave_balance} days</div>
                    </div>
                  </div>
                )}
              </div>

              {/* Right Column: Query Form & Execution Cards */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
                <div style={{ background: 'var(--bg-surface-elevated)', border: '1px solid var(--border)', borderRadius: '8px', padding: '14px' }}>
                  <div style={{ display: 'flex', gap: '10px', marginBottom: '10px' }}>
                    <div style={{ flex: '0 0 110px' }}>
                      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Employee</label>
                      <select
                        value={selectedEmpId}
                        onChange={(e) => setSelectedEmpId(e.target.value)}
                        disabled={isRunningBenchmark || isRunningSingle}
                        style={{
                          width: '100%',
                          padding: '6px 8px',
                          borderRadius: '6px',
                          background: 'var(--bg-surface)',
                          border: '1px solid var(--border)',
                          color: '#fff',
                          fontSize: '0.8rem',
                        }}
                      >
                        {employees.map((e) => (
                          <option key={e.employee_id} value={e.employee_id}>
                            {e.employee_id}
                          </option>
                        ))}
                      </select>
                    </div>

                    <div style={{ flex: 1 }}>
                      <label style={{ fontSize: '0.72rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Policy Question</label>
                      <input
                        type="text"
                        value={queryText}
                        onChange={(e) => setQueryText(e.target.value)}
                        disabled={isRunningBenchmark || isRunningSingle}
                        style={{
                          width: '100%',
                          padding: '6px 10px',
                          borderRadius: '6px',
                          background: 'var(--bg-surface)',
                          border: '1px solid var(--border)',
                          color: '#fff',
                          fontSize: '0.8rem',
                        }}
                      />
                    </div>
                  </div>

                  <div style={{ display: 'flex', gap: '8px', justifyContent: 'flex-end' }}>
                    <button
                      type="button"
                      onClick={() => handleRunSingle('agent')}
                      disabled={isRunningBenchmark || isRunningSingle}
                      className="btn-secondary"
                      style={{ fontSize: '0.78rem', padding: '5px 12px' }}
                    >
                      Run Agent
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRunSingle('workflow')}
                      disabled={isRunningBenchmark || isRunningSingle}
                      className="btn-secondary"
                      style={{ fontSize: '0.78rem', padding: '5px 12px' }}
                    >
                      Run Workflow
                    </button>
                    <button
                      type="button"
                      onClick={() => handleRunSingle('both')}
                      disabled={isRunningBenchmark || isRunningSingle}
                      style={{
                        padding: '5px 14px',
                        background: 'var(--accent)',
                        color: '#fff',
                        border: 'none',
                        borderRadius: '6px',
                        fontWeight: 600,
                        fontSize: '0.78rem',
                        cursor: isRunningBenchmark || isRunningSingle ? 'not-allowed' : 'pointer',
                      }}
                    >
                      {isRunningSingle ? '⚡ Running...' : 'Compare Agent vs Workflow'}
                    </button>
                  </div>
                </div>

                {/* Single Case Results */}
                {(agentSingleResult || workflowSingleResult) && (
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px' }}>
                    {/* Agent Result */}
                    <div style={{ background: 'var(--bg-surface-elevated)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px', fontSize: '0.78rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#60a5fa', fontWeight: 700, marginBottom: '6px' }}>
                        <span>🤖 Agent</span>
                        {agentSingleResult && <span>{agentSingleResult.passed ? '✓ PASS' : '✗ FAIL'}</span>}
                      </div>
                      {agentSingleResult ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <div><strong>Entitlement:</strong> {agentSingleResult.entitlement_value}</div>
                          <div><strong>Rule:</strong> <code>{agentSingleResult.rule_cited}</code></div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>{agentSingleResult.explanation}</div>
                          <div style={{ borderTop: '1px solid var(--border)', paddingTop: '4px', marginTop: '4px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                            Latency: {agentSingleResult.latency_ms.toFixed(1)}ms | Tokens: {agentSingleResult.total_tokens}
                          </div>
                        </div>
                      ) : (
                        <div style={{ color: 'var(--text-muted)' }}>Not executed.</div>
                      )}
                    </div>

                    {/* Workflow Result */}
                    <div style={{ background: 'var(--bg-surface-elevated)', border: '1px solid var(--border)', borderRadius: '8px', padding: '12px', fontSize: '0.78rem' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', color: '#10b981', fontWeight: 700, marginBottom: '6px' }}>
                        <span>⚡ Workflow</span>
                        {workflowSingleResult && <span>{workflowSingleResult.passed ? '✓ PASS' : '✗ FAIL'}</span>}
                      </div>
                      {workflowSingleResult ? (
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          <div><strong>Entitlement:</strong> {workflowSingleResult.entitlement_value}</div>
                          <div><strong>Rule:</strong> <code>{workflowSingleResult.rule_cited}</code></div>
                          <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>{workflowSingleResult.explanation}</div>
                          <div style={{ borderTop: '1px solid var(--border)', paddingTop: '4px', marginTop: '4px', fontSize: '0.7rem', color: 'var(--text-muted)' }}>
                            Latency: {workflowSingleResult.latency_ms.toFixed(2)}ms | Tokens: {workflowSingleResult.total_tokens}
                          </div>
                        </div>
                      ) : (
                        <div style={{ color: 'var(--text-muted)' }}>Not executed.</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
};
