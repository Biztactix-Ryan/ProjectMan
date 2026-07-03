---
acceptance_criteria:
- All tool references in pm skill correspond to actual MCP tools
- Non-existent tool references either implemented or removed
- Skill tested to verify all routing targets exist
created: '2026-03-09'
epic_id: EPIC-PRJ-11
id: US-PRJ-57
points: 2
priority: must
status: backlog
tags:
- skills
- mcp
title: Fix pm skill references to non-existent tools
updated: '2026-03-09'
---

As a user running /pm, I want all referenced tools to actually exist so that the skill works correctly. The pm skill (line 61-62) references validate_conventions, create_feature_branch, and create_pr which don't exist in server.py. Either implement these tools or remove the references.