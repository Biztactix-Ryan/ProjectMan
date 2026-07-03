---
acceptance_criteria:
- PR commands use subprocess list args or shlex.quote for all user input
- Cross-ref block renders newlines correctly in GitHub
- Titles and descriptions with quotes/backticks/semicolons are safe
- Tests cover special character edge cases
created: '2026-03-09'
epic_id: EPIC-PRJ-9
id: US-PRJ-47
points: 3
priority: must
status: backlog
tags:
- security
- changesets
title: Fix shell injection risk in changeset PR command generation
updated: '2026-03-09'
---

As a security-conscious developer, I want PR command generation to be safe from injection so that changeset titles/descriptions with special characters don't execute arbitrary commands. changesets.py lines 119-124 build shell commands with unescaped user input. Cross-ref block (line 104) uses escaped newlines incorrectly. Use subprocess list args or proper shell escaping.