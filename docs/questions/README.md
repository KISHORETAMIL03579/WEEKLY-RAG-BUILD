# Question files, Weeks 5 to 9

One importable `.txt` per week. All 83 cases parse with zero invalid rows through the app's own importer
(`backend/services/evaluation_dataset.py`, checked for both the `policy` and `judge` evaluators).

| File | Cases | Use it for |
| --- | ---: | --- |
| [`week5_error_analysis_questions.txt`](week5_error_analysis_questions.txt) | 20 | Ask in **Chat**, then read the traces and open-code what you saw. Five per failure mode in `taxonomy.md`; verified expected answers and section numbers from the handbook. |
| [`week6_judge_eval_25_cases.txt`](week6_judge_eval_25_cases.txt) | 25 | **Judge Evaluator**. Each case is a *question + the answer under judgment* (not ground truth), tagged with its taxonomy mode; 3 are regression replays. Generated from `week6/eval_cases_25.json`. |
| [`week7_agent_vs_workflow_questions.txt`](week7_agent_vs_workflow_questions.txt) | 16 | **Policy Assistant** race: 10 canonical (same tool path, different answers) + 6 branching (jurisdiction from the record, HRIS tools, handbook silent on a country). Generated from the benchmark JSON. |
| [`week8_trajectory_questions.txt`](week8_trajectory_questions.txt) | 12 | Path-sensitive questions. The expected tool path is in each case header. Includes an unknown employee (must stop after the lookup) and a lower-case id. |
| [`week9_mcp_questions.txt`](week9_mcp_questions.txt) | 10 | Questions that need the HRIS server, a handbook-only question that must **not** call it, and two error paths. |

## Before you run anything

1. Start the app and open the **Chat** page.
2. Upload `WEEKLY_RAG_TASK/HRPolicy.pdf`.
3. For Weeks 7 to 9 also upload `backend/data/samples/employee_records.md` (the roster the tools read).
4. Week 9 HRIS answers come from `backend/data/samples/hris_records.json` (a stand-in extract): EMP001 grade G7 / 12 days,
   EMP004 G9 / 20, EMP006 G6 / 10, EMP008 6 days, EMP010 15 days.

The policy tools read only what the current browser session uploaded; without it the policy pages show
"Upload the HR policy documents first".

## Import format

```text
### Case 01 [free text after the id is ignored]
Case ID: w5_01
Employee ID: EMP001
Question: ...
Expected Answer: ...
Section: 5.3.2
```

`Q:` / `A:` also work. Only those keys are recognised; any other line after an answer would be swallowed *into*
the answer, so keep extras inside the `### Case` header line (as the Week 8 and 9 files do for the expected tool path).
Comment lines (`#`) belong at the top of the file only.

## What "correct" means per file

- **Weeks 5 and 6:** answers come from `HRPolicy.pdf`. Three questions (overtime, dress code, daily hours) are **not** in the
  handbook: the right behaviour is to say so. The retirement-age question **is** (Section 10.3, age 65), so a refusal is a
  retrieval miss. `case_16` in Week 6 is labelled the other way; see [`../training/week6/README.md`](../training/week6/README.md).
- **Weeks 7 and 8:** the handbook contains Kenya text only. Irish, Rwandan and Ivorian "statutory" questions must end with
  "the documents do not cover it"; quoting outside law is scored as a failure (forbidden phrases).
- **Week 9:** read the trace: each call shows `tool@server`, arguments, attempts/retries. `get_grade_band@hris` proves the
  discovered HRIS tool was used with no agent change.
