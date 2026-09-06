---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-29-4
id: US-PM-29-6
points: 1
status: done
story_id: US-PM-29
tags: []
title: Decide tracked versus generated for the five index files with the churn numbers
  and document it
updated: '2026-09-06'
---

With the per-write rebuilds gone, measure how often pm_commit still changes INDEX.md, INDEX-EPICS.md, INDEX-STORIES.md, INDEX-TASKS.md and index.yaml on this repo's history (git log --stat over .project). If they still churn on most commits, gitignore them inside .project and generate on demand; otherwise keep them tracked. Either way record the decision and the numbers in docs/reference/file-formats.md and the run log.