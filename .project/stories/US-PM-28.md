---
acceptance_criteria:
- pm_next reads and replaces and appends to and clears .project/NEXT.md
- pm_context returns the note under next_time when it exists and omits the key when
  it does not
- /pm-next skill is rendered by refresh-skills and documented alongside the other
  pm skills
- NEXT.md is ignored by the indexer and the audit and pm_search
created: '2026-09-05'
depends_on: []
epic_id: EPIC-PM-4
id: US-PM-28
points: 3
priority: should
status: done
tags:
- feature
- workflow
- skills
title: 'A note to the next session: pm_next and /pm-next'
updated: '2026-09-05'
---

As a developer who has to clear context mid-plan, I want to leave myself a short note that the next session sees first so that "we decided to fix X by doing Y and Z" survives a restart without becoming a story or an epic.

Requested by the user on 2026-09-05 right after a restart that lost exactly this kind of decision (it survived only because the assistant wrote it into its own memory). This is deliberately not a backlog item: it is scratch text with one owner and a short life.

Design:
- Storage: `.project/NEXT.md`, plain markdown, no frontmatter, not indexed, not audited, ignored by pm_search and pm_status. Tracked in git like the rest of .project so it follows the project across machines; pm_commit includes it.
- MCP tool `pm_next(text=None, append=False, clear=False)`: no args returns the note or "no note saved"; `text` replaces the note (or appends a dated paragraph when `append=true`); `clear=true` deletes the file. Setting text and clear together is an error. Log a single activity event on write and clear.
- `pm_context` puts the note first in its result when it exists, under a `next_time` key, so any session-start read surfaces it without a separate call.
- Skill `/pm-next` (template skill_pm_next.md.j2, installed by refresh-skills alongside the other pm skills): with no arguments read the note, restate it, and propose the first concrete step; with text save it; with "clear" clear it. The skill tells the agent to offer clearing the note once the work it describes is done.
- Docs: one section in the user guide and a row in docs/reference/skills.md and the MCP tool reference.