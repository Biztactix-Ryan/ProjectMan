# Usage-telemetry baseline -- windowed-post-fix

**This is the WINDOWED-POST-FIX baseline for the ProjectMan tool-usage epic (US-PM-32).** It is a *third* capture, not a replacement for either committed one: it re-measures the corpus with every session that predates the US-PM-1 note-length fix removed, so the Sprint 1-9 claims can be judged without the defect that dominated [`baseline-post-subtraction.md`](baseline-post-subtraction.md). Do not overwrite it, or either of the two baselines it is compared against.

It is compared here against both:

| baseline | label | commit | captured (UTC) |
| --- | --- | --- | --- |
| [`baseline-pre-fix.json`](baseline-pre-fix.json) / [`.md`](baseline-pre-fix.md) | `pre-fix` | `fca9f189a85c1bf31226290ce07d75fb906a6277` | 2026-07-29T00:10:28.479453+00:00 |
| [`baseline-post-subtraction.json`](baseline-post-subtraction.json) / [`.md`](baseline-post-subtraction.md) | `post-subtraction` | `10610849baf0f8fe3edcd41a19dd800c752ad5f1` | 2026-09-05T11:15:47.554499+00:00 |
| this file (`baseline-windowed-post-fix.json`) | `windowed-post-fix` | `0930a7bdc59b9b41daf4e98c0e2d18e4efedaa5f` | 2026-09-06T01:24:20.393499+00:00 |

The generated sections below (provenance, window, headline numbers, busiest tools) come straight from `tools.usage_telemetry.baseline capture` -- the same extractor and the same schema as the other two. The [three-way comparison](#three-way-comparison) and the [per-claim verdicts](#verdicts-on-the-sprint-1-to-9-claims) are the output of `baseline compare`, transcribed and read.

## Provenance

| field | value |
| --- | --- |
| captured at (UTC) | `2026-09-06T01:24:20.393499+00:00` |
| code at commit | `0930a7bdc59b9b41daf4e98c0e2d18e4efedaa5f` (working tree **dirty** at capture -- the analysis code was not fully committed, so re-running at this commit alone may not reproduce it) |
| branch | `main` |
| corpus root | `/home/user/.claude/projects` |
| tool prefix | `mcp__projectman__` |
| transcript files | 150 |
| sessions | 89 |
| calls | 487 |
| call->result match rate | 100.00% (0 unmatched) |
| schema | `projectman.usage-telemetry.baseline/1` |
| capture window | sessions starting at or after `2026-09-05T02:16:15+00:00` (744 earlier sessions excluded) |

> Windowed post-fix baseline for US-PM-32. The window starts one second after the LAST pre-fix run-log-note rejection anywhere in the corpus ("error: Run-log note must be 1024 characters or fewer", pm_update, 2026-09-05T02:16:14.796Z), so every session counted here began after the last moment the pre-US-PM-1 server was observed running; zero rejections remain inside the window, and both active projects in it show post-fix response fields (note_long, evidence_clamped). --since auto could not be used: US-PM-1 raised the hard cap to 4096 chars, so note_truncated: true only fires above 4096 and no note in this corpus reaches that, leaving the corpus without the auto signature. HEAD is 0930a7b (pm: NEXT.md -- server reinstalled from the tree 2026-09-06); the uncommitted Sprint 10 working tree sits on top of it (US-PM-29 index-derivation changes and the US-PM-32-4 --since flag this capture uses), so git.dirty is true and expected.

## This capture is windowed

Only sessions whose first transcript timestamp is at or after `2026-09-05T02:16:15+00:00` are counted; 744 earlier sessions were excluded, whole. Filtering is per session rather than per call, because calls-per-session, run lengths and bigrams mean nothing across a transcript cut in half.

**A windowed capture is not comparable to an unwindowed one on absolute counts.** It is a different, smaller corpus by construction. Compare the rates, and read the window as part of the claim: these numbers describe the sessions in it, not the whole transcript tree.

## Why this window, and why not `--since auto`

The task asked for `--since auto`. **It could not be used, and this capture says so rather than quietly falling back.** `--since auto` looks for the first session whose response carries `note_truncated: true` -- the post-US-PM-1 signature. No session in the corpus carries it, and structurally almost none ever will: US-PM-1 did not only replace the rejection, it raised the hard cap from 1,024 to **4,096** characters (`store.RUN_LOG_NOTE_LIMIT`), so `note_truncated` fires only above 4,096. The longest run-log note anywhere in this corpus is **1,143** characters. The auto signature is therefore a real post-fix marker that this corpus has no example of. That is a finding about the signature US-PM-32-4 chose, not a defect in the `--since` filter, and the tool behaved correctly: it exited `1` and wrote nothing.

The cutoff used instead is derived from the corpus by the complementary evidence -- the *disappearance* of the pre-fix behaviour:

| | |
| --- | --- |
| last pre-fix rejection anywhere in the corpus | `{"result":"error: Run-log note must be 1024 characters or fewer"}` from `pm_update`, 2026-09-05T02:16:14.796Z, transcript `agent-ac78611c5814213fb` |
| cutoff passed to `--since` | `2026-09-05T02:16:15Z` -- one second later |
| sessions kept | 89 (150 transcript files, 487 calls) |
| sessions excluded | 744 |
| rejections remaining inside the window | **0** of 912 in the whole corpus |
| projects inside the window | `-mnt-repos-Kura` (250 calls), `-mnt-repos-ProjectMan` (237 calls) |
| post-fix response fields inside the window | 67 calls carry `note_long: true` / `evidence_clamped: true` -- 40 in Kura, 27 in ProjectMan |

So every session counted here began after the last moment the pre-US-PM-1 server was observed running, and both projects active in the window are demonstrably talking to a post-fix server. One `pm_update` inside the window sent a **1,143-character** note and was answered `note_long: true, note_length: 1143` -- accepted, not rejected -- which is the fix working on the exact input that used to fail.

**Two honest weaknesses in this cutoff:**

1. Absence of the rejection is weaker evidence than presence of a post-fix flag. A session that simply never wrote a long note is indistinguishable from one running fixed code. The 67 post-fix-field calls above cover the gap for the two projects present, not for every individual session.
2. `2026-09-05T02:16:15Z` is a *corpus* boundary, not a deploy record. `.project/NEXT.md` records the installed server being reinstalled from the tree on 2026-09-06; the corpus shows the rejection stopping a day earlier. Narrowing the window to 2026-09-06 would leave 7 sessions, which is too few to compute anything, so the wider evidence-based boundary is used and this caveat stands in its place.

## The window is small

487 calls over 89 sessions, against 3,416 / 484 for pre-fix and 6,053 / 780 for post-subtraction. That is **8% of the post-subtraction call volume**, and it is the unavoidable price of the window: the fix is recent, so the post-fix corpus is young. Consequences for every number below:

- Rate movements of several percentage points are real; movements of a fraction of a point are not. The `hard_error_rate_pct` rise of +0.18 against post-subtraction is **4 calls**.
- Tail statistics (`p99`, `max`) over 89 sessions are single sessions, not distributions.
- A tool the window never saw reports a measured `0`, which means *absent*, not *improved*. `pm_archive` is exactly that case -- see the verdicts.
- `transcript files` reads 150 against 89 sessions. `filter_extraction_since` derives it by subtracting the 744 excluded *sessions* from the 894 files the scan walked, and a file with no `mcp__projectman__` call at all was never a session to begin with -- so the 61-file gap is transcripts the window keeps but that contain no ProjectMan traffic. Every measured number below is computed from the 89 sessions, not the 150 files.

## The corpus is live, not a fixed dataset

The corpus is the local Claude transcript tree, and it is still being written to.
**It includes the ProjectMan calls made by the orchestration session that captured this baseline**, and it grew while that session worked -- a capture taken minutes later would already have more calls. The numbers below are a snapshot as of `2026-09-06T01:24:20.393499+00:00`, not a static dataset.

Two consequences for anyone comparing against this file:

1. Compare **rates**, not absolute counts. The denominator moves.
2. A later capture includes these transcripts plus everything since, so it is a superset, not an independent sample. Improvements are diluted by the history still in the corpus; the true post-fix rate is better than a whole-corpus re-capture will show.

## Headline numbers

| metric | value |
| --- | --- |
| calls | 487 |
| total response bytes | 898,699 (0.90 MB, ~223,905 tokens) |
| median bytes per call | 712 |
| failing calls (distinct) | 4 (0.82%) |
| hard errors (`is_error`) | 4 (0.82%) |
| soft errors (error body) | 0 (0.00%) |
| malformed inputs (`__unparsedToolInput`) | 0 (0.00%) |
| longest consecutive run | 12x `pm_update` |
| consecutive runs total | 367 |
| completions with no run-log entry | 0 of 92 (0.00%) |
| run-log note length | median 218, p90 713, p95 854 chars (gate: median <= 300, p90 <= 800 -- pass) |
| guidance tool usage | `pm_context` 5 calls in 5.62% of sessions, `pm_estimate` 2 calls in 2.25% of sessions |
| `tools/list` schema bytes | 91,084 for 42 tools by default, 97,449 with every gated family on (6,365 saved, 6.53%) |

The three failure classes overlap (one call can be both malformed and a hard error), so they do not sum to the distinct failure count.

## Busiest tools by call count

| tool | calls | % calls | response bytes | % bytes |
| --- | --- | --- | --- | --- |
| `pm_grab` | 94 | 19.3% | 334,285 | 37.2% |
| `pm_accept` | 90 | 18.5% | 106,186 | 11.8% |
| `pm_update` | 84 | 17.2% | 9,293 | 1.0% |
| `pm_get` | 57 | 11.7% | 129,092 | 14.4% |
| `pm_audit` | 32 | 6.6% | 54,176 | 6.0% |
| `pm_create_story` | 15 | 3.1% | 13,184 | 1.5% |
| `pm_create_tasks` | 15 | 3.1% | 7,816 | 0.9% |
| `pm_run_log` | 12 | 2.5% | 31,303 | 3.5% |
| `pm_board` | 11 | 2.3% | 53,629 | 6.0% |
| `pm_list_sprints` | 11 | 2.3% | 17,157 | 1.9% |

## Three-way comparison

Produced by:

```sh
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-pre-fix.json \
    docs/telemetry/baseline-windowed-post-fix.json

python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-post-subtraction.json \
    docs/telemetry/baseline-windowed-post-fix.json
```

```
baseline  pre-fix           2026-07-29T00:10:28.479453+00:00  commit fca9f189a85c
baseline  post-subtraction  2026-09-05T11:15:47.554499+00:00  commit 10610849baf0
current   windowed-post-fix 2026-09-06T01:24:20.393499+00:00  commit 0930a7bdc59b
```

| metric | pre-fix | post-subtraction | windowed-post-fix | vs pre-fix | vs post-subtraction |
| --- | ---: | ---: | ---: | --- | --- |
| `transcript_files` | 515 | 835 | 150 | -365 | -685 |
| `sessions` | 484 | 780 | 89 | -395 | -691 |
| `calls` | 3,416 | 6,053 | 487 | -2,929 | -5,566 |
| `match_rate_pct` | 100.00 | 100.00 | 100.00 | 0.00 | 0.00 |
| `response_bytes` | 4,066,642 | 7,445,600 | 898,699 | -3,167,943 **better** | -6,546,901 **better** |
| `estimated_tokens` | 1,012,318 | 1,853,783 | 223,905 | -788,413 **better** | -1,629,878 **better** |
| `median_bytes_per_call` | 341 | 202 | 712 | +371 worse | +510 worse |
| `failures` | 214 | 980 | 4 | -210 **better** | -976 **better** |
| `failure_rate_pct` | 6.26 | 16.19 | 0.82 | -5.44 **better** | -15.37 **better** |
| `hard_errors` | 47 | 39 | 4 | -43 **better** | -35 **better** |
| `hard_error_rate_pct` | 1.38 | 0.64 | 0.82 | -0.55 **better** | +0.18 worse |
| `soft_errors` | 167 | 941 | 0 | -167 **better** | -941 **better** |
| `soft_error_rate_pct` | 4.89 | 15.55 | 0.00 | -4.89 **better** | -15.55 **better** |
| `malformed_inputs` | 27 | 34 | 0 | -27 **better** | -34 **better** |
| `malformed_input_rate_pct` | 0.79 | 0.56 | 0.00 | -0.79 **better** | -0.56 **better** |
| `completions` | - | 2,236 | 92 | - | -2,144 |
| `completions_without_run_log` | - | 0 | 0 | - | 0 |
| `completions_without_run_log_rate_pct` | - | 0.00 | 0.00 | - | 0.00 |
| `note_length_median` | - | 971 | 218 | - | -753 **better** |
| `note_length_p90` | - | 1,355 | 713 | - | -642 **better** |
| `note_length_p95` | - | 1,678 | 854 | - | -824 **better** |
| `note_length_gate_passed` | - | 0 | 1 | - | - |
| `pm_context_calls` | - | 5 | 5 | - | 0 |
| `pm_estimate_calls` | - | 13 | 2 | - | -11 worse |
| `pm_context_sessions_pct` | - | 0.51 | 5.62 | - | +5.11 **better** |
| `pm_estimate_sessions_pct` | - | 1.28 | 2.25 | - | +0.97 **better** |
| `runs_total` | 2,431 | 4,027 | 367 | -2,064 | -3,660 |
| `longest_run` | 45 | 30 | 12 | -33 **better** | -18 **better** |
| `longest_run_tool` | pm_update | pm_update | pm_update | - | - |
| `tool_list_bytes_all` | - | 94,809 | 97,449 | - | +2,640 |
| `tool_list_bytes_default` | - | 88,441 | 91,084 | - | +2,643 worse |
| `tool_list_tools_default` | - | 42 | 42 | - | 0 |
| `pm_update_longest_run` | 45 | 30 | 12 | -33 **better** | -18 **better** |
| `pm_archive_longest_run` | 15 | 26 | 0 | -15 **better** | -26 **better** |

> `pre-fix` and `post-subtraction` are **unwindowed** captures and this one is
> windowed, so the absolute-count rows (`sessions`, `calls`, `response_bytes`,
> `runs_total`) fall by construction and mean nothing on their own. Read the
> `*_rate_pct` rows and the per-session normalisations below.

### Calls per task

One transcript session is the closest thing the corpus has to "one worker working one task", so calls per session is the measurable form of *calls per task*. It comes from `report.totals.calls_per_session`, which all three captures carry.

| calls per session | pre-fix | post-subtraction | windowed-post-fix |
| --- | ---: | ---: | ---: |
| sessions (n) | 484 | 780 | 89 |
| mean | 7.06 | 7.76 | 5.47 |
| median | 2 | 3 | 1 |
| p90 | 6 | 8 | 4 |
| p95 | 40 | 42 | 30 |
| p99 | 104 | 83 | 146 |
| max | 256 | 277 | 146 |

Mean -22.5% against pre-fix and -29.5% against post-subtraction; median, p90 and p95 all fall too. `p99` reads 146 only because with 89 sessions the 99th percentile *is* the single busiest session, which is also the max.

### Context per worker

Response bytes returned into a session's context is the measurable form of *context per worker*: it is exactly the payload a worker has to read.

| context per session | pre-fix | post-subtraction | windowed-post-fix |
| --- | ---: | ---: | ---: |
| total response bytes | 4,066,642 | 7,445,600 | 898,699 |
| bytes per session (mean) | 8,402 | 9,546 | 10,098 |
| estimated tokens per session (mean) | 2,092 | 2,377 | 2,516 |
| median bytes per call | 341 | 202 | 712 |
| p90 bytes per call | 3,099 | 3,234 | 4,805 |
| p95 bytes per call | 4,486 | 4,684 | 6,306 |

This is the one claim the window does **not** rescue. Bytes per session rose to 10,098 -- above both earlier captures -- even though calls per session fell to 5.47.

Both movements have the same cause, and it is a composition shift rather than any single tool getting fatter. Excluding the pre-fix sessions removed the cheap calls: `pm_update` was 39.8% of all calls in the post-subtraction capture at ~84 bytes a call, and it is 17.2% of calls here. What is left is dominated by the three genuinely large reads -- `pm_grab` (19.3% of calls, 37.2% of bytes), `pm_get` (11.7% / 14.4%) and `pm_accept` (18.5% / 11.8%). Fewer, larger calls is a better shape than more, smaller ones, but it is not what "less context per worker" claimed, and per session the worker reads more, not less.

### Bulk-verb longest runs (`BULK_RUN_TOOLS`)

| metric | pre-fix | post-subtraction | windowed-post-fix |
| --- | ---: | ---: | ---: |
| `pm_update_longest_run` | 45 | 30 | 12 |
| `pm_archive_longest_run` | 15 | 26 | 0 |

Supporting per-tool detail from `report.by_tool[].runs`:

| | `pm_update` pre-fix | `pm_update` post-sub | `pm_update` windowed | `pm_archive` pre-fix | `pm_archive` post-sub | `pm_archive` windowed |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| calls | 1,199 | 2,411 | 84 | 29 | 57 | 0 |
| runs | 588 | 866 | 43 | 6 | 13 | 0 |
| removable calls | 611 | 1,545 | 41 | 23 | 44 | 0 |
| longest run | 45 | 30 | 12 | 15 | 26 | 0 |

`pm_update_many` was called 4 times inside the window and `pm_archive_many` once, against 3 and 1 in the whole post-subtraction corpus -- adoption is starting, from nearly nothing.

The `pm_archive` column is the trap this document has to name: **`pm_archive` was not called at all inside the window**, so `pm_archive_longest_run` is `0` because the tool is absent, not because its runs got shorter. `compare` correctly marks `26 -> 0` as "better"; that label is arithmetically right and evidentially empty.

## Verdicts on the Sprint 1 to 9 claims

Each verdict is one of **holds**, **does not hold**, **inconclusive**, and is a statement about the windowed corpus -- i.e. about what happens *once sessions that predate the note-length fix are excluded*.

| claim | metric | pre-fix | post-subtraction | windowed-post-fix | verdict |
| --- | --- | ---: | ---: | ---: | --- |
| fewer calls per task | mean calls per session | 7.06 | 7.76 | 5.47 | **holds** |
| less context per worker | mean response bytes per session | 8,402 | 9,546 | 10,098 | **does not hold** |
| shorter `pm_update` runs | `pm_update_longest_run` | 45 | 30 | 12 | **holds** |
| shorter `pm_archive` runs | `pm_archive_longest_run` | 15 | 26 | 0 (tool never called) | **inconclusive** |
| fewer failures | combined failure rate | 6.26% | 16.19% | 0.82% | **holds** |

Claim by claim:

- **fewer calls per task -- holds.** 7.06 -> 5.47 against pre-fix (-22.5%) and 7.76 -> 5.47 against post-subtraction (-29.5%), with the median falling 2 -> 1 and p90 6 -> 4. The post-subtraction capture read this as *not supported* (median rose 2 -> 3); that reading was the defect, not the work. 906 of its 941 soft errors were rejected run-log notes, and every rejection was retried, so the pre-fix sessions were paying for the same note twice.
- **less context per worker -- does not hold.** 8,402 -> 10,098 bytes per session (+20.2% on pre-fix, +5.8% on post-subtraction). The per-call median also rose, 341 -> 712. Excluding the pre-fix sessions does not rescue this claim; it makes it slightly worse, because the calls it removes were the small ones. The honest statement is that a session now makes fewer, bigger calls, and `pm_grab` / `pm_get` / `pm_accept` still return ~63% of all bytes.
- **shorter `pm_update` runs -- holds.** Longest run 45 -> 30 -> 12, and the whole run profile shrinks with it (588 -> 866 -> 43 runs, 611 -> 1,545 -> 41 removable calls). The window makes this a stronger result than post-subtraction could: `longest_run` is a maximum over a corpus that only grows, so an unwindowed re-capture can never show it fall, and this one does.
- **shorter `pm_archive` runs -- inconclusive.** Zero `pm_archive` calls in 89 sessions. The metric reads `0`, which is absence, not improvement. The post-subtraction capture measured a real *regression* here (15 -> 26) and the window neither confirms nor clears it. One `pm_archive_many` call is the only archiving traffic in the window -- consistent with the bulk verb having replaced the loop, but one call is not evidence.
- **fewer failures -- holds, decisively.** 6.26% -> 0.82% against pre-fix, 16.19% -> 0.82% against post-subtraction. Soft errors go to **exactly zero** (4.89% and 15.55% before), and malformed inputs to zero (0.79%, 0.56%). All 4 remaining failures are hard errors. The `hard_error_rate_pct` rise against post-subtraction (0.64 -> 0.82) is 4 calls in 487 and is noise at this n. The run-log note-length gate, which the post-subtraction capture **failed** (median 971, p90 1,355), now **passes** (median 218, p90 713) -- the same movement seen from the other side.

### What this changes about the post-subtraction verdict

[`baseline-post-subtraction.md`](baseline-post-subtraction.md) closed with four "not supported" rows and named one suspect: the note-length rejection. This capture tests that hypothesis by removing the sessions that carry the defect, and the hypothesis is **confirmed for three of the four rows** -- calls per task, failures, and (already supported) `pm_update` runs all move decisively the right way once those sessions are gone.

It is **not** confirmed for context per worker. That row was not a measurement artefact of the defect, and it is the one Sprint 1-9 claim this document cannot support. `pm_archive` runs remain untested.

Two things this does not license:
1. Replacing the post-subtraction numbers. They describe a corpus that really happened, and the two files answer different questions.
2. Reading 0.82% as the steady-state failure rate. 487 calls over about 23 hours of two projects' work is a young window; re-capture with a wider one before quoting it as the number.

## Re-capture and compare

```sh
# take a fresh capture next to this one
python -m tools.usage_telemetry.baseline capture \
    --out-dir docs/telemetry --name baseline-YYYY-MM-DD --label post-fix

# compare this baseline against a live capture
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-windowed-post-fix.json
```

See [README.md](README.md) for the full procedure. The full machine-readable record is `baseline-windowed-post-fix.json`; this file is only its summary.
