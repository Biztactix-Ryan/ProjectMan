---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-31-6
points: 3
status: done
story_id: US-PM-31
tags: []
title: 'hub/stores.py: the store map that locates each subproject''s store at projects/{name}/.project'
updated: '2026-09-06'
---

New module src/projectman/hub/stores.py with hub_stores(root) -> list of {name, prefix, path, attached: bool}. Walk config.projects; for each, path = root/projects/{name}/.project; attached when worktree.is_worktree(path) and config.yaml exists; read prefix from that config.yaml. Cache per process the way _store_cache does. Replace _resolve_project_dir and the project branch of _store in server.py, and the .project/projects references in hub/rollup.py, indexer.py, cli.py and web/routes/api.py, with lookups through the map. Grep must find no remaining '.project/projects' or '"projects" /' path construction under src/.