---
acceptance_criteria:
- A done or archived story whose criteria have no test task produces no warning and
  a backlog or active story in that state still does
- The missing-evidence warning counts only done tasks that could have carried evidence
  and the rule is stated in the audit code
- pm_audit on this repository reports zero warnings without any historical item being
  edited
- The full suite passes
created: '2026-09-08'
depends_on: []
epic_id: null
id: US-PM-43
points: 3
priority: should
status: done
tags:
- audit
- quality
- orchestrator
title: pm_audit warns only about what someone can act on
updated: '2026-09-08'
---

As an orchestrator or a planner reading pm_audit, I want every WARN line to point at something that can be fixed now so that a clean project reports zero warnings and a new warning is noticed.

State on 2026-09-08: this repo has had the same three warnings for weeks and none of them is actionable.

1. "Story US-PM-1 has 4 acceptance criteria with no test task" and the same for US-PM-2. Both stories are done and predate test-task reconciliation (US-PM-5). Re-applying their criteria as the message suggests would create todo test tasks under done stories, which is worse than the warning. The check should skip stories that are done or archived: the criteria were verified some other way and nothing remains to act on.

2. "447 done tasks have no structured evidence on any run-log entry". Every one of those was completed before the evidence contract existed (US-PM-9, Sprint 4). The count can never shrink without rewriting history. Restrict the check so it counts only tasks that could have carried evidence: a task whose done transition was made under an orchestrator run (run_id stamped) or whose run-log entries were written after evidence became available. The audit code and its docstring should state the rule so the cutoff is not a magic date.

Do not alter any historical item to make the numbers move. The fix lives in audit.py and its tests. Keep the INFO findings as they are.