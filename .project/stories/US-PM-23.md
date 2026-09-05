---
acceptance_criteria:
- docs/installation.md has an Upgrading section with the pipx force-reinstall from
  a local path and the refresh-skills step
- The Upgrading section names the symptom of a stale install and the mcp<2 requirement
- README links to the Upgrading section from its install instructions
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-23
points: 1
priority: must
status: done
tags:
- docs
- subtraction
title: Upgrade docs cover reinstalling from the local tree
updated: '2026-09-05'
---

As a developer running ProjectMan from a pipx install, I want the docs to say how to refresh that install from my working tree so that the MCP server I talk to is not silently weeks behind the code I just changed.

Background: on 2026-09-05 the pipx install was found lagging the repo by several sprints. The fix is `pipx install --force "/path/to/ProjectMan[all]"` followed by `projectman refresh-skills --keep-local`. Neither step is written down anywhere. The `mcp<2` pin (commit 1061084) also needs mentioning because a stale venv with mcp 2.x fails with "MCP extras not installed".