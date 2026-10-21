"""The cost pane and ``orch-cost`` agree on one recorded run (US-PM-61-8).

The mod (``hooks/cost-record.ts``, drawn by ``hooks/cost-pane.tsx``) records
each request's usage in-process; ``orch-cost`` reads the same usage back out
of the session transcript afterwards.  Both are run on one synthetic
orchestrator transcript, ``tests/fixtures/orch-replay/session.jsonl``:

* ``tests/mod/cost-crosscheck.test.ts`` replays it through the mod's hooks
  and asserts the run summary the mod records is ``REPLAY_MOD_RUN`` (kept in
  ``tests/mod/fixtures/orch-replay.ts``, beside the transcript's mirror — a
  mod test can import only code);
* this module runs ``orch-cost`` on the ``.jsonl`` and holds its totals to
  ``REPLAY_MOD_RUN`` within the stated tolerance, after the one documented
  systematic difference.

**Tolerance: zero tokens**, per run, for input, cache-read, cache-write and
output, once the *opening requests* are taken off orch-cost's side.  Those
are the requests orch-cost counts from the first record that mentions the
run id up to and including the request whose response makes the run's first
run-carrying pm call: the engine runs a request before the tool call it
produced, so no run is active yet when the mod sees them.  orch-cost has no
per-task attribution, so per task there is nothing to compare; the mod's
per-task, heartbeat and unattributed buckets partition its run total (held
by the mod test), which is what is compared here.

See *Cross-check with the cost pane* in ``docs/reference/cli.md`` for the
other systematic differences (worker requests, heartbeat counting, TTL gaps).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from projectman.orch_cost import analyze

ROOT = Path(__file__).resolve().parent
FIXTURE_DIR = ROOT / "fixtures" / "orch-replay"
TRANSCRIPT = FIXTURE_DIR / "session.jsonl"
MIRROR = ROOT / "mod" / "fixtures" / "orch-replay.ts"

#: The run the fixture records.
RUN = "orch-2026-10-01-0b5e"

#: Allowed per-run difference, in tokens, after the opening requests.
TOLERANCE_TOKENS = 0

#: The cache TTL the mod holds gaps to (``CACHE_TTL_MS``), in minutes.
TTL_MINUTES = 60

#: A projectman MCP tool name, under either server prefix (``PM_TOOL``).
PM_TOOL = re.compile(r"^mcp__(?:plugin_projectman_)?projectman__(pm_\w+)$")

#: orch-cost's totals keys, by the mod's names for them.
KEYS = {"input": "input", "cacheRead": "cache_read", "cacheWrite": "cache_write", "output": "output"}


def _template(source: str, name: str) -> str:
    """The body of ``export const <name> ... String.raw`...``` in the mirror."""
    match = re.search(
        rf"export const {name}\b[^=]*=\s*(?:JSON\.parse\()?String\.raw`([^`]*)`", source
    )
    assert match, f"{name} not found in {MIRROR}"
    return match.group(1)


@pytest.fixture(scope="module")
def mirror() -> str:
    return MIRROR.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def mod_run(mirror) -> dict:
    """What the mod records replaying the transcript (asserted by the mod test)."""
    return json.loads(_template(mirror, "REPLAY_MOD_RUN"))


def _records(path: Path):
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            yield line, json.loads(line)


def _opening_requests(path: Path, run_id: str) -> dict:
    """Usage of the requests orch-cost counts and the mod cannot.

    From the first record that mentions ``run_id`` (where orch-cost starts),
    once per message id, up to and including the message whose tool use is
    the run's first projectman call carrying ``run_id`` (where the mod's run
    starts, after that request was made).
    """
    totals = {"calls": 0, "input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
    started = False
    seen: set[str] = set()
    for line, record in _records(path):
        started = started or run_id in line
        if not started or record.get("type") != "assistant":
            continue
        message = record["message"]
        if message["id"] not in seen:
            seen.add(message["id"])
            usage = message["usage"]
            totals["calls"] += 1
            totals["input"] += usage["input_tokens"]
            totals["cache_read"] += usage["cache_read_input_tokens"]
            totals["cache_write"] += usage["cache_creation_input_tokens"]
            totals["output"] += usage["output_tokens"]
        for block in message["content"]:
            if (
                block.get("type") == "tool_use"
                and PM_TOOL.match(block.get("name", ""))
                and block.get("input", {}).get("run_id") == run_id
            ):
                return totals
    raise AssertionError(f"no pm call carries {run_id}")


def test_the_mod_mirror_is_the_committed_transcript_byte_for_byte(mirror):
    assert _template(mirror, "REPLAY_TRANSCRIPT") == TRANSCRIPT.read_text(encoding="utf-8"), (
        "tests/mod/fixtures/orch-replay.ts has drifted from "
        "tests/fixtures/orch-replay/session.jsonl; regenerate the mirror"
    )
    assert f"REPLAY_RUN_ID = '{RUN}'" in mirror


def test_the_fixture_is_synthetic():
    """Never a real transcript: every record is the made-up session and cwd."""
    for line, record in _records(TRANSCRIPT):
        assert record["sessionId"] == "00000000-0000-4000-8000-00000000c0de"
        assert record["cwd"] == "/work/demo"
        assert "/home/" not in line and "/Users/" not in line


def test_per_run_totals_agree_within_the_tolerance(mod_run):
    report = analyze(TRANSCRIPT, RUN)
    opening = _opening_requests(TRANSCRIPT, RUN)
    # The fixture's opening is the one request that made the first pm_grab.
    assert opening["calls"] == 1

    assert report["calls"] - opening["calls"] == mod_run["totals"]["requests"]
    for mod_key, cost_key in KEYS.items():
        difference = report["totals"][cost_key] - opening[cost_key] - mod_run["totals"][mod_key]
        assert abs(difference) <= TOLERANCE_TOKENS, (mod_key, difference)


def test_without_the_adjustment_orch_cost_reads_exactly_the_opening_more(mod_run):
    """The raw gap is systematic, never noise: it is the opening request."""
    report = analyze(TRANSCRIPT, RUN)
    opening = _opening_requests(TRANSCRIPT, RUN)
    for mod_key, cost_key in KEYS.items():
        assert report["totals"][cost_key] - mod_run["totals"][mod_key] == opening[cost_key]


def test_heartbeats_and_ttl_gaps_agree(mod_run):
    report = analyze(TRANSCRIPT, RUN)
    # orch-cost counts heartbeat firings, the mod the requests in heartbeat
    # turns: equal while each firing is answered in one request.
    assert report["heartbeats"] == mod_run["heartbeat"]["requests"] == 1
    # orch-cost finds misses by token shape, the mod gaps by the clock: here
    # the one wait over the TTL is the one full miss, on the same task.
    over_ttl = [m for m in report["misses"] if m["gap_min"] is not None and m["gap_min"] > TTL_MINUTES]
    assert len(over_ttl) == sum(mod_run["pastTtl"].values()) == 1
    # The bridged wait cost orch-cost no miss: the heartbeat kept the prefix.
    assert len(report["misses"]) == 1


def test_the_cli_reports_the_same_totals(monkeypatch, tmp_path):
    from click.testing import CliRunner

    from projectman.cli import cli

    monkeypatch.chdir(tmp_path)
    runner = CliRunner()
    payload = runner.invoke(cli, ["orch-cost", RUN, "--transcripts", str(FIXTURE_DIR), "--json"])
    assert payload.exit_code == 0, payload.output
    assert json.loads(payload.output)["totals"] == analyze(TRANSCRIPT, RUN)["totals"]

    text = runner.invoke(cli, ["orch-cost", RUN, "--transcripts", str(FIXTURE_DIR)])
    assert text.exit_code == 0, text.output
    assert "input 28  cache read 306,016  cache write 38,480  output 2,083" in text.output
