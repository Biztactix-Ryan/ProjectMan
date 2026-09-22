---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-05'
depends_on:
- US-PM-25-7
- US-PM-25-8
id: US-PM-25-9
points: 1
status: done
story_id: US-PM-25
tags: []
title: Update the skill-content tests to the new wording
updated: '2026-09-05'
---

tests/test_skill_release_instructions.py, test_skill_guidance_tools.py, test_skill_verdict_verbs.py and test_verdict_verbs_note_length.py pin phrases from the orchestrate template. Run them; for each failure decide whether the test protects behaviour (keep the phrase in the template) or pins prose that was deliberately cut (update the test). Add one test asserting the rendered orchestrate skill is <= 9000 characters and one asserting the five worker rules are present.