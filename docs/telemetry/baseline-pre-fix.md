# Usage-telemetry baseline -- pre-fix

**This is the PRE-FIX baseline for the ProjectMan tool-usage epic.** It is the measurement every later claim of improvement is compared against. It was captured *before* the epic's fixes landed; do not overwrite it.

## Provenance

| field | value |
| --- | --- |
| captured at (UTC) | `2026-07-29T00:10:28.479453+00:00` |
| code at commit | `fca9f189a85c1bf31226290ce07d75fb906a6277` (working tree **dirty** at capture -- the analysis code was not fully committed, so re-running at this commit alone may not reproduce it) |
| branch | `main` |
| corpus root | `/home/user/.claude/projects` |
| tool prefix | `mcp__projectman__` |
| transcript files | 515 |
| sessions | 484 |
| calls | 3,416 |
| call->result match rate | 100.00% (0 unmatched) |
| schema | `projectman.usage-telemetry.baseline/1` |

> PRE-FIX baseline for the ProjectMan tool-usage epic (US-PM-6-9). Captured before any fix in the epic landed; the working tree held the US-PM-6 telemetry tooling uncommitted at this moment.

## The corpus is live, not a fixed dataset

The corpus is the local Claude transcript tree, and it is still being written to.
**It includes the ProjectMan calls made by the orchestration session that captured this baseline**, and it grew while that session worked -- a capture taken minutes later would already have more calls. The numbers below are a snapshot as of `2026-07-29T00:10:28.479453+00:00`, not a static dataset.

Two consequences for anyone comparing against this file:

1. Compare **rates**, not absolute counts. The denominator moves.
2. A later capture includes these transcripts plus everything since, so it is a superset, not an independent sample. Improvements are diluted by the history still in the corpus; the true post-fix rate is better than a whole-corpus re-capture will show.

## Headline numbers

| metric | value |
| --- | --- |
| calls | 3,416 |
| total response bytes | 4,066,642 (4.07 MB, ~1,012,318 tokens) |
| median bytes per call | 341 |
| failing calls (distinct) | 214 (6.26%) |
| hard errors (`is_error`) | 47 (1.38%) |
| soft errors (error body) | 167 (4.89%) |
| malformed inputs (`__unparsedToolInput`) | 27 (0.79%) |
| longest consecutive run | 45x `pm_update` |
| consecutive runs total | 2,431 |

The three failure classes overlap (one call can be both malformed and a hard error), so they do not sum to the distinct failure count.

## Busiest tools by call count

| tool | calls | % calls | response bytes | % bytes |
| --- | --- | --- | --- | --- |
| `pm_update` | 1,199 | 35.1% | 115,829 | 2.8% |
| `pm_grab` | 516 | 15.1% | 1,336,007 | 32.9% |
| `pm_get` | 425 | 12.4% | 1,130,183 | 27.8% |
| `pm_done_next` | 420 | 12.3% | 492,331 | 12.1% |
| `pm_audit` | 172 | 5.0% | 37,488 | 0.9% |
| `pm_create_story` | 103 | 3.0% | 53,090 | 1.3% |
| `pm_create_tasks` | 90 | 2.6% | 32,195 | 0.8% |
| `pm_list_sprints` | 56 | 1.6% | 72,822 | 1.8% |
| `pm_status` | 54 | 1.6% | 12,742 | 0.3% |
| `pm_active` | 44 | 1.3% | 29,997 | 0.7% |

## Re-capture and compare

```sh
# take a fresh capture next to this one
python -m tools.usage_telemetry.baseline capture \
    --out-dir docs/telemetry --name baseline-YYYY-MM-DD --label post-fix

# compare this baseline against a live capture
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-pre-fix.json
```

See [README.md](README.md) for the full procedure. The full machine-readable record is `baseline-pre-fix.json`; this file is only its summary.
