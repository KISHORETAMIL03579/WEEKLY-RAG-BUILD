import json
import time
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

with open(REPO_ROOT / "week6" / "eval_cases_25.json", "r", encoding="utf-8") as f:
    cases = json.load(f)

v1_template = (REPO_ROOT / "week6" / "judge_v1.txt").read_text(encoding="utf-8")
v2_template = (REPO_ROOT / "week6" / "judge_v2.txt").read_text(encoding="utf-8")

for i in range(min(3, len(cases))):
    c = cases[i]
    cid = c.get("case_id", f"case_{i+1}")
    p1 = (
        v1_template.replace("{question}", c.get("question", ""))
        .replace("{context}", c.get("retrieved_context", ""))
        .replace("{answer}", c.get("answer", ""))
    )

    t0 = time.perf_counter()
    req = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(
            {
                "model": "llama3.1:8b",
                "prompt": p1,
                "stream": False,
                "options": {
                    "temperature": 0.0,
                    "top_p": 0.1,
                    "num_predict": 16,
                    "stop": ["\n", "}", "```"],
                },
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        res = json.loads(resp.read().decode("utf-8"))
    t_wall = (time.perf_counter() - t0) * 1000

    print(
        f"[{cid}] V1 Wall: {t_wall:.1f}ms | Prompt Tokens: {res.get('prompt_eval_count')} ({res.get('prompt_eval_duration',0)/1e6:.1f}ms) | Eval Tokens: {res.get('eval_count')} ({res.get('eval_duration',0)/1e6:.1f}ms) | Response: {repr(res.get('response'))}"
    )
