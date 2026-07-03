---
assignee: claude
created: '2026-02-17'
id: US-PRJ-11-9
points: 2
status: done
story_id: US-PRJ-11
title: Wire auto-rebase into coordinated_push and push_hub
updated: '2026-02-19'
---

Integrate the auto-rebase logic into the existing push paths.

1. Update `push_hub()` (US-PRJ-4-8) to use `hub_push_with_rebase()` instead of plain `git push`
2. Update `coordinated_push()` (US-PRJ-4-9) orchestrator to handle rebase results:
   - Rebase succeeded + pushed → report "hub push required rebase (N retries)"
   - Rebase failed (diverged refs) → report which projects conflicted, suggest resolution
   - Max retries exceeded → report "hub push failed after N retries, manual resolution needed"
3. Log all ref updates (successful and conflicted) via ref update logger (first task)
4. Update the coordinated push report to show rebase activity:
   ```
   Hub:
     main → origin  h7i8j9k  ✓  (rebased, 1 retry)
   ```

Files: src/projectman/hub/registry.py