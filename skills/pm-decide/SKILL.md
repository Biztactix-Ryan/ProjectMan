---
name: pm-decide
description: Work through open decisions one by one — brief each, ask the user, record the answer and report what it unblocked. Use when the user says "decide", "answer the open questions", "what's blocked on me", or pm_context / pm_status reports open decisions.
args: "[<batch-size>]"
---

# /projectman:pm-decide — Decision Session

Open decisions hold work back: a task they block never becomes ready. This session clears a batch of them in the order that unblocks the most, one question at a time.

**Argument** — batch size `n`, default 7. `/projectman:pm-decide 3` asks about at most three.

## Phase 1 — Load the batch

1. `pm_list_decisions(order="session", limit=n)` — open decisions only, active-sprint blockers first, then planning, then the rest, each by `blocked_points`. Rows carry `id`, `title` (the question), `options`, `recommendation`, `blocks`, `blocked` (`{id, title}` per blocked item), `blocked_points` and `tier`.
2. Empty list → say there is nothing waiting on a decision and stop.
3. Fetch every context in one call: `pm_get("<id1>,<id2>,…", fields="body")`. The body is the decision's context.
4. Tell the user how many are in the batch, how many are open in total (`total`), and the points they hold.

## Phase 2 — One decision at a time

For each decision, in list order:

5. **Brief** — a few lines, no more:
   - **Question** — the `title`.
   - **Context** — the body, condensed to what the choice turns on.
   - **Blocks** — each `blocked` item as `id — title`, and `blocked_points` points held.
   - **Options** — each option's `label` and `summary`, pros and cons in one line each.
   - **Recommendation** — the `recommendation` label and why, if there is one.
   - **Docs** — only when the context cites a project doc (VISION, ARCHITECTURE, PROJECT, INFRASTRUCTURE, SECURITY, DECISIONS): `pm_docs(doc="<name>")` and quote just the cited lines. Never pull docs it does not cite.
6. **Ask** — one `AskUserQuestion`:
   - Options: the recommended option first, its label marked `(Recommended)`; then the other options; then **Skip**; then **Withdraw**.
   - It takes at most four options. When they do not fit, keep the recommendation and the next options, and drop Withdraw, then Skip, into the question text: "or type *skip*, or *withdraw: <reason>*".
   - The free-text answer is always open: the user may type an answer of their own instead of picking a label.
7. **Record** with `pm_answer_decision`:
   - Picked option → `pm_answer_decision(id, answer="<label>", rationale="<the user's why, if given>")`.
   - Free-text answer → `pm_answer_decision(id, answer="<their words>", rationale=…)`, recorded as typed.
   - Withdraw → `pm_answer_decision(id, withdraw=true, reason="<why>")`. No reason given → ask for one; withdrawing needs it.
   - Skip → write nothing; it stays open.
   - A `conflict` means someone closed it meanwhile: report the existing outcome and move on. Pass `overwrite=true` only when the user asks to replace it.
8. Keep the `unblocked` task IDs each call returns, and say them in one line: "Unblocked US-PRJ-4-2, US-PRJ-4-3."

## Phase 3 — Summary

9. Points unblocked: `pm_get("<all unblocked IDs>", fields="points")`, summed.
10. Summarize the session:
    - **Answered** — each `id — question → answer`.
    - **Skipped** — each `id — question`, still open.
    - **Withdrawn** — each `id — question — reason`.
    - **Unblocked** — the task IDs and the points unblocked in total.
11. More left (`has_more`) → offer the next batch: `pm_list_decisions(order="session", limit=n, offset=<skipped count>)`, since skipped ones stay first in line.
12. Offer `/projectman:pm-plan` to plan the unblocked work into a sprint.

Example summary:
```
Decision session — 3 of 5 open
Answered:  DEC-PRJ-2 — Which queue backend? → Redis streams
Skipped:   DEC-PRJ-5 — Keep the v1 API? (still open)
Withdrawn: DEC-PRJ-3 — Shard by tenant? — superseded by DEC-PRJ-2
Unblocked: US-PRJ-4-2, US-PRJ-4-3, US-PRJ-6-1 — 8 pts
Next: plan them into a sprint with /projectman:pm-plan?
```
