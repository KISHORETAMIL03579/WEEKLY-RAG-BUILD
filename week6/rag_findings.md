# Week 6 RAG Findings & Trace Failure Root-Cause Analysis

This document records the comprehensive failure taxonomy, trace error analysis, and code issue resolutions discovered during the Week 6 evaluation experiment against the 2018 GESCI HR Policy Manual (`WEEKLY_RAG_TASK/HRPolicy.pdf`).

Per the Week 6 protocol:
1. **Core Application RAG Code was kept strictly frozen** during evaluation.
2. **Evaluation Code Issues** (e.g. assertion catalog gaps, regex limitations, and judge client timeout handling) were identified, fixed, and verified via unit tests.
3. Every failing case and evaluation disagreement is classified into one of three distinct root-cause categories:
   - **`pipeline_failure`**: Retrieval truncations, cross-chapter dispersal, or embedding score threshold starvation.
   - **`llm_model_failure`**: Generation hallucinations, inline metadata citation drifting, or judge prompt few-shot hyper-critical bias.
   - **`code_issue`**: Assertion catalog omissions, regex mismatches, or evaluation runner / client defects.

---

## 1. Failure Taxonomy & Root-Cause Classification

| Failure Category | Primary Root Cause | Affected Cases / Traces | Impact & Mechanism |
| :--- | :--- | :--- | :--- |
| **`pipeline_failure`** | **Retrieval Budget & Chunking** | `case_01`, `case_03`, `case_06`, `case_21`, `case_22` | $K=4$ truncated essential sub-clauses (e.g. sick leave 2-month tenure rule, salary advance 3rd condition) or clustered in Chapter 2 while missing Chapter 9. |
| **`llm_model_failure`** | **LLM Generation & Judge Bias** | `case_02`, `case_04`, `case_05`, `case_07`–`case_20`, `case_23`–`case_25` | Generation citation drift at $T=0.7$ (`case_12`, `case_14`), and Judge V2 few-shot hyper-critical false-negative rejections (96% rejection rate). |
| **`code_issue`** | **Assertion Catalog & Client Handling** | `week6/assertions.py`, `week6/judge.py`, `week6/eval_week6.py` | Missing subsections in catalog (e.g. `4.3.1`, `10.5.3`), lack of hierarchical prefix matching, and Ollama 45s batch timeouts. *(Resolved)* |

---

## 2. Complete Case-by-Case Trace Failure Breakdown

The table below maps all 25 evaluation test cases, their underlying trace IDs, human ground truth, failure category, failure type, and specific diagnostic explanation:

| Case ID | Trace ID | Taxonomy Mode | Human Label | Failure Category | Failure Type | Root Cause & Diagnostic Explanation |
| :--- | :--- | :--- | :---: | :---: | :--- | :--- |
| `case_01` | `66f5c2a9` | Low-K Multi-Clause Truncation | 0 | **`pipeline`** | `low_k_truncation` | **Pipeline Failure:** At $K=4$, retrieval omitted the 2-month service requirement and 1-day half-pay rule of Section 5.3.2. Generator outputted an incomplete entitlement. |
| `case_02` | `067c1ade` | Low-K Multi-Clause Truncation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Complete answer at $K=9$ (Label 1) was false-negatively rejected by Judge V2 due to strict few-shot omission over-correction. |
| `case_03` | `c87ef1b4` | Low-K Multi-Clause Truncation | 0 | **`pipeline`** | `low_k_truncation` | **Pipeline Failure:** $K=4$ truncated Section 4.3.1 paragraph 3 (CEO written authorization for exceptional cases), omitting the 3rd advance condition. |
| `case_04` | `8cd01732` | Low-K Multi-Clause Truncation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Complete 3-condition answer at $K=5$ falsely rejected by Judge V2. |
| `case_05` | `c30ee16f` | Low-K Multi-Clause Truncation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Valid 16-week maternity summary falsely rejected by Judge V2. |
| `case_06` | `c71b8fb1` | Sub-Clause Dispersal | 1 | **`pipeline`** | `dispersed_subclause_omission` | **Pipeline Failure:** Chunks clustered purely in Chapter 2 (Section 2.2.3), omitting cross-chapter grievance timeline in Section 9.1.1 and Section 9.6. |
| `case_07` | `137a9ac0` | Sub-Clause Dispersal | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Complete cross-chapter answer at $K=5$ falsely rejected by Judge V2. |
| `case_08` | `39623159` | Sub-Clause Dispersal | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate gift policy summary falsely rejected by Judge V2. |
| `case_09` | `379e2c7d` | Sub-Clause Dispersal | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Complete hospitality synthesis at $K=8$ falsely rejected by Judge V2. |
| `case_10` | `89bb2866` | Sub-Clause Dispersal | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate resignation notice rules falsely rejected by Judge V2. |
| `case_11` | `30b526af` | Citation Drifting | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Clean $T=0.0$ paternity answer falsely rejected by Judge V2. |
| `case_12` | `cfd0d330` | Citation Drifting | 1 | **`llm_model`** | `citation_drifting` | **LLM Generator Failure:** At $T=0.7$, generator injected raw prompt headers (`"According to section 5.3.3 Parental Leave in HRPolicy.pdf..."`) into opening sentence. |
| `case_13` | `8e6c8052` | Citation Drifting | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate misdemeanor list falsely rejected by Judge V2. |
| `case_14` | `ded4abe6` | Citation Drifting | 1 | **`llm_model`** | `citation_drifting` | **LLM Generator Failure:** At $T=0.7$, generator attached citation brackets to intro headers rather than factual claim sentences. |
| `case_15` | `0c151121` | Citation Drifting | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate HR manager responsibilities list falsely rejected by Judge V2. |
| `case_16` | `5fa69a94` | Unstated Invariant Refusal | 1 | **`llm_model`** | `judge_refusal_misclassification` | **LLM Judge Failure:** Retirement age is unstated. Assistant correctly responded `"I don't know."` but Judge V1/V2 misclassified refusal as defective. |
| `case_17` | `b14df5a2` | Unstated Invariant Refusal | 1 | **`llm_model`** | `judge_refusal_misclassification` | **LLM Judge Failure:** Dress code is unstated. Assistant correctly refused. Judge V1/V2 rejected. |
| `case_18` | `a4d2b2eb` | Unstated Invariant Refusal | 1 | **`llm_model`** | `judge_refusal_misclassification` | **LLM Judge Failure:** Overtime eligibility for senior managers correctly refused. Judge V1 rejected. |
| `case_19` | `57b6a4af` | Unstated Invariant Refusal | 1 | **`llm_model`** | `judge_refusal_misclassification` | **LLM Judge Failure:** Overtime rates unstated. Assistant correctly refused. Judge rejected. |
| `case_20` | `e8dd8884` | Unstated Invariant Refusal | 1 | **`llm_model`** | `judge_refusal_misclassification` | **LLM Judge Failure:** Unstated retirement policy correctly refused. Judge rejected. |
| `case_21` | `7f03ac6c` | Threshold Starvation | 1 | **`pipeline`** | `threshold_starvation` | **Pipeline Failure:** Dense score cutoff `EMBED_MIN_SCORE=0.55` limited candidate pool to 4 chunks even when $K=10$. |
| `case_22` | `51e1eed1` | Threshold Starvation | 1 | **`pipeline`** | `threshold_starvation` | **Pipeline Failure:** Identical 4 chunks retrieved at $K=4$ and $K=10$ due to threshold starvation. |
| `case_23` | `50dbc236` | Threshold Starvation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate WFH rules from Section 8.6 falsely rejected by Judge V2. |
| `case_24` | `1666a48b` | Threshold Starvation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate 9:00am–5:30pm hours from Section 5.1 falsely rejected by Judge V2. |
| `case_25` | `ec27744b` | Threshold Starvation | 1 | **`llm_model`** | `judge_fewshot_overcorrection` | **LLM Judge Failure:** Accurate 5-day carryover from Section 5.2 falsely rejected by Judge V2. |

---

## 3. Code Issues Discovered, Root Causes, and Resolutions

During evaluation verification, three distinct **Code Issues** were identified in the evaluation and assertion harness. Below is the full documentation of each issue, its root cause, and how it was resolved in code:

### Issue 1: Incomplete Section Catalog & Lack of Hierarchical Prefix Resolution
* **File Affected**: [`week6/assertions.py`](file:///d:/RAG_WEEK_3/WEEK-3-RAG/week6/assertions.py)
* **Description of Bug**:
  The `VALID_HANDBOOK_SECTIONS` set only listed major sections and omitted valid subsections from the 2018 GESCI HR manual (e.g. `4.3.1 Salary Advances`, `10.5.3 Termination for Ill Health`, `3.4.2 Acceptance of Appointment`, `5.2.4`, `6.3.2`, `8.4.1`, `9.1.1`). Furthermore, `policy_section_reference_resolves` used a strict flat set check `normalized_sec in valid_sections`. If an answer cited `Section 4.3.1` or `Section 5.3.2.1`, the assertion would return `False` even though the section is factually valid in the handbook.
* **Root Cause**:
  Hardcoded incomplete constant without hierarchical parent-tree lookup.
* **How It Was Resolved**:
  1. Extracted and populated all **113+ canonical sections and subsections** from `WEEKLY_RAG_TASK/HRPolicy.pdf` into `VALID_HANDBOOK_SECTIONS`.
  2. Implemented hierarchical prefix matching in `policy_section_reference_resolves`: if a cited subsection `X.Y.Z` exists or its parent `X.Y` is in the canonical catalog, it is recognized as valid.
* **Code Change**:
  ```python
  # week6/assertions.py
  def policy_section_reference_resolves(answer: str, valid_sections: Set[str] = None) -> bool:
      ...
      for sec in sec_matches:
          normalized_sec = sec.strip().rstrip(".")
          # 1. Exact match in catalog
          if normalized_sec in valid_sections:
              continue
          # 2. Hierarchical prefix check (e.g. 5.3.2.1 -> 5.3.2 -> 5.3)
          parts = normalized_sec.split(".")
          is_valid_hierarchy = any(
              ".".join(parts[:depth]) in valid_sections
              for depth in range(len(parts) - 1, 0, -1)
          )
          if is_valid_hierarchy:
              continue
          return False
      return True
  ```
* **Verification**: Verified with automated unit tests in `test_week6.py` covering exact matches, hierarchical subsections, and invalid fabricated citations (`Section 42.1`).

---

### Issue 2: Transient Ollama Request Timeout & Lack of Retry Mechanism
* **File Affected**: [`week6/judge.py`](file:///d:/RAG_WEEK_3/WEEK-3-RAG/week6/judge.py)
* **Description of Bug**:
  `call_llm_judge` had a short default timeout (45s) and no retry mechanism. When executing long prompt batches (such as Judge V2 containing two few-shot demonstrations), Ollama's local inference queue occasionally exceeded 45s, returning `ERROR: timed out`. The output parser then converted this error string to fallback `0`, confounding transport timeouts with LLM judge verdicts.
* **Root Cause**:
  Single-attempt synchronous HTTP request with inadequate timeout for multi-token few-shot prompts on CPU/GPU.
* **How It Was Resolved**:
  1. Increased default timeout to **90 seconds**.
  2. Added **exponential backoff retry logic** (up to 3 attempts with 1.5s multiplier) to gracefully handle queue pauses.
* **Code Change**:
  ```python
  # week6/judge.py
  def call_llm_judge(prompt: str, timeout: int = 90, retries: int = 3) -> str:
      last_err = None
      for attempt in range(1, retries + 1):
          try:
              with urllib.request.urlopen(req, timeout=timeout) as resp:
                  res_json = json.loads(resp.read().decode("utf-8"))
                  return res_json.get("response", "").strip()
          except Exception as e:
              last_err = e
              if attempt < retries:
                  time.sleep(1.5 * attempt)
      return f"ERROR: {last_err}"
  ```

---

### Issue 3: Missing Trace Diagnostic Export & Root-Cause Failure Reporting
* **File Affected**: [`week6/eval_week6.py`](file:///d:/RAG_WEEK_3/WEEK-3-RAG/week6/eval_week6.py)
* **Description of Bug**:
  The evaluation runner only aggregated taxonomy mode pass rates but lacked a root-cause breakdown table (Pipeline vs LLM Model vs Code Issue) and did not serialize the case-level diagnostic results into a persistent JSON artifact.
* **Root Cause**:
  Aggregation logic only tracked Week 5 mode names without failure category indexing.
* **How It Was Resolved**:
  1. Added `compute_failure_category_statistics()` to aggregate distribution across `pipeline`, `llm_model`, `code_issue`, and `pass`.
  2. Added the **"Failure Root Cause Breakdown Table"** to standard CLI stdout.
  3. Added automatic export to [`week6/trace_eval_results.json`](file:///d:/RAG_WEEK_3/WEEK-3-RAG/week6/trace_eval_results.json) containing trace ID, question, assertions, judge verdicts, failure category, failure type, and resolution.

---

## 4. Pipeline Findings (Underlying RAG System Issues)

The 5 architectural RAG issues discovered during evaluation (with RAG code kept frozen):

1. **Finding 1: Low-K Multi-Clause Entitlement Truncation**
   - *Severity*: **High / Legal & Financial Risk**
   - *Cause*: Structured chunking breaks clauses; $K=4$ drops qualifying tiers.
   - *Fix*: Increase $K \ge 8$ with parent-document retrieval and cross-encoder reranking.

2. **Finding 2: Sub-Clause Dispersal Across Disparate Policy Chapters**
   - *Severity*: **High / Operational & Compliance Risk**
   - *Cause*: Policies split across Chapter 2 (Conduct) and Chapter 9 (Grievance). Dense single-query search clusters in one chapter.
   - *Fix*: Multi-query decomposition / HyDE.

3. **Finding 3: Citation Drifting & In-Prose Structural Inversion**
   - *Severity*: **Low / UI Fragility**
   - *Cause*: Elevated temperature ($T \ge 0.7$) causes LLM to echo chunk metadata headers in prose.
   - *Fix*: Clamp $T \le 0.2$ and enforce strict citation output schema.

4. **Finding 4: Invariant Refusals on Absent Policies**
   - *Severity*: **Low / Desirable Behavior**
   - *Cause*: Proper refusal on unstated topics (Retirement age, General overtime).
   - *Fix*: Preserve refusal guardrails; train judges to recognize valid refusals.

5. **Finding 5: Embedding Similarity Threshold Starvation**
   - *Severity*: **Low / Informational**
   - *Cause*: `EMBED_MIN_SCORE = 0.55` drops distant candidate chunks even when $K=10$.
   - *Fix*: Dynamic similarity threshold relaxation when candidate count is $< K$.\n