---
assignee: claude
created: '2026-08-21'
depends_on: []
id: US-PRJ-47-5
points: 2
status: done
story_id: US-PRJ-47
tags:
- security
- changesets
title: Build changeset PR commands from argv lists with shlex quoting
updated: '2026-08-22'
---

In `src/projectman/changesets.py` (`changeset_create_prs`, ~line 104-135) the `gh pr create` command is assembled as an f-string: `f'gh pr create --title "{meta.title}: {entry.project}" --body "{pr_body}" --head {entry.ref}'`. Title, body and ref are user/agent-supplied, so a double quote, backtick, `$(`, or `;` in any of them breaks out of the quoted argument.

Fix: build each command as an argv list (`["gh", "pr", "create", "--title", ..., "--body", ..., "--head", entry.ref]`) and render the display string with `shlex.join(...)` (and `shlex.quote(entry.project)` for the `cd` prefix). Keep the returned dict shape (`project`, `ref`, `command`) so callers and the MCP tool output are unchanged; optionally add an `argv` key alongside `command`.

Also fix `cross_ref_block = "\\n".join(cross_refs)` and the `\\n\\n` in `pr_body` — these are literal backslash-n in the source, so the body renders as one line on GitHub. Use real newlines; shlex quoting makes them safe in the rendered command.

Tests (US-PRJ-47-1..4) cover: list/quoted args for all inputs, newline rendering, quotes/backticks/semicolons in titles and bodies, and special-character edge cases.