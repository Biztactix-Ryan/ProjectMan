---
created: '2026-02-15'
epic_id: EPIC-PRJ-4
id: US-PRJ-18
points: 5
priority: should
status: done
tags: []
title: Add dark mode theme toggle to the web dashboard
updated: '2026-02-15'
---

As a user, I want to switch the web dashboard between light and dark themes so that I can use it comfortably in low-light environments.

Acceptance criteria:
- Theme toggle button in the nav bar
- Clicking toggles between light and dark mode
- Theme preference persists across page reloads (localStorage)
- Defaults to system preference (prefers-color-scheme) if no saved value
- All UI elements (badges, progress bars, cards, dialogs) render correctly in both themes
- Hardcoded light-mode colors replaced with theme-aware alternatives