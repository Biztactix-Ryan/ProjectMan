---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-29-4
points: 2
status: done
story_id: US-PM-29
tags: []
title: Drop the per-write write_index calls and rebuild indexes only in pm_reindex,
  pm_commit and the CLI reindex
updated: '2026-09-06'
---

Remove the 18 indexer.write_index call sites that follow mutating tools in src/projectman/server.py. Keep exactly three rebuild points: pm_reindex, pm_commit (immediately before staging, in server.py and in hub/registry.pm_commit and cli.commit) and the CLI reindex command. After a pm_update on a clean tree, git status inside .project must show only the item file and activity.jsonl. Files: src/projectman/server.py, src/projectman/cli.py, src/projectman/hub/registry.py.