---
assignee: null
created: '2026-02-15'
id: US-PRJ-13-1
points: 1
status: done
story_id: US-PRJ-13
title: Add search bar to nav in base layout
updated: '2026-02-15'
---

Add search input to the nav bar in `templates/base.html`:
- Text input with search icon/button
- Form submits to `/search?q=` (GET request)
- Visible on every page
- Styled to fit within existing nav layout
- Placeholder text: "Search stories, tasks..."