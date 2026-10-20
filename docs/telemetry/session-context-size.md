# SessionStart status block where the sprint band draws

US-PM-62-8 reduces the status block `projectman session-context` (the
plugin's SessionStart command hook) puts in the model's context when the
sprint band draws in the session. This file is the **measured** saving, so
the claim is a number and not an assumption.

- Measured: **2026-10-21**
- Fixture: `representative` in `tests/test_session_context_band.py` — a store
  shaped like a live one: an active sprint, six tasks in progress (five listed
  plus "… and 1 more"), one open decision, a 233-character NEXT.md note (cut
  to 200 in the block) and a HANDOFF.md
- Paths: the fixture's tmp root is replaced by `/home/user/project`, so the
  numbers do not move with pytest's temporary directory
- Tokens: estimated as `chars // 4`, the estimate `tools/usage_telemetry`
  uses (`CHARS_PER_TOKEN`); no tokenizer is run

## Headline

| block | lines | bytes | est. tokens |
| --- | ---: | ---: | ---: |
| full (no band: `claude -p`, the SDK, vscode or mobile only, mod disabled) | 17 | 1,071 | 266 |
| reduced (the band draws in this session) | 6 | 625 | 155 |
| **saved per session start** | **11** | **446 (41.6%)** | **111** |

The block is injected once per SessionStart (startup, resume, `/clear`,
compaction), so the saving recurs at each.

## What is dropped and what is kept

Dropped (the band shows the person sprint progress and the task in flight;
the model gets them from `pm_context` / `pm_active` when it needs them): the
epic, story and task counts, points, the in-progress list and the active
sprint.

Kept (what steers the model's first move and the band does not carry to the
model): the header and project line, open decisions, the next-session note
(the band shows its head to the person, but the model still needs it) and the
last handoff, plus one pointer line to `pm_context`.

Not dropped outright: the band draws only once its MCP read lands, which no
SessionStart can wait for, and an unconnected server draws no band at all, so
the reduced block keeps what the model must not lose.

## The signal

The mod's `classic.SessionStart` hook (hooks/register.ts, hooks/band-session.ts)
sets `PROJECTMAN_BAND_SESSION` to the session's id where `$.session.surfaces()`
lists a surface the band draws on, and unsets it everywhere else, **before**
`next(e)`. The band draws through the `AbovePrompt` render hook, which the
engine raises on the `terminal` and `desktop` surfaces only (`BAND_SURFACES` in
hooks/sprint-band.tsx, from the `AbovePrompt` entry of the mod types'
`RenderPropsOf`). So a session listing only `vscode` or `mobile` gets today's
full block, as does one listing nothing (`claude -p`, the SDK, Claude Code for
VS Code, which attaches no surface today); a mixed list such as
`vscode` + `terminal` counts, since the terminal draws the band. Hooks
modules sit above the plugin's command hooks in the classic chain and
`$.env.set` reaches every process started after, so the command reads the
answer for this very SessionStart. The command reduces the block only when the
value equals its payload's `session_id` exactly; unset, empty, another
session's id (before a `/clear`, a parent of a nested `claude -p`) or anything
malformed prints today's full block, byte for byte.

## Keeping it honest

`test_us_pm_62_4_context_saved_is_recorded` re-runs the measurement and
compares it to the block below. If it fails, the block moved: the failure
prints the new JSON to paste here; update the table to match.

<!-- session-context-size:measurement -->

```json
{
  "estimate": "chars // 4",
  "fixture": "tests/test_session_context_band.py::representative",
  "full": {
    "bytes": 1071,
    "chars": 1065,
    "est_tokens": 266,
    "lines": 17
  },
  "reduced": {
    "bytes": 625,
    "chars": 623,
    "est_tokens": 155,
    "lines": 6
  },
  "saved": {
    "bytes": 446,
    "est_tokens": 111,
    "pct": 41.6
  },
  "schema": "projectman.session-context-size/1"
}
```
