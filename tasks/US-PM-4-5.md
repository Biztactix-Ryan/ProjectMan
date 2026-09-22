---
assignee: claude
created: '2026-07-29'
depends_on: []
id: US-PM-4-5
points: 1
status: done
story_id: US-PM-4
tags: []
title: Determine whether the templates or the checks are wrong
updated: '2026-07-29'
---

readiness.py:66-70 fires all three warnings on 100% of items (Study B: 758/758). Before deleting, check whether the project templates simply never produce Implementation / Testing / Definition of Done sections — in which case the templates are the defect and the checks are correct.

This decision determines whether the fix is template work or check removal.