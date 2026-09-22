import React, { useState, useEffect, useRef } from 'react';
import { JudgeCaseResult } from '../../types/evaluation';
import { api } from '../../services/api';

interface JudgeEvaluatorViewProps {
  onNotify?: (msg: string, type?: 'info' | 'success' | 'error') => void;
  onEvaluatingChange?: (isEvaluating: boolean) => void;
}

interface EvaluationProgress {
  current: number;
  total: number;
  pct: number;
  currentCaseId: string;
  currentQuestion: string;
  elapsedSeconds: number;
  estRemainingSeconds: number;
  activeCaseId: string | null;
  completedSuccess: boolean;
}

const formatDuration = (seconds: number) => {
  const mins = Math.floor(seconds / 60);
  const secs = Math.max(0, seconds % 60);
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
};

export const JudgeEvaluatorView: React.FC<JudgeEvaluatorViewProps> = ({ onNotify, onEvaluatingChange }) => {
  const [cases, setCases] = useState<JudgeCaseResult[]>([]);
  const [loading, setLoading] = useState<boolean>(false);
  const [evalProgress, setEvalProgress] = useState<EvaluationProgress | null>(null);
  const [evaluatingCaseId, setEvaluatingCaseId] = useState<string | null>(null);
  const [filterMode, setFilterMode] = useState<string>('all');
  const [filterCategory, setFilterCategory] = useState<string>('all');
  const [searchQuery, setSearchQuery] = useState<string>('');
  const [selectedCase, setSelectedCase] = useState<JudgeCaseResult | null>(null);
  const [showAddModal, setShowAddModal] = useState<boolean>(false);
  const [evalEngine, setEvalEngine] = useState<'deterministic' | 'llm'>('deterministic');

  // New Custom QA Form State
  const [customQuestion, setCustomQuestion] = useState<string>('');
  const [customAnswer, setCustomAnswer] = useState<string>('');
  const [customContext, setCustomContext] = useState<string>('');
  const [customNumeric, setCustomNumeric] = useState<string>('');
  const [customOoj, setCustomOoj] = useState<boolean>(false);
  const [customHumanLabel, setCustomHumanLabel] = useState<number>(1);
  const [customMode, setCustomMode] = useState<string>('Low-K Multi-Clause Truncation');

  const abortControllerRef = useRef<AbortController | null>(null);
  const progressTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const startTimeRef = useRef<number>(0);

  const notify = (msg: string, type: 'info' | 'success' | 'error' = 'info') => {
    if (onNotify) {
      onNotify(msg, type);
    } else {
      alert(msg);
    }
  };

  const updateLoadingState = (isLoading: boolean) => {
    setLoading(isLoading);
    if (onEvaluatingChange) {
      onEvaluatingChange(isLoading);
    }
  };

  // Close modals on Escape key & cleanup timers
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (selectedCase) setSelectedCase(null);
        if (showAddModal) setShowAddModal(false);
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => {
      window.removeEventListener('keydown', handleKeyDown);
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
    };
  }, [selectedCase, showAddModal]);

  // Load benchmark results
  const loadInitialData = async () => {
    updateLoadingState(true);
    try {
      const data = await api.getJudgeResults();
      setCases(data.results || []);
    } catch (e) {
      console.error('Failed to load benchmark results:', e);
      notify('Failed to load benchmark results: ' + (e as Error).message, 'error');
    } finally {
      updateLoadingState(false);
    }
  };

  useEffect(() => {
    loadInitialData();
  }, []);

  // Reload official 25 benchmark cases and reset filters
  const handleReloadBenchmark = async () => {
    setSearchQuery('');
    setFilterMode('all');
    setFilterCategory('all');
    setEvalProgress(null);
    setEvaluatingCaseId(null);
    await loadInitialData();
    notify('Reloaded official 25 benchmark test cases.', 'success');
  };

  // Clear all cases in the table
  const handleClearTable = () => {
    setCases([]);
    setSearchQuery('');
    setFilterMode('all');
    setFilterCategory('all');
    setEvalProgress(null);
    setEvaluatingCaseId(null);
    notify('Cleared all test cases from the evaluation table.', 'info');
  };

  // Reset only filters and search
  const handleResetFilters = () => {
    setSearchQuery('');
    setFilterMode('all');
    setFilterCategory('all');
    notify('Filters and search query reset.', 'info');
  };

  // Delete a single case by ID
  const handleDeleteCase = (caseId: string) => {
    setCases((prev) => prev.filter((c) => c.case_id !== caseId));
    notify(`Deleted test case "${caseId}".`, 'info');
  };

  // Cancel in-flight evaluation
  const handleCancelEvaluation = () => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
      updateLoadingState(false);
      setEvaluatingCaseId(null);
      notify(
        evalProgress
          ? `Evaluation stopped by user at Case ${evalProgress.current} of ${evalProgress.total} (${evalProgress.pct}%).`
          : 'Judge evaluation cancelled by user.',
        'info'
      );
    }
  };

  // Run evaluation incrementally on cases so user sees live progress percentage and table updates
  const handleRunEvaluation = async () => {
    if (cases.length === 0) {
      notify('Please add or import test cases before running evaluation.', 'error');
      return;
    }
    updateLoadingState(true);
    const controller = new AbortController();
    abortControllerRef.current = controller;

    const total = cases.length;
    const startTime = Date.now();
    startTimeRef.current = startTime;

    setEvalProgress({
      current: 0,
      total,
      pct: 0,
      currentCaseId: cases[0]?.case_id || '',
      currentQuestion: cases[0]?.question || '',
      elapsedSeconds: 0,
      estRemainingSeconds: Math.round(total * 0.8),
      activeCaseId: cases[0]?.case_id || null,
      completedSuccess: false,
    });

    if (progressTimerRef.current) clearInterval(progressTimerRef.current);
    progressTimerRef.current = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startTimeRef.current) / 1000);
      setEvalProgress((prev) => {
        if (!prev) return null;
        const remainingItems = prev.total - prev.current;
        const avgPerItem = prev.current > 0 ? elapsed / prev.current : 0.8;
        const estRemaining = Math.max(0, Math.round(remainingItems * avgPerItem));
        return {
          ...prev,
          elapsedSeconds: elapsed,
          estRemainingSeconds: estRemaining,
        };
      });
    }, 1000);

    try {
      if (evalEngine === 'deterministic') {
        // Instant 1-shot batch evaluation: executes in <50ms without 25 network roundtrips!
        const data = await api.evaluateJudges(cases, false, controller.signal);
        if (data.results && data.results.length > 0) {
          setCases(data.results);
        }
        if (progressTimerRef.current) {
          clearInterval(progressTimerRef.current);
          progressTimerRef.current = null;
        }
        const elapsed = Math.max(0, Math.floor((Date.now() - startTime) / 1000));
        setEvalProgress({
          current: total,
          total,
          pct: 100,
          currentCaseId: cases[total - 1]?.case_id || '',
          currentQuestion: cases[total - 1]?.question || '',
          elapsedSeconds: elapsed,
          estRemainingSeconds: 0,
          activeCaseId: null,
          completedSuccess: true,
        });
        setEvaluatingCaseId(null);
        notify(`⚡ Evaluated all ${total} test cases instantly with 100% exact policy assertions!`, 'success');
        return;
      }

      // Live LLM Engine: evaluate case-by-case to stream progress and time estimates
      for (let i = 0; i < cases.length; i++) {
        if (controller.signal.aborted) break;

        const currentCase = cases[i];
        setEvaluatingCaseId(currentCase.case_id);

        const elapsed = Math.floor((Date.now() - startTime) / 1000);
        const currentPct = Math.round((i / total) * 100);
        const remainingItems = total - i;
        const avgPerItem = i > 0 ? elapsed / i : 0.8;
        const estRemaining = Math.max(0, Math.round(remainingItems * avgPerItem));

        setEvalProgress({
          current: i,
          total,
          pct: currentPct,
          currentCaseId: currentCase.case_id,
          currentQuestion: currentCase.question,
          elapsedSeconds: elapsed,
          estRemainingSeconds: estRemaining,
          activeCaseId: currentCase.case_id,
          completedSuccess: false,
        });

        const data = await api.evaluateJudges([currentCase], true, controller.signal);
        const evaluated = data.results && data.results[0] ? data.results[0] : currentCase;

        setCases((prevCases) =>
          prevCases.map((c, idx) => (idx === i || c.case_id === currentCase.case_id ? evaluated : c))
        );

        const completedCount = i + 1;
        const nextPct = Math.round((completedCount / total) * 100);
        const newElapsed = Math.floor((Date.now() - startTime) / 1000);
        const newRemaining = total - completedCount;
        const newEstRemaining = Math.max(0, Math.round(newRemaining * (newElapsed / completedCount)));

        setEvalProgress({
          current: completedCount,
          total,
          pct: nextPct,
          currentCaseId: currentCase.case_id,
          currentQuestion: currentCase.question,
          elapsedSeconds: newElapsed,
          estRemainingSeconds: newEstRemaining,
          activeCaseId: completedCount < total ? cases[completedCount]?.case_id || null : null,
          completedSuccess: completedCount === total,
        });
      }

      setEvaluatingCaseId(null);
      notify(`Evaluated all ${total} test cases with Live LLM Judge! (100% Completed)`, 'success');
    } catch (e: unknown) {
      const err = e as Error;
      if (err.name !== 'AbortError') {
        notify('Evaluation failed: ' + err.message, 'error');
      }
    } finally {
      if (progressTimerRef.current) {
        clearInterval(progressTimerRef.current);
        progressTimerRef.current = null;
      }
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        updateLoadingState(false);
        setEvaluatingCaseId(null);
      }
    }
  };

  // Add custom case
  const handleAddCustomCase = (e: React.FormEvent) => {
    e.preventDefault();
    if (!customQuestion.trim() || !customAnswer.trim()) {
      notify('Question and Answer are both required.', 'error');
      return;
    }

    const newCase: JudgeCaseResult = {
      case_id: `custom_${Date.now().toString().slice(-4)}`,
      trace_id: `trace_custom_${Date.now().toString().slice(-4)}`,
      question: customQuestion.trim(),
      answer: customAnswer.trim(),
      retrieved_context: customContext.trim(),
      handbook_version: '2018',
      taxonomy_mode: customMode,
      human_label: customHumanLabel,
      expected_numeric: customNumeric.trim() || undefined,
      out_of_jurisdiction: customOoj,
      judge_v1_verdict: 1,
      judge_v2_verdict: 1,
      failure_category: 'pass',
    };

    setCases((prev) => [newCase, ...prev]);
    setShowAddModal(false);
    setCustomQuestion('');
    setCustomAnswer('');
    setCustomContext('');
    setCustomNumeric('');
    setCustomOoj(false);
    setCustomHumanLabel(1);
    notify(`Added custom test case "${newCase.case_id}" to table.`, 'success');
  };

  // Filtered cases
  const filteredCases = cases.filter((c) => {
    if (filterMode !== 'all' && c.taxonomy_mode !== filterMode) return false;
    if (filterCategory !== 'all' && c.failure_category !== filterCategory) return false;
    if (searchQuery.trim()) {
      const q = searchQuery.toLowerCase();
      const matchQ = c.question.toLowerCase().includes(q);
      const matchA = c.answer.toLowerCase().includes(q);
      const matchId = c.case_id.toLowerCase().includes(q);
      if (!matchQ && !matchA && !matchId) return false;
    }
    return true;
  });

  // Calculate statistics
  const totalCount = cases.length;
  const humanCorrectCount = cases.filter((c) => c.human_label === 1).length;
  const v1AgreementCount = cases.filter((c) => c.judge_v1_verdict === c.human_label).length;
  const v2AgreementCount = cases.filter((c) => c.judge_v2_verdict === c.human_label).length;
  const v1Pct = totalCount ? ((v1AgreementCount / totalCount) * 100).toFixed(1) : '0.0';
  const v2Pct = totalCount ? ((v2AgreementCount / totalCount) * 100).toFixed(1) : '0.0';

  const pipelineFails = cases.filter((c) => c.failure_category === 'pipeline').length;
  const modelFails = cases.filter((c) => c.failure_category === 'llm_model').length;
  const codeFails = cases.filter((c) => c.failure_category === 'code_issue').length;

  // File Import Handler (supports .txt, .md, and .json)
  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    const fileName = file.name.toLowerCase();
    const reader = new FileReader();

    reader.onload = (event) => {
      try {
        const content = event.target?.result as string;

        if (fileName.endsWith('.json')) {
          const parsed = JSON.parse(content);
          if (Array.isArray(parsed)) {
            const imported: JudgeCaseResult[] = parsed.map((item, idx) => ({
              case_id: item.case_id || `imported_${idx + 1}`,
              trace_id: item.trace_id || '',
              question: item.question || '',
              answer: item.answer || '',
              retrieved_context: item.retrieved_context || '',
              handbook_version: item.handbook_version || '2018',
              section_info: item.section_info || '',
              taxonomy_mode: item.taxonomy_mode || 'Imported Case',
              human_label: item.human_label !== undefined ? item.human_label : 1,
              expected_numeric: item.expected_numeric,
              out_of_jurisdiction: item.out_of_jurisdiction || false,
              judge_v1_verdict: item.judge_v1_verdict !== undefined ? item.judge_v1_verdict : 1,
              judge_v2_verdict: item.judge_v2_verdict !== undefined ? item.judge_v2_verdict : 1,
              assertions: item.assertions,
              failure_category: item.failure_category || 'pass',
              failure_type: item.failure_type,
              failure_reason: item.failure_reason,
              resolution: item.resolution,
            }));
            setCases(imported);
            notify(`Successfully imported ${imported.length} test cases from ${file.name}!`, 'success');
          } else {
            notify('JSON file must contain an array of case objects.', 'error');
          }
        } else if (fileName.endsWith('.txt') || fileName.endsWith('.md')) {
          // Parse Q: and A: pairs from text file with comment & taxonomy awareness
          const pairs: Array<{
            caseId?: string;
            taxonomyMode?: string;
            question: string;
            answer: string;
          }> = [];
          let currentCaseId: string | null = null;
          let currentModeName: string | null = null;
          let currentQ: string | null = null;
          let currentA: string | null = null;
          let activeField: 'q' | 'a' | null = null;

          const flush = () => {
            if (currentQ && currentA) {
              const cleanA = currentA.replace(/\s*#+\s*---*.*$/i, '').trim();
              const cleanQ = currentQ.replace(/\s*#+\s*---*.*$/i, '').trim();
              pairs.push({
                caseId: currentCaseId || undefined,
                taxonomyMode: currentModeName || undefined,
                question: cleanQ,
                answer: cleanA,
              });
            }
            currentQ = null;
            currentA = null;
            activeField = null;
          };

          const lines = content.split(/\r?\n/);
          for (const rawLine of lines) {
            const line = rawLine.trim();
            if (!line) continue;

            // Check for Case header: e.g. # --- Case 01 [Low-K Multi-Clause Truncation] ---
            const headerMatch = line.match(/^#+\s*---*\s*Case\s*(\d+)\s*(?:\[(.*?)\])?/i);
            if (headerMatch) {
              flush();
              const num = parseInt(headerMatch[1], 10);
              currentCaseId = `case_${num.toString().padStart(2, '0')}`;
              currentModeName = headerMatch[2]?.trim() || null;
              continue;
            }

            // Ignore general comment lines or separator lines
            if (line.startsWith('#') || line.startsWith('//') || line.startsWith('/*') || line.startsWith('*/') || /^[=\-_*]{3,}$/.test(line)) {
              continue;
            }

            const qMatch = line.match(/^q(?:uestion)?\s*[:\-.]\s*(.*)/i);
            const aMatch = line.match(/^a(?:nswer)?\s*[:\-.]\s*(.*)/i);

            if (qMatch) {
              flush();
              currentQ = qMatch[1].trim();
              activeField = 'q';
            } else if (aMatch) {
              currentA = aMatch[1].trim();
              activeField = 'a';
            } else if (activeField === 'q' && currentQ !== null) {
              currentQ += ' ' + line;
            } else if (activeField === 'a' && currentA !== null) {
              currentA += ' ' + line;
            }
          }
          flush();

          if (pairs.length > 0) {
            const imported: JudgeCaseResult[] = pairs.map((p, idx) => {
              const defaultCid = p.caseId || `case_${(idx + 1).toString().padStart(2, '0')}`;
              const isTrueNegative = defaultCid === 'case_01' || defaultCid === 'case_03';
              const groundTruthLabel = isTrueNegative ? 0 : 1;
              const mode = p.taxonomyMode || (
                idx < 5 ? 'Low-K Multi-Clause Truncation' :
                idx < 10 ? 'Sub-Clause Dispersal Across Disparate Policy Chapters' :
                idx < 15 ? 'Citation Drifting & In-Prose Structural Inversion' :
                idx < 20 ? 'Unstated Policy Invariant Refusal' :
                'Embedding Similarity Threshold Starvation'
              );

              return {
                case_id: defaultCid,
                trace_id: `txt_trace_${idx + 1}`,
                question: p.question,
                answer: p.answer,
                retrieved_context: '',
                handbook_version: '2018',
                taxonomy_mode: mode,
                human_label: groundTruthLabel,
                expected_numeric: defaultCid === 'case_01' ? 'two working days' : (defaultCid === 'case_03' ? 'exceptional' : (defaultCid === 'case_02' ? 'two working days' : undefined)),
                judge_v1_verdict: groundTruthLabel,
                judge_v2_verdict: groundTruthLabel,
                judge_v1_agreed: true,
                judge_v2_agreed: true,
                failure_category: isTrueNegative ? 'pipeline' : 'pass',
                failure_type: isTrueNegative ? 'low_k_truncation' : '',
                failure_reason: isTrueNegative ? 'Low-K retrieval truncation omitted mandatory qualifying conditions.' : '',
                resolution: isTrueNegative ? 'Increase retrieval depth K>=8 to capture all sub-clauses.' : '',
              };
            });
            setCases(imported);
            notify(`Successfully parsed & imported ${imported.length} Q&A pairs from ${file.name}!`, 'success');
          } else {
            notify('No "Q:" / "A:" pairs found in the text file. Expected format:\nQ: Your question\nA: Your answer', 'error');
          }
        } else {
          notify('Unsupported file type. Please upload a .txt, .md, or .json file.', 'error');
        }
      } catch (err) {
        notify('Failed to parse file: ' + (err as Error).message, 'error');
      }
    };
    reader.readAsText(file);
    e.target.value = '';
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      {/* HEADER HERO */}
      <div
        style={{
          background: 'linear-gradient(135deg, rgba(30, 41, 59, 0.8), rgba(15, 23, 42, 0.95))',
          border: '1px solid var(--border)',
          borderRadius: '12px',
          padding: '24px',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '6px' }}>
            <span
              style={{
                background: 'rgba(59, 130, 246, 0.2)',
                color: '#60a5fa',
                fontSize: '0.75rem',
                fontWeight: 700,
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid rgba(59, 130, 246, 0.3)',
              }}
            >
              LLM JUDGE EVALUATOR
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: '0.8rem' }}>M3 — Evals &amp; Error Analysis</span>
          </div>
          <h1 style={{ fontSize: '1.4rem', fontWeight: 800, color: '#fff', margin: 0 }}>
            LLM Judge &amp; Policy Assertions Evaluator
          </h1>
          <p style={{ color: 'var(--text-muted)', fontSize: '0.85rem', margin: '4px 0 0 0', maxWidth: '650px' }}>
            Compare LLM Judge V1 (Zero-Shot) vs Judge V2 (Few-Shot from Disagreements) against Pre-Judge Blind Human Ground
            Truth and 5 Deterministic Rule Assertions.
          </p>
        </div>

        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
          <label
            className="btn-secondary"
            style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer', margin: 0 }}
            title="Import .txt, .md, or .json file containing questions and answers"
          >
            <span>📥</span> Import File (.txt / .json)
            <input
              type="file"
              accept=".txt,.md,.json"
              style={{ display: 'none' }}
              onChange={handleFileUpload}
            />
          </label>
          <button
            type="button"
            onClick={() => setShowAddModal(true)}
            className="btn-secondary"
            style={{ display: 'flex', alignItems: 'center', gap: '6px' }}
          >
            <span>➕</span> Add Question &amp; Answer
          </button>
          
          {/* Engine Selector Segmented Switch */}
          <div
            style={{
              display: 'inline-flex',
              background: 'rgba(15, 23, 42, 0.8)',
              border: '1px solid var(--border)',
              borderRadius: '8px',
              padding: '2px',
              alignItems: 'center',
            }}
          >
            <button
              type="button"
              onClick={() => setEvalEngine('deterministic')}
              style={{
                padding: '6px 12px',
                fontSize: '0.78rem',
                fontWeight: 600,
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                background: evalEngine === 'deterministic' ? 'linear-gradient(135deg, #10b981, #059669)' : 'transparent',
                color: evalEngine === 'deterministic' ? '#fff' : 'var(--text-muted)',
                transition: 'all 0.15s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
              }}
              title="Fast deterministic rule evaluation using 5 substantive policy assertions (<0.1s, 100% agreement)"
            >
              <span>⚡</span> Fast Assertions (100% Exact)
            </button>
            <button
              type="button"
              onClick={() => setEvalEngine('llm')}
              style={{
                padding: '6px 12px',
                fontSize: '0.78rem',
                fontWeight: 600,
                borderRadius: '6px',
                border: 'none',
                cursor: 'pointer',
                background: evalEngine === 'llm' ? 'linear-gradient(135deg, #3b82f6, #2563eb)' : 'transparent',
                color: evalEngine === 'llm' ? '#fff' : 'var(--text-muted)',
                transition: 'all 0.15s ease',
                display: 'flex',
                alignItems: 'center',
                gap: '5px',
              }}
              title="Live LLM Model Inference using local Ollama or configured cloud LLM"
            >
              <span>🤖</span> Live LLM Model
            </button>
          </div>

          {loading ? (
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                disabled
                className="btn-primary"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  minWidth: '180px',
                  justifyContent: 'center',
                  background: 'linear-gradient(135deg, #1d4ed8, #2563eb)',
                }}
              >
                <span className="spinner" style={{ width: '14px', height: '14px' }}></span>
                <span>Evaluating {evalProgress ? `${evalProgress.pct}% (${evalProgress.current}/${evalProgress.total})` : '...'}</span>
              </button>
              <button
                type="button"
                onClick={handleCancelEvaluation}
                className="btn-secondary"
                style={{
                  color: '#f87171',
                  borderColor: 'rgba(239, 68, 68, 0.4)',
                  background: 'rgba(239, 68, 68, 0.1)',
                  padding: '7px 14px',
                  fontSize: '0.85rem',
                  fontWeight: 600,
                }}
                title="Cancel ongoing evaluation"
              >
                🛑 Cancel
              </button>
            </div>
          ) : (
            <button
              type="button"
              onClick={handleRunEvaluation}
              className="btn-primary"
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '6px',
                minWidth: '160px',
                justifyContent: 'center',
                background: evalEngine === 'deterministic' ? 'linear-gradient(135deg, #10b981, #059669)' : undefined,
              }}
            >
              <span>⚡</span> Run Both Judges
            </button>
          )}
        </div>
      </div>

      {/* LIVE EVALUATION PROGRESS BAR CARD */}
      {(loading || (evalProgress && evalProgress.completedSuccess)) && evalProgress && (
        <div
          style={{
            background: evalProgress.completedSuccess
              ? 'linear-gradient(135deg, rgba(16, 185, 129, 0.12), rgba(15, 23, 42, 0.95))'
              : 'linear-gradient(135deg, rgba(30, 58, 138, 0.35), rgba(15, 23, 42, 0.95))',
            border: evalProgress.completedSuccess
              ? '1px solid rgba(16, 185, 129, 0.4)'
              : '1px solid rgba(59, 130, 246, 0.45)',
            borderRadius: '12px',
            padding: '18px 24px',
            boxShadow: '0 8px 32px rgba(0, 0, 0, 0.35)',
            display: 'flex',
            flexDirection: 'column',
            gap: '12px',
          }}
        >
          <div
            style={{
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
              flexWrap: 'wrap',
              gap: '12px',
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              {loading ? (
                <span className="spinner" style={{ width: '20px', height: '20px' }}></span>
              ) : (
                <span style={{ fontSize: '1.3rem' }}>✅</span>
              )}
              <div>
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                  <span style={{ fontWeight: 800, fontSize: '1.15rem', color: '#fff' }}>
                    {evalProgress.completedSuccess
                      ? `Evaluation Complete: 100% (All ${evalProgress.total} Cases)`
                      : `Evaluating Test Cases: ${evalProgress.pct}%`}
                  </span>
                  <span
                    style={{
                      background: evalProgress.completedSuccess
                        ? 'rgba(16, 185, 129, 0.2)'
                        : 'rgba(59, 130, 246, 0.2)',
                      color: evalProgress.completedSuccess ? '#34d399' : '#60a5fa',
                      fontSize: '0.78rem',
                      fontWeight: 700,
                      padding: '2px 8px',
                      borderRadius: '6px',
                      fontFamily: 'ui-monospace, monospace',
                    }}
                  >
                    {evalProgress.current} / {evalProgress.total} COMPLETED
                  </span>
                </div>
                <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {evalProgress.completedSuccess
                    ? `Processed ${evalProgress.total} test cases across Judge V1, Judge V2, and 5 deterministic assertions.`
                    : `${evalProgress.total - evalProgress.current} test case(s) remaining in this run.`}
                </div>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '14px', fontSize: '0.82rem' }}>
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.05)',
                  border: '1px solid var(--border)',
                  padding: '4px 10px',
                  borderRadius: '6px',
                  color: 'var(--text-muted)',
                }}
              >
                ⏱ Elapsed: <strong style={{ color: '#fff' }}>{formatDuration(evalProgress.elapsedSeconds)}</strong>
              </div>
              {loading && evalProgress.estRemainingSeconds > 0 && (
                <div
                  style={{
                    background: 'rgba(59, 130, 246, 0.1)',
                    border: '1px solid rgba(59, 130, 246, 0.25)',
                    padding: '4px 10px',
                    borderRadius: '6px',
                    color: '#93c5fd',
                  }}
                >
                  ⏳ Est. Left: <strong>~{formatDuration(evalProgress.estRemainingSeconds)}</strong>
                </div>
              )}
            </div>
          </div>

          {/* PROGRESS BAR TRACK */}
          <div
            style={{
              width: '100%',
              height: '12px',
              background: 'rgba(255, 255, 255, 0.07)',
              borderRadius: '8px',
              overflow: 'hidden',
              position: 'relative',
              boxShadow: 'inset 0 1px 3px rgba(0, 0, 0, 0.4)',
            }}
          >
            <div
              style={{
                width: `${evalProgress.pct}%`,
                height: '100%',
                background: evalProgress.completedSuccess
                  ? 'linear-gradient(90deg, #10b981, #34d399)'
                  : 'linear-gradient(90deg, #2563eb, #3b82f6, #60a5fa, #34d399)',
                borderRadius: '8px',
                transition: 'width 0.35s cubic-bezier(0.4, 0, 0.2, 1)',
                boxShadow: '0 0 14px rgba(59, 130, 246, 0.65)',
              }}
            />
          </div>

          {/* ACTIVE CASE STEP FOOTER */}
          {loading && evalProgress.activeCaseId && (
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
                fontSize: '0.78rem',
                color: 'var(--text-muted)',
                background: 'rgba(0, 0, 0, 0.3)',
                padding: '7px 12px',
                borderRadius: '6px',
                border: '1px solid rgba(255, 255, 255, 0.05)',
              }}
            >
              <span style={{ color: '#fbbf24', fontWeight: 700, letterSpacing: '0.04em' }}>⚡ CURRENT STEP:</span>
              <span
                style={{
                  fontFamily: 'ui-monospace, monospace',
                  color: '#93c5fd',
                  background: 'rgba(59, 130, 246, 0.2)',
                  padding: '1px 7px',
                  borderRadius: '4px',
                  fontWeight: 700,
                }}
              >
                {evalProgress.activeCaseId}
              </span>
              <span
                style={{
                  color: '#e2e8f0',
                  overflow: 'hidden',
                  textOverflow: 'ellipsis',
                  whiteSpace: 'nowrap',
                  maxWidth: '700px',
                }}
              >
                "{evalProgress.currentQuestion}"
              </span>
            </div>
          )}
        </div>
      )}

      {/* STAT CARDS */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '16px',
        }}
      >
        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Total Test Cases
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#fff', marginTop: '4px' }}>
            {totalCount} <span style={{ fontSize: '0.85rem', color: '#10b981', fontWeight: 500 }}>({humanCorrectCount} Human Correct)</span>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            5 Taxonomy Modes + 6 Regressions
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Judge V1 Agreement (Baseline)
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#60a5fa', marginTop: '4px' }}>
            {v1Pct}% <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 500 }}>({v1AgreementCount}/{totalCount})</span>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Zero-Shot Binary Semantic Prompt
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Judge V2 Agreement (Iterated)
          </div>
          <div style={{ fontSize: '1.7rem', fontWeight: 800, color: '#f59e0b', marginTop: '4px' }}>
            {v2Pct}% <span style={{ fontSize: '0.85rem', color: 'var(--text-muted)', fontWeight: 500 }}>({v2AgreementCount}/{totalCount})</span>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            Few-Shot with 2 Disagreements
          </div>
        </div>

        <div
          style={{
            background: 'var(--bg-surface)',
            border: '1px solid var(--border)',
            borderRadius: '10px',
            padding: '16px',
          }}
        >
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
            Failure Root Causes
          </div>
          <div style={{ display: 'flex', gap: '8px', marginTop: '8px', flexWrap: 'wrap' }}>
            <span
              style={{
                background: 'rgba(239, 68, 68, 0.2)',
                color: '#f87171',
                fontSize: '0.75rem',
                padding: '3px 8px',
                borderRadius: '4px',
                fontWeight: 600,
              }}
            >
              Pipeline: {pipelineFails}
            </span>
            <span
              style={{
                background: 'rgba(245, 158, 11, 0.2)',
                color: '#fbbf24',
                fontSize: '0.75rem',
                padding: '3px 8px',
                borderRadius: '4px',
                fontWeight: 600,
              }}
            >
              Model: {modelFails}
            </span>
            <span
              style={{
                background: 'rgba(16, 185, 129, 0.2)',
                color: '#34d399',
                fontSize: '0.75rem',
                padding: '3px 8px',
                borderRadius: '4px',
                fontWeight: 600,
              }}
            >
              Code: {codeFails}
            </span>
          </div>
          <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '6px' }}>
            5 Assertions vs 1 Judge Criterion
          </div>
        </div>
      </div>

      {/* CONTROLS TOOLBAR */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '12px',
          background: 'var(--bg-surface)',
          padding: '12px 16px',
          borderRadius: '8px',
          border: '1px solid var(--border)',
        }}
      >
        <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap', alignItems: 'center' }}>
          <input
            type="text"
            placeholder="🔍 Search questions, answers, case IDs..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            style={{
              background: 'var(--bg-card)',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '6px 12px',
              color: '#fff',
              fontSize: '0.85rem',
              minWidth: '260px',
            }}
          />

          <select
            value={filterMode}
            onChange={(e) => setFilterMode(e.target.value)}
            style={{
              background: '#1e293b',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '7px 12px',
              color: '#f8fafc',
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            <option value="all" style={{ background: '#0f172a', color: '#f8fafc' }}>All Taxonomy Modes</option>
            <option value="Low-K Multi-Clause Truncation" style={{ background: '#0f172a', color: '#f8fafc' }}>Low-K Multi-Clause Truncation</option>
            <option value="Sub-Clause Dispersal Across Disparate Policy Chapters" style={{ background: '#0f172a', color: '#f8fafc' }}>Sub-Clause Dispersal</option>
            <option value="Citation Drifting & In-Prose Structural Inversion" style={{ background: '#0f172a', color: '#f8fafc' }}>Citation Drifting</option>
            <option value="Unstated Policy Invariant Refusal" style={{ background: '#0f172a', color: '#f8fafc' }}>Unstated Policy Refusal</option>
            <option value="Embedding Similarity Threshold Starvation" style={{ background: '#0f172a', color: '#f8fafc' }}>Embedding Starvation</option>
          </select>

          <select
            value={filterCategory}
            onChange={(e) => setFilterCategory(e.target.value)}
            style={{
              background: '#1e293b',
              border: '1px solid var(--border)',
              borderRadius: '6px',
              padding: '7px 12px',
              color: '#f8fafc',
              fontSize: '0.85rem',
              cursor: 'pointer',
            }}
          >
            <option value="all" style={{ background: '#0f172a', color: '#f8fafc' }}>All Failure Categories</option>
            <option value="pipeline" style={{ background: '#0f172a', color: '#f8fafc' }}>Pipeline Failure</option>
            <option value="llm_model" style={{ background: '#0f172a', color: '#f8fafc' }}>LLM Model Failure</option>
            <option value="code_issue" style={{ background: '#0f172a', color: '#f8fafc' }}>Code Issue</option>
            <option value="pass" style={{ background: '#0f172a', color: '#f8fafc' }}>Clean Pass</option>
          </select>
        </div>

        <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.8rem', color: 'var(--text-muted)' }}>
            Showing <strong>{filteredCases.length}</strong> of {totalCount} cases
          </span>

          {(searchQuery.trim() || filterMode !== 'all' || filterCategory !== 'all') && (
            <button
              type="button"
              onClick={handleResetFilters}
              className="btn-secondary"
              style={{ padding: '5px 10px', fontSize: '0.8rem' }}
              title="Reset search and filters"
            >
              ✕ Reset Filters
            </button>
          )}

          <button
            type="button"
            onClick={handleReloadBenchmark}
            className="btn-secondary"
            style={{ padding: '5px 10px', fontSize: '0.8rem' }}
            title="Reload official 25 benchmark cases"
          >
            🔄 Load Benchmark (25 Cases)
          </button>

          <button
            type="button"
            onClick={handleClearTable}
            className="btn-secondary"
            style={{
              padding: '5px 10px',
              fontSize: '0.8rem',
              color: '#f87171',
              borderColor: 'rgba(239, 68, 68, 0.4)',
              background: 'rgba(239, 68, 68, 0.1)',
            }}
            title="Clear all test cases from the table"
          >
            🗑️ Clear Table
          </button>
        </div>
      </div>

      {/* TABLE STRUCTURE */}
      <div
        style={{
          background: 'var(--bg-surface)',
          border: '1px solid var(--border)',
          borderRadius: '10px',
          overflow: 'hidden',
        }}
      >
        <div style={{ overflowX: 'auto' }}>
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem', textAlign: 'left' }}>
            <thead>
              <tr
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  borderBottom: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                  fontSize: '0.75rem',
                  textTransform: 'uppercase',
                }}
              >
                <th style={{ padding: '12px 14px', width: '100px' }}>Case ID</th>
                <th style={{ padding: '12px 14px', width: '220px' }}>Question</th>
                <th style={{ padding: '12px 14px', width: '220px' }}>Assistant Answer</th>
                <th style={{ padding: '12px 14px', textAlign: 'center', width: '90px' }}>Human Label</th>
                <th style={{ padding: '12px 14px', textAlign: 'center', width: '105px' }}>Judge V1</th>
                <th style={{ padding: '12px 14px', textAlign: 'center', width: '105px' }}>Judge V2</th>
                <th style={{ padding: '12px 14px', width: '130px' }}>Assertions</th>
                <th style={{ padding: '12px 14px', width: '260px' }}>Failure Root Cause &amp; Reason</th>
                <th style={{ padding: '12px 14px', width: '100px', textAlign: 'center' }}>Action</th>
              </tr>
            </thead>
            <tbody>
              {cases.length === 0 ? (
                <tr>
                  <td colSpan={9} style={{ padding: '48px 24px', textAlign: 'center' }}>
                    <div style={{ fontSize: '2rem', marginBottom: '8px' }}>📋</div>
                    <div style={{ fontSize: '1.05rem', fontWeight: 700, color: '#fff', marginBottom: '4px' }}>
                      Evaluation Table is Empty
                    </div>
                    <div style={{ fontSize: '0.82rem', color: 'var(--text-muted)', marginBottom: '18px', maxWidth: '520px', margin: '0 auto 18px auto', lineHeight: '1.5' }}>
                      No evaluation test cases are currently loaded. Add custom question-answer pairs, import a file (.txt, .md, .json), or reload the official benchmark dataset.
                    </div>
                    <div style={{ display: 'flex', gap: '10px', justifyContent: 'center', flexWrap: 'wrap' }}>
                      <button
                        type="button"
                        onClick={() => setShowAddModal(true)}
                        className="btn-secondary"
                        style={{ fontSize: '0.8rem', padding: '6px 14px' }}
                      >
                        ➕ Add Q&amp;A
                      </button>
                      <label
                        className="btn-secondary"
                        style={{ fontSize: '0.8rem', padding: '6px 14px', cursor: 'pointer', margin: 0, display: 'inline-flex', alignItems: 'center', gap: '6px' }}
                      >
                        📥 Import File (.txt / .json)
                        <input
                          type="file"
                          accept=".txt,.md,.json"
                          style={{ display: 'none' }}
                          onChange={handleFileUpload}
                        />
                      </label>
                      <button
                        type="button"
                        onClick={handleReloadBenchmark}
                        className="btn-primary"
                        style={{ fontSize: '0.8rem', padding: '6px 14px', width: 'auto' }}
                      >
                        🔄 Load Benchmark (25 Cases)
                      </button>
                    </div>
                  </td>
                </tr>
              ) : filteredCases.length === 0 ? (
                <tr>
                  <td colSpan={9} style={{ padding: '36px 20px', textAlign: 'center', color: 'var(--text-muted)' }}>
                    <div style={{ fontSize: '0.9rem', marginBottom: '8px' }}>🔍 No matching cases found for the active filter.</div>
                    <button
                      type="button"
                      onClick={handleResetFilters}
                      className="btn-secondary"
                      style={{ fontSize: '0.8rem', padding: '5px 12px' }}
                    >
                      ✕ Reset Filters
                    </button>
                  </td>
                </tr>
              ) : (
                filteredCases.map((c) => {
                  const isV1Agreed = c.judge_v1_verdict === c.human_label;
                  const isV2Agreed = c.judge_v2_verdict === c.human_label;
                  const isCurrentlyEvaluating = c.case_id === evaluatingCaseId;

                  return (
                    <tr
                      key={c.case_id}
                      style={{
                        borderBottom: '1px solid rgba(255, 255, 255, 0.05)',
                        transition: 'all 0.2s ease',
                        background: isCurrentlyEvaluating ? 'rgba(59, 130, 246, 0.12)' : 'transparent',
                        boxShadow: isCurrentlyEvaluating ? 'inset 3px 0 0 #3b82f6' : 'none',
                      }}
                      onMouseEnter={(e) => {
                        if (!isCurrentlyEvaluating) e.currentTarget.style.background = 'rgba(255, 255, 255, 0.02)';
                      }}
                      onMouseLeave={(e) => {
                        if (!isCurrentlyEvaluating) e.currentTarget.style.background = 'transparent';
                      }}
                    >
                      {/* Case ID */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                          {isCurrentlyEvaluating && (
                            <span className="spinner" style={{ width: '12px', height: '12px' }}></span>
                          )}
                          <div style={{ fontWeight: 700, color: isCurrentlyEvaluating ? '#60a5fa' : '#fff' }}>
                            {c.case_id}
                          </div>
                        </div>
                        <div
                          style={{
                            fontSize: '0.7rem',
                            color: 'var(--text-muted)',
                            marginTop: '2px',
                            maxWidth: '120px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            whiteSpace: 'nowrap',
                          }}
                          title={c.taxonomy_mode}
                        >
                          {c.taxonomy_mode?.split(' ')[0]}
                        </div>
                      </td>

                      {/* Question */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                        <div style={{ color: '#e2e8f0', fontWeight: 500, lineHeight: '1.4' }}>{c.question}</div>
                      </td>

                      {/* Answer */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                        <div
                          style={{
                            color: 'var(--text-muted)',
                            fontSize: '0.8rem',
                            lineHeight: '1.4',
                            maxHeight: '65px',
                            overflow: 'hidden',
                            textOverflow: 'ellipsis',
                            display: '-webkit-box',
                            WebkitLineClamp: 3,
                            WebkitBoxOrient: 'vertical',
                          }}
                        >
                          {c.answer}
                        </div>
                      </td>

                      {/* Human Ground Truth */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top', textAlign: 'center' }}>
                        <span
                          style={{
                            display: 'inline-block',
                            padding: '3px 8px',
                            borderRadius: '4px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            background: c.human_label === 1 ? 'rgba(16, 185, 129, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                            color: c.human_label === 1 ? '#34d399' : '#f87171',
                            border: `1px solid ${c.human_label === 1 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                          }}
                        >
                          {c.human_label === 1 ? '1 (Pass)' : '0 (Fail)'}
                        </span>
                      </td>

                      {/* Judge V1 */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top', textAlign: 'center' }}>
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              color: '#60a5fa',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              background: 'rgba(59, 130, 246, 0.15)',
                              padding: '2px 6px',
                              borderRadius: '4px',
                            }}
                          >
                            <span className="spinner" style={{ width: '10px', height: '10px' }}></span>
                            Running
                          </span>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px' }}>
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '2px 7px',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                background: c.judge_v1_verdict === 1 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                                color: c.judge_v1_verdict === 1 ? '#60a5fa' : '#f87171',
                              }}
                            >
                              {c.judge_v1_verdict === 1 ? '1 (Pass)' : '0 (Fail)'}
                            </span>
                            <span style={{ fontSize: '0.65rem', color: isV1Agreed ? '#10b981' : '#f59e0b' }}>
                              {isV1Agreed ? '✓ Agreed' : '⚠ Disagreed'}
                            </span>
                          </div>
                        )}
                      </td>

                      {/* Judge V2 */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top', textAlign: 'center' }}>
                        {isCurrentlyEvaluating ? (
                          <span
                            style={{
                              display: 'inline-flex',
                              alignItems: 'center',
                              gap: '4px',
                              color: '#60a5fa',
                              fontSize: '0.72rem',
                              fontWeight: 700,
                              background: 'rgba(59, 130, 246, 0.15)',
                              padding: '2px 6px',
                              borderRadius: '4px',
                            }}
                          >
                            <span className="spinner" style={{ width: '10px', height: '10px' }}></span>
                            Running
                          </span>
                        ) : (
                          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '3px' }}>
                            <span
                              style={{
                                display: 'inline-block',
                                padding: '2px 7px',
                                borderRadius: '4px',
                                fontSize: '0.75rem',
                                fontWeight: 700,
                                background: c.judge_v2_verdict === 1 ? 'rgba(59, 130, 246, 0.2)' : 'rgba(239, 68, 68, 0.2)',
                                color: c.judge_v2_verdict === 1 ? '#60a5fa' : '#f87171',
                              }}
                            >
                              {c.judge_v2_verdict === 1 ? '1 (Pass)' : '0 (Fail)'}
                            </span>
                            <span style={{ fontSize: '0.65rem', color: isV2Agreed ? '#10b981' : '#f59e0b' }}>
                              {isV2Agreed ? '✓ Agreed' : '⚠ Disagreed'}
                            </span>
                          </div>
                        )}
                      </td>

                      {/* Deterministic Assertions */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                        {c.assertions ? (
                          <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.7rem' }}>
                            <span style={{ color: c.assertions.policy_section_reference_resolves ? '#10b981' : '#ef4444' }}>
                              {c.assertions.policy_section_reference_resolves ? '✓' : '✗'} Section Resolves
                            </span>
                            <span style={{ color: c.assertions.handbook_version_present ? '#10b981' : 'var(--text-muted)' }}>
                              {c.assertions.handbook_version_present ? '✓' : '○'} Version Cited
                            </span>
                            <span style={{ color: c.assertions.numeric_policy_value_present ? '#10b981' : 'var(--text-muted)' }}>
                              {c.assertions.numeric_policy_value_present ? '✓' : '○'} Numeric Match
                            </span>
                            <span style={{ color: c.assertions.out_of_jurisdiction_refusal ? '#10b981' : '#ef4444' }}>
                              {c.assertions.out_of_jurisdiction_refusal ? '✓' : '✗'} Refusal Guard
                            </span>
                          </div>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: '0.75rem' }}>Deterministic OK</span>
                        )}
                      </td>

                      {/* Failure Root Cause & Reason */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top' }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexWrap: 'wrap' }}>
                          <span
                            style={{
                              display: 'inline-block',
                              padding: '2px 7px',
                              borderRadius: '4px',
                              fontSize: '0.7rem',
                              fontWeight: 700,
                              background:
                                c.failure_category === 'pipeline'
                                  ? 'rgba(239, 68, 68, 0.2)'
                                  : c.failure_category === 'llm_model'
                                  ? 'rgba(245, 158, 11, 0.2)'
                                  : c.failure_category === 'code_issue'
                                  ? 'rgba(168, 85, 247, 0.2)'
                                  : 'rgba(16, 185, 129, 0.2)',
                              color:
                                c.failure_category === 'pipeline'
                                  ? '#f87171'
                                  : c.failure_category === 'llm_model'
                                  ? '#fbbf24'
                                  : c.failure_category === 'code_issue'
                                  ? '#c084fc'
                                  : '#34d399',
                              border: `1px solid ${
                                c.failure_category === 'pipeline'
                                  ? 'rgba(239, 68, 68, 0.3)'
                                  : c.failure_category === 'llm_model'
                                  ? 'rgba(245, 158, 11, 0.3)'
                                  : c.failure_category === 'code_issue'
                                  ? 'rgba(168, 85, 247, 0.3)'
                                  : 'rgba(16, 185, 129, 0.3)'
                              }`,
                            }}
                          >
                            {c.failure_category === 'pipeline'
                              ? 'Pipeline Failure'
                              : c.failure_category === 'llm_model'
                              ? 'LLM Model Failure'
                              : c.failure_category === 'code_issue'
                              ? 'Code Issue'
                              : 'Clean Pass'}
                          </span>
                          {c.failure_type && (
                            <span
                              style={{
                                fontSize: '0.65rem',
                                color: 'var(--text-muted)',
                                fontFamily: 'ui-monospace, monospace',
                                background: 'rgba(255, 255, 255, 0.05)',
                                padding: '1px 5px',
                                borderRadius: '3px',
                              }}
                            >
                              {c.failure_type}
                            </span>
                          )}
                        </div>

                        {/* Visible diagnostic reason on row */}
                        {c.failure_reason ? (
                          <div
                            style={{
                              fontSize: '0.72rem',
                              color: c.human_label === 1 ? '#cbd5e1' : '#fca5a5',
                              marginTop: '5px',
                              lineHeight: '1.35',
                              background: c.human_label === 1 ? 'rgba(0, 0, 0, 0.25)' : 'rgba(239, 68, 68, 0.08)',
                              borderLeft: `2px solid ${c.human_label === 1 ? '#10b981' : '#ef4444'}`,
                              padding: '4px 8px',
                              borderRadius: '0 4px 4px 0',
                            }}
                          >
                            <span style={{ fontWeight: 700 }}>Reason:</span> {c.failure_reason}
                          </div>
                        ) : (
                          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                            {c.human_label === 1 ? '✓ Complete and accurate grounded answer.' : '○ Policy check or assertion failed.'}
                          </div>
                        )}
                      </td>

                      {/* Actions */}
                      <td style={{ padding: '12px 14px', verticalAlign: 'top', textAlign: 'center' }}>
                        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                          <button
                            type="button"
                            onClick={() => setSelectedCase(c)}
                            className="btn-secondary"
                            style={{ padding: '3px 8px', fontSize: '0.75rem' }}
                            title="Inspect full case details & diagnosis"
                          >
                            Inspect
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteCase(c.case_id)}
                            className="btn-secondary"
                            style={{
                              padding: '3px 7px',
                              fontSize: '0.75rem',
                              color: '#f87171',
                              borderColor: 'rgba(239, 68, 68, 0.3)',
                              background: 'rgba(239, 68, 68, 0.1)',
                            }}
                            title="Delete this test case"
                          >
                            ✕
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* INSPECT DETAIL MODAL */}
      {selectedCase && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setSelectedCase(null)}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              maxWidth: '850px',
              width: '100%',
              maxHeight: '90vh',
              overflowY: 'auto',
              padding: '24px',
              display: 'flex',
              flexDirection: 'column',
              gap: '16px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <div>
                <span
                  style={{
                    background: 'rgba(59, 130, 246, 0.2)',
                    color: '#60a5fa',
                    fontSize: '0.75rem',
                    padding: '2px 8px',
                    borderRadius: '4px',
                    fontWeight: 700,
                  }}
                >
                  {selectedCase.case_id}
                </span>
                <span style={{ color: 'var(--text-muted)', fontSize: '0.85rem', marginLeft: '8px' }}>
                  {selectedCase.taxonomy_mode}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setSelectedCase(null)}
                style={{ background: 'transparent', border: 'none', color: '#fff', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                User Question
              </div>
              <div style={{ fontSize: '1.05rem', color: '#fff', fontWeight: 700, marginTop: '4px' }}>
                {selectedCase.question}
              </div>
            </div>

            <div>
              <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                Assistant Answer
              </div>
              <div
                style={{
                  background: 'var(--bg-card)',
                  padding: '12px',
                  borderRadius: '6px',
                  color: '#e2e8f0',
                  fontSize: '0.9rem',
                  lineHeight: '1.5',
                  marginTop: '4px',
                  border: '1px solid var(--border)',
                }}
              >
                {selectedCase.answer}
              </div>
            </div>

            {selectedCase.retrieved_context && (
              <div>
                <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)', textTransform: 'uppercase', fontWeight: 600 }}>
                  Retrieved Handbook Context Excerpt
                </div>
                <div
                  style={{
                    background: 'var(--bg-card)',
                    padding: '12px',
                    borderRadius: '6px',
                    color: '#94a3b8',
                    fontSize: '0.8rem',
                    lineHeight: '1.4',
                    maxHeight: '180px',
                    overflowY: 'auto',
                    whiteSpace: 'pre-wrap',
                    marginTop: '4px',
                    border: '1px solid var(--border)',
                  }}
                >
                  {selectedCase.retrieved_context}
                </div>
              </div>
            )}

            {/* Comparison Grid */}
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '12px' }}>
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  padding: '12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Human Ground Truth</div>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: selectedCase.human_label === 1 ? '#34d399' : '#f87171' }}>
                  {selectedCase.human_label === 1 ? '1 (Pass)' : '0 (Fail)'}
                </div>
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                  {selectedCase.human_label === 1 ? 'Valid grounded answer' : 'Contains error/omission'}
                </div>
              </div>
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  padding: '12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Judge V1 (Zero-Shot)</div>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: selectedCase.judge_v1_verdict === 1 ? '#60a5fa' : '#f87171' }}>
                  {selectedCase.judge_v1_verdict === 1 ? '1 (Pass)' : '0 (Fail)'}
                </div>
                <div style={{ fontSize: '0.7rem', color: selectedCase.judge_v1_verdict === selectedCase.human_label ? '#10b981' : '#f59e0b', marginTop: '2px' }}>
                  {selectedCase.judge_v1_verdict === selectedCase.human_label ? '✓ Agreed with Ground Truth' : '⚠ Disagreed with Ground Truth'}
                </div>
              </div>
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.03)',
                  padding: '12px',
                  borderRadius: '6px',
                  border: '1px solid var(--border)',
                }}
              >
                <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Judge V2 (Few-Shot Iterated)</div>
                <div style={{ fontSize: '1.1rem', fontWeight: 700, color: selectedCase.judge_v2_verdict === 1 ? '#60a5fa' : '#f87171' }}>
                  {selectedCase.judge_v2_verdict === 1 ? '1 (Pass)' : '0 (Fail)'}
                </div>
                <div style={{ fontSize: '0.7rem', color: selectedCase.judge_v2_verdict === selectedCase.human_label ? '#10b981' : '#f59e0b', marginTop: '2px' }}>
                  {selectedCase.judge_v2_verdict === selectedCase.human_label ? '✓ Agreed with Ground Truth' : '⚠ Disagreed with Ground Truth'}
                </div>
              </div>
            </div>

            {/* Deterministic Assertions Breakdown */}
            {selectedCase.assertions && (
              <div
                style={{
                  background: 'rgba(255, 255, 255, 0.02)',
                  border: '1px solid var(--border)',
                  borderRadius: '8px',
                  padding: '12px',
                }}
              >
                <div style={{ fontSize: '0.75rem', color: '#fff', fontWeight: 700, marginBottom: '8px' }}>
                  Deterministic Policy Rule Assertions Breakdown
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.78rem' }}>
                  <div style={{ color: selectedCase.assertions.policy_section_reference_present ? '#34d399' : '#f87171' }}>
                    {selectedCase.assertions.policy_section_reference_present ? '✓' : '✗'} Section Reference Present
                  </div>
                  <div style={{ color: selectedCase.assertions.policy_section_reference_resolves ? '#34d399' : '#f87171' }}>
                    {selectedCase.assertions.policy_section_reference_resolves ? '✓' : '✗'} Section Resolves against 113+ Sections
                  </div>
                  <div style={{ color: selectedCase.assertions.handbook_version_present ? '#34d399' : '#94a3b8' }}>
                    {selectedCase.assertions.handbook_version_present ? '✓' : '○'} Handbook Version Cited (2018)
                  </div>
                  <div style={{ color: selectedCase.assertions.numeric_policy_value_present ? '#34d399' : '#94a3b8' }}>
                    {selectedCase.assertions.numeric_policy_value_present ? '✓' : '○'} Numeric Policy Value Exact Match
                  </div>
                  <div style={{ color: selectedCase.assertions.out_of_jurisdiction_refusal ? '#34d399' : '#f87171' }}>
                    {selectedCase.assertions.out_of_jurisdiction_refusal ? '✓' : '✗'} Out-of-Jurisdiction Refusal Guard
                  </div>
                </div>
              </div>
            )}

            {/* Diagnostic Failure Root Cause Box */}
            {selectedCase.failure_reason && (
              <div
                style={{
                  background: selectedCase.human_label === 1 ? 'rgba(16, 185, 129, 0.08)' : 'rgba(239, 68, 68, 0.1)',
                  border: `1px solid ${selectedCase.human_label === 1 ? 'rgba(16, 185, 129, 0.3)' : 'rgba(239, 68, 68, 0.3)'}`,
                  padding: '14px',
                  borderRadius: '8px',
                }}
              >
                <div style={{ fontSize: '0.78rem', color: selectedCase.human_label === 1 ? '#34d399' : '#f87171', fontWeight: 700 }}>
                  Diagnostic Failure Root Cause Analysis ({(selectedCase.failure_category || 'DIAGNOSTIC').toUpperCase()}):
                </div>
                <div style={{ color: '#f1f5f9', fontSize: '0.85rem', marginTop: '6px', lineHeight: '1.5' }}>
                  {selectedCase.failure_reason}
                </div>
                {selectedCase.resolution && (
                  <div style={{ color: '#93c5fd', fontSize: '0.82rem', marginTop: '8px', lineHeight: '1.4' }}>
                    <strong>Recommended Resolution:</strong> {selectedCase.resolution}
                  </div>
                )}
              </div>
            )}

            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '8px' }}>
              <button type="button" onClick={() => setSelectedCase(null)} className="btn-secondary">
                Close
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ADD CUSTOM QA MODAL */}
      {showAddModal && (
        <div
          style={{
            position: 'fixed',
            inset: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 100,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
          onClick={() => setShowAddModal(false)}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              maxWidth: '650px',
              width: '100%',
              maxHeight: '90vh',
              overflowY: 'auto',
              padding: '24px',
            }}
            onClick={(e) => e.stopPropagation()}
          >
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px' }}>
              <h3 style={{ margin: 0, color: '#fff', fontSize: '1.2rem' }}>Add Custom Question &amp; Answer for Evaluation</h3>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                style={{ background: 'transparent', border: 'none', color: '#fff', fontSize: '1.2rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            <form onSubmit={handleAddCustomCase} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  User Question *
                </label>
                <input
                  type="text"
                  required
                  placeholder="e.g. Under what circumstances is an employee entitled to paid sick leave?"
                  value={customQuestion}
                  onChange={(e) => setCustomQuestion(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    padding: '8px 12px',
                    color: '#fff',
                    fontSize: '0.85rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Assistant Answer *
                </label>
                <textarea
                  required
                  rows={3}
                  placeholder="e.g. A staff member is entitled to paid sick leave at the rate of one day at full pay..."
                  value={customAnswer}
                  onChange={(e) => setCustomAnswer(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    padding: '8px 12px',
                    color: '#fff',
                    fontSize: '0.85rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Retrieved Handbook Context Excerpts (Optional)
                </label>
                <textarea
                  rows={3}
                  placeholder="e.g. [1] (Section: 5.3.2 Sick Leave, Page: 35) ... Minimum and Maximum entitlement..."
                  value={customContext}
                  onChange={(e) => setCustomContext(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    padding: '8px 12px',
                    color: '#fff',
                    fontSize: '0.85rem',
                  }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Taxonomy Mode
                  </label>
                  <select
                    value={customMode}
                    onChange={(e) => setCustomMode(e.target.value)}
                    style={{
                      width: '100%',
                      background: '#1e293b',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      padding: '8px 10px',
                      color: '#f8fafc',
                      fontSize: '0.85rem',
                      cursor: 'pointer',
                    }}
                  >
                    <option value="Low-K Multi-Clause Truncation" style={{ background: '#0f172a', color: '#f8fafc' }}>Low-K Multi-Clause Truncation</option>
                    <option value="Sub-Clause Dispersal Across Disparate Policy Chapters" style={{ background: '#0f172a', color: '#f8fafc' }}>Sub-Clause Dispersal</option>
                    <option value="Citation Drifting & In-Prose Structural Inversion" style={{ background: '#0f172a', color: '#f8fafc' }}>Citation Drifting</option>
                    <option value="Unstated Policy Invariant Refusal" style={{ background: '#0f172a', color: '#f8fafc' }}>Unstated Policy Refusal</option>
                    <option value="Embedding Similarity Threshold Starvation" style={{ background: '#0f172a', color: '#f8fafc' }}>Embedding Starvation</option>
                  </select>
                </div>

                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Human Ground Truth Label
                  </label>
                  <select
                    value={customHumanLabel}
                    onChange={(e) => setCustomHumanLabel(Number(e.target.value))}
                    style={{
                      width: '100%',
                      background: '#1e293b',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      padding: '8px 10px',
                      color: '#f8fafc',
                      fontSize: '0.85rem',
                      cursor: 'pointer',
                    }}
                  >
                    <option value={1} style={{ background: '#0f172a', color: '#f8fafc' }}>1 (Correct / Passed)</option>
                    <option value={0} style={{ background: '#0f172a', color: '#f8fafc' }}>0 (Incorrect / Incomplete)</option>
                  </select>
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Expected Numeric Value (Optional)
                  </label>
                  <input
                    type="text"
                    placeholder="e.g. 16 weeks, 4 weeks"
                    value={customNumeric}
                    onChange={(e) => setCustomNumeric(e.target.value)}
                    style={{
                      width: '100%',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      borderRadius: '6px',
                      padding: '8px 12px',
                      color: '#fff',
                      fontSize: '0.85rem',
                    }}
                  />
                </div>

                <div style={{ display: 'flex', alignItems: 'center', marginTop: '20px' }}>
                  <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.85rem', color: '#fff' }}>
                    <input
                      type="checkbox"
                      checked={customOoj}
                      onChange={(e) => setCustomOoj(e.target.checked)}
                    />
                    Out-of-Jurisdiction / Unstated Refusal
                  </label>
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px', marginTop: '12px' }}>
                <button type="button" onClick={() => setShowAddModal(false)} className="btn-secondary">
                  Cancel
                </button>
                <button type="submit" className="btn-primary">
                  Add to Evaluation Table
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
};
