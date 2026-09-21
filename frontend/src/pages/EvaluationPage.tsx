import React, { useState, useEffect, useRef, useCallback } from 'react';
import { EvalQuestionInput, EvalRunResponse } from '../types/evaluation';
import { FormView } from '../components/Evaluation/FormView';
import { ResultsView } from '../components/Evaluation/ResultsView';
import { JudgeEvaluatorView } from '../components/Evaluation/JudgeEvaluatorView';
import { ToastContainer, ToastItem } from '../components/common/ToastContainer';
import { PRESETS } from '../components/Evaluation/KeyTakeaways';
import { api } from '../services/api';
import { generateId } from '../utils/helpers';

export const EvaluationPage: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'week6' | 'retrieval'>('week6');
  const [isJudgeEvaluating, setIsJudgeEvaluating] = useState<boolean>(false);

  // Retrieval Benchmark State
  const [questions, setQuestions] = useState<EvalQuestionInput[]>([
    { id: generateId('q'), question: '', expected: '' },
    { id: generateId('q'), question: '', expected: '' },
    { id: generateId('q'), question: '', expected: '' },
  ]);
  const [topK, setTopK] = useState<number | string>(8);
  const [strategyFilter, setStrategyFilter] = useState<string>('');
  const [presets, setPresets] = useState<Record<string, boolean>>({
    'tfidf': true,
    'bm25-qdrant-blend': true,
    'bm25-qdrant-rrf': true,
    'rrf-rerank': true,
    'rrf-rerank-rewrite': true,
  });
  const [isRunning, setIsRunning] = useState<boolean>(false);
  const [results, setResults] = useState<EvalRunResponse | null>(null);
  const [view, setView] = useState<'form' | 'results'>('form');
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const abortControllerRef = useRef<AbortController | null>(null);
  const toastTimersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const dismissToast = useCallback((id: string) => {
    if (toastTimersRef.current.has(id)) {
      clearTimeout(toastTimersRef.current.get(id));
      toastTimersRef.current.delete(id);
    }
    setToasts((prev) => prev.filter((t) => t.id !== id));
  }, []);

  const showToast = useCallback(
    (message: string, type: 'info' | 'success' | 'error' = 'info', duration = 5000) => {
      const id = generateId('toast');
      setToasts((prev) => [...prev, { id, message, type }]);
      if (duration > 0) {
        const timer = setTimeout(() => {
          dismissToast(id);
        }, duration);
        toastTimersRef.current.set(id, timer);
      }
    },
    [dismissToast]
  );

  useEffect(() => {
    return () => {
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
      toastTimersRef.current.forEach((timer) => clearTimeout(timer));
      toastTimersRef.current.clear();
    };
  }, []);

  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'smooth' });
  }, [view, activeTab]);

  const handleCancel = () => {
    const controller = abortControllerRef.current;
    if (controller) {
      controller.abort();
      abortControllerRef.current = null;
      setIsRunning(false);
      showToast('Retrieval benchmark cancelled by user.', 'info');
    }
  };

  const handleRun = async () => {
    // Validate both question AND expected ground truth
    const invalidEmptyExpected = questions.filter((q) => q.question.trim() && !q.expected.trim());
    if (invalidEmptyExpected.length > 0) {
      showToast('Please provide an expected section/filename substring for all entered questions.', 'error');
      return;
    }

    const validQ = questions.filter((q) => q.question.trim() && q.expected.trim());
    if (!validQ.length) {
      showToast('Please enter at least one question and its expected target substring.', 'error');
      return;
    }

    const active = Object.keys(presets).filter((k) => presets[k]);
    if (!active.length) {
      showToast('Please select at least one retrieval strategy to compare.', 'error');
      return;
    }

    const rawTopK = String(topK).trim();
    if (!/^\d+$/.test(rawTopK)) {
      showToast('Top-K must be a whole number between 1 and 20.', 'error');
      return;
    }
    const kVal = Math.max(1, Math.min(20, Number(rawTopK)));

    setIsRunning(true);

    const controller = new AbortController();
    abortControllerRef.current = controller;

    try {
      const data = await api.runEvaluation(
        {
          questions: validQ.map((q) => ({
            id: q.id,
            question: q.question.trim(),
            expected: q.expected.trim(),
          })),
          top_k: kVal,
          presets: active,
          strategy_filter: strategyFilter,
        },
        controller.signal
      );

      // Response schema and result integrity validation
      if (!data || typeof data !== 'object' || !data.modes || typeof data.modes !== 'object') {
        throw new Error('Malformed evaluation response: missing modes dictionary.');
      }

      const submittedIds = new Set(validQ.map((q) => q.id));
      for (const mk of active) {
        const modeData = data.modes[mk];
        if (!modeData || typeof modeData !== 'object' || !Array.isArray(modeData.results)) {
          throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" missing results array in server response.`);
        }

        modeData.hit_rate =
          typeof modeData.hit_rate === 'number' && !isNaN(modeData.hit_rate)
            ? modeData.hit_rate
            : Number(modeData.hit_rate) || 0;
        modeData.mrr =
          typeof modeData.mrr === 'number' && !isNaN(modeData.mrr)
            ? modeData.mrr
            : Number(modeData.mrr) || 0;
        modeData.hits =
          typeof modeData.hits === 'number' && !isNaN(modeData.hits)
            ? modeData.hits
            : Number(modeData.hits) || 0;
        modeData.total =
          typeof modeData.total === 'number' && !isNaN(modeData.total)
            ? modeData.total
            : Number(modeData.total) || 0;

        const resultIds: string[] = [];
        for (const r of modeData.results) {
          if (!r || typeof r !== 'object' || typeof r.id !== 'string') {
            throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" returned an invalid result item structure.`);
          }
          // Strict boolean hit normalization
          if (typeof r.hit === 'boolean') {
            // Valid boolean
          } else if ((r.hit as unknown) === 1 || (r.hit as unknown) === '1' || (r.hit as unknown) === 'true') {
            r.hit = true;
          } else if ((r.hit as unknown) === 0 || (r.hit as unknown) === '0' || (r.hit as unknown) === 'false') {
            r.hit = false;
          } else {
            throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" returned invalid hit value for question ID "${r.id}".`);
          }

          if (r.rank !== null && r.rank !== undefined) {
            const parsedRank = Number(r.rank);
            r.rank = isNaN(parsedRank) || parsedRank <= 0 ? null : Math.floor(parsedRank);
          } else {
            r.rank = null;
          }
          resultIds.push(r.id);
        }

        const uniqueIds = new Set(resultIds);
        if (uniqueIds.size !== resultIds.length) {
          throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" returned duplicate question IDs.`);
        }
        for (const qId of submittedIds) {
          if (!uniqueIds.has(qId)) {
            throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" did not return a result for question ID "${qId}".`);
          }
        }
        for (const resultId of resultIds) {
          if (!submittedIds.has(resultId)) {
            throw new Error(`Strategy "${PRESETS[mk]?.label || mk}" returned unexpected question ID "${resultId}".`);
          }
        }
      }

      setResults(data);
      setView('results');
      showToast(`Retrieval benchmark evaluated across ${active.length} strategies!`, 'success');
    } catch (e: unknown) {
      const err = e as Error;
      if (err.name !== 'AbortError') {
        showToast('Evaluation Integrity Error: ' + err.message, 'error');
      }
    } finally {
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
        setIsRunning(false);
      }
    }
  };

  const goToForm = () => {
    setView('form');
  };

  const goToResults = () => {
    setView('results');
  };

  const handleClear = () => {
    setResults(null);
    setView('form');
    showToast('Evaluation results cleared.', 'info');
  };

  return (
    <div className="eval-root">
      <ToastContainer toasts={toasts} onDismiss={dismissToast} />

      {/* TOPBAR */}
      <header
        style={{
          position: 'sticky',
          top: 0,
          zIndex: 50,
          background: 'var(--bg-surface)',
          borderBottom: '1px solid var(--border)',
          padding: '12px 28px',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div>
          <div style={{ fontSize: '0.95rem', fontWeight: 700, color: '#fff' }}>Evaluation Hub</div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            LLM Judges (V1 vs V2), Deterministic Assertions &amp; Retrieval Benchmarks
          </div>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <button
            type="button"
            onClick={() => setActiveTab('week6')}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer',
              border: activeTab === 'week6' ? '1px solid var(--accent)' : '1px solid var(--border)',
              background: activeTab === 'week6' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
              color: activeTab === 'week6' ? '#60a5fa' : 'var(--text-muted)',
              transition: 'all 0.15s ease',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>⚖️ Judge Evaluator</span>
            {isJudgeEvaluating && (
              <span
                style={{
                  background: 'rgba(245, 158, 11, 0.2)',
                  color: '#fbbf24',
                  fontSize: '0.7rem',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  fontWeight: 700,
                  animation: 'pulse 1.5s infinite',
                }}
              >
                ⚡ Running...
              </span>
            )}
          </button>

          <button
            type="button"
            onClick={() => setActiveTab('retrieval')}
            style={{
              padding: '6px 14px',
              borderRadius: '6px',
              fontSize: '0.85rem',
              fontWeight: 600,
              cursor: 'pointer',
              border: activeTab === 'retrieval' ? '1px solid var(--accent)' : '1px solid var(--border)',
              background: activeTab === 'retrieval' ? 'rgba(59, 130, 246, 0.15)' : 'transparent',
              color: activeTab === 'retrieval' ? '#60a5fa' : 'var(--text-muted)',
              transition: 'all 0.15s ease',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>📊 Retrieval Benchmark (Recall@K)</span>
            {isRunning && (
              <span
                style={{
                  background: 'rgba(245, 158, 11, 0.2)',
                  color: '#fbbf24',
                  fontSize: '0.7rem',
                  padding: '1px 6px',
                  borderRadius: '4px',
                  fontWeight: 700,
                  animation: 'pulse 1.5s infinite',
                }}
              >
                ⚡ Running...
              </span>
            )}
          </button>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          {activeTab === 'retrieval' && view === 'form' && results && (
            <button
              type="button"
              onClick={goToResults}
              className="btn-secondary"
              style={{ borderColor: 'var(--accent)', color: 'var(--accent)' }}
            >
              View Results →
            </button>
          )}

          <a href="/" className="btn-secondary">
            ← Back to chat
          </a>
        </div>
      </header>

      {/* MAIN CONTENT WITH PERSISTENT DUAL-TAB DOM MOUNTING */}
      <main style={{ maxWidth: '1200px', width: '100%', margin: '0 auto', padding: '28px 20px 50px 20px', flex: 1 }}>
        {/* TAB 1: JUDGE EVALUATOR */}
        <div style={{ display: activeTab === 'week6' ? 'block' : 'none' }}>
          <JudgeEvaluatorView
            onNotify={showToast}
            onEvaluatingChange={setIsJudgeEvaluating}
          />
        </div>

        {/* TAB 2: RETRIEVAL BENCHMARK */}
        <div style={{ display: activeTab === 'retrieval' ? 'block' : 'none', maxWidth: '1000px', margin: '0 auto' }}>
          {view === 'form' ? (
            <FormView
              questions={questions}
              setQuestions={setQuestions}
              topK={topK}
              setTopK={setTopK}
              strategyFilter={strategyFilter}
              setStrategyFilter={setStrategyFilter}
              presets={presets}
              setPresets={setPresets}
              onRun={handleRun}
              onCancel={handleCancel}
              isRunning={isRunning}
              onNotify={showToast}
            />
          ) : (
            <ResultsView results={results} onBack={goToForm} onClear={handleClear} />
          )}
        </div>
      </main>
    </div>
  );
};
