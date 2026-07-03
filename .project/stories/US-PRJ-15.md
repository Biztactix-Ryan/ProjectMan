---
acceptance_criteria:
- CreateStoryRequest and CreateTaskRequest schemas include optional tags field
- TaskResponse schema includes tags field
- stories.html has tag input in create form and tags column in table
- story_detail.html displays and allows editing tags
- task_detail.html displays and allows editing tags
- Web API routes pass tags through on create
created: '2026-02-17'
epic_id: EPIC-PRJ-2
id: US-PRJ-15
points: 5
priority: should
status: done
tags: []
title: Web dashboard tag support for stories and tasks
updated: '2026-03-01'
---

As a web dashboard user, I want to see and manage tags on stories and tasks, not just epics. Add tag input fields to story/task create forms, display tags in list tables and detail views, and add tags to the web API request/response schemas (CreateStoryRequest, CreateTaskRequest, TaskResponse).