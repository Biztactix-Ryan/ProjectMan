"""Measure the ``tools/list`` payload with and without the gated families (US-PM-15-7).

US-PM-15 hides three tool families (``changesets``, ``maintenance``, ``web``)
behind config flags so their schemas are not paid for in every request. The
story's last acceptance criterion is that the saving is *measurable*, which
means a number produced by a repeatable command rather than an estimate.

What is measured
----------------

Exactly the bytes a client receives as the ``result`` of a ``tools/list``
request: :class:`mcp.types.ListToolsResult` serialised the way the MCP session
serialises every result on the way out --
``model_dump_json(by_alias=True, exclude_none=True)`` (see
``mcp/shared/session.py``; the transports then write that with pydantic's
compact separators). Nothing here re-implements the serialisation, so the
number moves if and only if the real payload moves.

The measurement is a pure function of the code: both configurations are driven
by passing an explicit ``{family: enabled}`` mapping to
:func:`projectman.server.apply_tool_gating`, never by reading a config file, so
the numbers do not depend on which repo the command is run in. The registry is
put back exactly as it was found, so importing this module cannot change what a
running server serves.

Usage::

    python -m tools.usage_telemetry.tool_list_size            # text summary
    python -m tools.usage_telemetry.tool_list_size --json     # machine-readable
    python -m tools.usage_telemetry.tool_list_size --markdown # the committed doc

``docs/telemetry/tool-list-size.md`` is the recorded result;
``tests/test_tool_list_size.py`` re-runs the measurement and fails if the doc
has drifted from it.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Sequence

import anyio
from mcp import types

from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp,
)

#: Bumped only when the artifact layout changes incompatibly.
SCHEMA = "projectman.tool-list-size/1"

#: How the bytes below were produced, recorded in the artifact so a reader can
#: tell a serialisation change from a real payload change.
SERIALISATION = "mcp.types.ListToolsResult.model_dump_json(by_alias=True, exclude_none=True)"

#: The command that regenerates every number in this module's artifacts.
COMMAND = "python -m tools.usage_telemetry.tool_list_size --markdown"

#: Every gated family on. Not the shipped configuration -- the "before" the
#: gating is measured against.
ALL_FAMILIES: dict[str, bool] = {family: True for family in TOOL_FAMILIES}

#: The shipped default for a plain single-project install: every gated family
#: off. ``changesets`` follows ``hub`` when unset, so a hub measures between
#: this and :data:`ALL_FAMILIES`; the headline number is the common case.
DEFAULT_FAMILIES: dict[str, bool] = {family: False for family in TOOL_FAMILIES}

#: The doc this module writes and the test compares against.
DOC_PATH = "docs/telemetry/tool-list-size.md"

#: Fences the machine-readable block inside that doc, so the test can find it
#: without parsing prose.
JSON_FENCE_MARKER = "<!-- tool-list-size:measurement -->"


# ------------------------------------------------------------- measurement --


def _payload_bytes(tools: Sequence[types.Tool]) -> int:
    """Bytes of the ``result`` object for a ``tools/list`` carrying ``tools``."""
    result = types.ListToolsResult(tools=list(tools))
    return len(result.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))


def _tool_bytes(tool: types.Tool) -> int:
    """Bytes of one tool's own JSON object, framing commas excluded."""
    return len(tool.model_dump_json(by_alias=True, exclude_none=True).encode("utf-8"))


def _list_tools(families: dict[str, bool]) -> list[types.Tool]:
    """The ``tools/list`` a client would be served under ``families``."""
    apply_tool_gating(families)
    return list(anyio.run(mcp.list_tools))


def measure() -> dict[str, Any]:
    """Measure both configurations and the per-family contribution.

    Restores whatever gating was in effect before the call, including when a
    measurement raises: this runs inside the same process as a real server in
    the tests, and leaving the registry half-gated would corrupt every test
    that follows.
    """
    before = gated_tool_state()
    try:
        all_tools = _list_tools(ALL_FAMILIES)
        default_tools = _list_tools(DEFAULT_FAMILIES)

        all_bytes = _payload_bytes(all_tools)
        default_bytes = _payload_bytes(default_tools)

        by_name = {tool.name: tool for tool in all_tools}
        families: dict[str, Any] = {}
        for family, names in TOOL_FAMILIES.items():
            members = [by_name[name] for name in names if name in by_name]
            # Two readings of "what this family costs". ``schema_bytes`` is the
            # sum of the tools' own JSON objects. ``payload_delta_bytes`` is
            # what the whole payload actually shrinks by when only this family
            # is turned off, which is ``schema_bytes`` plus one framing comma
            # per tool -- reported separately so the framing is visible rather
            # than hidden inside a single number.
            only_this_off = {**ALL_FAMILIES, family: False}
            without = _payload_bytes(_list_tools(only_this_off))
            families[family] = {
                "tools": len(members),
                "schema_bytes": sum(_tool_bytes(tool) for tool in members),
                "payload_delta_bytes": all_bytes - without,
            }
    finally:
        apply_tool_gating(before)

    saved = all_bytes - default_bytes
    return {
        "schema": SCHEMA,
        "serialisation": SERIALISATION,
        "command": COMMAND,
        "all_families": {"tools": len(all_tools), "bytes": all_bytes},
        "default": {"tools": len(default_tools), "bytes": default_bytes},
        "reduction": {
            "tools": len(all_tools) - len(default_tools),
            "bytes": saved,
            "pct": round(100.0 * saved / all_bytes, 2) if all_bytes else 0.0,
        },
        "families": families,
    }


def headline(measurement: dict[str, Any]) -> dict[str, Any]:
    """The two keys :mod:`tools.usage_telemetry.baseline` carries as metrics."""
    return {
        "tool_list_bytes_all": (measurement.get("all_families") or {}).get("bytes"),
        "tool_list_bytes_default": (measurement.get("default") or {}).get("bytes"),
    }


# ---------------------------------------------------------------- renderers --


def format_text(measurement: dict[str, Any]) -> str:
    all_f, default, reduction = (
        measurement["all_families"],
        measurement["default"],
        measurement["reduction"],
    )
    lines = [
        f"tools/list payload  ({measurement['serialisation']})",
        "",
        f"  {'configuration':<24}{'tools':>8}{'bytes':>12}",
        f"  {'all families enabled':<24}{all_f['tools']:>8}{all_f['bytes']:>12}",
        f"  {'default (all gated off)':<24}{default['tools']:>8}{default['bytes']:>12}",
        f"  {'saved':<24}{reduction['tools']:>8}{reduction['bytes']:>12}"
        f"   ({reduction['pct']}%)",
        "",
        f"  {'gated family':<24}{'tools':>8}{'schema B':>12}{'payload B':>12}",
    ]
    for family, row in measurement["families"].items():
        lines.append(
            f"  {family:<24}{row['tools']:>8}{row['schema_bytes']:>12}"
            f"{row['payload_delta_bytes']:>12}"
        )
    return "\n".join(lines)


def format_markdown(measurement: dict[str, Any], *, provenance: dict[str, Any]) -> str:
    """The committed doc: prose plus a fenced block the test compares exactly.

    Provenance (date, commit) lives in the prose and *not* in the fenced block,
    so the test can demand an exact match on the numbers without the doc going
    stale the moment another commit lands.
    """
    all_f, default, reduction = (
        measurement["all_families"],
        measurement["default"],
        measurement["reduction"],
    )
    rows = [
        f"| `{family}` | {row['tools']} | {row['schema_bytes']:,} | "
        f"{row['payload_delta_bytes']:,} |"
        for family, row in measurement["families"].items()
    ]
    body = json.dumps(measurement, indent=2, sort_keys=True)
    return f"""# Tool-list payload size

US-PM-15 gates three tool families behind config flags. This file is the
**measured** saving, so the context claim in
[`reference/mcp-tools.md`](../reference/mcp-tools.md) is a number and not an
assumption.

- Measured: **{provenance['date']}**
- Commit basis: **{provenance['commit']}**
- Command: `{measurement['command']}` (run from the repo root)
- Serialisation: `{measurement['serialisation']}` — exactly what the MCP
  session writes as the `result` of a `tools/list` request, so this moves if
  and only if the real payload moves.

## Headline

| configuration | tools | `tools/list` bytes |
| --- | ---: | ---: |
| all families enabled | {all_f['tools']} | {all_f['bytes']:,} |
| default (`changesets`, `maintenance`, `web` all off) | {default['tools']} | {default['bytes']:,} |
| **saved** | **{reduction['tools']}** | **{reduction['bytes']:,} ({reduction['pct']}%)** |

## Per family

`schema B` is the sum of the family's own tool JSON objects. `payload B` is
what the whole payload shrinks by when only that family is turned off — the
same bytes plus one framing comma per tool.

| family | tools | schema B | payload B |
| --- | ---: | ---: | ---: |
{chr(10).join(rows)}

## Keeping it honest

`tests/test_tool_list_size.py` re-runs the measurement and compares it to the
block below. If it fails, the payload moved: re-run the command above and
commit the regenerated file.

{JSON_FENCE_MARKER}

```json
{body}
```
"""


# --------------------------------------------------------------------- CLI --


def _provenance() -> dict[str, Any]:
    from datetime import datetime, timezone
    from pathlib import Path

    from tools.usage_telemetry.baseline import git_provenance

    repo = Path(__file__).resolve().parents[2]
    git = git_provenance(repo)
    commit = git.get("commit") or "unknown"
    if git.get("dirty"):
        commit = f"{commit} (working tree dirty)"
    return {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "commit": commit,
        "repo": repo,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.usage_telemetry.tool_list_size",
        description="Measure the tools/list payload with and without the gated families.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--json", action="store_true", help="print the raw measurement")
    group.add_argument(
        "--markdown",
        action="store_true",
        help=f"write {DOC_PATH} (use --stdout to print it instead)",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="with --markdown, print the document instead of writing it",
    )
    args = parser.parse_args(argv)

    measurement = measure()
    if args.json:
        print(json.dumps(measurement, indent=2, sort_keys=True))
        return 0
    if args.markdown:
        provenance = _provenance()
        text = format_markdown(measurement, provenance=provenance)
        if args.stdout:
            print(text, end="")
            return 0
        path = provenance["repo"] / DOC_PATH
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
        return 0
    print(format_text(measurement))
    return 0


if __name__ == "__main__":  # pragma: no cover - CLI entry point
    raise SystemExit(main(sys.argv[1:]))
