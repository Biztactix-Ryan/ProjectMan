---
acceptance_criteria:
- CHANGELOG.md exists with entries for 0.8.0 through 0.8.3
- Each version lists added/changed/fixed items
- Format follows Keep a Changelog convention
created: '2026-03-09'
epic_id: EPIC-PRJ-10
id: US-PRJ-54
points: 3
priority: should
status: done
tags:
- docs
title: Create CHANGELOG.md with version history
updated: '2026-09-06'
---

As a user upgrading ProjectMan, I want a changelog so that I can see what changed between versions.

Planning note (2026-09-05): CHANGELOG.md now exists (commit aae7e09) in Keep a Changelog format, but it holds a single Unreleased section covering 2026-08-19 to 2026-09-02. The remaining work is the versioned history: sections for 0.8.0 through 0.8.15 (pyproject.toml is at 0.8.15) compiled from git log, each with Added, Changed and Fixed. History was rewritten on 2026-09-02, so use the current SHAs and tags, not any older references.