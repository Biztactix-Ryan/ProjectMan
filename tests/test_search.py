"""Direct unit tests for projectman.search.keyword_search.

These exercise the module itself rather than the pm_search MCP tool, so the
scoring rule, the snippet window, the tag filter and the id fallback are all
pinned independently of the server layer.

Note: ``keyword_search`` lowercases ``"{title} {content}"`` before matching, so
snippets always come back lower-cased.
"""

import frontmatter
import pytest

from projectman.search import SearchResult, keyword_search


def write_item(project_dir, subdir, stem, content="", **meta):
    """Write one frontmatter markdown file into ``project_dir/subdir``."""
    d = project_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    path = d / f"{stem}.md"
    path.write_text(frontmatter.dumps(frontmatter.Post(content, **meta)), encoding="utf-8")
    return path


@pytest.fixture
def project_dir(tmp_path):
    """A .project/ directory with the three searched subdirectories."""
    proj = tmp_path / ".project"
    for sub in ("epics", "stories", "tasks"):
        (proj / sub).mkdir(parents=True)
    return proj


class TestScoring:
    def test_title_match_scores_one(self, project_dir):
        write_item(project_dir, "stories", "US-T-1", "unrelated body text",
                   id="US-T-1", title="Auth System")

        results = keyword_search("auth", project_dir)

        assert len(results) == 1
        assert isinstance(results[0], SearchResult)
        assert results[0].id == "US-T-1"
        assert results[0].title == "Auth System"
        assert results[0].type == "story"
        assert results[0].score == 1.0

    def test_content_only_match_scores_half(self, project_dir):
        write_item(project_dir, "stories", "US-T-2", "the auth flow lives here",
                   id="US-T-2", title="Widget Rendering")

        results = keyword_search("auth", project_dir)

        assert len(results) == 1
        assert results[0].id == "US-T-2"
        assert results[0].score == 0.5

    def test_results_sorted_by_score_descending(self, project_dir):
        write_item(project_dir, "stories", "US-T-3", "mentions auth in the body",
                   id="US-T-3", title="Body Only")
        write_item(project_dir, "stories", "US-T-4", "no mention in the body",
                   id="US-T-4", title="Auth In Title")

        results = keyword_search("auth", project_dir)

        assert [r.id for r in results] == ["US-T-4", "US-T-3"]
        assert [r.score for r in results] == [1.0, 0.5]

    def test_type_reflects_subdirectory(self, project_dir):
        write_item(project_dir, "epics", "EPIC-T-1", "", id="EPIC-T-1", title="Auth Epic")
        write_item(project_dir, "stories", "US-T-5", "", id="US-T-5", title="Auth Story")
        write_item(project_dir, "tasks", "US-T-5-1", "", id="US-T-5-1", title="Auth Task")

        results = keyword_search("auth", project_dir)

        assert {r.id: r.type for r in results} == {
            "EPIC-T-1": "epic",
            "US-T-5": "story",
            "US-T-5-1": "task",
        }


class TestSnippet:
    def test_match_at_start_of_content(self, project_dir):
        write_item(project_dir, "stories", "US-S-1", "needle " + "x" * 300,
                   id="US-S-1", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert "needle" in result.snippet
        assert len(result.snippet) <= len("needle") + 100
        assert result.snippet.startswith("zulu needle")

    def test_match_in_middle_of_content(self, project_dir):
        write_item(project_dir, "stories", "US-S-2", "y" * 300 + " needle " + "z" * 300,
                   id="US-S-2", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert "needle" in result.snippet
        assert len(result.snippet) <= len("needle") + 100
        assert result.snippet.startswith("y")
        assert result.snippet.endswith("z")

    def test_match_at_end_of_content(self, project_dir):
        write_item(project_dir, "stories", "US-S-3", "z" * 300 + " needle",
                   id="US-S-3", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert result.snippet.endswith("needle")
        assert len(result.snippet) <= len("needle") + 100

    def test_content_shorter_than_window(self, project_dir):
        write_item(project_dir, "stories", "US-S-4", "tiny needle", id="US-S-4", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert result.snippet == "zulu tiny needle"
        assert len(result.snippet) <= len("needle") + 100

    def test_content_much_longer_than_window_is_clamped(self, project_dir):
        write_item(project_dir, "stories", "US-S-5", "q" * 5000 + " needle " + "r" * 5000,
                   id="US-S-5", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert "needle" in result.snippet
        assert len(result.snippet) <= len("needle") + 100

    def test_multiword_query_snippet_bound(self, project_dir):
        query = "deployment pipeline"
        write_item(project_dir, "stories", "US-S-6", "a" * 400 + f" {query} " + "b" * 400,
                   id="US-S-6", title="Zulu")

        (result,) = keyword_search(query, project_dir)

        assert query in result.snippet
        assert len(result.snippet) <= len(query) + 100

    def test_snippet_is_lowercased(self, project_dir):
        write_item(project_dir, "stories", "US-S-7", "The NEEDLE Is Here",
                   id="US-S-7", title="Zulu")

        (result,) = keyword_search("needle", project_dir)

        assert result.snippet == "zulu the needle is here"


class TestMatchingBehaviour:
    def test_uppercase_query_matches_lowercase_content(self, project_dir):
        write_item(project_dir, "stories", "US-M-1", "kubernetes deployment notes",
                   id="US-M-1", title="Infra")

        (result,) = keyword_search("KUBERNETES", project_dir)

        assert result.id == "US-M-1"
        assert result.score == 0.5
        assert "kubernetes" in result.snippet

    def test_lowercase_query_matches_uppercase_title(self, project_dir):
        write_item(project_dir, "stories", "US-M-2", "body", id="US-M-2", title="AUTH SYSTEM")

        (result,) = keyword_search("auth", project_dir)

        assert result.score == 1.0

    def test_no_match_returns_empty_list(self, project_dir):
        write_item(project_dir, "stories", "US-M-3", "nothing relevant here",
                   id="US-M-3", title="Widget")

        assert keyword_search("zzzznotfound", project_dir) == []

    def test_empty_project_returns_empty_list(self, project_dir):
        assert keyword_search("anything", project_dir) == []

    def test_top_k_truncates(self, project_dir):
        for n in range(5):
            write_item(project_dir, "stories", f"US-M-{n}", "auth mentioned",
                       id=f"US-M-{n}", title=f"Story {n}")

        assert len(keyword_search("auth", project_dir)) == 5
        assert len(keyword_search("auth", project_dir, top_k=2)) == 2

    def test_top_k_keeps_highest_scores(self, project_dir):
        for n in range(4):
            write_item(project_dir, "stories", f"US-K-{n}", "auth mentioned",
                       id=f"US-K-{n}", title=f"Story {n}")
        write_item(project_dir, "stories", "US-K-top", "body", id="US-K-top", title="Auth Title")

        results = keyword_search("auth", project_dir, top_k=1)

        assert [r.id for r in results] == ["US-K-top"]


class TestTagFilter:
    def test_tag_filter_keeps_tagged_and_drops_untagged(self, project_dir):
        write_item(project_dir, "stories", "US-G-1", "auth work",
                   id="US-G-1", title="Tagged", tags=["security"])
        write_item(project_dir, "stories", "US-G-2", "auth work", id="US-G-2", title="Untagged")

        results = keyword_search("auth", project_dir, tag="security")

        assert [r.id for r in results] == ["US-G-1"]

    def test_null_tags_field_is_handled(self, project_dir):
        write_item(project_dir, "stories", "US-G-3", "auth work",
                   id="US-G-3", title="Null Tags", tags=None)
        write_item(project_dir, "stories", "US-G-4", "auth work",
                   id="US-G-4", title="Tagged", tags=["security"])

        results = keyword_search("auth", project_dir, tag="security")

        assert [r.id for r in results] == ["US-G-4"]

    def test_null_tags_field_still_searchable_without_filter(self, project_dir):
        write_item(project_dir, "stories", "US-G-5", "auth work",
                   id="US-G-5", title="Null Tags", tags=None)

        (result,) = keyword_search("auth", project_dir)

        assert result.id == "US-G-5"

    def test_non_matching_tag_returns_empty_list(self, project_dir):
        write_item(project_dir, "stories", "US-G-6", "auth work",
                   id="US-G-6", title="Tagged", tags=["security"])

        assert keyword_search("auth", project_dir, tag="perf") == []


class TestEdgeCases:
    def test_missing_subdirectory_is_skipped(self, tmp_path):
        proj = tmp_path / ".project"
        write_item(proj, "stories", "US-E-1", "auth work", id="US-E-1", title="Story")
        assert not (proj / "epics").exists()

        (result,) = keyword_search("auth", proj)

        assert result.id == "US-E-1"
        assert result.type == "story"

    def test_all_subdirectories_missing_returns_empty_list(self, tmp_path):
        proj = tmp_path / ".project"
        proj.mkdir()

        assert keyword_search("auth", proj) == []

    def test_id_falls_back_to_file_stem(self, project_dir):
        write_item(project_dir, "stories", "US-E-2", "auth work", title="No Id In Frontmatter")

        (result,) = keyword_search("auth", project_dir)

        assert result.id == "US-E-2"

    def test_missing_title_defaults_to_empty_string(self, project_dir):
        write_item(project_dir, "stories", "US-E-3", "auth work", id="US-E-3")

        (result,) = keyword_search("auth", project_dir)

        assert result.title == ""
        assert result.score == 0.5

    def test_non_markdown_files_are_ignored(self, project_dir):
        (project_dir / "stories" / "notes.txt").write_text("auth work", encoding="utf-8")

        assert keyword_search("auth", project_dir) == []
