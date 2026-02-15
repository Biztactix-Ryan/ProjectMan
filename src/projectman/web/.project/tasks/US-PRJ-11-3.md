---
assignee: null
created: '2026-02-15'
id: US-PRJ-11-3
points: 1
status: done
story_id: US-PRJ-11
title: Add live markdown preview panel
updated: '2026-02-15'
---

Enhance doc editor with live preview:
- Split layout: textarea on left, rendered preview on right
- Preview updates on input (debounced ~300ms)
- Server-side rendering via HTMX (POST textarea content, return rendered HTML) or client-side with a lightweight markdown library
- Preview panel scrolls in sync with textarea if possible