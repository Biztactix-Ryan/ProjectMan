---
assignee: claude
created: '2026-07-29'
depends_on:
- US-PM-6-6
id: US-PM-6-7
points: 2
status: done
story_id: US-PM-6
tags: []
title: Classify failures correctly across all three classes
updated: '2026-07-29'
---

Hard errors via is_error, soft errors by matching an error prefix in the response body, and malformed inputs via the __unparsedToolInput key in the input dict. Report the three separately and as a combined true failure rate.

This is the step two of the four studies got wrong, producing ~1% failure rates where the truth was 6-12%.