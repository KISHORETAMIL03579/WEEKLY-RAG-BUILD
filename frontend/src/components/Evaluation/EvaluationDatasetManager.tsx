// frontend/src/components/Evaluation/EvaluationDatasetManager.tsx — Enterprise Dataset Management & Modal Authoring for All Evaluators
import React, { useState, useRef, useEffect } from 'react';
import { api } from '../../services/api';
import { QADataSetCase, DatasetParseResult, DatasetMode, DatasetInvalidCase } from '../../types/dataset';

interface EvaluationDatasetManagerProps {
  evaluatorType: 'judge' | 'retrieval' | 'policy';
  title: string;
  builtinCount: number;
  builtinLabel?: string;
  datasetMode: DatasetMode;
  customCases: QADataSetCase[];
  isRunning?: boolean;
  onModeChange: (mode: DatasetMode) => void;
  onCustomCasesChange: (cases: QADataSetCase[]) => void;
  onResetToBuiltin: () => void;
  onNotify: (msg: string, type?: 'info' | 'success' | 'error') => void;
  storageKey?: string;
}

export const EvaluationDatasetManager: React.FC<EvaluationDatasetManagerProps> = ({
  evaluatorType,
  title,
  builtinCount,
  builtinLabel = 'Canonical Benchmark',
  datasetMode,
  customCases,
  isRunning = false,
  onModeChange,
  onCustomCasesChange,
  onResetToBuiltin,
  onNotify,
  storageKey,
}) => {
  const actualStorageKey = storageKey || `${evaluatorType}_custom_dataset`;
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Pre-import Validation Modal State
  const [showValidationModal, setShowValidationModal] = useState<boolean>(false);
  const [parseResult, setParseResult] = useState<DatasetParseResult | null>(null);
  const [isParsingFile, setIsParsingFile] = useState<boolean>(false);

  // Manual Add/Edit Case Modal State
  const [showEditModal, setShowEditModal] = useState<boolean>(false);
  const [editingCase, setEditingCase] = useState<QADataSetCase | null>(null);
  const [isNewCase, setIsNewCase] = useState<boolean>(false);

  // View Answer Modal State
  const [viewingCase, setViewingCase] = useState<QADataSetCase | null>(null);

  // Table expanded / collapsed state
  const [showCasesDrawer, setShowCasesDrawer] = useState<boolean>(false);

  // Load custom cases from localStorage on mount
  useEffect(() => {
    try {
      const saved = localStorage.getItem(actualStorageKey);
      if (saved) {
        const parsed = JSON.parse(saved);
        if (Array.isArray(parsed) && parsed.length > 0) {
          onCustomCasesChange(parsed);
        }
      }
    } catch (err) {
      console.warn('Failed to load custom dataset from storage:', err);
    }
  }, [actualStorageKey]);

  // Ensure active mode is always 'builtin' (Canonical) when customCases is empty
  useEffect(() => {
    if (datasetMode === 'custom' && customCases.length === 0) {
      onModeChange('builtin');
    }
  }, [datasetMode, customCases.length, onModeChange]);

  // Save custom cases to localStorage on change
  const saveCases = (newCases: QADataSetCase[]) => {
    onCustomCasesChange(newCases);
    try {
      localStorage.setItem(actualStorageKey, JSON.stringify(newCases));
    } catch (err) {
      console.warn('Failed to save custom dataset to storage:', err);
    }
  };

  // 1. File Upload & Pre-Import Validation
  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setIsParsingFile(true);
    try {
      const res = await api.parseEvaluationDataset(file, evaluatorType);
      setParseResult(res);
      setShowValidationModal(true);
      if (res.warnings && res.warnings.length > 0) {
        onNotify(`Dataset parsed with ${res.warnings.length} notice(s)`, 'info');
      }
    } catch (err: any) {
      onNotify(`Failed to parse dataset file: ${err.message || err}`, 'error');
    } finally {
      setIsParsingFile(false);
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const handleConfirmImport = () => {
    if (!parseResult || !parseResult.valid_cases || parseResult.valid_cases.length === 0) {
      onNotify('No valid cases to import', 'error');
      setShowValidationModal(false);
      return;
    }

    const imported = parseResult.valid_cases;
    saveCases(imported);
    onModeChange('custom');
    setShowValidationModal(false);
    setShowCasesDrawer(true);
    onNotify(`Successfully imported ${imported.length} valid cases into custom dataset`, 'success');
  };

  // 2. Add / Edit Handlers
  const handleOpenAdd = () => {
    if (isRunning) return;
    const nextIdx = customCases.length + 1;
    const newCase: QADataSetCase = {
      case_id: `CASE_${String(nextIdx).padStart(2, '0')}`,
      question: '',
      expected_answer: '',
      employee_id: evaluatorType === 'policy' ? 'EMP001' : undefined,
      expected_section: '',
    };
    setEditingCase(newCase);
    setIsNewCase(true);
    setShowEditModal(true);
  };

  const handleOpenEdit = (c: QADataSetCase) => {
    if (isRunning) return;
    setEditingCase({ ...c });
    setIsNewCase(false);
    setShowEditModal(true);
  };

  const handleSaveEdit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!editingCase) return;
    if (!editingCase.question.trim()) {
      onNotify('Question is required', 'error');
      return;
    }
    if (evaluatorType !== 'retrieval' && !editingCase.expected_answer?.trim()) {
      onNotify('Expected answer is required', 'error');
      return;
    }

    let updated: QADataSetCase[];
    if (isNewCase) {
      // Check ID conflict
      const exists = customCases.some((c) => c.case_id === editingCase.case_id);
      const safeId = exists ? `${editingCase.case_id}_${customCases.length + 1}` : editingCase.case_id;
      updated = [...customCases, { ...editingCase, case_id: safeId }];
    } else {
      updated = customCases.map((c) => (c.case_id === editingCase.case_id ? editingCase : c));
    }

    saveCases(updated);
    if (datasetMode !== 'custom') onModeChange('custom');
    setShowEditModal(false);
    setEditingCase(null);
    onNotify(isNewCase ? `Added case ${editingCase.case_id}` : `Updated case ${editingCase.case_id}`, 'success');
  };

  // 3. Duplicate & Delete Handlers
  const handleDuplicateCase = (c: QADataSetCase) => {
    if (isRunning) return;
    const newId = `${c.case_id}_copy`;
    const dup: QADataSetCase = {
      ...c,
      case_id: newId,
    };
    const updated = [...customCases, dup];
    saveCases(updated);
    if (datasetMode !== 'custom') onModeChange('custom');
    onNotify(`Duplicated case as ${newId}`, 'info');
  };

  const handleDeleteCase = (caseId: string) => {
    if (isRunning) return;
    const updated = customCases.filter((c) => c.case_id !== caseId);
    saveCases(updated);
    onNotify(`Deleted case ${caseId}`, 'info');
  };

  const handleClearCustom = () => {
    if (isRunning) return;
    saveCases([]);
    localStorage.removeItem(actualStorageKey);
    onResetToBuiltin();
    onNotify('Cleared custom dataset. Switched back to canonical benchmark.', 'info');
  };

  return (
    <div
      style={{
        background: 'var(--bg-surface)',
        border: '1px solid var(--border)',
        borderRadius: '10px',
        padding: '16px 20px',
        marginBottom: '20px',
        display: 'flex',
        flexDirection: 'column',
        gap: '14px',
      }}
    >
      {/* Top Bar: Title, Dataset Mode Selector & Action Buttons */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <span style={{ fontSize: '1.15rem' }}>📁</span>
          <div>
            <div style={{ fontWeight: 600, fontSize: '0.95rem', color: '#fff' }}>{title} Dataset Input</div>
            <div style={{ fontSize: '0.78rem', color: 'var(--text-muted)' }}>
              Currently active: <strong style={{ color: '#60a5fa' }}>{datasetMode === 'custom' ? `Custom Dataset (${customCases.length} cases)` : `${builtinLabel} (${builtinCount} cases)`}</strong>
            </div>
          </div>
        </div>

        {/* Action Controls */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
          {/* Mode Pill Toggle */}
          <div
            style={{
              display: 'flex',
              background: 'var(--bg-card)',
              padding: '2px',
              borderRadius: '6px',
              border: '1px solid var(--border)',
            }}
          >
            <button
              type="button"
              disabled={isRunning}
              onClick={() => onModeChange('builtin')}
              style={{
                padding: '4px 10px',
                fontSize: '0.78rem',
                border: 'none',
                borderRadius: '4px',
                background: datasetMode === 'builtin' ? 'var(--accent)' : 'transparent',
                color: datasetMode === 'builtin' ? '#fff' : 'var(--text-muted)',
                cursor: isRunning ? 'not-allowed' : 'pointer',
                fontWeight: 600,
              }}
            >
              Canonical ({builtinCount})
            </button>
            <button
              type="button"
              disabled={isRunning}
              onClick={() => {
                if (customCases.length === 0) {
                  onNotify('Custom dataset is empty. Click "Import Q&A File" or "+ Add Case" to add custom test cases.', 'info');
                  return;
                }
                onModeChange('custom');
              }}
              style={{
                padding: '4px 10px',
                fontSize: '0.78rem',
                border: 'none',
                borderRadius: '4px',
                background: datasetMode === 'custom' && customCases.length > 0 ? 'var(--accent)' : 'transparent',
                color: datasetMode === 'custom' && customCases.length > 0 ? '#fff' : 'var(--text-muted)',
                cursor: isRunning ? 'not-allowed' : (customCases.length === 0 ? 'default' : 'pointer'),
                fontWeight: 600,
              }}
              title={customCases.length === 0 ? 'No custom cases yet. Import or add cases first.' : 'Switch to Custom Dataset'}
            >
              Custom ({customCases.length})
            </button>
          </div>

          {/* Import File Button */}
          <input
            ref={fileInputRef}
            type="file"
            accept=".json,.txt,.md"
            style={{ display: 'none' }}
            onChange={handleFileSelect}
            disabled={isRunning || isParsingFile}
          />
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            disabled={isRunning || isParsingFile}
            style={{
              padding: '6px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              background: 'rgba(59, 130, 246, 0.12)',
              color: '#60a5fa',
              border: '1px solid rgba(59, 130, 246, 0.3)',
              borderRadius: '6px',
              cursor: isRunning || isParsingFile ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>📥</span> {isParsingFile ? 'Validating...' : 'Import Q&A File (.json, .txt, .md)'}
          </button>

          {/* Add Case Button */}
          <button
            type="button"
            onClick={handleOpenAdd}
            disabled={isRunning}
            style={{
              padding: '6px 12px',
              fontSize: '0.78rem',
              fontWeight: 600,
              background: 'rgba(16, 185, 129, 0.12)',
              color: '#34d399',
              border: '1px solid rgba(16, 185, 129, 0.3)',
              borderRadius: '6px',
              cursor: isRunning ? 'not-allowed' : 'pointer',
              display: 'flex',
              alignItems: 'center',
              gap: '6px',
            }}
          >
            <span>➕</span> Add Case
          </button>

          {/* Toggle Table Drawer */}
          {customCases.length > 0 && (
            <button
              type="button"
              onClick={() => setShowCasesDrawer(!showCasesDrawer)}
              style={{
                padding: '6px 12px',
                fontSize: '0.78rem',
                fontWeight: 500,
                background: 'var(--bg-card)',
                color: 'var(--text-muted)',
                border: '1px solid var(--border)',
                borderRadius: '6px',
                cursor: 'pointer',
              }}
            >
              {showCasesDrawer ? 'Hide Custom Cases ▲' : `Manage Custom Cases (${customCases.length}) ▼`}
            </button>
          )}

          {/* Reset / Clear Button */}
          {customCases.length > 0 && (
            <button
              type="button"
              onClick={handleClearCustom}
              disabled={isRunning}
              style={{
                padding: '6px 10px',
                fontSize: '0.75rem',
                color: '#ef4444',
                background: 'transparent',
                border: '1px solid rgba(239, 68, 68, 0.3)',
                borderRadius: '6px',
                cursor: isRunning ? 'not-allowed' : 'pointer',
              }}
              title="Clear custom dataset and switch back to canonical benchmark"
            >
              Reset to Canonical
            </button>
          )}
        </div>
      </div>

      {/* Safety Notice during Benchmark Execution */}
      {isRunning && (
        <div style={{ fontSize: '0.75rem', color: '#fbbf24', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <span>🔒</span> Benchmark execution active. Dataset modifications are locked until execution finishes.
        </div>
      )}

      {/* Custom Cases Interactive Drawer / Table */}
      {showCasesDrawer && customCases.length > 0 && (
        <div
          style={{
            marginTop: '8px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '8px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              padding: '10px 14px',
              background: 'rgba(255, 255, 255, 0.02)',
              borderBottom: '1px solid var(--border)',
              display: 'flex',
              justifyContent: 'space-between',
              alignItems: 'center',
            }}
          >
            <span style={{ fontSize: '0.8rem', fontWeight: 600, color: 'var(--text-muted)' }}>
              Custom Dataset ({customCases.length} Cases Loaded)
            </span>
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>
              Zero-Leakage Protection: Expected answers are isolated from LLM context
            </span>
          </div>

          <div style={{ maxHeight: '280px', overflowY: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: 'rgba(0, 0, 0, 0.2)', borderBottom: '1px solid var(--border)', textAlign: 'left' }}>
                  <th style={{ padding: '8px 12px', width: '100px' }}>Case ID</th>
                  {evaluatorType === 'policy' && <th style={{ padding: '8px 12px', width: '90px' }}>Emp ID</th>}
                  <th style={{ padding: '8px 12px' }}>Question</th>
                  <th style={{ padding: '8px 12px', width: '120px' }}>Ground Truth</th>
                  <th style={{ padding: '8px 12px', width: '160px', textAlign: 'right' }}>Actions</th>
                </tr>
              </thead>
              <tbody>
                {customCases.map((c, idx) => (
                  <tr
                    key={c.case_id || idx}
                    style={{
                      borderBottom: '1px solid var(--border)',
                      background: idx % 2 === 0 ? 'transparent' : 'rgba(255, 255, 255, 0.01)',
                    }}
                  >
                    <td style={{ padding: '8px 12px', fontFamily: 'monospace', fontWeight: 600, color: '#60a5fa' }}>
                      {c.case_id}
                    </td>
                    {evaluatorType === 'policy' && (
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{c.employee_id || 'EMP001'}</td>
                    )}
                    <td style={{ padding: '8px 12px', maxWidth: '350px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                      {c.question}
                    </td>
                    <td style={{ padding: '8px 12px' }}>
                      <button
                        type="button"
                        onClick={() => setViewingCase(c)}
                        style={{
                          padding: '3px 8px',
                          fontSize: '0.72rem',
                          background: 'rgba(255, 255, 255, 0.06)',
                          border: '1px solid var(--border)',
                          borderRadius: '4px',
                          color: '#34d399',
                          cursor: 'pointer',
                        }}
                      >
                        👁 View Answer
                      </button>
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right' }}>
                      <div style={{ display: 'inline-flex', gap: '6px' }}>
                        <button
                          type="button"
                          onClick={() => handleOpenEdit(c)}
                          disabled={isRunning}
                          style={{
                            padding: '3px 7px',
                            fontSize: '0.72rem',
                            background: 'transparent',
                            border: '1px solid var(--border)',
                            borderRadius: '4px',
                            color: 'var(--text-muted)',
                            cursor: isRunning ? 'not-allowed' : 'pointer',
                          }}
                        >
                          Edit
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDuplicateCase(c)}
                          disabled={isRunning}
                          style={{
                            padding: '3px 7px',
                            fontSize: '0.72rem',
                            background: 'transparent',
                            border: '1px solid var(--border)',
                            borderRadius: '4px',
                            color: 'var(--text-muted)',
                            cursor: isRunning ? 'not-allowed' : 'pointer',
                          }}
                        >
                          Duplicate
                        </button>
                        <button
                          type="button"
                          onClick={() => handleDeleteCase(c.case_id)}
                          disabled={isRunning}
                          style={{
                            padding: '3px 7px',
                            fontSize: '0.72rem',
                            background: 'transparent',
                            border: '1px solid rgba(239, 68, 68, 0.3)',
                            borderRadius: '4px',
                            color: '#ef4444',
                            cursor: isRunning ? 'not-allowed' : 'pointer',
                          }}
                        >
                          ✕
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* =========================================================================
          MODAL 1: PRE-IMPORT VALIDATION MODAL
          ========================================================================= */}
      {showValidationModal && parseResult && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              width: '100%',
              maxWidth: '640px',
              maxHeight: '90vh',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
              overflow: 'hidden',
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                <span style={{ fontSize: '1.2rem' }}>📋</span>
                <span style={{ fontWeight: 600, fontSize: '1rem', color: '#fff' }}>
                  Pre-Import Dataset Validation — {parseResult.filename}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setShowValidationModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.1rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* Body */}
            <div style={{ padding: '20px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '16px' }}>
              {/* Validation Stats Grid */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: '12px',
                  background: 'var(--bg-card)',
                  padding: '14px',
                  borderRadius: '8px',
                  border: '1px solid var(--border)',
                  textAlign: 'center',
                }}
              >
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Total Found</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#fff' }}>{parseResult.total_found}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Valid Rows</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: '#34d399' }}>{parseResult.valid_count}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Invalid Rows</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: parseResult.invalid_count > 0 ? '#ef4444' : 'var(--text-muted)' }}>
                    {parseResult.invalid_count}
                  </div>
                </div>
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase' }}>Duplicate IDs</div>
                  <div style={{ fontSize: '1.25rem', fontWeight: 700, color: parseResult.duplicate_count > 0 ? '#fbbf24' : 'var(--text-muted)' }}>
                    {parseResult.duplicate_count}
                  </div>
                </div>
              </div>

              {/* Warnings / Notices */}
              {parseResult.warnings && parseResult.warnings.length > 0 && (
                <div
                  style={{
                    background: 'rgba(251, 191, 36, 0.1)',
                    border: '1px solid rgba(251, 191, 36, 0.3)',
                    borderRadius: '8px',
                    padding: '12px 14px',
                  }}
                >
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#fbbf24', marginBottom: '6px' }}>
                    Auto-Disambiguation & Warnings ({parseResult.warnings.length}):
                  </div>
                  <ul style={{ margin: 0, paddingLeft: '18px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                    {parseResult.warnings.slice(0, 5).map((w, i) => (
                      <li key={i}>{w}</li>
                    ))}
                    {parseResult.warnings.length > 5 && <li>...and {parseResult.warnings.length - 5} more</li>}
                  </ul>
                </div>
              )}

              {/* Invalid Rows Section */}
              {parseResult.invalid_cases && parseResult.invalid_cases.length > 0 && (
                <div
                  style={{
                    background: 'rgba(239, 68, 68, 0.08)',
                    border: '1px solid rgba(239, 68, 68, 0.25)',
                    borderRadius: '8px',
                    padding: '12px 14px',
                  }}
                >
                  <div style={{ fontSize: '0.8rem', fontWeight: 600, color: '#ef4444', marginBottom: '6px' }}>
                    Invalid Cases Skipped ({parseResult.invalid_cases.length}):
                  </div>
                  <div style={{ maxHeight: '120px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {parseResult.invalid_cases.map((inv: DatasetInvalidCase, idx: number) => (
                      <div key={idx} style={{ fontSize: '0.74rem', color: 'var(--text-muted)' }}>
                        <strong>Row {inv.row}:</strong> {inv.reason}
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Preview of first 3 valid cases */}
              {parseResult.valid_cases && parseResult.valid_cases.length > 0 && (
                <div>
                  <div style={{ fontSize: '0.78rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '8px' }}>
                    Sample Valid Cases Preview:
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {parseResult.valid_cases.slice(0, 3).map((vc, i) => (
                      <div
                        key={i}
                        style={{
                          background: 'var(--bg-card)',
                          padding: '8px 12px',
                          borderRadius: '6px',
                          border: '1px solid var(--border)',
                          fontSize: '0.76rem',
                        }}
                      >
                        <div style={{ color: '#60a5fa', fontWeight: 600, marginBottom: '2px' }}>{vc.case_id}</div>
                        <div style={{ color: '#fff', marginBottom: '2px' }}>{vc.question}</div>
                        <div style={{ color: 'var(--text-muted)', fontSize: '0.72rem' }}>
                          Target: {vc.expected_answer || vc.expected_section || 'N/A'}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Footer Buttons */}
            <div
              style={{
                padding: '14px 20px',
                borderTop: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '10px',
              }}
            >
              <button
                type="button"
                onClick={() => setShowValidationModal(false)}
                style={{
                  padding: '8px 16px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.82rem',
                }}
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={handleConfirmImport}
                disabled={parseResult.valid_count === 0}
                style={{
                  padding: '8px 18px',
                  background: parseResult.valid_count > 0 ? 'var(--accent)' : 'var(--bg-card)',
                  color: parseResult.valid_count > 0 ? '#fff' : 'var(--text-muted)',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: parseResult.valid_count > 0 ? 'pointer' : 'not-allowed',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                }}
              >
                Import {parseResult.valid_count} Valid Cases
              </button>
            </div>
          </div>
        </div>
      )}

      {/* =========================================================================
          MODAL 2: MANUAL ADD / EDIT CASE MODAL
          ========================================================================= */}
      {showEditModal && editingCase && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <form
            onSubmit={handleSaveEdit}
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              width: '100%',
              maxWidth: '560px',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
              overflow: 'hidden',
            }}
          >
            {/* Header */}
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <div style={{ fontWeight: 600, fontSize: '0.98rem', color: '#fff' }}>
                {isNewCase ? '➕ Add New Evaluation Case' : `✏️ Edit Case ${editingCase.case_id}`}
              </div>
              <button
                type="button"
                onClick={() => setShowEditModal(false)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.1rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>

            {/* Inputs */}
            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Case ID
                </label>
                <input
                  type="text"
                  value={editingCase.case_id}
                  onChange={(e) => setEditingCase({ ...editingCase, case_id: e.target.value })}
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
                  }}
                  required
                />
              </div>

              {evaluatorType === 'policy' && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                    Employee ID (e.g. EMP001 – EMP010)
                  </label>
                  <input
                    type="text"
                    value={editingCase.employee_id || 'EMP001'}
                    onChange={(e) => setEditingCase({ ...editingCase, employee_id: e.target.value })}
                    style={{
                      width: '100%',
                      padding: '8px 12px',
                      borderRadius: '6px',
                      background: 'var(--bg-card)',
                      border: '1px solid var(--border)',
                      color: '#fff',
                      fontSize: '0.82rem',
                    }}
                  />
                </div>
              )}

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Question / Evaluation Query
                </label>
                <textarea
                  rows={3}
                  value={editingCase.question}
                  onChange={(e) => setEditingCase({ ...editingCase, question: e.target.value })}
                  placeholder="Enter evaluation question..."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
                  }}
                  required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Expected Ground Truth Answer {evaluatorType === 'retrieval' ? '(Optional in Retrieval)' : '(Required)'}
                </label>
                <textarea
                  rows={3}
                  value={editingCase.expected_answer || ''}
                  onChange={(e) => setEditingCase({ ...editingCase, expected_answer: e.target.value })}
                  placeholder="Enter expected ground truth answer or entitlement..."
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
                  }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 600, color: 'var(--text-muted)', marginBottom: '4px' }}>
                  Target Policy Section (Optional)
                </label>
                <input
                  type="text"
                  value={editingCase.expected_section || ''}
                  onChange={(e) => setEditingCase({ ...editingCase, expected_section: e.target.value })}
                  placeholder="e.g. Section 5.2.1: Annual Leave"
                  style={{
                    width: '100%',
                    padding: '8px 12px',
                    borderRadius: '6px',
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    color: '#fff',
                    fontSize: '0.82rem',
                  }}
                />
              </div>
            </div>

            {/* Footer Buttons */}
            <div
              style={{
                padding: '14px 20px',
                borderTop: '1px solid var(--border)',
                display: 'flex',
                justifyContent: 'flex-end',
                gap: '10px',
              }}
            >
              <button
                type="button"
                onClick={() => setShowEditModal(false)}
                style={{
                  padding: '8px 16px',
                  background: 'transparent',
                  border: '1px solid var(--border)',
                  color: 'var(--text-muted)',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.82rem',
                }}
              >
                Cancel
              </button>
              <button
                type="submit"
                style={{
                  padding: '8px 18px',
                  background: 'var(--accent)',
                  color: '#fff',
                  border: 'none',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.82rem',
                  fontWeight: 600,
                }}
              >
                Save Case
              </button>
            </div>
          </form>
        </div>
      )}

      {/* =========================================================================
          MODAL 3: VIEW ANSWER MODAL
          ========================================================================= */}
      {viewingCase && (
        <div
          style={{
            position: 'fixed',
            top: 0,
            left: 0,
            right: 0,
            bottom: 0,
            background: 'rgba(0, 0, 0, 0.75)',
            zIndex: 9999,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            padding: '20px',
          }}
        >
          <div
            style={{
              background: 'var(--bg-surface)',
              border: '1px solid var(--border)',
              borderRadius: '12px',
              width: '100%',
              maxWidth: '500px',
              display: 'flex',
              flexDirection: 'column',
              boxShadow: '0 20px 40px rgba(0, 0, 0, 0.6)',
              overflow: 'hidden',
            }}
          >
            <div
              style={{
                padding: '16px 20px',
                borderBottom: '1px solid var(--border)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'space-between',
              }}
            >
              <span style={{ fontWeight: 600, fontSize: '0.95rem', color: '#fff' }}>
                Ground Truth for {viewingCase.case_id}
              </span>
              <button
                type="button"
                onClick={() => setViewingCase(null)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: '1.1rem', cursor: 'pointer' }}
              >
                ✕
              </button>
            </div>
            <div style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
                  Question:
                </div>
                <div style={{ fontSize: '0.85rem', color: '#fff' }}>{viewingCase.question}</div>
              </div>
              <div>
                <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
                  Expected Answer / Entitlement:
                </div>
                <div
                  style={{
                    background: 'var(--bg-card)',
                    border: '1px solid var(--border)',
                    borderRadius: '6px',
                    padding: '10px 12px',
                    fontSize: '0.85rem',
                    color: '#34d399',
                    fontFamily: 'monospace',
                    whiteSpace: 'pre-wrap',
                  }}
                >
                  {viewingCase.expected_answer || 'No expected answer set'}
                </div>
              </div>
              {viewingCase.expected_section && (
                <div>
                  <div style={{ fontSize: '0.72rem', color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: '4px' }}>
                    Expected Document / Section:
                  </div>
                  <div style={{ fontSize: '0.82rem', color: '#60a5fa' }}>{viewingCase.expected_section}</div>
                </div>
              )}
            </div>
            <div style={{ padding: '12px 20px', borderTop: '1px solid var(--border)', display: 'flex', justifyContent: 'flex-end' }}>
              <button
                type="button"
                onClick={() => setViewingCase(null)}
                style={{
                  padding: '6px 14px',
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  color: '#fff',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  fontSize: '0.8rem',
                }}
              >
                Close
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
