---
assignee: null
created: '2026-02-15'
id: US-PRJ-16-1
points: 2
status: done
story_id: US-PRJ-16
title: Add responsive breakpoints and collapsible hamburger nav
updated: '2026-02-15'
---

Make layout responsive in `templates/base.html` and `static/style.css`:
- Responsive breakpoints: mobile < 768px, tablet < 1024px, desktop
- Collapsible hamburger menu on mobile (CSS + minimal JS toggle)
- Nav items hidden behind hamburger on small screens
- Touch-friendly: larger tap targets (min 44px), appropriate spacing
- Test at 375px width (iPhone SE)