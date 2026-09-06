---
archived: false
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-09-06'
depends_on:
- US-PRJ-42-5
id: US-PRJ-42-6
points: 1
status: done
story_id: US-PRJ-42
tags: []
title: Extract the documentation checks into one shared helper
updated: '2026-09-06'
---

Check 7 in run_audit (missing-documentation, unfilled-documentation, stale-documentation over PROJECT.md, INFRASTRUCTURE.md and SECURITY.md) inlines the template-detection line filter and the mtime age check. Extract them into a module-level _check_documentation(project_dir, doc_files, today) -> list[dict] (with the line-filter as its own small function) and call it from run_audit; if the same unfilled-template detection exists elsewhere (grep for '*Last reviewed' and 'appears to be an unfilled template' in src/projectman, e.g. pm_docs or the init wizard support code) point that caller at the shared function too. Behaviour and finding text unchanged. Unit tests in tests/test_audit.py call the helper directly for the three states (missing, unfilled template, stale).