---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on: []
id: US-PRJ-62-5
points: 2
status: done
story_id: US-PRJ-62
tags: []
title: Write tests/test_search.py covering keyword_search directly
updated: '2026-09-06'
---

Create tests/test_search.py that exercises src/projectman/search.py keyword_search without going through pm_search. Fixture: a tmp project_dir with epics/, stories/ and tasks/ holding frontmatter markdown files (id, title, tags) written by a small helper. Cover: a title match scores 1.0 and a content-only match 0.5 and results are sorted by score; snippet generation when the match is at the start, in the middle and at the end of content, for content shorter than the 50-char window and much longer than it, asserting the snippet contains the query and is at most query length plus 100 chars; case-insensitive matching (query in upper case finds lower-case content); no match returns an empty list; top_k truncates; the tag filter excludes untagged items and handles a null tags field; a missing subdirectory (no epics/) is skipped without error; the id falls back to the file stem when frontmatter has no id. Each test asserts on SearchResult fields, not on printed output.