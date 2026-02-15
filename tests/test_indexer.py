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


def test_non_hub_does_not_write_root_readme(store):
    write_index(store)
    assert not (store.root / "README.md").exists()
