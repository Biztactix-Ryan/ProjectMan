---
archived: false
assignee: null
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PM-31-6
id: US-PM-31-9
points: 2
status: todo
story_id: US-PM-31
tags: []
title: Rollup, dashboards and pm_status report unattached stores instead of raising
updated: '2026-09-06'
---

hub/rollup.rollup and hub/dashboards iterate hub_stores(); an entry with attached false is reported with status 'not attached' and the attach hint, and never constructs a Store. pm_status in a hub without a prefix lists the subprojects with their attached state. Update the existing hub fixtures in tests (about 20 files build .project/projects) to the projects/{name}/.project layout through one shared fixture in tests/conftest.py so later stories do not rebuild them. Files: src/projectman/hub/rollup.py, src/projectman/hub/dashboards.py, src/projectman/server.py, tests/conftest.py.