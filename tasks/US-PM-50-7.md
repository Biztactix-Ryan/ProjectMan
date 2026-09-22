---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-09'
depends_on: []
id: US-PM-50-7
points: 1
status: done
story_id: US-PM-50
tags: []
title: Add the orchestrate.max_task_minutes config key
updated: '2026-09-09'
---

config.py: new `orchestrate.max_task_minutes` key, default 60, read through the same accessor pattern as stale_claim_hours, with a commented line in templates/config.yaml.j2. Test in tests/test_config.py that the default applies and an override is read.