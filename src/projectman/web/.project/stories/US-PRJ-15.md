---
created: '2026-02-15'
epic_id: EPIC-PRJ-3
id: US-PRJ-15
points: 2
priority: could
status: done
tags: []
title: Toast notifications
updated: '2026-02-15'
---

As a user, I want toast messages for create/update/error actions so that I get feedback when operations succeed or fail.

**Features:**
- Toast component (slide-in from top-right or bottom)
- Success toasts: "Story created", "Task updated", "Doc saved"
- Error toasts: "Failed to update", validation errors
- Auto-dismiss after 3-5 seconds
- Triggered by HTMX response headers (HX-Trigger) or custom events

**Implementation:**
- HTMX `hx-on::after-request` or response header triggers
- Minimal JS toast handler in `static/app.js`
- CSS animations for slide-in/fade-out

**Acceptance criteria:**
- All create/update/delete operations show success toast
- Errors show error toast with message
- Toasts auto-dismiss
- Multiple toasts stack without overlap