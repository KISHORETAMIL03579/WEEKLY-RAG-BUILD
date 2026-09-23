# backend/evaluation/judge.py — LLM Judge Evaluation Engine
# Re-exports judge suite and inference engine from week6 package for clean modular architecture
from week6.judge import (
    call_llm_judge,
    call_llm_judge_detailed,
    check_ollama_health,
    evaluate_case_deterministically,
    evaluate_case_with_judge,
    evaluate_case_with_judge_detailed,
    parse_judge_output,
    run_judge_suite,
)

