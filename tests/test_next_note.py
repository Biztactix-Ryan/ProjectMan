"""The next-session note — ``.project/NEXT.md`` (US-PM-28-5).

Criterion under test: *pm_next reads and replaces and appends to and clears
``.project/NEXT.md``*.

The note is scratch text with one owner and a short life ("we decided to fix X
by doing Y and Z"), so the things worth pinning down are the ones a careless
implementation gets wrong and a user only notices after losing a note:

* reading an absent note is a *successful* "nothing here", not a failure;
* appending keeps what was already there, in the order it was written;
* clearing an absent note is a no-op that says so rather than raising;
* the two argument combinations that cannot mean anything are hard errors;
* every mutation leaves exactly one activity-log event — no more, no fewer;
* the file is written atomically, so a crash mid-write cannot destroy the
  note that was already there.

Everything runs against ``tmp_project`` / ``server_project`` — never the real
``.project/`` this repository keeps its own backlog in.
"""

import json
import os

import pytest
import yaml
from mcp.server.fastmcp.exceptions import ToolError

from projectman.store import Store, _cache


@pytest.fixture
def store(tmp_project):
    return Store(tmp_project)


@pytest.fixture
def server_project(tmp_project, monkeypatch):
    """Point the MCP tools at *tmp_project*, never at the repo's own project.

    ``PROJECTMAN_ROOT`` wins over cwd in ``find_project_root``, so it is
    dropped here: left set from the ambient environment, ``pm_next`` would
    write its note into a real project. The assert is a guard rail, not
    decoration.
    """
    from projectman.config import find_project_root
    from projectman.server import _store_cache

    monkeypatch.delenv("PROJECTMAN_ROOT", raising=False)
    monkeypatch.chdir(tmp_project)
    _store_cache.clear()
    _cache.clear()
    assert find_project_root() == tmp_project.resolve()
    yield tmp_project
    _store_cache.clear()


def note_events(store) -> list[dict]:
    """Every activity-log entry the note produced, oldest first.

    Read the way ``pm_activity`` reads it — raw JSONL lines off
    ``activity.jsonl`` — rather than through the model, so a change that
    stopped the event being written at all cannot pass here.
    """
    log_path = store.project_dir / "activity.jsonl"
    if not log_path.exists():
        return []
    entries = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    return [e for e in entries if e.get("item_type") == "note"]


# ===========================================================================
# Store: read, replace, append, clear.
# ===========================================================================


class TestReadNext:
    def test_the_note_lives_at_project_next_md(self, store, tmp_project):
        assert store.next_note_path == tmp_project / ".project" / "NEXT.md"

    def test_reading_an_absent_note_is_none_not_an_error(self, store):
        """"Nobody left you anything" is an answer, so it must not raise."""
        assert not store.next_note_path.exists()
        assert store.read_next() is None

    def test_a_blank_note_reads_the_same_as_no_note(self, store):
        """A file emptied by hand is not a note; it must not read as one."""
        store.next_note_path.write_text("   \n\n\t\n")
        assert store.read_next() is None

    def test_reading_does_not_create_the_file(self, store):
        store.read_next()
        assert not store.next_note_path.exists()

    def test_reading_never_logs(self, store):
        store.read_next()
        store.write_next("something")
        store.read_next()
        assert len(note_events(store)) == 1


class TestWriteNext:
    def test_replace_writes_the_text(self, store):
        assert store.write_next("fix X by doing Y and Z") == "fix X by doing Y and Z"
        assert store.read_next() == "fix X by doing Y and Z"

    def test_replace_strips_and_ends_with_exactly_one_newline(self, store):
        store.write_next("\n\n  trailing whitespace everywhere  \n\n")
        assert store.next_note_path.read_text() == "trailing whitespace everywhere\n"

    def test_replace_discards_the_previous_note(self, store):
        store.write_next("the old plan")
        store.write_next("the new plan")
        assert store.read_next() == "the new plan"
        assert "old plan" not in store.next_note_path.read_text()

    def test_the_note_has_no_frontmatter(self, store):
        """It is scratch markdown, not an item — nothing may parse it as one."""
        store.write_next("just prose")
        assert not store.next_note_path.read_text().startswith("---")

    def test_append_to_an_absent_note_writes_the_first_dated_entry(self, store):
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date().isoformat()
        result = store.write_next("first thought", append=True)
        assert result == f"### {today}\n\nfirst thought"

    def test_appending_twice_keeps_both_entries_in_order(self, store):
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date().isoformat()
        store.write_next("first thought", append=True)
        store.write_next("second thought", append=True)

        text = store.read_next()
        assert text.count(f"### {today}") == 2
        assert text.index("first thought") < text.index("second thought")
        assert "\n\n### " in text, text

    def test_appending_to_a_replaced_note_keeps_the_replaced_text(self, store):
        store.write_next("the standing plan")
        store.write_next("and one more thing", append=True)
        text = store.read_next()
        assert text.startswith("the standing plan")
        assert text.endswith("and one more thing")

    def test_each_write_logs_exactly_one_event(self, store):
        store.write_next("one")
        assert len(note_events(store)) == 1
        store.write_next("two", append=True)
        events = note_events(store)
        assert len(events) == 2
        assert [e["event_type"] for e in events] == ["update", "update"]
        assert [e["item_id"] for e in events] == ["NEXT", "NEXT"]
        assert [e["changes"]["mode"] for e in events] == ["replace", "append"]


class TestClearNext:
    def test_clearing_an_absent_note_returns_false_and_does_not_raise(self, store):
        assert store.clear_next() is False

    def test_clearing_a_present_note_deletes_it_and_returns_true(self, store):
        store.write_next("done with this")
        assert store.clear_next() is True
        assert not store.next_note_path.exists()
        assert store.read_next() is None

    def test_clearing_logs_one_delete_event_either_way(self, store):
        store.clear_next()
        store.write_next("something")
        store.clear_next()

        events = note_events(store)
        assert [e["event_type"] for e in events] == ["delete", "update", "delete"]
        assert [e["changes"]["had_note"] for e in events if e["event_type"] == "delete"] == [
            False,
            True,
        ]


class TestTheNoteIsWrittenAtomically:
    """A half-written note is worse than no note: the old one is gone too."""

    def test_a_failed_rename_leaves_no_partial_next_md(self, store, monkeypatch):
        import projectman.store as store_module

        def boom(src, dst):
            raise OSError("no rename for you")

        monkeypatch.setattr(store_module.os, "replace", boom)
        with pytest.raises(OSError):
            store.write_next("the note that never landed")

        assert not store.next_note_path.exists()
        # ...and the temp file it staged was cleaned up rather than left behind.
        assert not list(store.project_dir.glob(".NEXT.md.*"))

    def test_a_failed_rename_leaves_the_previous_note_intact(self, store, monkeypatch):
        import projectman.store as store_module

        store.write_next("the note worth keeping")

        monkeypatch.setattr(
            store_module.os, "replace", lambda src, dst: (_ for _ in ()).throw(OSError("nope"))
        )
        with pytest.raises(OSError):
            store.write_next("the note that never landed")

        assert store.read_next() == "the note worth keeping"


# ===========================================================================
# The tool: pm_next.
# ===========================================================================


class TestPmNextTool:
    def test_no_arguments_with_no_note_says_so(self, server_project):
        from projectman.server import pm_next

        assert yaml.safe_load(pm_next()) == {"note": None, "message": "no note saved"}

    def test_no_arguments_returns_the_note(self, server_project):
        from projectman.server import pm_next

        pm_next("fix X by doing Y and Z")
        assert yaml.safe_load(pm_next()) == {"note": "fix X by doing Y and Z"}

    def test_text_replaces_and_returns_the_new_note(self, server_project):
        from projectman.server import pm_next

        pm_next("the old plan")
        assert yaml.safe_load(pm_next("the new plan")) == {"note": "the new plan"}
        assert yaml.safe_load(pm_next()) == {"note": "the new plan"}

    def test_append_returns_the_whole_note_not_just_the_addition(self, server_project):
        from projectman.server import pm_next

        pm_next("the standing plan")
        note = yaml.safe_load(pm_next("and one more thing", append=True))["note"]
        assert "the standing plan" in note and "and one more thing" in note

    def test_clear_reports_whether_there_was_anything_to_clear(self, server_project):
        from projectman.server import pm_next

        assert yaml.safe_load(pm_next(clear=True)) == {"cleared": False}
        pm_next("something to forget")
        assert yaml.safe_load(pm_next(clear=True)) == {"cleared": True}
        assert yaml.safe_load(pm_next()) == {"note": None, "message": "no note saved"}

    def test_the_tool_writes_the_file_the_store_reads(self, server_project):
        from projectman.server import pm_next

        pm_next("written through the tool")
        assert (server_project / ".project" / "NEXT.md").read_text() == (
            "written through the tool\n"
        )

    def test_text_and_clear_together_is_an_error(self, server_project):
        from projectman.server import pm_next

        with pytest.raises(ToolError, match="pass text or clear, not both"):
            pm_next("a note", clear=True)

    def test_text_and_clear_together_writes_nothing(self, server_project):
        """An ambiguous call must not half-happen."""
        from projectman.server import pm_next

        pm_next("the standing note")
        with pytest.raises(ToolError):
            pm_next("a note", clear=True)
        assert yaml.safe_load(pm_next()) == {"note": "the standing note"}

    def test_append_without_text_is_an_error(self, server_project):
        from projectman.server import pm_next

        with pytest.raises(ToolError, match="append needs text"):
            pm_next(append=True)

    def test_the_annotations_say_it_writes_but_does_not_destroy(self):
        """`clear` is deliberate, but the note is scratch by design."""
        import anyio

        from projectman.server import mcp as mcp_server

        tool = next(t for t in anyio.run(mcp_server.list_tools) if t.name == "pm_next")
        assert tool.annotations.readOnlyHint is False
        assert tool.annotations.destructiveHint is False

    def test_the_tool_is_registered_by_default(self):
        """It is core, not one of the gated families."""
        import anyio

        from projectman.server import TOOL_FAMILIES, mcp as mcp_server

        assert "pm_next" not in {n for names in TOOL_FAMILIES.values() for n in names}
        assert "pm_next" in {t.name for t in anyio.run(mcp_server.list_tools)}

    def test_the_docstring_explains_the_purpose_and_the_three_modes(self):
        from projectman.server import pm_next

        doc = pm_next.__doc__
        assert "no note saved" in doc
        for mode in ("read", "append", "clear"):
            assert mode in doc, mode

    def test_one_event_per_tool_mutation(self, server_project):
        from projectman.server import _store, pm_next

        pm_next()
        pm_next("one")
        pm_next("two", append=True)
        pm_next(clear=True)

        events = note_events(_store())
        assert [e["event_type"] for e in events] == ["update", "update", "delete"]


def test_the_note_is_documented_in_the_mcp_tool_reference():
    """`tests/test_docs_after_subtraction.py` enforces the heading; this says why."""
    from pathlib import Path

    doc = (
        Path(__file__).resolve().parents[1] / "docs" / "reference" / "mcp-tools.md"
    ).read_text(encoding="utf-8")
    assert "### pm_next(" in doc
    assert "NEXT.md" in doc


def test_os_replace_is_still_the_atomicity_mechanism():
    """The atomicity tests patch ``os.replace``; they are vacuous if it moved."""
    import inspect

    from projectman.store import _atomic_write_text

    assert "os.replace" in inspect.getsource(_atomic_write_text)
    assert os.replace is not None
