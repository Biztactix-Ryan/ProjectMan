"""Tests for index generation."""

import pytest

from projectman.indexer import build_index, write_index
from projectman.store import Store


@pytest.fixture
def hub_store(tmp_hub):
    """Store backed by a hub project."""
    return Store(tmp_hub)


def test_build_empty_index(store):
    index = build_index(store)
    assert index.story_count == 0
    assert index.task_count == 0
    assert index.total_points == 0


def test_build_index_with_stories(store):
    store.create_story("Story 1", "Desc", points=3)
    store.create_story("Story 2", "Desc", points=5)
    index = build_index(store)
    assert index.story_count == 2
    assert index.total_points == 8


def test_build_index_with_tasks(store):
    store.create_story("Story", "Desc", points=5)
    store.create_task("US-TST-1", "Task 1", "Desc", points=2)
    store.create_task("US-TST-1", "Task 2", "Desc", points=3)
    index = build_index(store)
    assert index.task_count == 2
    assert index.total_points == 10  # 5 + 2 + 3


def test_completed_points(store):
    store.create_story("Story", "Desc", points=5)
    store.update("US-TST-1", status="done")
    index = build_index(store)
    assert index.completed_points == 5


def test_write_index(store):
    store.create_story("Story", "Desc", points=3)
    write_index(store)
    index_path = store.project_dir / "index.yaml"
    assert index_path.exists()


# --- Markdown index tests ---


def test_write_index_generates_all_markdown_files(store):
    store.create_story("Story", "Desc", points=3)
    write_index(store)
    for name in ("INDEX.md", "INDEX-EPICS.md", "INDEX-STORIES.md", "INDEX-TASKS.md"):
        assert (store.project_dir / name).exists(), f"{name} not generated"


def test_empty_project_markdown_indexes(store):
    write_index(store)
    epics_md = (store.project_dir / "INDEX-EPICS.md").read_text()
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    tasks_md = (store.project_dir / "INDEX-TASKS.md").read_text()
    assert "_No epics yet._" in epics_md
    assert "_No stories yet._" in stories_md
    assert "_No tasks yet._" in tasks_md


def test_epic_row_in_markdown(store):
    store.create_epic("Auth Epic", "Authentication epic")
    write_index(store)
    epics_md = (store.project_dir / "INDEX-EPICS.md").read_text()
    assert "[EPIC-TST-1](epics/EPIC-TST-1.md)" in epics_md
    assert "Auth Epic" in epics_md


def test_story_row_in_markdown(store):
    store.create_story("Login Flow", "Desc", points=5)
    write_index(store)
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    assert "[US-TST-1](stories/US-TST-1.md)" in stories_md
    assert "Login Flow" in stories_md


def test_task_row_in_markdown(store):
    store.create_story("Story", "Desc", points=3)
    store.create_task("US-TST-1", "Write tests", "Desc", points=2)
    write_index(store)
    tasks_md = (store.project_dir / "INDEX-TASKS.md").read_text()
    assert "[US-TST-1-1](tasks/US-TST-1-1.md)" in tasks_md
    assert "Write tests" in tasks_md
    assert "[US-TST-1](stories/US-TST-1.md)" in tasks_md


def test_story_with_epic_link_in_markdown(store):
    store.create_epic("Epic", "Desc")
    store.create_story("Linked Story", "Desc", points=3)
    store.update("US-TST-1", epic_id="EPIC-TST-1")
    write_index(store)
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    assert "[EPIC-TST-1](epics/EPIC-TST-1.md)" in stories_md


def test_index_md_has_counts_and_links(store):
    store.create_epic("Epic", "Desc")
    store.create_story("Story", "Desc", points=3)
    store.create_task("US-TST-1", "Task", "Desc")
    write_index(store)
    index_md = (store.project_dir / "INDEX.md").read_text()
    assert "| Epics | 1 |" in index_md
    assert "| Stories | 1 |" in index_md
    assert "| Tasks | 1 |" in index_md
    assert "[Epics](INDEX-EPICS.md)" in index_md
    assert "[Stories](INDEX-STORIES.md)" in index_md
    assert "[Tasks](INDEX-TASKS.md)" in index_md


def test_story_ac_and_task_counts_in_markdown(store):
    store.create_story(
        "Story",
        "Desc",
        points=5,
        acceptance_criteria=["AC1", "AC2"],
    )
    # acceptance_criteria auto-creates 2 test tasks, add one more
    store.create_task("US-TST-1", "Manual task", "Desc")
    write_index(store)
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    # Find the row for US-TST-1
    for line in stories_md.splitlines():
        if "US-TST-1" in line and "stories/" in line:
            assert "| 2 |" in line  # 2 ACs
            assert "| 3 |" in line  # 3 tasks (2 auto + 1 manual)
            break
    else:
        raise AssertionError("US-TST-1 row not found")


def test_hub_writes_readme_at_root(hub_store):
    write_index(hub_store)
    readme = (hub_store.root / "README.md").read_text()
    assert "# test-hub" in readme
    # Links should point into .project/
    assert "[Epics](.project/INDEX-EPICS.md)" in readme
    assert "[Stories](.project/INDEX-STORIES.md)" in readme
    assert "[Tasks](.project/INDEX-TASKS.md)" in readme


def test_epic_tags_column_in_markdown(store):
    store.create_epic("Tagged Epic", "Desc", tags=["security", "mvp"])
    store.create_epic("No Tags", "Desc")
    write_index(store)
    epics_md = (store.project_dir / "INDEX-EPICS.md").read_text()
    # Header row includes Tags column
    assert "| Tags |" in epics_md
    # Tagged epic renders comma-separated tags
    for line in epics_md.splitlines():
        if "Tagged Epic" in line:
            assert "security, mvp" in line
            break
    else:
        raise AssertionError("Tagged Epic row not found")
    # Untagged epic has an empty tags cell (no crash)
    for line in epics_md.splitlines():
        if "No Tags" in line:
            # Should not contain any tag text — just empty between pipes
            assert "security" not in line
            break
    else:
        raise AssertionError("No Tags row not found")


def test_story_tags_column_in_markdown(store):
    store.create_story("Tagged Story", "Desc", tags=["backend", "api"])
    store.create_story("No Tags", "Desc")
    write_index(store)
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    # Header row includes Tags column
    assert "| Tags |" in stories_md
    # Tagged story renders comma-separated tags
    for line in stories_md.splitlines():
        if "Tagged Story" in line:
            assert "backend, api" in line
            break
    else:
        raise AssertionError("Tagged Story row not found")
    # Untagged story has an empty tags cell (no crash)
    for line in stories_md.splitlines():
        if "No Tags" in line:
            assert "backend" not in line
            break
    else:
        raise AssertionError("No Tags row not found")


def test_task_tags_column_in_markdown(store):
    story, _ = store.create_story("Parent Story", "Desc")
    store.create_task(story.id, "Tagged Task", "Desc", tags=["infra", "ci"])
    store.create_task(story.id, "No Tags", "Desc")
    write_index(store)
    tasks_md = (store.project_dir / "INDEX-TASKS.md").read_text()
    # Header row includes Tags column
    assert "| Tags |" in tasks_md
    # Tagged task renders comma-separated tags
    for line in tasks_md.splitlines():
        if "Tagged Task" in line:
            assert "infra, ci" in line
            break
    else:
        raise AssertionError("Tagged Task row not found")
    # Untagged task has an empty tags cell (no crash)
    for line in tasks_md.splitlines():
        if "No Tags" in line:
            assert "infra" not in line
            break
    else:
        raise AssertionError("No Tags row not found")


def test_tags_comma_separated_in_all_indexes(store):
    """Tags with multiple values are rendered as comma-separated in all index tables."""
    store.create_epic("Multi Tag Epic", "Desc", tags=["alpha", "beta", "gamma"])
    store.create_epic("Single Tag Epic", "Desc", tags=["solo"])
    story, _ = store.create_story("Multi Tag Story", "Desc", tags=["x", "y", "z"])
    store.create_story("Single Tag Story", "Desc", tags=["only"])
    store.create_task(story.id, "Multi Tag Task", "Desc", tags=["a", "b", "c"])
    store.create_task(story.id, "Single Tag Task", "Desc", tags=["one"])
    write_index(store)

    epics_md = (store.project_dir / "INDEX-EPICS.md").read_text()
    stories_md = (store.project_dir / "INDEX-STORIES.md").read_text()
    tasks_md = (store.project_dir / "INDEX-TASKS.md").read_text()

    # Multiple tags are comma-separated
    for line in epics_md.splitlines():
        if "Multi Tag Epic" in line:
            assert "alpha, beta, gamma" in line
            break
    else:
        raise AssertionError("Multi Tag Epic row not found")

    for line in stories_md.splitlines():
        if "Multi Tag Story" in line:
            assert "x, y, z" in line
            break
    else:
        raise AssertionError("Multi Tag Story row not found")

    for line in tasks_md.splitlines():
        if "Multi Tag Task" in line:
            assert "a, b, c" in line
            break
    else:
        raise AssertionError("Multi Tag Task row not found")

    # Single tag renders without a comma
    for line in epics_md.splitlines():
        if "Single Tag Epic" in line:
            assert "solo" in line
            assert "," not in line.split("solo")[0].rsplit("|", 1)[-1]
            break
    else:
        raise AssertionError("Single Tag Epic row not found")

    for line in stories_md.splitlines():
        if "Single Tag Story" in line:
            assert "only" in line
            break
    else:
        raise AssertionError("Single Tag Story row not found")

    for line in tasks_md.splitlines():
        if "Single Tag Task" in line:
            assert "one" in line
            break
    else:
        raise AssertionError("Single Tag Task row not found")


def test_task_depends_on_column_in_markdown(store):
    """INDEX-TASKS.md includes a Depends On column showing task dependencies."""
    story, _ = store.create_story("Parent Story", "Desc")
    task_a = store.create_task(story.id, "Task A", "Desc")
    store.create_task(story.id, "Task B", "Desc", depends_on=[task_a.id])
    write_index(store)
    tasks_md = (store.project_dir / "INDEX-TASKS.md").read_text()
    # Header includes the Depends On column
    assert "| Depends On |" in tasks_md
    # Parse rows by splitting on '|'
    # Columns: empty | ID | Title | Status | Points | Tags | Assignee | Depends On | Story | empty
    for line in tasks_md.splitlines():
        cells = [c.strip() for c in line.split("|")]
        if "Task A" in line:
            # Depends On column (index 7) should be "—" for no deps
            assert cells[7] == "—"
        if "Task B" in line:
            # Depends On column should contain task_a's ID
            assert task_a.id in cells[7]


def test_non_hub_does_not_write_root_readme(store):
    write_index(store)
    assert not (store.root / "README.md").exists()
