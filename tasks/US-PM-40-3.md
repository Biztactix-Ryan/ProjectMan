---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PM-40-3
points: 1
status: done
story_id: US-PM-40
tags: []
title: keyword_search tolerates a malformed file and reports the skipped count
updated: '2026-09-07'
---

In src/projectman/search.py wrap `frontmatter.load` per file in try/except (yaml.YAMLError, ValueError, OSError as the indexer does), count the skipped file, and continue. Return the count alongside results without breaking the two callers: either return a small dataclass/tuple or attach `skipped` to the result list via a companion function; then surface it as `skipped: N` on the pm_search response in server.py and as a `skipped` key in the /api/search JSON in web/routes/api.py. Add a tests/test_search.py case with one file whose frontmatter is `---\n: bad\n---`.