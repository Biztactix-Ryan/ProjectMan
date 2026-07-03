---
assignee: claude
created: '2026-02-17'
id: US-PRJ-11-6
points: 2
status: done
story_id: US-PRJ-11
title: Implement hub ref update logging for auditability
updated: '2026-02-19'
---

Add a ref update log so all hub submodule ref changes are tracked.

Create `.project/ref-log.yaml` (or append to existing audit log):
```yaml
- timestamp: "2026-02-17T14:30:00Z"
  project: api
  old_ref: a1b2c3d
  new_ref: d4e5f6g
  author: developer-a
  source: coordinated_push   # or: changeset, manual, sync
  commit: h7i8j9k            # hub commit sha
```

Add `log_ref_update(project, old_ref, new_ref, source, root)` to `hub/registry.py`.

Wire into all paths that update hub refs:
- `update_hub_refs()` (US-PRJ-7-9)
- `push_hub()` (US-PRJ-4-8)
- `sync()` (existing, when submodule refs change after pull)

Keep the log append-only, capped at last 500 entries (rotate older entries to ref-log.archive.yaml).

Files: src/projectman/hub/registry.py