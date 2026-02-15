---
assignee: null
created: '2026-02-15'
id: US-PRJ-18-2
points: 2
status: done
story_id: US-PRJ-18
title: Add theme management JS to app.js
updated: '2026-02-15'
---

Add theme management logic to app.js: on page load, read localStorage('pm-theme') and apply to <html> data-theme. If no saved value, detect system preference via prefers-color-scheme. On toggle click, flip theme, update <html> attribute, save to localStorage.