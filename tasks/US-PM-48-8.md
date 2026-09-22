---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on:
- US-PM-48-6
- US-PM-48-7
id: US-PM-48-8
points: 2
status: done
story_id: US-PM-48
tags: []
title: Update skill-content tests and regenerate the rendered orchestrate skill
updated: '2026-09-09'
---

Adjust the tests that assert on pm-orchestrate wording (tests/test_field_projection.py, tests/test_interactive_skills_optional_context.py and any others grepping skill_pm_orchestrate) to the validator flow, and add assertions that the template contains the validator prompt block, the JSON verdict shape, and stays under 9000 characters. Regenerate the tracked rendered copies under .claude/ by rendering into the scratchpad and cp-ing over, never by writing into .claude/ directly.