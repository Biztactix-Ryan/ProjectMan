"""The next-session note, surfaced once and ignored everywhere else (US-PM-28-6).

Two criteria are under test here, and they pull in opposite directions:

* *pm_context returns the note under ``next_time`` when it exists and omits the
  key when it does not* — the note has to be impossible to miss at session
  start, which means first in the payload and never truncated;
* *NEXT.md is ignored by the indexer and the audit and pm_search* — and
  everywhere else that walks ``.project/``.  ``NEXT.md`` carries no
  frontmatter and no id, so any enumerator that mistakes it for an item would
  report it as malformed, index it, or return it as a search hit.  Each
  enumerator gets its own test rather than an assumption, because "it happens
  to skip it today" and "it is written to skip it" fail differently later.

The note text carries a deliberately unique word (``zarquon``) so a search hit
can only have come from the note and not from fixture boilerplate.

Everything runs against ``tmp_project`` — never the real ``.project/`` this
repository keeps its own backlog in.
"""

import pytest
import yaml

from projectman.store import Store, _cache

NOTE = "we decided to fix zarquon by doing Y and Z"


@pytest.fixture
def store(tmp_project):
    return Store(tmp_project)


@pytest.fixture
def server_project(tmp_project, monkeypatch):
    """Point the MCP tools at *tmp_project*, never at the repo's own project.

    ``PROJECTMAN_ROOT`` wins over cwd in ``find_project_root``, so it is
    dropped here: left set from the ambient environment, these tools would
    read and write a real project.  The assert is a guard rail, not
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


def write_note(project_root, text=NOTE) -> None:
    """Put a note on disk the way ``Store.write_next`` does."""
    Store(project_root).write_next(text)


# ===========================================================================
# pm_context surfaces it — first, whole, and only when there is one.
# ===========================================================================


class TestContextSurfacesTheNote:
    def test_note_comes_back_under_next_time(self, server_project):
        from projectman.server import pm_context

        write_note(server_project)
        assert yaml.safe_load(pm_context())["next_time"] == NOTE

    def test_next_time_is_the_first_key(self, server_project):
        """Ordering is the feature: a note below 4 KB of PROJECT.md is missed."""
        from projectman.server import pm_context

        write_note(server_project)
        assert next(iter(yaml.safe_load(pm_context()))) == "next_time"

    def test_next_time_is_the_first_line_of_the_rendered_yaml(self, server_project):
        """The reader sees text, not a dict — check the bytes, not just order."""
        from projectman.server import pm_context

        write_note(server_project)
        assert pm_context().startswith("next_time:")

    def test_absent_note_omits_the_key_entirely(self, server_project):
        """Not ``next_time: null`` — an empty value reads as "nothing to say"."""
        from projectman.server import pm_context

        assert "next_time" not in yaml.safe_load(pm_context())

    def test_blank_note_file_omits_the_key(self, server_project):
        """A note emptied by hand is the same answer as no note at all."""
        from projectman.server import pm_context

        (server_project / ".project" / "NEXT.md").write_text("\n   \n\n")
        assert "next_time" not in yaml.safe_load(pm_context())

    def test_cleared_note_omits_the_key_again(self, server_project):
        from projectman.server import pm_context

        write_note(server_project)
        Store(server_project).clear_next()
        assert "next_time" not in yaml.safe_load(pm_context())

    def test_the_note_is_not_truncated_with_the_docs(self, server_project):
        """max_doc_chars governs documents; the note is short by design."""
        from projectman.server import pm_context

        long_note = "zarquon " * 200
        write_note(server_project, long_note)
        assert yaml.safe_load(pm_context(max_doc_chars=10))["next_time"] == (
            long_note.strip()
        )

    def test_the_rest_of_the_context_still_comes_back(self, server_project):
        """Prepending must add a key, not replace the payload."""
        from projectman.server import pm_context

        write_note(server_project)
        result = yaml.safe_load(pm_context())
        assert "project" in result["project_docs"]
        assert result["active_stories_total"] == 0

    def test_the_docstring_mentions_it(self):
        """A tool nobody knows returns the note is a tool nobody reads."""
        from projectman.server import pm_context

        assert "next_time" in (pm_context.__doc__ or "")


# ===========================================================================
# The audit does not see a frontmatter-less file as a broken item.
# ===========================================================================


class TestAuditIgnoresTheNote:
    def test_a_project_with_a_note_still_audits_clean(self, tmp_project):
        from projectman.audit import run_audit

        write_note(tmp_project)
        assert "No issues found" in run_audit(tmp_project)

    def test_no_finding_names_the_note(self, tmp_project):
        from projectman.audit import run_audit

        write_note(tmp_project)
        report = run_audit(tmp_project)
        assert "NEXT.md" not in report
        assert "zarquon" not in report

    def test_the_tool_reports_nothing_about_it_either(self, server_project):
        from projectman.server import pm_audit

        write_note(server_project)
        report = pm_audit(include_info=True)
        assert "NEXT.md" not in report
        assert "zarquon" not in report

    def test_no_stale_documentation_finding_for_an_old_note(self, tmp_project):
        """Doc staleness covers the three named docs, not arbitrary markdown."""
        import os
        import time

        from projectman.audit import run_audit

        write_note(tmp_project)
        note_path = tmp_project / ".project" / "NEXT.md"
        year_ago = time.time() - 400 * 86400
        os.utime(note_path, (year_ago, year_ago))
        assert "NEXT.md" not in run_audit(tmp_project)

    def test_the_notes_bytes_do_not_enter_the_state_digest(self, tmp_project):
        """The audit reads no byte of it, so it is not audit input.

        The file is written directly rather than through ``write_next`` so
        only ``NEXT.md`` changes: the store's activity-log event is a real
        change to a real audit input and rightly moves the digest.
        Otherwise a note would cost a full re-audit on the next poll, for a
        file no check consults.
        """
        from projectman.audit import compute_state_digest

        note_path = tmp_project / ".project" / "NEXT.md"
        before = compute_state_digest(tmp_project)
        note_path.write_text(NOTE + "\n")
        after_write = compute_state_digest(tmp_project)
        note_path.write_text("an entirely different plan\n")
        after_rewrite = compute_state_digest(tmp_project)
        assert before == after_write == after_rewrite


# ===========================================================================
# Malformed-file quarantine never claims it.
# ===========================================================================


class TestMalformedIgnoresTheNote:
    def test_pm_malformed_does_not_list_it(self, server_project):
        from projectman.server import pm_malformed

        write_note(server_project)
        assert pm_malformed() == "no malformed files"

    def test_listing_items_does_not_pick_it_up(self, store):
        """It sits beside PROJECT.md, not in stories/ or tasks/."""
        write_note(store.root)
        assert store.list_stories() == []
        assert store.list_tasks() == []
        assert store.list_epics() == []


# ===========================================================================
# Search — keyword and tool level.
# ===========================================================================


class TestSearchIgnoresTheNote:
    def test_keyword_search_returns_nothing_from_it(self, tmp_project):
        from projectman.search import keyword_search

        write_note(tmp_project)
        assert keyword_search("zarquon", tmp_project / ".project") == []

    def test_pm_search_returns_nothing_from_it(self, server_project):
        from projectman.server import pm_search

        write_note(server_project)
        assert not yaml.safe_load(pm_search("zarquon"))

    def test_real_items_are_still_found_alongside_a_note(self, server_project):
        """Guard against passing by breaking search altogether."""
        from projectman.server import pm_search

        write_note(server_project)
        Store(server_project).create_story("Findable story", "about zarquon too")
        hits = yaml.safe_load(pm_search("zarquon"))
        assert [h["type"] for h in hits] == ["story"]


# ===========================================================================
# The indexer writes items, not scratch text.
# ===========================================================================


class TestIndexerIgnoresTheNote:
    def test_index_yaml_has_no_trace_of_it(self, store):
        from projectman.indexer import write_index

        write_note(store.root)
        store.create_story("A story", "A description long enough to pass")
        write_index(store)
        text = (store.project_dir / "index.yaml").read_text()
        assert "NEXT" not in text
        assert "zarquon" not in text

    def test_no_markdown_index_lists_it(self, store):
        from projectman.indexer import write_index

        write_note(store.root)
        store.create_story("A story", "A description long enough to pass")
        write_index(store)
        for name in ("INDEX.md", "INDEX-EPICS.md", "INDEX-STORIES.md", "INDEX-TASKS.md"):
            text = (store.project_dir / name).read_text()
            assert "NEXT.md" not in text, f"{name} lists the note"
            assert "zarquon" not in text, f"{name} lists the note"

    def test_indexing_leaves_the_note_on_disk(self, store):
        """Ignoring it must mean ignoring, not tidying it away."""
        from projectman.indexer import write_index

        write_note(store.root)
        write_index(store)
        assert store.read_next() == NOTE


# ===========================================================================
# Documents: pm_docs lists a fixed set, and the note is not in it.
# ===========================================================================


class TestDocsIgnoreTheNote:
    def test_the_summary_does_not_list_it(self, server_project):
        from projectman.server import pm_docs

        write_note(server_project)
        summary = yaml.safe_load(pm_docs())
        assert "next" not in summary
        assert all(entry["file"] != "NEXT.md" for entry in summary.values())

    def test_it_is_not_addressable_as_a_doc(self, server_project):
        """pm_docs serves six named documents; the note is not one of them."""
        from mcp.server.fastmcp.exceptions import ToolError
        from projectman.server import pm_docs

        write_note(server_project)
        with pytest.raises(ToolError, match="unknown doc"):
            pm_docs(doc="next")
