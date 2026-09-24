// frontend/src/components/Evaluation/PolicyAssistantView.tsx — Interactive HR Policy Assistant View
import React, { useState, useEffect } from 'react';
import { api } from '../../services/api';
import {
  EmployeeRecord,
  BenchmarkCase,
  PolicyOutputContract,
  PolicyBenchmarkResponse,
} from '../../types/policy';

interface PolicyAssistantViewProps {
  onNotify: (msg: string, type?: 'info' | 'success' | 'error') => void;
}

export const PolicyAssistantView: React.FC<PolicyAssistantViewProps> = ({ onNotify }) => {
  const [employees, setEmployees] = useState<EmployeeRecord[]>([]);
  const [cases, setCases] = useState<BenchmarkCase[]>([]);
  const [selectedEmpId, setSelectedEmpId] = useState<string>('EMP001');
  const [queryText, setQueryText] = useState<string>(
    'What is the standard annual leave entitlement and monthly accrual rate for EMP001?'
  );
  const [selectedCaseId, setSelectedCaseId] = useState<string>('case_01');

  const [isRunningSingle, setIsRunningSingle] = useState<boolean>(false);
  const [isRunningBenchmark, setIsRunningBenchmark] = useState<boolean>(false);

  const [agentSingleResult, setAgentSingleResult] = useState<PolicyOutputContract | null>(null);
  const [workflowSingleResult, setWorkflowSingleResult] = useState<PolicyOutputContract | null>(null);
  const [benchmarkData, setBenchmarkData] = useState<PolicyBenchmarkResponse | null>(null);

  useEffect(() => {
    loadInitialData();
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

  const handleSelectCase = (c: BenchmarkCase) => {
    setSelectedCaseId(c.case_id);
    setSelectedEmpId(c.employee_id);
    setQueryText(c.question);
  };

  const handleRunSingle = async (mode: 'both' | 'agent' | 'workflow') => {
    if (!selectedEmpId || !queryText.trim()) {
      onNotify('Please enter employee ID and query', 'error');
      return;
    }

    setIsRunningSingle(true);
    try {
      if (mode === 'both' || mode === 'agent') {
        const aRes = await api.runPolicyAgent({
          employee_id: selectedEmpId,
          question: queryText.trim(),
          case_id: selectedCaseId,
        });
        setAgentSingleResult(aRes);
      }
      if (mode === 'both' || mode === 'workflow') {
        const wRes = await api.runPolicyWorkflow({
          employee_id: selectedEmpId,
          question: queryText.trim(),
          case_id: selectedCaseId,
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

  const handleRunBenchmark = async () => {
    setIsRunningBenchmark(true);
    try {
      const data = await api.runPolicyBenchmark();
      setBenchmarkData(data);
      onNotify('Benchmark run complete across all 10 cases!', 'success');
    } catch (err: any) {
      onNotify('Benchmark failed: ' + err.message, 'error');
    } finally {
      setIsRunningBenchmark(false);
    }
  };

  const selectedEmp = employees.find((e) => e.employee_id === selectedEmpId);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* HEADER CARD */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '10px',
          padding: '20px 24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <h2 style={{ margin: 0, fontSize: '1.25rem', color: '#fff', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <span>👔</span> HR Policy Assistant
          </h2>
          <p style={{ margin: '4px 0 0 0', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
            Dynamic ReAct Agent vs 3-Step Deterministic Workflow comparison with 4 execution budgets.
          </p>
        </div>

        <button
          type="button"
          onClick={handleRunBenchmark}
          disabled={isRunningBenchmark}
          style={{
            padding: '8px 18px',
            background: isRunningBenchmark ? 'var(--bg-tertiary)' : 'var(--accent)',
            color: '#fff',
            border: 'none',
            borderRadius: '6px',
            fontWeight: 600,
            fontSize: '0.85rem',
            cursor: isRunningBenchmark ? 'not-allowed' : 'pointer',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
          }}
        >
          {isRunningBenchmark ? '⚡ Running 10-Case Benchmark...' : '🏁 Run 10-Case Benchmark Race'}
        </button>
      </div>

      {/* BENCHMARK SCORECARD (IF AVAILABLE) */}
      {benchmarkData && benchmarkData.summary && (
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--accent)',
            borderRadius: '10px',
            padding: '20px',
          }}
        >
          <h3 style={{ margin: '0 0 16px 0', fontSize: '1.05rem', color: '#60a5fa' }}>
            🏁 Benchmark Scorecard Summary (10 Policy Cases)
          </h3>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '14px' }}>
            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Pass Rate</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#10b981', marginTop: '4px' }}>
                Agent: {benchmarkData.summary.agent.pass_rate_pct}% | WF: {benchmarkData.summary.workflow.pass_rate_pct}%
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                {benchmarkData.summary.agent.passed_count}/10 vs {benchmarkData.summary.workflow.passed_count}/10
              </div>
            </div>

            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>p50 Latency</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#60a5fa', marginTop: '4px' }}>
                Agent: {benchmarkData.summary.agent.p50_latency_ms}ms | WF: {benchmarkData.summary.workflow.p50_latency_ms}ms
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>Sub-millisecond resolution</div>
            </div>

            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Token Consumption</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#fbbf24', marginTop: '4px' }}>
                Agent: {benchmarkData.summary.agent.total_tokens} | WF: {benchmarkData.summary.workflow.total_tokens}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>Total prompt + completion</div>
            </div>

            <div style={{ background: 'var(--bg-surface-elevated)', padding: '14px', borderRadius: '8px' }}>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>Cost per Question</div>
              <div style={{ fontSize: '1.2rem', fontWeight: 700, color: '#a78bfa', marginTop: '4px' }}>
                ${benchmarkData.summary.agent.cost_per_question_usd.toFixed(6)} vs ${benchmarkData.summary.workflow.cost_per_question_usd.toFixed(6)}
              </div>
              <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>$2.00 / 1M token rate</div>
            </div>
          </div>
        </div>
      )}

      {/* TWO-COLUMN WORKSPACE */}
      <div style={{ display: 'grid', gridTemplateColumns: 'minmax(300px, 360px) 1fr', gap: '20px' }}>
        {/* LEFT COLUMN: PRESET CASES & EMPLOYEE PROFILES */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* CASES LIST */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: '10px', padding: '16px' }}>
            <h4 style={{ margin: '0 0 12px 0', fontSize: '0.9rem', color: '#fff' }}>📋 Verified Benchmark Cases</h4>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '320px', overflowY: 'auto' }}>
              {cases.map((c) => (
                <button
                  key={c.case_id}
                  type="button"
                  onClick={() => handleSelectCase(c)}
                  style={{
                    textAlign: 'left',
                    padding: '8px 10px',
                    borderRadius: '6px',
                    border: selectedCaseId === c.case_id ? '1px solid var(--accent)' : '1px solid var(--border)',
                    background: selectedCaseId === c.case_id ? 'rgba(59, 130, 246, 0.1)' : 'transparent',
                    color: selectedCaseId === c.case_id ? '#60a5fa' : 'var(--text-main)',
                    cursor: 'pointer',
                    fontSize: '0.78rem',
                  }}
                >
                  <div style={{ fontWeight: 600 }}>{c.case_id.toUpperCase()} ({c.employee_id})</div>
                  <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem', marginTop: '2px', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {c.question}
                  </div>
                </button>
              ))}
            </div>
          </div>

          {/* SELECTED EMPLOYEE PROFILE CARD */}
          {selectedEmp && (
            <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: '10px', padding: '16px' }}>
              <h4 style={{ margin: '0 0 10px 0', fontSize: '0.9rem', color: '#fff' }}>👤 Selected Employee Record</h4>
              <div style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '6px', color: 'var(--text-main)' }}>
                <div><strong>ID:</strong> {selectedEmp.employee_id} ({selectedEmp.name})</div>
                <div><strong>Role:</strong> {selectedEmp.job_title} ({selectedEmp.department})</div>
                <div><strong>Jurisdiction:</strong> {selectedEmp.duty_station}, {selectedEmp.jurisdiction}</div>
                <div><strong>Status:</strong> <span style={{ color: selectedEmp.employment_status === 'Confirmed' ? '#10b981' : '#fbbf24' }}>{selectedEmp.employment_status}</span></div>
                <div><strong>Tenure:</strong> {selectedEmp.tenure_months} months</div>
                <div><strong>Basic Salary:</strong> ${selectedEmp.basic_salary_monthly}/month</div>
                <div><strong>Leave Balance:</strong> {selectedEmp.annual_leave_balance} days</div>
                {selectedEmp.separation_reason && (
                  <div><strong>Separation:</strong> <span style={{ color: '#ef4444' }}>{selectedEmp.separation_reason}</span></div>
                )}
              </div>
            </div>
          )}
        </div>

        {/* RIGHT COLUMN: QUERY INPUT & SIDE-BY-SIDE EXECUTION */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
          {/* QUERY INPUT FORM */}
          <div style={{ background: 'var(--bg-surface)', border: '1px solid var(--border)', borderRadius: '10px', padding: '18px' }}>
            <div style={{ display: 'flex', gap: '12px', marginBottom: '12px' }}>
              <div style={{ flex: '0 0 120px' }}>
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Employee ID</label>
                <select
                  value={selectedEmpId}
                  onChange={(e) => setSelectedEmpId(e.target.value)}
                  style={{
                    width: '100%',
                    padding: '8px',
                    borderRadius: '6px',
                    background: 'var(--bg-surface-elevated)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
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
                <label style={{ fontSize: '0.75rem', color: 'var(--text-muted)', display: 'block', marginBottom: '4px' }}>Policy Question</label>
                <input
                  type="text"
                  value={queryText}
                  onChange={(e) => setQueryText(e.target.value)}
                  placeholder="Ask an HR policy question..."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-surface-elevated)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
                  }}
                />
              </div>
            </div>

            <div style={{ display: 'flex', gap: '10px', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => handleRunSingle('agent')}
                disabled={isRunningSingle}
                className="btn-secondary"
                style={{ fontSize: '0.8rem', padding: '6px 14px' }}
              >
                Run Agent Only
              </button>
              <button
                type="button"
                onClick={() => handleRunSingle('workflow')}
                disabled={isRunningSingle}
                className="btn-secondary"
                style={{ fontSize: '0.8rem', padding: '6px 14px' }}
              >
                Run Workflow Only
              </button>
              <button
                type="button"
                onClick={() => handleRunSingle('both')}
                disabled={isRunningSingle}
                style={{
                  padding: '6px 16px',
                  borderRadius: '6px',
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  cursor: isRunningSingle ? 'not-allowed' : 'pointer',
                }}
              >
                {isRunningSingle ? '⚡ Executing...' : '⚔️ Run Agent vs Workflow'}
              </button>
            </div>
          </div>

          {/* SIDE-BY-SIDE RESULT CARDS */}
          {(agentSingleResult || workflowSingleResult) && (
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>
              {/* AGENT CARD */}
              <div
                style={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                  borderRadius: '10px',
                  padding: '16px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <h4 style={{ margin: 0, fontSize: '0.92rem', color: '#60a5fa' }}>🤖 ReAct Agent</h4>
                  {agentSingleResult && (
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        background: agentSingleResult.passed ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                        color: agentSingleResult.passed ? '#10b981' : '#ef4444',
                      }}
                    >
                      {agentSingleResult.passed ? 'PASS' : 'FAIL'} ({agentSingleResult.termination_reason})
                    </span>
                  )}
                </div>

                {agentSingleResult ? (
                  <div style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div><strong>Entitlement:</strong> {agentSingleResult.entitlement_value}</div>
                    <div><strong>Rule Cited:</strong> <code>{agentSingleResult.rule_cited}</code></div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', lineHeight: '1.4' }}>
                      {agentSingleResult.explanation}
                    </div>
                    <div style={{ borderTop: '1px solid var(--border)', paddingTop: '8px', marginTop: '4px', display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      <span>Latency: {agentSingleResult.latency_ms.toFixed(2)}ms</span>
                      <span>Tokens: {agentSingleResult.total_tokens}</span>
                      <span>Cost: ${agentSingleResult.cost_usd.toFixed(6)}</span>
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>No agent execution result yet.</div>
                )}
              </div>

              {/* WORKFLOW CARD */}
              <div
                style={{
                  background: 'var(--bg-surface)',
                  border: '1px solid var(--border)',
                  borderRadius: '10px',
                  padding: '16px',
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
                  <h4 style={{ margin: 0, fontSize: '0.92rem', color: '#10b981' }}>⚡ Deterministic Workflow</h4>
                  {workflowSingleResult && (
                    <span
                      style={{
                        padding: '2px 8px',
                        borderRadius: '4px',
                        fontSize: '0.72rem',
                        fontWeight: 700,
                        background: workflowSingleResult.passed ? 'rgba(16, 185, 129, 0.15)' : 'rgba(239, 68, 68, 0.15)',
                        color: workflowSingleResult.passed ? '#10b981' : '#ef4444',
                      }}
                    >
                      {workflowSingleResult.passed ? 'PASS' : 'FAIL'} ({workflowSingleResult.termination_reason})
                    </span>
                  )}
                </div>

                {workflowSingleResult ? (
                  <div style={{ fontSize: '0.8rem', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div><strong>Entitlement:</strong> {workflowSingleResult.entitlement_value}</div>
                    <div><strong>Rule Cited:</strong> <code>{workflowSingleResult.rule_cited}</code></div>
                    <div style={{ color: 'var(--text-muted)', fontSize: '0.75rem', lineHeight: '1.4' }}>
                      {workflowSingleResult.explanation}
                    </div>
                    <div style={{ borderTop: '1px solid var(--border)', paddingTop: '8px', marginTop: '4px', display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                      <span>Latency: {workflowSingleResult.latency_ms.toFixed(2)}ms</span>
                      <span>Tokens: {workflowSingleResult.total_tokens}</span>
                      <span>Cost: ${workflowSingleResult.cost_usd.toFixed(6)}</span>
                    </div>
                  </div>
                ) : (
                  <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>No workflow execution result yet.</div>
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};
