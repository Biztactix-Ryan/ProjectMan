# Usage telemetry — baselines

This directory holds **measurements**, not code. The code is
`tools/usage_telemetry/` and is covered by
`tests/test_usage_telemetry_{extract,classify,report,separation,baseline}.py`.

| file | what it is |
| --- | --- |
| `baseline-pre-fix.json` | the machine-readable **pre-fix baseline**. Every later claim of improvement is diffed against this. Do not overwrite it. |
| `baseline-pre-fix.md` | human summary of the same capture: provenance, headline numbers, busiest tools. |
| `baseline-post-subtraction.json` | the machine-readable **post-subtraction baseline** (US-PM-30), captured after Sprints 1-8. Same extractor, same schema, same `capture` command as the pre-fix file. Do not overwrite it either. |
| `baseline-post-subtraction.md` | human summary of that capture **plus the comparison against pre-fix**: calls per task, context per worker, and the `BULK_RUN_TOOLS` longest-run metrics. Also records why the two corpora turned out to be disjoint rather than nested, and the `git.dirty: true` provenance caveat. |
| `baseline-windowed-post-fix.json` | the machine-readable **windowed post-fix baseline** (US-PM-32), captured with `--since` so that only sessions started after the last observed pre-US-PM-1 note rejection are counted. Same extractor, same schema, same `capture` command as the other two. Do not overwrite it either. |
| [`baseline-windowed-post-fix.md`](baseline-windowed-post-fix.md) | human summary of that capture **plus the three-way comparison** against `baseline-pre-fix` and `baseline-post-subtraction`, and a **holds / does not hold / inconclusive** verdict on each Sprint 1-9 claim once pre-fix sessions are excluded. Also records why `--since auto` could not resolve on this corpus, and the `git.dirty: true` provenance caveat. |
| `tool-list-size.md` | the US-PM-15-7 **tool-list payload measurement**: `tools/list` bytes with and without the gated tool families, per family, plus the command that regenerates it. Not a corpus measurement -- it describes the schema surface the server offers, so it is regenerated on demand rather than pinned. |

## What a baseline is

A baseline is the full JSON report from `tools.usage_telemetry.report` wrapped in
a `provenance` block:

```jsonc
{
  "schema": "projectman.usage-telemetry.baseline/1",
  "provenance": {
    "label": "pre-fix",
    "captured_at": "…",        // exact UTC moment, not just the date
    "corpus_root": "…",        // which transcript tree was scanned
    "tool_prefix": "mcp__projectman__",
    "transcript_files": 515,   // files scanned
    "sessions": 484,           // transcripts that actually contained calls
    "calls": 3416,
    "matched_calls": 3416,
    "unmatched_calls": 0,
    "match_rate": 1.0,         // the call→result join rate; distrust anything below ~1.0
    "window_since": null,      // --since cutoff, or null for a whole-corpus capture
    "sessions_excluded": null, // sessions the window left out; null when there is no window
    "git": { "repo": ".", "commit": "…", "branch": "…", "dirty": true },
    "corpus_is_live": true
  },
  "report": { "corpus": …, "totals": …, "by_tool": …, "runs": …, "bigrams": …, "failures": … }
}
```

The provenance block is the whole point. Two captures can differ because the
fixes worked, because the corpus grew, or because the analysis code changed —
and without `captured_at` / `corpus_root` / `git.commit` nothing in the file
tells you which.

`git.dirty` is not decoration: a capture taken from a dirty tree is **not**
reproducible from `git.commit` alone. `dirty: null` means git could not be read
at all — unknown, not clean.

`git.repo` is a path **relative to the git root** — `"."` when the capture was
taken from the root itself, `"tools/usage_telemetry"` when taken from that
subdirectory, and `null` when the git root could not be read. It used to be the
absolute path of the capturing machine, which made the artifact readable only
there; `docs/telemetry/baseline-pre-fix.json` was rewritten to the relative form
(`"."`) and no measured number in it changed. What pins the code is
`git.commit`; `git.repo` only says where in that tree the capture ran.

## The corpus is live

The corpus is the local Claude transcript tree (`$CLAUDE_PROJECTS_DIR`, default
`~/.claude/projects`). It is still being written to, it includes the ProjectMan
calls made by the session that captured the baseline, and it grows while work
proceeds. Consequences:

1. **Compare rates, not absolute counts.** The denominator moves. A rising
   absolute failure count with a falling failure rate is an improvement.
2. **A later capture is a superset, not an independent sample.** It contains the
   pre-fix history plus everything since, so post-fix improvements are *diluted*.
   The true post-fix rate is better than a whole-corpus re-capture will show. To
   see the undiluted number, scope the capture to a fresh corpus subtree with
   `--root`, or window it in time with `--since` (below).
3. The baseline is a snapshot at a stated instant, not a fixed dataset.
4. **The corpus also shrinks at the far end.** Transcripts age out of
   `~/.claude/projects`, so point 2 stops holding once enough time passes: the
   pre-fix corpus (2026-07-29) had rolled off entirely before the
   post-subtraction capture (2026-09-05), whose oldest transcript dates from
   2026-08-03. Those two captures are therefore *disjoint*, which makes them a
   clean before/after — and makes each committed baseline the only surviving
   record of its own corpus. Never overwrite one.

## Re-capture

```sh
python -m tools.usage_telemetry.baseline capture \
    --out-dir docs/telemetry \
    --name baseline-2026-08-15 \
    --label post-fix \
    --min-match-rate 0.99 \
    --note "after US-PM-1..5 landed"
```

Writes `<name>.json` and `<name>.md`. Useful flags:

| flag | effect |
| --- | --- |
| `--root DIR` | scan a different transcript tree (e.g. only post-fix sessions) |
| `--prefix P` | analyse a different tool prefix (`''` for all tools) |
| `--min-match-rate R` | **refuse to capture** below this call→result join rate — a partial join silently invalidates every downstream number |
| `--repo DIR` | which repo's commit is recorded (default: cwd) |
| `--since WHEN` | count only sessions that started at or after `WHEN` — see below |
| `--stdout` | print the JSON, write nothing |

Exit codes: `0` ok, `1` the capture was **refused** (join rate below
`--min-match-rate`, or `--since` could not be resolved), `2` no matching calls
found (empty corpus, or a window that excluded everything). A failed capture
writes no artifact.

## Windowing a capture — `--since`

`--root` narrows the corpus by *directory*. `--since` narrows it by *time*:

```sh
# an explicit cutoff — a date, or a full ISO-8601 timestamp
python -m tools.usage_telemetry.baseline capture --since 2026-08-21
python -m tools.usage_telemetry.baseline capture --since 2026-08-21T14:03:00Z

# derive the cutoff from the corpus instead of guessing it
python -m tools.usage_telemetry.baseline capture \
    --since auto \
    --name baseline-windowed-post-fix --label windowed-post-fix
```

Why it exists (US-PM-32): the corpus mixes months of sessions run against
different server code. `baseline-post-subtraction` found **906 of its 941 soft
errors** were one defect — `pm_update` rejecting a run-log note over 1024
characters — that US-PM-1 fixed in Sprint 3. Reading a whole-corpus failure rate
as "how ProjectMan behaves now" therefore measures code that no longer exists.

How it filters:

- The unit is a **session** (one transcript file), and a session is included only
  when its **first** timestamp is at or after the cutoff. Filtering is never
  per call: calls-per-session, run lengths and bigrams are statements about a
  whole transcript, and half a transcript is not a sample of anything. A late
  call inside an early session is excluded with the rest of that session.
- The boundary is **inclusive** — a session starting exactly at the cutoff is in.
- A session with no parseable timestamp is **excluded**. It cannot be shown to be
  inside the window, and the window exists to be able to say that everything
  counted is.
- A naive timestamp (`2026-08-21`, `2026-08-21T14:03:00`) is read as UTC.
- `transcript_files` counts only the windowed transcripts, so the corpus block
  describes the window rather than the tree it was carved from.
- `--min-match-rate` is checked against the **whole** scan, before the window is
  applied: a broken call→result join is a property of the extractor and the
  corpus, and a window must not be able to hide one.

`--since auto` derives the cutoff from evidence rather than from a date someone
remembers. It finds the earliest session whose response carries the post-US-PM-1
`note_truncated: true` field, and uses **that session's start**, so the session
supplying the evidence is itself inside its own window. Two false positives are
deliberately excluded: the field is read only from the tools that can emit it
(`baseline.NOTE_TRUNCATION_TOOLS` — `pm_update`, `pm_update_many`,
`pm_done_next`, `pm_release`, `pm_accept`, `pm_retry`), and it must appear as a
field (`note_truncated: true`), not as prose. Task bodies in this repo name the
flag, and they come back through `pm_get` and `pm_update` responses; a substring
match would date the window to whenever one of them was last read.

If **no** session carries the signature, `--since auto` exits `1` with an error
and writes nothing. It never falls back to a full capture — a whole-corpus
capture published under a windowed name is the exact mistake this flag exists to
prevent.

The window is recorded in provenance as `window_since` and `sessions_excluded`,
and the generated markdown gains a *This capture is windowed* section. Both are
`null` for an unwindowed capture — `0` would claim a window was applied and
happened to match everything.

**A windowed capture is not comparable to an unwindowed one on absolute counts.**
It is a smaller corpus by construction. `compare` will happily diff the two;
read the `*_rate_pct` rows and the two `window_since` values together.

## Compare

Against a fresh live capture (the usual case):

```sh
python -m tools.usage_telemetry.baseline compare docs/telemetry/baseline-pre-fix.json
```

Between two stored captures:

```sh
python -m tools.usage_telemetry.baseline compare \
    docs/telemetry/baseline-pre-fix.json docs/telemetry/baseline-2026-08-15.json
```

Add `--json` for a machine-readable diff. The comparison covers calls, response
bytes, estimated tokens, median bytes/call, the three failure classes with their
rates, run totals, the corpus-wide longest run, and a *per-tool* longest run for
each tool in `baseline.BULK_RUN_TOOLS` (`pm_update_longest_run`,
`pm_archive_longest_run`). Metrics where lower is better are marked
`better` / `worse`; `corpus_grew` flags the growing-denominator case explicitly.

The per-tool run keys exist because the corpus-wide `longest_run` names only
whichever tool happens to top the corpus. US-PM-12's bulk verbs
(`pm_update_many` / `pm_archive_many`) are meant to shorten `pm_update` and
`pm_archive` runs specifically, and a capture where some other tool holds the
record leaves `longest_run` unmoved -- or rising -- while those runs collapse.
The per-tool numbers are computed from the `by_tool[].runs` profile every
capture already stores, so a baseline taken before this metric existed still
answers the question with no re-capture (the pre-fix file reads 45x `pm_update`,
15x `pm_archive`).

One caveat when reading them: a longest run is a **maximum over the whole
corpus**, and the corpus only grows, so a whole-corpus re-capture can never show
the maximum fall -- the pre-bulk-verb history stays in it forever. To see
adoption, point `--root` at a transcript tree containing only post-release
sessions, and read `by_tool[].runs.histogram` / `removable_calls` alongside the
`pm_update_many` and `pm_archive_many` call counts.

Because both files carry provenance, the diff header prints each capture's label,
moment and commit — so a "regression" caused by re-running against different code
is visible rather than mysterious.

## Sanity checks

A capture is trustworthy when:

- `match_rate` is ~1.0 (a low join rate means the two-pass `tool_use_id` join
  broke; every rate below is then wrong);
- failures are counted across **all three** classes — `is_error` hard errors,
  error envelopes in the response body (soft errors, `is_error` false), and
  `__unparsedToolInput` malformed calls. Counting only `is_error` reports ~1%
  where the real rate is ~6%; two of the four original the original usage studies scripts made
  exactly that mistake;
- the classes overlap, so they do not sum to the distinct failure count.

The pre-fix capture reproduces the numbers independently derived in the four
the original usage studies appendices: ~6.2% combined failure rate, ~1.4% hard, ~4.8% soft, ~0.8%
malformed, ~4 MB total response bytes, longest run 45× `pm_update`.

## Related commands

```sh
python -m tools.usage_telemetry.report            # text report
python -m tools.usage_telemetry.report --json     # raw JSON, no provenance
python -m tools.usage_telemetry.classify          # failure breakdown only
```

`baseline` is purely additive over these — it calls them and adds the wrapper.
`tests/test_usage_telemetry_baseline.py::test_baseline_adds_no_behaviour_to_the_modules_it_consumes`
pins that: the report embedded in a baseline must equal the report produced
directly from the same corpus.
