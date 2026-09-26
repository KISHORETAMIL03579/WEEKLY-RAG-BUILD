import React, { useState } from "react";
import { EvalQuestionInput } from "../../types/evaluation";
import { PRESETS } from "./KeyTakeaways";
import { CANONICAL_RETRIEVAL_QUESTIONS } from "../../data/canonicalRetrievalQuestions";
import { EvaluationProgressCard } from "./EvaluationProgressCard";
import { EvaluationDatasetManager } from "./EvaluationDatasetManager";
import { QADataSetCase, DatasetMode } from "../../types/dataset";
import { Card } from "../common/Card";

interface FormViewProps {
  questions: EvalQuestionInput[];
  setQuestions: React.Dispatch<React.SetStateAction<EvalQuestionInput[]>>;
  topK: number | string;
  setTopK: (k: number | string) => void;
  strategyFilter: string;
  setStrategyFilter: (s: string) => void;
  presets: Record<string, boolean>;
  setPresets: React.Dispatch<React.SetStateAction<Record<string, boolean>>>;
  onRun: () => void;
  onCancel: () => void;
  isRunning: boolean;
  onNotify?: (msg: string, type?: "info" | "success" | "error") => void;
}

export const FormView: React.FC<FormViewProps> = ({
  questions,
  setQuestions,
  topK,
  setTopK,
  strategyFilter,
  setStrategyFilter,
  presets,
  setPresets,
  onRun,
  onCancel,
  isRunning,
  onNotify,
}) => {
  // Common Dataset State
  const [datasetMode, setDatasetMode] = useState<DatasetMode>("builtin");
  const [customDatasetCases, setCustomDatasetCases] = useState<QADataSetCase[]>(
    [],
  );

  const handleCustomCasesChange = (cases: QADataSetCase[]) => {
    setCustomDatasetCases(cases);
    if (datasetMode === "custom") {
      const mapped: EvalQuestionInput[] = cases.map((c) => ({
        id: c.case_id,
        question: c.question,
        expected: c.expected_answer || c.expected || "",
        expected_section: c.expected_section || "",
      }));
      setQuestions(mapped);
    }
  };

  const handleModeChange = (mode: DatasetMode) => {
    setDatasetMode(mode);
    if (mode === "builtin") {
      setQuestions(CANONICAL_RETRIEVAL_QUESTIONS);
      notify("Switched to Canonical Retrieval Benchmark dataset.", "info");
    } else {
      const mapped: EvalQuestionInput[] = customDatasetCases.map((c) => ({
        id: c.case_id,
        question: c.question,
        expected: c.expected_answer || c.expected || "",
        expected_section: c.expected_section || "",
      }));
      setQuestions(mapped);
      notify(
        `Switched to Custom Dataset (${customDatasetCases.length} cases loaded).`,
        "info",
      );
    }
  };

  const notify = (msg: string, type: "info" | "success" | "error" = "info") => {
    if (onNotify) {
      onNotify(msg, type);
    } else {
      alert(msg);
    }
  };

  const resetToCanonical = () => {
    setQuestions(CANONICAL_RETRIEVAL_QUESTIONS);
    notify("Reset to canonical 25-case benchmark questions.", "info");
  };

  const toggleP = (key: string) => {
    setPresets((prev) => ({ ...prev, [key]: !prev[key] }));
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: "20px" }}>
      {/* HERO BANNER & PRIMARY EXECUTION CTA */}
      <Card
        style={{
          background:
            "linear-gradient(135deg, rgba(30, 41, 59, 0.7) 0%, rgba(15, 23, 42, 0.9) 100%)",
          border: "1px solid var(--border)",
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          flexWrap: "wrap",
          gap: "16px",
        }}
      >
        <div>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              gap: "8px",
              marginBottom: "4px",
            }}
          >
            <span
              style={{
                fontSize: "0.72rem",
                fontWeight: 700,
                textTransform: "uppercase",
                letterSpacing: "0.06em",
                color: "var(--accent)",
                background: "var(--accent-dim)",
                padding: "2px 8px",
                borderRadius: "4px",
                border: "1px solid rgba(59, 130, 246, 0.3)",
              }}
            >
              RETRIEVAL BENCHMARK
            </span>
            <span
              style={{ color: "#10b981", fontSize: "0.78rem", fontWeight: 600 }}
            >
              ● {questions.length}/{questions.length} Ready
            </span>
          </div>
          <h1
            style={{
              fontSize: "1.35rem",
              fontWeight: 800,
              color: "#fff",
              margin: 0,
            }}
          >
            Multi-Strategy Retrieval Benchmark
          </h1>
          <p
            style={{
              color: "var(--text-muted)",
              fontSize: "0.84rem",
              margin: "4px 0 0 0",
              maxWidth: "650px",
            }}
          >
            Compare Document &amp; Section Recall@K and MRR across ablation
            stages (TF-IDF, Hybrid Weighted, Hybrid RRF, Cross-Encoder Rerank,
            Query Rewriting).
          </p>
        </div>

        <div
          style={{
            display: "flex",
            gap: "12px",
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <div
            style={{
              background: "rgba(16, 185, 129, 0.12)",
              border: "1px solid rgba(16, 185, 129, 0.35)",
              borderRadius: "8px",
              padding: "8px 16px",
              textAlign: "right",
            }}
          >
            <div
              style={{
                fontSize: "0.72rem",
                color: "var(--text-muted)",
                textTransform: "uppercase",
                fontWeight: 600,
              }}
            >
              Benchmark Dataset
            </div>
            <div
              style={{ fontSize: "1.25rem", fontWeight: 800, color: "#34d399" }}
            >
              {questions.length} Cases Loaded
            </div>
          </div>

          <button
            type="button"
            onClick={onRun}
            disabled={isRunning || questions.length === 0}
            className="btn-primary"
            style={{
              padding: "10px 22px",
              fontSize: "0.9rem",
              fontWeight: 700,
              display: "flex",
              alignItems: "center",
              gap: "8px",
            }}
          >
            {isRunning ? (
              <>
                <span
                  className="spinner"
                  style={{ width: "16px", height: "16px" }}
                />
                <span>Running Benchmark...</span>
              </>
            ) : (
              <>
                <span>▶</span>
                <span>Run Retrieval Benchmark ({questions.length} Cases)</span>
              </>
            )}
          </button>
        </div>
      </Card>

      {/* LIVE PROGRESS CARD WHEN RUNNING */}
      {isRunning && (
        <EvaluationProgressCard
          title="Retrieval Benchmark Running"
          current={0}
          total={questions.length}
          isRunning={true}
          isComplete={false}
          statusText="Executing retrieval across active ablation strategies..."
          configurationText={`Top-K: ${topK} | Active Strategies: ${Object.keys(presets).filter((k) => presets[k]).length}`}
          onCancel={onCancel}
        />
      )}

      {/* UNIFIED DATASET MANAGEMENT (UPLOAD / MANUAL EDITING) */}
      <EvaluationDatasetManager
        evaluatorType="retrieval"
        title="Multi-Strategy Retrieval"
        builtinCount={CANONICAL_RETRIEVAL_QUESTIONS.length}
        builtinLabel="Canonical 25-Case Retrieval Benchmark"
        datasetMode={datasetMode}
        customCases={customDatasetCases}
        isRunning={isRunning}
        onModeChange={handleModeChange}
        onCustomCasesChange={handleCustomCasesChange}
        onResetToBuiltin={() => {
          setDatasetMode("builtin");
          resetToCanonical();
        }}
        onNotify={notify}
        storageKey="retrieval_custom_dataset"
      />

      {/* RETRIEVAL SETTINGS */}
      <Card>
        <h2
          style={{
            fontSize: "0.82rem",
            fontWeight: 700,
            textTransform: "uppercase",
            letterSpacing: "0.05em",
            color: "var(--text-primary)",
            margin: "0 0 16px 0",
          }}
        >
          Retrieval Settings
        </h2>

        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "16px",
            marginBottom: "18px",
          }}
        >
          <div>
            <div
              style={{
                display: "flex",
                justifyContent: "space-between",
                alignItems: "center",
                marginBottom: "6px",
              }}
            >
              <label
                htmlFor="top-k-stepper-input"
                style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}
              >
                Top-k
              </label>
              <div style={{ display: "flex", gap: "6px" }}>
                <button
                  type="button"
                  onClick={() => setTopK(5)}
                  style={{
                    fontSize: "0.7rem",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    border:
                      Number(topK) === 5
                        ? "1px solid var(--accent)"
                        : "1px solid var(--border)",
                    background:
                      Number(topK) === 5 ? "var(--accent-dim)" : "transparent",
                    color: Number(topK) === 5 ? "#fff" : "var(--text-muted)",
                    cursor: "pointer",
                  }}
                  title="Application Default (K=5)"
                >
                  K=5 (Default)
                </button>
                <button
                  type="button"
                  onClick={() => setTopK(8)}
                  style={{
                    fontSize: "0.7rem",
                    padding: "2px 6px",
                    borderRadius: "4px",
                    border:
                      Number(topK) === 8
                        ? "1px solid var(--accent)"
                        : "1px solid var(--border)",
                    background:
                      Number(topK) === 8 ? "var(--accent-dim)" : "transparent",
                    color: Number(topK) === 8 ? "#fff" : "var(--text-muted)",
                    cursor: "pointer",
                  }}
                  title="Week 6 Baseline (K=8)"
                >
                  K=8 (Week 6)
                </button>
              </div>
            </div>
            <div
              style={{
                display: "flex",
                alignItems: "center",
                background: "var(--bg-raised)",
                border: "1px solid var(--border)",
                borderRadius: "8px",
                overflow: "hidden",
                height: "38px",
              }}
            >
              <button
                type="button"
                onClick={() => {
                  const current = parseInt(String(topK), 10) || 1;
                  setTopK(Math.max(1, current - 1));
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--text-muted)",
                  width: "36px",
                  height: "100%",
                  cursor: "pointer",
                  fontSize: "1.1rem",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                title="Decrease Top-k"
              >
                −
              </button>
              <input
                id="top-k-stepper-input"
                type="number"
                min="1"
                max="20"
                step="1"
                value={topK}
                onChange={(e) => {
                  const raw = e.target.value;
                  if (raw === "") {
                    setTopK("");
                  } else {
                    const val = parseInt(raw, 10);
                    if (!isNaN(val)) {
                      setTopK(Math.max(1, Math.min(20, val)));
                    }
                  }
                }}
                onBlur={() => {
                  const trimmed = String(topK).trim();
                  if (!/^\d+$/.test(trimmed)) {
                    setTopK(5);
                    return;
                  }
                  const val = Number(trimmed);
                  setTopK(Math.max(1, Math.min(20, val)));
                }}
                style={{
                  flex: 1,
                  textAlign: "center",
                  background: "transparent",
                  border: "none",
                  color: "#fff",
                  fontSize: "0.85rem",
                  fontWeight: 600,
                  outline: "none",
                  padding: 0,
                }}
              />
              <button
                type="button"
                onClick={() => {
                  const current = parseInt(String(topK), 10) || 1;
                  setTopK(Math.min(20, current + 1));
                }}
                style={{
                  background: "none",
                  border: "none",
                  color: "var(--text-muted)",
                  width: "36px",
                  height: "100%",
                  cursor: "pointer",
                  fontSize: "1.1rem",
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                }}
                title="Increase Top-k"
              >
                +
              </button>
            </div>
          </div>
          <div>
            <label
              htmlFor="strategy-filter-input"
              style={{
                display: "block",
                fontSize: "0.75rem",
                color: "var(--text-muted)",
                marginBottom: "6px",
              }}
            >
              Chunk strategy filter (optional)
            </label>
            <input
              id="strategy-filter-input"
              type="text"
              placeholder="e.g. structured — leave blank for all"
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
              className="input-field"
              style={{ width: "100%" }}
            />
          </div>
        </div>

        <div
          style={{
            fontSize: "0.75rem",
            color: "var(--text-muted)",
            marginBottom: "10px",
            fontWeight: 600,
          }}
        >
          Ablation stages to compare
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
            gap: "10px",
            marginBottom: "22px",
          }}
        >
          {Object.keys(PRESETS).map((key) => {
            const meta = PRESETS[key];
            const isChecked = !!presets[key];
            return (
              <label
                key={key}
                className={`stage-checkbox ${isChecked ? "checked" : ""}`}
              >
                <input
                  type="checkbox"
                  checked={isChecked}
                  onChange={() => toggleP(key)}
                  style={{
                    accentColor: "var(--accent)",
                    width: "15px",
                    height: "15px",
                    cursor: "pointer",
                  }}
                />
                <div>
                  <div
                    style={{
                      fontSize: "0.8rem",
                      fontWeight: 600,
                      color: isChecked ? "#fff" : "var(--text-muted)",
                    }}
                  >
                    {meta.label}
                  </div>
                  <div
                    style={{
                      fontSize: "0.68rem",
                      color: "var(--text-muted)",
                      marginTop: "1px",
                    }}
                  >
                    {meta.desc}
                  </div>
                </div>
              </label>
            );
          })}
        </div>

        <div style={{ display: "flex", alignItems: "center", gap: "10px" }}>
          <button
            type="button"
            onClick={onRun}
            disabled={isRunning || questions.length === 0}
            className="btn-primary"
          >
            {isRunning ? "Running benchmark..." : "Run Retrieval Benchmark"}
          </button>

          {isRunning && (
            <button
              type="button"
              onClick={onCancel}
              className="btn-secondary btn-danger"
            >
              Cancel
            </button>
          )}
        </div>
      </Card>
    </div>
  );
};
