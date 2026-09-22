---
assignee: claude
claimed_at: null
claimed_by_run: null
created: '2026-07-30'
depends_on: []
id: US-PRJ-54-4
points: 2
status: done
story_id: US-PRJ-54
tags: []
title: Compile version history for 0.8.0 through 0.8.15 from git log
updated: '2026-09-06'
---

Compile the per-version history that CHANGELOG.md is missing. CHANGELOG.md already exists (added 2026-09-02) but only has an [Unreleased] section covering 2026-08-19 to 2026-09-02. Version bumps survive the 2026-09-02 history rewrite in the commit log of pyproject.toml: `git log --format='%h %ad %s' --date=short -- pyproject.toml` shows 0.8.3 (2026-03-08), 0.8.4 (03-10), 0.8.5 (03-13), 0.8.10 (05-28), 0.8.11 through 0.8.15 (07-02 to 07-05); use `git log <prev>..<bump>` between bumps to gather added/changed/fixed items for each. For 0.8.0 through 0.8.2 and anything the rewrite squashed, the `pre-rewrite-backup` branch has the fuller log (45 pyproject commits) — read it, never check it out. Output: a scratch notes file per version with Added/Changed/Fixed bullets, ready for US-PRJ-54-5 to write into CHANGELOG.md.