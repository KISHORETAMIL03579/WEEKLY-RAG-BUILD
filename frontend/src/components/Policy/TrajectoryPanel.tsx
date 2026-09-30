// Week 8 trajectory evaluation of a finished benchmark run: did the agent take the
// right path, not just reach the right answer? All numbers come from run.trajectory
// (backend/services/policy_trajectory.py); nothing is recomputed client-side.
import React, { useState } from "react";
import { api } from "../../services/api";
import { describeError } from "../../services/apiError";
import {
  PolicyBenchmarkRunStateResponse,
  TrajectoryCaseRecord,
  TrajectoryComparison,
  TrajectoryReport,
  TrajectorySummary,
} from "../../types/policy";
import {
  formatInt,
  formatMs,
  formatPct,
  formatRatioPct,
  formatUsd,
} from "../../utils/helpers";
import { DataTable } from "../common/DataTable";
import { MetricCard } from "../common/MetricCard";
import { ProgressBar } from "../common/ProgressBar";
import { StatusBadge } from "../common/StatusBadge";
import { PathSequence } from "./ToolTrace";

const FAILURE_MODE_HELP: Record<string, string> = {
  provider_error: "The model provider failed or timed out.",
  budget_exhausted: "A token, cost, wall-clock or iteration budget ran out.",
  tool_error: "A tool call failed and the run could not recover.",
  invalid_tool_call: "The model asked for a tool call the host rejected.",
  skipped_required_tool: "A tool the question needed was never called.",
  wrong_tool_selection: "A tool outside the allowed paths was called.",
  bad_arguments:
    "An argument was not real (unknown employee, wrong jurisdiction, unresolved citation).",
  redundant_calls:
    "The same tool was called more than once, or extras were added.",
  answer_wrong:
    "The path was right but the answer did not satisfy the criteria.",
};

const ExpectedPaths: React.FC<{
  paths: string[][];
  matched?: string[];
  exact: boolean;
}> = ({ paths, matched, exact }) => (
  <div className="path-list">
    {paths.map((path, index) => {
      const isMatched =
        matched !== undefined &&
        path.length === matched.length &&
        path.every((name, i) => name === matched[i]);
      return (
        <div
          key={index}
          className="u-row"
          style={{ gap: 6, flexWrap: "nowrap" }}
        >
          {paths.length > 1 && (
            <span className="u-tiny u-muted" style={{ minWidth: 14 }}>
              {String.fromCharCode(65 + index)}
            </span>
          )}
          <PathSequence
            sequence={path}
            tone={isMatched ? (exact ? "match" : "miss") : "plain"}
          />
        </div>
      );
    })}
    {paths.length > 1 && (
      <span className="u-tiny u-muted">
        any one of these {paths.length} paths passes
      </span>
    )}
  </div>
);

interface TrajectoryPanelProps {
  run: PolicyBenchmarkRunStateResponse;
  report: TrajectoryReport;
  /** Other finished runs the current run can be compared against. */
  baselineCandidates: Array<{ run_id: string; label: string }>;
}

const Summary: React.FC<{ summary: TrajectorySummary }> = ({ summary }) => {
  const gap = summary.outcome_vs_trajectory_gap_pct;
  const validity = summary.argument_validity_rate;
  return (
    <>
      <div className="metric-grid">
        <MetricCard
          label="Tool-choice accuracy"
          value={formatRatioPct(summary.tool_choice_accuracy)}
          hint={`Overlap between tools called and the closest allowed path. Exact tool set in ${formatPct(summary.exact_tool_set_rate_pct)} of cases.`}
          tone={summary.tool_choice_accuracy >= 0.9 ? "success" : "warning"}
        />
        <MetricCard
          label="Argument validity"
          value={validity === null ? "n/a" : formatRatioPct(validity)}
          hint={
            validity === null
              ? "No argument checks were recorded."
              : `${summary.argument_checks_failed ?? 0} of ${summary.argument_checks_total ?? 0} checks failed (real ids, matching jurisdiction, resolving citations).`
          }
          tone={
            validity === null
              ? "neutral"
              : validity >= 0.95
                ? "success"
                : "warning"
          }
        />
        <MetricCard
          label="Step efficiency"
          value={`${summary.step_efficiency_mean.toFixed(2)}× mean · ${summary.step_efficiency_worst.toFixed(2)}× worst`}
          hint="Steps taken ÷ steps needed. 1.00× is ideal; higher is wasteful."
          tone={summary.step_efficiency_worst <= 1.25 ? "success" : "warning"}
        />
        <MetricCard
          label="Cost p50 / max"
          value={`${formatUsd(summary.cost_usd.p50)} / ${formatUsd(summary.cost_usd.max)}`}
          hint="Estimated token cost (proxy, not billing)"
          tone="purple"
        />
        <MetricCard
          label="Latency p50 / max"
          value={`${formatMs(summary.latency_ms.p50, 0)} / ${formatMs(summary.latency_ms.max, 0)}`}
          hint="Agent runs, end to end"
          tone="info"
        />
        <MetricCard
          label="Tokens p50 / max"
          value={`${formatInt(summary.total_tokens.p50)} / ${formatInt(summary.total_tokens.max)}`}
          hint="Prompt + completion per agent run"
          tone="warning"
        />
      </div>

      <div className="panel-inset u-stack" style={{ gap: 10 }}>
        <div className="u-row">
          <span className="section-label">Outcome vs trajectory</span>
          <span
            className={`chip ${gap > 0 ? "tone-warning" : "tone-success"}`}
            title="Outcome pass rate minus trajectory pass rate"
          >
            GAP {gap > 0 ? "+" : ""}
            {gap.toFixed(1)} pts
          </span>
        </div>
        <div className="u-stack" style={{ gap: 6 }}>
          <div className="u-row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <span className="u-small" style={{ minWidth: 150 }}>
              Outcome (right answer)
            </span>
            <div className="u-grow">
              <ProgressBar
                percentage={summary.outcome_pass_rate_pct}
                ariaLabel="Outcome pass rate"
                tone="success"
              />
            </div>
            <strong style={{ minWidth: 56, textAlign: "right" }}>
              {formatPct(summary.outcome_pass_rate_pct)}
            </strong>
          </div>
          <div className="u-row" style={{ gap: 10, flexWrap: "nowrap" }}>
            <span className="u-small" style={{ minWidth: 150 }}>
              Trajectory (right path)
            </span>
            <div className="u-grow">
              <ProgressBar
                percentage={summary.trajectory_pass_rate_pct}
                ariaLabel="Trajectory pass rate"
                tone="accent"
              />
            </div>
            <strong style={{ minWidth: 56, textAlign: "right" }}>
              {formatPct(summary.trajectory_pass_rate_pct)}
            </strong>
          </div>
        </div>
        <div className="u-tiny u-muted">
          {gap > 0
            ? `${summary.right_answer_wrong_path.length} case(s) reached a correct answer by a path that was not an allowed one. Outcome-only scoring would hide this.`
            : gap < 0
              ? "Every correct answer followed an allowed path. The trajectory rate is higher because some runs took an allowed path but still missed the answer (wrong answer, provider error)."
              : "Every correct answer also followed an allowed path."}
          {summary.outcome_strict_pass_rate_pct !== undefined &&
            ` Legacy strict (literal-match) outcome: ${formatPct(summary.outcome_strict_pass_rate_pct)}.`}
        </div>
      </div>
    </>
  );
};

const FailureModes: React.FC<{ summary: TrajectorySummary }> = ({
  summary,
}) => {
  const modes = Object.keys(summary.failure_mode_counts);
  const any = summary.failure_mode_any_counts || {};
  return (
    <DataTable
      ariaLabel="Failure modes"
      caption="Failure modes (primary = the first mode that applies to a case; anywhere = every case the mode touches)"
      rows={modes}
      rowKey={(mode) => mode}
      columns={[
        {
          key: "mode",
          header: "Failure mode",
          render: (mode) => <span className="u-mono">{mode}</span>,
        },
        {
          key: "primary",
          header: "Primary",
          align: "right",
          render: (mode) => {
            const count = summary.failure_mode_counts[mode] ?? 0;
            return count > 0 ? (
              <span className="chip tone-danger">{count}</span>
            ) : (
              <span className="u-muted">0</span>
            );
          },
        },
        {
          key: "any",
          header: "Anywhere",
          align: "right",
          render: (mode) => any[mode] ?? 0,
        },
        {
          key: "what",
          header: "Meaning",
          render: (mode) => (
            <span className="u-muted">{FAILURE_MODE_HELP[mode] || ""}</span>
          ),
        },
      ]}
    />
  );
};

const PerCaseTable: React.FC<{ cases: TrajectoryCaseRecord[] }> = ({
  cases,
}) => (
  <DataTable
    ariaLabel="Per-case tool paths"
    rows={cases}
    rowKey={(row) => row.case_id}
    empty="No scored cases."
    columns={[
      {
        key: "case",
        header: "Case",
        render: (row) => (
          <div>
            <strong>{row.case_id.toUpperCase()}</strong>
            <div className="u-tiny u-muted">{row.employee_id}</div>
          </div>
        ),
      },
      {
        key: "expected",
        header: "Allowed path(s)",
        render: (row) => (
          <ExpectedPaths
            paths={row.expected_paths}
            matched={row.matched_path}
            exact={row.path_exact}
          />
        ),
      },
      {
        key: "observed",
        header: "Observed",
        render: (row) => (
          <PathSequence
            sequence={row.observed_sequence}
            tone={row.path_exact ? "match" : "miss"}
          />
        ),
      },
      {
        key: "exact",
        header: "Path exact",
        align: "center",
        render: (row) => (
          <StatusBadge
            status={row.path_exact ? "PASS" : "FAIL"}
            label={row.path_exact ? "YES" : "NO"}
          />
        ),
      },
      {
        key: "traj",
        header: "Trajectory",
        align: "center",
        render: (row) => (
          <StatusBadge status={row.trajectory_passed ? "PASS" : "FAIL"} />
        ),
      },
      {
        key: "outcome",
        header: "Outcome",
        align: "center",
        render: (row) => (
          <StatusBadge status={row.outcome_passed ? "PASS" : "FAIL"} />
        ),
      },
      {
        key: "steps",
        header: "Steps",
        align: "right",
        render: (row) => (
          <span title="steps taken / steps needed">
            {row.steps_taken}/{row.steps_needed}
          </span>
        ),
      },
      {
        key: "args",
        header: "Arg checks",
        render: (row) => {
          const bad = row.argument_checks.filter((c) => !c.ok);
          return row.argument_checks.length === 0 ? (
            <span className="u-muted">—</span>
          ) : (
            <span
              className={bad.length ? "chip tone-danger" : "chip tone-success"}
              title={
                bad.length
                  ? bad.map((c) => `${c.check}: ${c.detail}`).join("\n")
                  : "All argument checks passed"
              }
            >
              {row.argument_checks.length - bad.length}/
              {row.argument_checks.length} ok
            </span>
          );
        },
      },
      {
        key: "modes",
        header: "Failure modes",
        render: (row) =>
          row.failure_modes.length === 0 ? (
            <span className="u-muted">none</span>
          ) : (
            <div className="chip-list">
              {row.failure_modes.map((mode) => (
                <span
                  key={mode}
                  className={`chip is-mono${mode === row.primary_failure_mode ? " tone-danger" : ""}`}
                  title={
                    mode === row.primary_failure_mode
                      ? "primary failure mode"
                      : undefined
                  }
                >
                  {mode}
                </span>
              ))}
            </div>
          ),
      },
    ]}
  />
);

const ComparisonView: React.FC<{ comparison: TrajectoryComparison }> = ({
  comparison,
}) => (
  <div className="u-stack" style={{ gap: 8 }}>
    <div className="u-row">
      <span className="section-label">
        Comparison with baseline {comparison.baseline_run_id}
      </span>
      {comparison.outcome_pass_rate_delta_pct !== undefined && (
        <span className="chip">
          outcome {comparison.outcome_pass_rate_delta_pct >= 0 ? "+" : ""}
          {comparison.outcome_pass_rate_delta_pct} pts
        </span>
      )}
      {comparison.trajectory_pass_rate_delta_pct !== undefined && (
        <span className="chip">
          trajectory {comparison.trajectory_pass_rate_delta_pct >= 0 ? "+" : ""}
          {comparison.trajectory_pass_rate_delta_pct} pts
        </span>
      )}
    </div>
    {comparison.regressions.length > 0 ? (
      <div className="tool-error-box" role="alert">
        <strong>Regressions</strong>
        <ul className="check-list">
          {comparison.regressions.map((item) => (
            <li key={item} className="check-item is-bad">
              <span className="check-mark">✗</span>
              {item}
            </li>
          ))}
        </ul>
      </div>
    ) : (
      <div className="u-small" style={{ color: "var(--green)" }}>
        No failure mode got worse.
      </div>
    )}
    <DataTable
      ariaLabel="Failure mode comparison"
      rows={comparison.per_mode}
      rowKey={(row) => row.mode}
      columns={[
        {
          key: "m",
          header: "Mode",
          render: (row) => <span className="u-mono">{row.mode}</span>,
        },
        {
          key: "b",
          header: "Before",
          align: "right",
          render: (row) => row.before,
        },
        {
          key: "a",
          header: "After",
          align: "right",
          render: (row) => row.after,
        },
        {
          key: "d",
          header: "Δ",
          align: "right",
          render: (row) => (
            <span
              style={{
                color:
                  row.delta > 0
                    ? "var(--red)"
                    : row.delta < 0
                      ? "var(--green)"
                      : undefined,
              }}
            >
              {row.delta > 0 ? "+" : ""}
              {row.delta}
            </span>
          ),
        },
      ]}
    />
    <div className="chip-list" aria-label="Price of the change">
      {Object.entries(comparison.price).map(([key, value]) => (
        <span key={key} className="chip is-mono">
          {key}: {value > 0 ? "+" : ""}
          {value}
        </span>
      ))}
    </div>
  </div>
);

export const TrajectoryPanel: React.FC<TrajectoryPanelProps> = ({
  run,
  report,
  baselineCandidates,
}) => {
  const summary = report.summary;
  const [baselineId, setBaselineId] = useState("");
  const [comparison, setComparison] = useState<TrajectoryComparison | null>(
    null,
  );
  const [comparing, setComparing] = useState(false);
  const [compareError, setCompareError] = useState<string | null>(null);

  const compare = async () => {
    if (!baselineId) return;
    setComparing(true);
    setCompareError(null);
    try {
      const res = await api.evaluateTrajectory({
        run_id: run.run_id,
        baseline_run_id: baselineId,
      });
      setComparison(res.comparison ?? null);
    } catch (e: unknown) {
      setComparison(null);
      setCompareError(describeError(e));
    } finally {
      setComparing(false);
    }
  };

  if (report.cases.length === 0) {
    return (
      <section className="panel" aria-labelledby="trajectory-heading">
        <h3 className="panel-title" id="trajectory-heading">
          Trajectory evaluation
        </h3>
        <div className="panel-inset u-small u-muted">
          No case in this run has an expected trajectory (custom datasets are
          scored on the outcome only).
        </div>
      </section>
    );
  }

  return (
    <section className="panel is-accent" aria-labelledby="trajectory-heading">
      <div>
        <h3 className="panel-title" id="trajectory-heading">
          <span aria-hidden="true">🧭</span> Trajectory evaluation
          <span className="chip">
            {summary.case_count ?? report.cases.length} agent runs
          </span>
        </h3>
        <p className="panel-subtitle">
          Scores the agent's tool path against the allowed path(s) for each
          case: the right answer by the wrong route still counts against it.
        </p>
      </div>

      <Summary summary={summary} />

      <div className="u-stack" style={{ gap: 8 }}>
        <div className="section-label">Right answer, wrong path</div>
        {summary.right_answer_wrong_path.length === 0 ? (
          <div
            className="panel-inset u-small"
            style={{ color: "var(--green)" }}
          >
            None. No case reached a correct answer by a disallowed path.
          </div>
        ) : (
          <DataTable
            ariaLabel="Cases with the right answer but the wrong path"
            rows={summary.right_answer_wrong_path}
            rowKey={(row) => row.case_id}
            columns={[
              {
                key: "case",
                header: "Case",
                render: (row) => <strong>{row.case_id.toUpperCase()}</strong>,
              },
              {
                key: "observed",
                header: "Observed sequence",
                render: (row) => (
                  <PathSequence sequence={row.observed_sequence} tone="miss" />
                ),
              },
              {
                key: "expected",
                header: "Allowed path(s)",
                render: (row) => (
                  <ExpectedPaths paths={row.expected_paths} exact={false} />
                ),
              },
              {
                key: "why",
                header: "Why it is wrong",
                render: (row) => <span className="u-small">{row.why}</span>,
              },
            ]}
          />
        )}
      </div>

      <div className="u-stack" style={{ gap: 8 }}>
        <div className="section-label">Failure modes</div>
        <FailureModes summary={summary} />
      </div>

      {(Object.keys(summary.retries.tool_retries || {}).length > 0 ||
        (summary.retries.model_call_retries ?? 0) > 0) && (
        <div className="u-row" aria-label="Retries across the run">
          <span className="section-label">Retries</span>
          {Object.entries(summary.retries.tool_retries || {}).map(
            ([tool, n]) => (
              <span
                key={tool}
                className={`chip is-mono ${n > 0 ? "tone-warning" : ""}`}
              >
                {tool}: {n} retr{n === 1 ? "y" : "ies"} /{" "}
                {summary.retries.tool_attempts?.[tool] ?? 0} attempts
              </span>
            ),
          )}
          <span className="chip is-mono">
            model-call retries: {summary.retries.model_call_retries ?? 0}
          </span>
        </div>
      )}

      <div className="u-stack" style={{ gap: 8 }}>
        <div className="section-label">Per-case tool paths</div>
        <PerCaseTable cases={report.cases} />
      </div>

      {baselineCandidates.length > 0 && (
        <div className="u-stack" style={{ gap: 8 }}>
          <div className="section-label">Compare with an earlier run</div>
          <div className="u-row">
            <label className="field-label" htmlFor="trajectory-baseline">
              Baseline run
            </label>
            <select
              id="trajectory-baseline"
              className="field-select"
              style={{ width: "auto", minWidth: 220 }}
              value={baselineId}
              onChange={(event) => {
                setBaselineId(event.target.value);
                setComparison(null);
              }}
            >
              <option value="">Select a finished run…</option>
              {baselineCandidates.map((candidate) => (
                <option key={candidate.run_id} value={candidate.run_id}>
                  {candidate.label}
                </option>
              ))}
            </select>
            <button
              type="button"
              className="btn-secondary btn-small"
              disabled={!baselineId || comparing}
              onClick={() => void compare()}
            >
              {comparing ? "Comparing…" : "Compare"}
            </button>
          </div>
          {compareError && (
            <div className="field-error" role="alert">
              {compareError}
            </div>
          )}
          {comparison && <ComparisonView comparison={comparison} />}
        </div>
      )}
    </section>
  );
};
