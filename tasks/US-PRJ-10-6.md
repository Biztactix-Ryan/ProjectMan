---
assignee: claude
created: '2026-02-17'
id: US-PRJ-10-6
points: 3
status: done
story_id: US-PRJ-10
title: Define changeset data model and storage
updated: '2026-02-19'
---

Design and implement the changeset storage format.

A changeset is a logical grouping of related changes across multiple subprojects. Store in `.project/changesets/`.

Model (src/projectman/models.py):
```python
class Changeset(BaseModel):
    id: str                          # e.g. "CS-PRJ-1"
    name: str                        # human name: "auth-system-v2"
    status: str                      # "open" | "partial" | "merged" | "closed"
    projects: list[ChangesetProject]
    created: str
    updated: str

class ChangesetProject(BaseModel):
    name: str                        # subproject name
    branch: str                      # feature branch in that project
    pr_number: int | None = None     # PR number once created
    pr_url: str | None = None
    pr_state: str | None = None      # "open" | "merged" | "closed"
```

Storage: `.project/changesets/CS-PRJ-1.yaml` (YAML frontmatter + optional body for description, same pattern as stories/tasks).

Add CRUD functions in a new `src/projectman/changesets.py`: `create_changeset()`, `add_project_to_changeset()`, `get_changeset()`, `list_changesets()`, `update_changeset_status()`.

Files: src/projectman/models.py, src/projectman/changesets.py