---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-41-4
points: 1
status: todo
story_id: US-PM-41
tags: []
title: Delete hub/dashboards.py, its doc page, and the init-time dashboards directory
updated: '2026-09-06'
---

git rm src/projectman/hub/dashboards.py and docs/hub-mode/dashboards.md. In src/projectman/cli.py remove `(proj / "dashboards").mkdir()` from init. Sweep docs: drop the dashboards/ line from the layout trees in docs/reference/cli.md, docs/reference/file-formats.md, docs/hub-mode/setup.md; remove the dashboards pointer paragraph from docs/hub-mode/cron.md and the per-project Epics column remark from docs/hub-mode/epics.md; fix the comments in src/projectman/hub/stores.py (lines ~216 and ~240) that list 'the dashboards' among the rollup consumers. grep -ri dashboards src docs afterwards: only the web dashboard (projectman web, pm_web_start) may remain.