"""US-PRJ-49-6 — every tool's MCP hints are pinned, one row per tool.

US-PRJ-49 fixed the destructive hints on the mutating tools.  A fix like
that rots the moment someone adds a tool and forgets the annotation, so the
review outcome is pinned here as *data*: a full ``name -> (readOnlyHint,
destructiveHint)`` table, written by hand rather than generated from the
server at test time.  Changing an annotation is then a deliberate edit to
this file, and a new tool that arrives without annotations fails outright.

Three separate guards, because they fail for different reasons:

1. **coverage** — the registry and the table hold the same 50 tools, so a
   silently-dropped family or an unpinned new tool is a failure;
2. **explicitness** — every tool sets ``readOnlyHint``, and every tool that
   is *not* read-only also sets ``destructiveHint``.  Read-only tools may
   leave ``destructiveHint`` unset: "reads nothing away" already says it;
3. **the values themselves** — the pinned table, and the destructive set
   spelled out a second time so the highest-stakes hint is legible in one
   place instead of being read off 50 rows.

The gated families (maintenance, web) are absent from ``list_tools()`` under
default config, so the fixture turns every family on and puts the previous
visibility back afterwards — the registry is process-global and other
modules measure it.
"""

import anyio
import pytest

from projectman.server import (
    TOOL_FAMILIES,
    apply_tool_gating,
    gated_tool_state,
    mcp as mcp_server,
)

#: Every registered tool and the two hints it declares, as reviewed under
#: US-PRJ-49.  ``None`` means the hint is genuinely unset on the tool.
#:
#: To change a row: change the annotation in ``src/projectman/server.py``
#: *and* this table, in the same commit.
EXPECTED_HINTS: dict[str, tuple[bool, bool | None]] = {
    # ─── read-only: report, search, inspect ───────────────────────
    "pm_active": (True, None),
    "pm_activity": (True, None),
    "pm_audit": (True, None),
    "pm_auto_scope": (True, None),
    "pm_batch_get": (True, None),
    "pm_board": (True, None),
    "pm_burndown": (True, None),
    "pm_context": (True, None),
    "pm_docs": (True, None),
    "pm_epic": (True, None),
    "pm_estimate": (True, None),
    "pm_get": (True, None),
    "pm_get_sprint": (True, None),
    "pm_git_status": (True, None),
    "pm_list_sprints": (True, None),
    "pm_malformed": (True, None),
    "pm_run_log": (True, None),
    "pm_scope": (True, None),
    "pm_search": (True, None),
    "pm_status": (True, None),
    "pm_web_status": (True, None),
    # ─── writes, but additive or reversible ───────────────────────
    "pm_accept": (False, False),
    "pm_commit": (False, False),
    "pm_create_epic": (False, False),
    "pm_create_sprint": (False, False),
    "pm_create_story": (False, False),
    "pm_create_task": (False, False),
    "pm_create_tasks": (False, False),
    "pm_done_next": (False, False),
    "pm_grab": (False, False),
    "pm_next": (False, False),
    "pm_park": (False, False),
    "pm_reindex": (False, False),
    "pm_release": (False, False),
    "pm_retry": (False, False),
    "pm_review": (False, False),
    "pm_update": (False, False),
    "pm_update_doc": (False, False),
    "pm_update_many": (False, False),
    "pm_update_sprint": (False, False),
    "pm_web_start": (False, False),
    "pm_web_stop": (False, False),
    # ─── destructive: moves files, or changes remote state ────────
    "pm_archive": (False, True),
    "pm_archive_many": (False, True),
    "pm_fix_malformed": (False, True),
    "pm_push": (False, True),
    "pm_restore": (False, True),
}

#: 42 default tools plus the 5 in the gated families.
EXPECTED_TOOL_COUNT = 47

#: The review outcome of US-PRJ-49, spelled out rather than derived: these
#: five move item files out from under the caller or write to a git remote.
DESTRUCTIVE_TOOLS = frozenset(
    {
        "pm_archive",
        "pm_archive_many",
        "pm_fix_malformed",
        "pm_push",
        "pm_restore",
    }
)


@pytest.fixture(autouse=True)
def every_family_registered():
    """Show the gated tools, then put the previous visibility back.

    Same shape as ``tests/test_tool_list_size.py`` — the FastMCP registry is
    process-global, so leaving it widened would change what another module
    measures.
    """
    before = gated_tool_state()
    apply_tool_gating({family: True for family in TOOL_FAMILIES})
    yield
    apply_tool_gating(before)


def _tool_schemas() -> dict:
    return {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}


# ─── coverage ────────────────────────────────────────────────────


class TestTheTableCoversEveryTool:
    def test_the_registry_and_the_table_hold_the_same_names(self):
        """A new tool has to be pinned here before this suite goes green."""
        registered = frozenset(_tool_schemas())

        unpinned = registered - frozenset(EXPECTED_HINTS)
        assert not unpinned, (
            "these tools have no pinned annotations — add a row to "
            f"EXPECTED_HINTS: {sorted(unpinned)}"
        )
        missing = frozenset(EXPECTED_HINTS) - registered
        assert not missing, (
            "these tools are pinned but not registered — was a tool removed "
            f"or a family left gated? {sorted(missing)}"
        )

    def test_the_count_is_the_reviewed_one(self):
        """A whole family disappearing is a count change, not a name change."""
        assert len(_tool_schemas()) == EXPECTED_TOOL_COUNT

    def test_the_gated_families_are_part_of_the_table(self):
        """The 8 gated tools are reviewed too, not skipped for being hidden."""
        gated = {name for names in TOOL_FAMILIES.values() for name in names}

        assert gated <= frozenset(EXPECTED_HINTS)
        assert gated <= frozenset(_tool_schemas())


# ─── explicitness ────────────────────────────────────────────────


class TestEveryToolDeclaresItsHints:
    def test_every_tool_has_annotations(self):
        unannotated = [
            name
            for name, tool in sorted(_tool_schemas().items())
            if tool.annotations is None
        ]

        assert not unannotated, (
            "every @mcp.tool needs annotations=ToolAnnotations(...): "
            f"{unannotated}"
        )

    def test_every_tool_sets_read_only_hint_explicitly(self):
        """Unset is not "false" — an MCP client cannot tell the difference."""
        unset = [
            name
            for name, tool in sorted(_tool_schemas().items())
            if tool.annotations is None or tool.annotations.readOnlyHint is None
        ]

        assert not unset, f"readOnlyHint is unset on: {unset}"

    def test_every_writing_tool_sets_destructive_hint_explicitly(self):
        """Read-only tools may omit it; anything that writes may not."""
        unset = [
            name
            for name, tool in sorted(_tool_schemas().items())
            if tool.annotations is not None
            and tool.annotations.readOnlyHint is False
            and tool.annotations.destructiveHint is None
        ]

        assert not unset, (
            "these tools write and must say whether that is destructive: "
            f"{unset}"
        )


# ─── the values ──────────────────────────────────────────────────


class TestTheHintsMatchTheReview:
    def test_every_tool_matches_its_pinned_row(self):
        actual = {
            name: (tool.annotations.readOnlyHint, tool.annotations.destructiveHint)
            for name, tool in _tool_schemas().items()
            if tool.annotations is not None
        }

        drifted = {
            name: (actual[name], EXPECTED_HINTS[name])
            for name in sorted(actual.keys() & EXPECTED_HINTS.keys())
            if actual[name] != EXPECTED_HINTS[name]
        }

        assert not drifted, (
            "annotation drift — {tool: (actual, pinned)}; change the source "
            f"and this table together: {drifted}"
        )

    def test_the_destructive_set_is_exactly_the_reviewed_one(self):
        """US-PRJ-49's whole point, as one assertion."""
        destructive = frozenset(
            name
            for name, tool in _tool_schemas().items()
            if tool.annotations is not None
            and tool.annotations.destructiveHint is True
        )

        assert destructive == DESTRUCTIVE_TOOLS

    def test_the_destructive_set_and_the_table_agree(self):
        """Two pins of the same fact, kept from drifting apart."""
        from_table = frozenset(
            name
            for name, (_, destructive) in EXPECTED_HINTS.items()
            if destructive is True
        )

        assert from_table == DESTRUCTIVE_TOOLS

    def test_no_read_only_tool_claims_to_be_destructive(self):
        """A contradiction a client would have to guess its way through."""
        contradictory = [
            name
            for name, tool in sorted(_tool_schemas().items())
            if tool.annotations is not None
            and tool.annotations.readOnlyHint is True
            and tool.annotations.destructiveHint is True
        ]

        assert not contradictory
