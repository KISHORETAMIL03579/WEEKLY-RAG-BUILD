import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from week6.judge import check_ollama_health, call_llm_judge
import time

t0 = time.time()
health = check_ollama_health()
print(f"Ollama health: {health}, time: {time.time()-t0:.4f}s")

t1 = time.time()
res = call_llm_judge("Is 2+2=4?")
print(f"call_llm_judge result: {res}, time: {time.time()-t1:.4f}s")

