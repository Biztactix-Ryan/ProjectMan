---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-17'
depends_on: []
id: US-PM-54-7
points: 2
status: done
story_id: US-PM-54
tags: []
title: orch-cost reports the cache TTL mix and heartbeat count
updated: '2026-09-17'
---

analyze() gains `ttl` ({"5m": n, "1h": n} counted from usage.cache_creation.ephemeral_5m_input_tokens / ephemeral_1h_input_tokens per deduped call) and `heartbeats` (user records whose text carries the heartbeat prompt marker). The CLI prints both in the text report; --json carries them. Extend the baseline_transcript fixture rather than adding a new one, and update CHANGELOG.md under Unreleased.