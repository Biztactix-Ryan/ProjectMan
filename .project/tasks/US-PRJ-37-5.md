---
assignee: null
created: '2026-07-30'
depends_on: []
id: US-PRJ-37-5
points: 2
status: todo
story_id: US-PRJ-37
tags: []
title: Audit cached-read call sites for caller mutation risk
updated: '2026-07-30'
---

The deepcopy removal landed in commit 03a1674 (0.8.4). Walk every store.py path that returns cached frontmatter or lists of it (get/list/list_by_status and their epic/story/task/changeset variants) and confirm no caller mutates the returned Pydantic models or list objects in place. Document any site that does and convert it to a copy-on-write or model_copy at the call site rather than reinstating blanket deep copies.