---
acceptance_criteria:
- src/projectman/hub/dashboards.py and docs/hub-mode/dashboards.md do not exist and
  nothing under src or docs imports or links them
- projectman init no longer creates a .project/dashboards directory and no layout
  diagram under docs shows one
- Tests that reached rollup or the not-attached rows through generate_dashboards now
  call rollup directly and the full unit suite passes
created: '2026-09-06'
depends_on: []
epic_id: null
id: US-PM-41
points: 2
priority: should
status: backlog
tags:
- subtraction
- hub
title: hub/dashboards.py leaves the package
updated: '2026-09-06'
---

As a maintainer, I want unreachable code out of the package so that the hub surface is only what a command or tool can reach. generate_dashboards in src/projectman/hub/dashboards.py (96 lines) has no caller in src: docs/hub-mode/cron.md says no command regenerates dashboards, and docs/hub-mode/dashboards.md offers a two-line Python snippet as the only way in. Decision (2026-09-06): delete rather than wire a CLI command. Remove the module and docs/hub-mode/dashboards.md, stop `projectman init` scaffolding an empty .project/dashboards directory, and drop the directory from the layout diagrams in docs/reference/cli.md, docs/reference/file-formats.md and docs/hub-mode/setup.md; cron.md loses its pointer and epics.md its per-project Epics column remark. Ten test files mention dashboards; the ones that exercise rollup or the not-attached rows through generate_dashboards should call rollup directly, the ones that only assert the module's own rendering go. The hub's own docs and the web dashboard (projectman web) are unrelated and stay.