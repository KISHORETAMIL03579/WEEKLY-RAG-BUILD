<!-- Soft Suave · The AI Engineering League -->
# Week 9 Practical — Task Set C

## Bolt on the HRIS server without touching the agent

| | |
|---|---|
| Domain | HR policy |
| Week | 9 — MCP — the Standard Way Agents Reach Tools & Data |
| Module | M5 — MCP, Multi-agent & A2A |
| Sat on | Week 10 · Monday |
| Marks | 100 |

> **This is an extension of the app you already built in Week 9.** It is not a build from scratch, and it tests only this week's concepts. Bring your numbers written down.


---

## 1. Problem statement

People Ops has stood up an MCP server over the HRIS that exposes an employee's grade band and accrued leave balance by employee id. They want your policy assistant using it before the appraisal window opens on Wednesday, and they are not waiting for a code release. Your Week-9 agent already discovers tools from your own policy-search server — prove that discovery was real by adding server two with nothing but config.


---

## 2. Requirements

1. Add the HRIS server to your agent's MCP config and run one query that provably calls a tool from it (show the tool name in the trace).
2. Produce a git diff proving ZERO lines changed in your agent module between server one and server one plus two — config changes only.
3. Report the number of tools discovered before and after, with names, from tools/list — not from your own notes.
4. Capture the raw JSON-RPC initialize -> tools/list -> tools/call exchange against the new server, annotate every top-level field by hand, and state in one line where the model call happens and where it does not.
5. Rewrite ONE tool docstring on YOUR OWN server as a prompt and make one of its error paths recoverable (e.g. "no policy version effective 2023-01-01: earliest is 2024-04-01" not "Error 3"), then show a before/after transcript of the model handling that same failing call.
6. Write a 5-line supply-chain risk note for the HRIS server: who wrote it, what it can reach, what it logs, what a stolen token could do, ship or don't.


---

## 3. Expected output

agent_diff.txt (zero changed lines), the config diff, wire.json with hand annotations, tool counts before -> after with names, error_before_after.md transcript, risk_note.md (5 lines).


---

## 4. Evaluation rubric

| Criterion | Points |
|---|---|
| Config-only server swap proven by diff: agent module shows zero changed lines | 30 |
| Raw initialize/tools-list/tools-call captured and annotated, model-call location stated correctly | 25 |
| Docstring-as-prompt plus recoverable-error rewrite, evidenced by a before/after model transcript | 20 |
| Tool count reported before and after discovery, with names, taken from tools/list | 15 |
| Five-line third-party risk note answering who wrote it, what it reaches, what it logs | 10 |
| **Total** | **100** |

*Zero points for polish, UI, or "it works". This mirrors the House rubric: failure-finding and a number that moved are what score.*


---

## 5. Bonus challenge

Put both servers behind one gateway process: the agent connects to one front door, the gateway fans out, and every tools/call is written to a single audit line with caller, tool, and employee id. Then scope a token so grade-band lookup is denied while leave balance still works, and show the denial reaching the model as a recoverable message.


---

## 6. Submission checklist

- [ ] agent_diff.txt showing 0 changed lines in the agent module
- [ ] config diff adding the second server
- [ ] wire.json — raw initialize, tools/list, tools/call, annotated
- [ ] Tool count line: N before -> M after, with tool names
- [ ] error_before_after.md — same failing call, old docstring/error vs new
- [ ] risk_note.md — exactly 5 lines


---

## 7. Common mistakes

- **Hard-coding the tool list after connecting to the server, which throws away the entire point of discovery — your diff should show the agent unchanged when you add server two.**
- **Putting an LLM call inside your MCP server so it 'interprets the leave policy' — the server exposes a capability, the host runs the model, and this mistake means you never understood the architecture.**
- **Exposing the current policy handbook as a tool when it is context the app should attach — resources are app-attached, tools are model-invoked, and the wrong choice makes the model spend turns fetching the document it should have been handed.**
- **Swallowing the effective-date miss into 'Error: not found', so the model cannot tell 'this policy version does not exist yet' from 'the HRIS is down' and quotes last year's notice period anyway.**
- **Adding the third-party HRIS connector because it worked, without asking what it can reach — it now runs inside your agent's trust boundary with a token that can read salary-adjacent fields.**


---

*Set C of 6. Sets A–F are equivalent in difficulty and objectives; only the domain differs.*
