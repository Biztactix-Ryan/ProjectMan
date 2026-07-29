---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-2-2
points: 2
status: done
story_id: US-PM-2
tags: []
title: Inventory every error-string return path
updated: '2026-07-29'
---

Find every tool that catches an exception and returns a formatted error string rather than raising. Classify each as a genuine failure or an expected-negative result. Study B's observed messages are a starting point: run-log note cap, task is not ready to grab, No .project/config.yaml found in any parent directory, VISION.md not found.

Output: a list mapping each site to the intended classification. This drives the other tasks.