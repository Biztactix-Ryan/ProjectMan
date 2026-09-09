---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-51-7
id: US-PM-51-8
points: 3
status: done
story_id: US-PM-51
tags: []
title: Merge accepted branches and replace the snapshot checks with a branch diff
updated: '2026-09-09'
---

skill_pm_orchestrate.md.j2: the diff check becomes `git diff --stat orch/<run-id>...orch/<run-id>/<task-id>` plus a list of touched paths; drop the step 14 tar snapshot and md5 lists. On accept, merge the task branch onto the run branch (fast-forward when possible, else a merge commit titled with the task id) before the next dispatch. A merge conflict is one validation failure: pm_retry with the conflicting paths in evidence.files and a note telling the retry worker to rebase onto the run branch; a second conflict parks. Update the memory-recorded snap.sh rule in the design doc's Known failure modes to the branch model.