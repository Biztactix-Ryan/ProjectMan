---
assignee: null
created: '2026-02-15'
id: US-PRJ-18-3
points: 2
status: done
story_id: US-PRJ-18
title: Fix hardcoded colors for dark mode compatibility
updated: '2026-02-15'
---

Update style.css to replace hardcoded light-mode colors with theme-aware alternatives. Specifically: badge backgrounds (.badge-draft, .badge-ready, etc.) need [data-theme='dark'] variants, .detail-header .detail-meta code background (#f1f5f9) should use a CSS variable, progress bar background (#e2e8f0) should use a CSS variable. Ensure all cards, borders, and shadows look correct in dark mode.