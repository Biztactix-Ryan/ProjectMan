---
created: '2026-02-16'
id: EPIC-PRJ-1
points: null
priority: must
status: done
tags:
- workflow
- submodules
- hub
- devops
target_date: null
title: 'Hub Push Workflow: Fix Submodule Commit & Push Alignment'
updated: '2026-03-01'
---

Currently we are using submodules to be able to see code. However, when we update say 5 projects simultaneously we then commit 5 and then push 5. But if another person has changed the submodule tracking to another branch, it would push to the wrong branch. There are a lot of issues keeping this all aligned.

The hub project is on main because the docs/project stuff should never be branched, but the individual projects are going to need separate commits. We need to look at the workflow and find a clear way to fix this.

**Key Problems:**
- Simultaneous multi-project updates require N commits + N pushes
- Submodule branch tracking can drift if another person changes it
- Risk of pushing to the wrong branch
- Hub stays on main (docs/project data shouldn't branch), but subprojects need independent branching
- No clear coordination mechanism for keeping submodule refs aligned

**Success Criteria:**
- Clear, documented workflow for committing and pushing across hub + subprojects
- Eliminate risk of pushing to wrong branch due to stale submodule tracking
- Support independent branching per subproject while hub stays on main
- Minimal friction for multi-project simultaneous updates