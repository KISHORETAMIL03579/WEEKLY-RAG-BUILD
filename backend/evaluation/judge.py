# backend/evaluation/judge.py — LLM Judge Evaluation Engine
# Re-exports judge suite and inference engine from week6 package for clean modular architecture
from week6.judge import (
    call_llm_judge,
    check_ollama_health,
    evaluate_case_with_judge,
    parse_judge_output,
    run_judge_suite,
)

