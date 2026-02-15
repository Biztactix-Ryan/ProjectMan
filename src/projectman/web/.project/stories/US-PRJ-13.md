---
created: '2026-02-15'
epic_id: EPIC-PRJ-3
id: US-PRJ-13
points: 3
priority: should
status: done
tags: []
title: Search functionality
updated: '2026-02-15'
---

As a user, I want a search bar in the navigation and a results page so that I can quickly find stories, tasks, and epics by keyword.

**Features:**
- Search input in nav bar (all pages)
- Results page at `/search?q=` showing matched items
- Results grouped by type (epics, stories, tasks)
- Snippets with keyword highlighting
- Uses existing `pm_search()` (keyword + optional semantic search)

**Acceptance criteria:**
- Search bar visible on every page in nav
- Results page shows items with title, type, status, snippet
- Clicking result navigates to detail view
- Empty query shows helpful message
- No results state handled