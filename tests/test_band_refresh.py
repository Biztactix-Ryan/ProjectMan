"""The sprint band's write list matches the server's tools (US-PM-62-7).

hooks/band-refresh.ts re-reads the band after any pm tool that writes. Its
PM_WRITE_TOOLS list is kept by hand; this holds it equal to the tools the
MCP server registers without ``readOnlyHint=True``, so a new writing tool
cannot be left out (nor a removed one linger). Reads the registry only: no
tool is called and no store is touched.
"""

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
BAND_REFRESH = REPO_ROOT / "hooks" / "band-refresh.ts"
LIST_BLOCK = re.compile(r"// BEGIN PM_WRITE_TOOLS\n(.*?)// END PM_WRITE_TOOLS", re.S)


def _mod_write_tools() -> list[str]:
    block = LIST_BLOCK.search(BAND_REFRESH.read_text())
    assert block, "hooks/band-refresh.ts has no PM_WRITE_TOOLS block"
    return re.findall(r"'(pm_\w+)'", block.group(1))


def _server_tools():
    from projectman.server import mcp

    return mcp._tool_manager.list_tools()


def test_write_list_matches_server_tools_not_declared_read_only():
    writes = {
        t.name
        for t in _server_tools()
        if t.annotations is None or t.annotations.readOnlyHint is not True
    }
    listed = _mod_write_tools()
    assert len(listed) == len(set(listed)), "PM_WRITE_TOOLS names a tool twice"
    assert set(listed) == writes, (
        f"missing from PM_WRITE_TOOLS: {sorted(writes - set(listed))}; "
        f"not writing tools: {sorted(set(listed) - writes)}"
    )


def test_every_server_tool_declares_read_only_or_not():
    # The cross-check above relies on each tool saying which it is.
    undeclared = [
        t.name
        for t in _server_tools()
        if t.annotations is None or t.annotations.readOnlyHint is None
    ]
    assert undeclared == []


def test_status_changing_tools_are_listed():
    listed = set(_mod_write_tools())
    for name in ("pm_update", "pm_update_many", "pm_grab", "pm_release", "pm_accept",
                 "pm_retry", "pm_park", "pm_review", "pm_done_next", "pm_next",
                 "pm_create_task", "pm_update_sprint", "pm_answer_decision"):
        assert name in listed, name
