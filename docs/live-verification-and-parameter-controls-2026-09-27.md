# Live Verification and Shared Parameter Controls

**Date:** 2026-09-27  
**Branch:** `week-7`

## Live verification findings

The frontend and backend were reachable during live browser verification. The
chat composer rendered with the `.chat-composer-input` class. The home page
reported that its backend connection was established.

Live Week 7 Policy Search requests succeeded:

- Workflow run `search_34cd974cb686` answered that EMP001 receives 24 working
  days of annual leave per year, accruing at 2 days per month, and cited
  Section 5.2.1. The response reported Top-K 5, temperature 0.3, and model
  `openai/gpt-oss-20b`.
- Agent run `search_f1656f183c47` answered that EMP007 receives 30 days'
  notice and severance equivalent to 60 days of basic pay ($10,000), based on
  four completed years of service. It completed with 3,349 live Groq tokens.
- A live single-case Workflow run `wf_c42dfec7` returned success and reported
  Top-K 8, temperature 0.5, and model `openai/gpt-oss-20b`. Its answer cited
  Section 10.1 and stated the one-week written notice rule for probationary
  staff.

The single-case Workflow request had previously omitted the selected model
and temperature. The frontend now sends those values along with Top-K.

## Shared controls

`ModelParameterControls.tsx` provides the reusable Top-K and temperature
sliders used by the chat sidebar, Policy Search, Policy Assistant, Judge
Evaluator, and Retrieval Benchmark.

- Top-K is a draggable integer slider from 1 through 20. Retrieval Benchmark
  has no temperature setting because it measures retrieval and does not run
  generation.
- Temperature remains a continuous 0.00–1.00 slider. Named preset buttons set
  0.0 (Deterministic), 0.2 (Grounded), 0.5 (Balanced), and 0.8 (Hallucination
  risk). The current badge uses the application's existing category helper.
- Existing model selection and API payload pathways are retained.

## Verification limits and outstanding dependencies

No automated test suites or benchmark runs were launched during the live-only
verification. Frontend TypeScript checking and production build succeeded.

Backend `/healthz` returned HTTP 200. `/readyz` reported `app=true`,
`qdrant=true`, and `ollama=false`. The chat session had no indexed documents;
document upload and document-grounded chat could not be verified until the
configured Ollama embedding service is available.

The Ireland statutory sick-leave comparison previously failed with a token
budget error. The jurisdiction rules currently do not include an Ireland
statutory sick-leave guideline, so that comparison remains unverified and must
not be reported as fixed.

Judge and Retrieval benchmark pages were inspected without starting benchmark
runs. Their progress, cancellation, and completed-run result behavior therefore
remain unverified by this live session.
