---
acceptance_criteria:
- A criterion containing commas is stored as one criterion via pm_create_story
- A criterion containing commas is stored as one criterion via pm_update
- pm_update criteria edits still reconcile auto-generated test tasks correctly
- Tool docstrings no longer instruct comma-separated criteria
- Regression tests cover comma-bearing criteria on both tools
created: '2026-08-20'
depends_on: []
epic_id: null
id: US-PM-18
points: 5
priority: must
status: done
tags:
- bug
- mcp
- dx
title: Fix comma-splitting of acceptance criteria in MCP story tools
updated: '2026-08-20'
---

As an agent creating stories via MCP, I want acceptance_criteria to survive intact so that natural-language criteria are not shredded into fragments.

Long-standing bug: pm_create_story (src/projectman/server.py:1050) and pm_update (src/projectman/server.py:1481-1483) take acceptance_criteria as a comma-separated string and split blindly on ','. Any criterion written in natural language (e.g. \"Given a user, when they log in, then the dashboard loads\") is split into three bogus criteria. This bites every time Claude writes stories, and since acceptance criteria drive auto-generated test tasks, each mangled criterion also spawns a garbage test task.

Recommended fix: change the MCP param to accept a JSON list (list[str], as the web API already does in web/schemas.py) — optionally Union[str, list[str]] where a bare string is treated as a single criterion, never comma-split. Update the tool docstrings accordingly. The pm_update path must keep test-task reconciliation working. tags and depends_on can stay comma-split (they are IDs/slugs, commas never legitimate), but confirm while in there.