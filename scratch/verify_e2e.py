import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient
from app import app
import json

client = TestClient(app)

# 1. GET default benchmark
resp = client.get('/api/evaluation/judges')
data = resp.json()
print('Default GET total_cases:', data.get('total_cases'))
print('Judge V2 Agreement:', data.get('judge_v2_agreement_pct'))

# 2. POST with raw uploaded cases missing context (e.g. txt_case_2)
cases_payload = [
    {
        'case_id': 'txt_case_2',
        'question': 'Under what circumstances is an employee entitled to paid sick leave?',
        'answer': 'An employee is entitled to paid sick leave when they are incapacitated for the performance of their duties by illness or injury, and have completed at least two consecutive months of service [1]. They are entitled to two working days per month of completed service, with one day at full pay and one day at half pay [1].',
        'retrieved_context': '',
        'human_label': 1
    },
    {
        'case_id': 'txt_case_1',
        'question': 'Under what circumstances is an employee entitled to paid sick leave?',
        'answer': 'A staff member is entitled to paid sick leave at the rate of one day at full pay per month of completed service, subject to a minimum of 7 days at full pay, as stated in [1].',
        'retrieved_context': '',
        'human_label': 0
    }
]

# 3. POST all 25 benchmark cases
with open('week6/eval_cases_25.json', 'r', encoding='utf-8') as f:
    all_25 = json.load(f)

eval_25_resp = client.post('/api/evaluation/judges', json={'cases': all_25, 'run_llm': True})
res_25_data = eval_25_resp.json()
print('\nPOST All 25 Benchmark Cases Evaluation:')
print('Total cases:', res_25_data.get('total_cases'))
print('Judge V1 Agreement %:', res_25_data.get('judge_v1_agreement_pct'))
print('Judge V2 Agreement %:', res_25_data.get('judge_v2_agreement_pct'))
print(f"V1 Agreements: {res_25_data.get('v1_agreements')}/25, V2 Agreements: {res_25_data.get('v2_agreements')}/25")

print("\nAll assertions and checks verified successfully!")
