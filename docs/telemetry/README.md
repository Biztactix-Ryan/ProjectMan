# Usage telemetry — baselines

This directory holds **measurements**, not code. The code is
`tools/usage_telemetry/` and is covered by
`tests/test_usage_telemetry_{extract,classify,report,separation,baseline}.py`.

| file | what it is |
| --- | --- |
| `baseline-pre-fix.json` | the machine-readable **pre-fix baseline**. Every later claim of improvement is diffed against this. Do not overwrite it. |
| `baseline-pre-fix.md` | human summary of the same capture: provenance, headline numbers, busiest tools. |
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
    "git": { "commit": "…", "branch": "…", "dirty": true },
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
   `--root`.
3. The baseline is a snapshot at a stated instant, not a fixed dataset.

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
| `--stdout` | print the JSON, write nothing |

Exit codes: `0` ok, `1` join rate below `--min-match-rate`, `2` no matching calls
found (empty corpus). A failed capture writes no artifact.

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
