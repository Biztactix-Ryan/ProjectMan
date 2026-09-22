---
acceptance_criteria:
- Activity feed visible on web dashboard
- Entries show event type icon and item ID linked to detail view
- Relative timestamps displayed
- Feed loads recent entries with scroll/pagination
- API endpoint serves activity data as JSON
created: '2026-02-17'
epic_id: EPIC-PRJ-3
id: US-PRJ-20
points: 5
priority: should
status: done
tags: []
title: Web UI activity feed
updated: '2026-03-01'
---

As a user of the web dashboard, I want to see a live activity feed so that I can visually track what's happening across the project in real time.

Add an activity timeline/feed to the web UI that displays recent log entries in chronological order. Each entry should show: icon by event type, item ID (linked), description of what changed, timestamp (relative like "2 hours ago"), and actor. The feed should be on the main dashboard or accessible via a dedicated tab/page.