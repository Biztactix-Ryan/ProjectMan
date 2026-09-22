---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-08'
depends_on:
- US-PM-46-7
id: US-PM-47-4
points: 2
status: done
story_id: US-PM-47
tags: []
title: Delete docs/hub-mode and scrub hub mode from the docs and README and templates
updated: '2026-09-08'
---

Delete docs/hub-mode (cron.md, epics.md, git-workflow.md, setup.md, troubleshooting.md) and any nav or index that links to it (README.md, docs index pages). Remove hub-mode sections and prefix-argument mentions from docs/reference/agent.md, cli.md, mcp-tools.md, file-formats.md, skills.md, docs/user-guide/auditing.md, daily-workflow.md and README.md. In docs/reference/error-paths-inventory.md and readiness-warnings-determination.md either scrub or add a one-line history marker at the top saying the hub rows describe removed code. Remove the hub sections from src/projectman/templates/agent_pm.md.j2 and skill_pm.md.j2 (the user refreshes generated skills afterwards). Run tests/test_docs_after_subtraction.py tests/test_upgrading_docs.py tests/test_worktree_docs.py tests/test_readme_upgrade_link.py.