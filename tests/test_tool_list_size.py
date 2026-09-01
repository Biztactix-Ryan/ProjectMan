"""US-PM-15-7 — the tool-list saving is a measured number, not an assumption.

US-PM-15's last acceptance criterion is that the payload "drops measurably with
default config". This module holds the measurement honest in four ways:

1. it is **repeatable** — two runs of the utility agree exactly, and it leaves
   the registry as it found it, so it can be run beside a live server;
2. it measures the **real wire payload** — the same bytes the low-level
   ``tools/list`` request handler produces, not a re-implementation;
3. the drop is **real and floored** — at least the gated families' own schema
   bytes, and at least 10% of the whole payload;
4. the committed ``docs/telemetry/tool-list-size.md`` **cannot rot** — its
   machine-readable block is compared to a fresh measurement, exactly.
"""

import json
import re
from pathlib import Path
from typing import NamedTuple

import anyio
import pytest
import yaml
from mcp import types

from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)
from tools.usage_telemetry import baseline as bl
from tools.usage_telemetry import tool_list_size as tls

REPO_ROOT = Path(__file__).resolve().parents[1]
DOC = REPO_ROOT / tls.DOC_PATH

#: Printed on every doc-drift failure so the reader does not have to go looking.
REGENERATE = f"run `{tls.COMMAND}` from the repo root and commit the result"


class _Payload(NamedTuple):
    """One real ``tools/list`` result, as names and as bytes on the wire."""

    names: frozenset
    bytes: int


def _wire_payload() -> _Payload:
    """Drive the low-level ``tools/list`` handler under the current gating."""
    handler = mcp_server._mcp_server.request_handlers[types.ListToolsRequest]

    async def run():
        return (await handler(types.ListToolsRequest(method="tools/list"))).root

    result = anyio.run(run)
    serialised = result.model_dump_json(by_alias=True, exclude_none=True)
    return _Payload(
        frozenset(tool.name for tool in result.tools),
        len(serialised.encode("utf-8")),
    )


def _wire_payload_under(families: dict) -> _Payload:
    apply_tool_gating(families)
    return _wire_payload()


@pytest.fixture(scope="module")
def measurement():
    return tls.measure()


@pytest.fixture(scope="module")
def recorded():
    """The machine-readable block inside the committed document."""
    assert DOC.exists(), f"{tls.DOC_PATH} is missing — {REGENERATE}"
    text = DOC.read_text(encoding="utf-8")
    marker = text.find(tls.JSON_FENCE_MARKER)
    assert marker != -1, f"{tls.DOC_PATH} has no measurement marker — {REGENERATE}"
    block = re.search(r"```json\n(.*?)\n```", text[marker:], re.DOTALL)
    assert block, f"{tls.DOC_PATH} has no json block after the marker — {REGENERATE}"
    return json.loads(block.group(1))


@pytest.fixture(autouse=True)
def restore_gating():
    """Leave the registry exactly as this module found it, test by test."""
    before = gated_tool_state()
    yield
    apply_tool_gating(before)


# ------------------------------------------------------- it is repeatable --


def test_two_runs_of_the_measurement_agree_exactly():
    """A number that moves between runs cannot be recorded in a document."""
    assert tls.measure() == tls.measure()


def test_measuring_leaves_the_tool_registry_exactly_as_it_found_it():
    """The utility toggles real gating, so it must not be observable afterwards.

    Asserted from both the non-default states, not just the ambient one: a
    restore that happened to no-op for "everything off" would still be wrong.
    """
    for state in ({family: True for family in TOOL_FAMILIES}, tls.DEFAULT_FAMILIES):
        apply_tool_gating(state)
        before = {tool.name for tool in anyio.run(mcp_server.list_tools)}
        tls.measure()
        assert gated_tool_state() == state
        assert {tool.name for tool in anyio.run(mcp_server.list_tools)} == before


def test_a_failed_measurement_still_restores_the_gating(monkeypatch):
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    monkeypatch.setattr(tls, "_payload_bytes", lambda tools: 1 / 0)
    with pytest.raises(ZeroDivisionError):
        tls.measure()
    assert gated_tool_state() == {family: True for family in TOOL_FAMILIES}


# --------------------------------------------- it measures the real thing --


@pytest.mark.parametrize("families_key", ["all_families", "default"])
def test_the_bytes_are_the_bytes_the_request_handler_produces(measurement, families_key):
    """Not a re-implementation: drive the real ``tools/list`` handler.

    The MCP session serialises every result with
    ``model_dump_json(by_alias=True, exclude_none=True)``, so the length of the
    handler's own result under that serialisation *is* the payload size. If the
    library changes how it serialises, this fails rather than the doc quietly
    describing a different number from the one on the wire.
    """
    families = tls.ALL_FAMILIES if families_key == "all_families" else tls.DEFAULT_FAMILIES
    apply_tool_gating(families)
    handler = mcp_server._mcp_server.request_handlers[types.ListToolsRequest]

    async def run():
        request = types.ListToolsRequest(method="tools/list")
        return (await handler(request)).root

    result = anyio.run(run)
    on_the_wire = result.model_dump_json(by_alias=True, exclude_none=True)
    assert len(on_the_wire.encode("utf-8")) == measurement[families_key]["bytes"]
    assert len(result.tools) == measurement[families_key]["tools"]


def test_the_default_measurement_ignores_whatever_config_is_on_disk():
    """The number must be a property of the code, not of the repo it ran in."""
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    from_all_on = tls.measure()
    apply_tool_gating(tls.DEFAULT_FAMILIES)
    assert tls.measure() == from_all_on


def test_every_gated_family_is_accounted_for(measurement):
    assert set(measurement["families"]) == set(TOOL_FAMILIES)
    for family, names in TOOL_FAMILIES.items():
        assert measurement["families"][family]["tools"] == len(names)


# ----------------------------------------------------- the drop is floored --


def test_the_default_payload_is_smaller_by_the_gated_schemas(measurement):
    """Floor: the gated families' own schema bytes, framing commas excluded.

    The real drop is that plus one comma per hidden tool; asserting the floor
    rather than the equality keeps the test about the *saving* and not about
    JSON punctuation.
    """
    saved = measurement["all_families"]["bytes"] - measurement["default"]["bytes"]
    schema_bytes = sum(row["schema_bytes"] for row in measurement["families"].values())
    hidden = sum(row["tools"] for row in measurement["families"].values())
    assert saved == measurement["reduction"]["bytes"]
    assert saved >= schema_bytes - hidden
    # And the framing really is only the separators, nothing structural.
    assert saved == schema_bytes + hidden


def test_the_drop_is_measurable_not_marginal(measurement):
    """"Measurably" needs a floor or it means nothing. 10% of the payload."""
    assert measurement["reduction"]["pct"] >= 10.0, measurement["reduction"]
    assert measurement["reduction"]["tools"] == sum(
        len(names) for names in TOOL_FAMILIES.values()
    )


def test_each_family_contributes_its_own_schemas_to_the_payload(measurement):
    """Per-family numbers are the two readings the doc prints, and they agree."""
    for family, row in measurement["families"].items():
        assert row["payload_delta_bytes"] == row["schema_bytes"] + row["tools"], family


# -------------------------------------------------------- the doc can't rot --


def test_the_committed_document_matches_a_fresh_measurement(measurement, recorded):
    assert recorded == measurement, (
        f"docs/telemetry/tool-list-size.md records numbers the code no longer "
        f"produces. The tool list moved — {REGENERATE}."
    )


def test_the_documents_prose_tables_agree_with_its_own_json_block(recorded):
    """The prose is what a human reads; a stale table would mislead silently."""
    text = DOC.read_text(encoding="utf-8")
    assert (
        f"| all families enabled | {recorded['all_families']['tools']} | "
        f"{recorded['all_families']['bytes']:,} |"
    ) in text, REGENERATE
    for value in (
        recorded["all_families"]["bytes"],
        recorded["default"]["bytes"],
        recorded["reduction"]["bytes"],
    ):
        assert f"{value:,}" in text, f"{value:,} missing from {tls.DOC_PATH} — {REGENERATE}"
    assert f"{recorded['reduction']['pct']}%" in text
    for family, row in recorded["families"].items():
        assert f"| `{family}` | {row['tools']} | {row['schema_bytes']:,} |" in text


def test_the_document_records_how_and_when_it_was_produced(recorded):
    """Date, commit basis and the exact command — the task's DoD for the doc."""
    text = DOC.read_text(encoding="utf-8")
    assert re.search(r"- Measured: \*\*\d{4}-\d{2}-\d{2}\*\*", text), text[:400]
    assert re.search(r"- Commit basis: \*\*[0-9a-f]{40}", text), text[:400]
    assert tls.COMMAND in text
    assert recorded["command"] == tls.COMMAND
    assert recorded["serialisation"] == tls.SERIALISATION
    assert recorded["schema"] == tls.SCHEMA


def test_the_mcp_tools_reference_points_at_the_measurement():
    """The gating section claims a saving; it must cite where the number is."""
    reference = (REPO_ROOT / "docs/reference/mcp-tools.md").read_text(encoding="utf-8")
    assert "telemetry/tool-list-size.md" in reference


# ------------------------------------------------------- the CLI and the API --


def test_the_cli_prints_the_measurement(capsys):
    assert tls.main([]) == 0
    out = capsys.readouterr().out
    assert "all families enabled" in out and "saved" in out


def test_the_cli_json_output_is_the_measurement(capsys, measurement):
    assert tls.main(["--json"]) == 0
    assert json.loads(capsys.readouterr().out) == measurement


def test_the_cli_can_render_the_document_without_writing_it(capsys, measurement):
    """``--stdout`` so a reader can diff the doc without touching the tree."""
    assert tls.main(["--markdown", "--stdout"]) == 0
    rendered = capsys.readouterr().out
    assert json.dumps(measurement, indent=2, sort_keys=True) in rendered


# -------------------------------------------- wired into the baseline tooling --


def test_the_headline_carries_the_tool_list_bytes(measurement):
    from tools.usage_telemetry.report import build_report

    artifact = bl.build_baseline(
        build_report([], extraction_summary=None),
        repo=REPO_ROOT,
        tool_list=measurement,
    )
    metrics = bl.headline_metrics(artifact)
    assert metrics["tool_list_bytes_all"] == measurement["all_families"]["bytes"]
    assert metrics["tool_list_bytes_default"] == measurement["default"]["bytes"]
    assert metrics["tool_list_tools_default"] == measurement["default"]["tools"]
    assert "`tools/list` schema bytes" in bl.format_summary(artifact)


def test_only_the_default_payload_is_a_target(measurement):
    """A shrinking default is the win; the all-families total is just context."""
    assert "tool_list_bytes_default" in bl.LOWER_IS_BETTER
    assert "tool_list_bytes_all" not in bl.LOWER_IS_BETTER
    assert "tool_list_bytes_all" not in bl.HIGHER_IS_BETTER

    from tools.usage_telemetry.report import build_report

    def artifact(default_bytes):
        measured = json.loads(json.dumps(measurement))
        measured["default"]["bytes"] = default_bytes
        return bl.build_baseline(
            build_report([], extraction_summary=None), repo=REPO_ROOT, tool_list=measured
        )

    row = bl.compare(artifact(90_000), artifact(80_000))["metrics"][
        "tool_list_bytes_default"
    ]
    assert row["delta"] == -10_000 and row["direction"] == "better"


def test_a_baseline_without_the_measurement_reads_none():
    """The committed pre-fix baseline predates this metric and must still diff."""
    from tools.usage_telemetry.report import build_report

    artifact = bl.build_baseline(build_report([], extraction_summary=None), repo=REPO_ROOT)
    assert "tool_list" not in artifact, "an unmeasured baseline must not grow a key"
    metrics = bl.headline_metrics(artifact)
    assert metrics["tool_list_bytes_default"] is None
    assert metrics["tool_list_bytes_all"] is None
    assert "`tools/list` schema bytes" not in bl.format_summary(artifact)


def test_the_committed_baseline_is_untouched_by_this_metric():
    """US-PM-6 owns that file; US-PM-15 must not have edited it."""
    committed = json.loads(
        (REPO_ROOT / "docs/telemetry/baseline-pre-fix.json").read_text(encoding="utf-8")
    )
    assert set(committed) == {"schema", "provenance", "report"}
    assert bl.headline_metrics(committed)["tool_list_bytes_default"] is None


def test_a_capture_cannot_be_broken_by_an_unmeasurable_tool_list(monkeypatch):
    """Telemetry must still run where ``projectman``/``mcp`` are not importable."""
    def boom():
        raise ImportError("no mcp here")

    monkeypatch.setattr(tls, "measure", boom)
    assert bl.measure_tool_list() is None


# ----------------------------------- the default is what a real server serves --


def test_a_started_server_advertises_exactly_the_measured_default_payload(
    tmp_project, monkeypatch
):
    """US-PM-15-4 (d): the "default" number is what ``projectman serve`` sends.

    ``measure()`` models the default by passing :data:`tls.DEFAULT_FAMILIES`
    explicitly, never by reading a config. That is deliberate — the number must
    not depend on the repo it ran in — but it leaves one thing unasserted: that
    a *real* startup off a default ``.project/config.yaml`` resolves to the same
    families. ``run_server`` re-applies the gating at startup, so this drives it
    (with the transport stubbed) from a project whose config has no ``tools:``
    section at all, and compares both the tool names and the wire bytes to the
    utility's default configuration.
    """
    from projectman import server

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    assert "tools" not in yaml.safe_load(
        (tmp_project / ".project" / "config.yaml").read_text()
    )

    # Start from every family visible, so a ``run_server`` that forgot to gate
    # would leave the extra families behind and fail below.
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    ran = []
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: ran.append(kwargs))
    server.run_server(transport="stdio")
    assert ran == [{"transport": "stdio"}]

    served = _wire_payload()
    assert gated_tool_state() == tls.DEFAULT_FAMILIES

    modelled = _wire_payload_under(tls.DEFAULT_FAMILIES)
    assert served.names == modelled.names
    assert served.bytes == modelled.bytes == tls.measure()["default"]["bytes"]


def test_a_started_server_serves_fewer_bytes_than_an_all_families_one(
    tmp_project, monkeypatch
):
    """The saving, end to end: the same startup path with the families opted in."""
    from projectman import server

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    config_path = tmp_project / ".project" / "config.yaml"
    data = yaml.safe_load(config_path.read_text())

    config_path.write_text(yaml.dump(data))
    monkeypatch.setattr(server.mcp, "run", lambda **kwargs: None)
    server.run_server(transport="stdio")
    default = _wire_payload()

    data["tools"] = {family: True for family in TOOL_FAMILIES}
    config_path.write_text(yaml.dump(data))
    server.run_server(transport="stdio")
    every = _wire_payload()

    assert every.bytes - default.bytes == tls.measure()["reduction"]["bytes"]
    assert (every.bytes - default.bytes) / every.bytes >= 0.10


# ------------------------------------------- the capture populates the keys --


def test_a_live_capture_carries_the_measured_tool_list(tmp_path):
    """US-PM-15-4 (e): ``capture()`` — not just ``build_baseline()`` — fills them.

    The other headline test builds the artifact with the measurement handed in.
    This one takes the path the CLI takes, where nothing passes ``tool_list``
    and ``capture`` has to reach for it itself.
    """
    corpus = tmp_path / "projects"
    corpus.mkdir()
    artifact = bl.capture(root=str(corpus), repo=REPO_ROOT)
    live = tls.measure()

    assert artifact["tool_list"] == live
    metrics = bl.headline_metrics(artifact)
    assert metrics["tool_list_bytes_all"] == live["all_families"]["bytes"]
    assert metrics["tool_list_bytes_default"] == live["default"]["bytes"]
    assert metrics["tool_list_tools_default"] == live["default"]["tools"]
    assert metrics["tool_list_bytes_default"] < metrics["tool_list_bytes_all"]
