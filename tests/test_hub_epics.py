"""Epics are hub-level, and an ``epic_id`` link is checked before it is written.

US-PM-36's first two acceptance criteria, plus the single-project regression
that says none of it moved for an ordinary install:

* **In a hub ``pm_create_epic`` writes only to the hub store** — it takes no
  ``prefix`` at all, because there is no project to choose: an epic exists so
  that stories from *several* subprojects can hang off it.  A subproject's
  ``epics/`` directory never gains a file.
* **A subproject story can set ``epic_id`` to a hub epic**, at creation or
  later, and an ``epic_id`` that exists in neither the hub nor the story's own
  store is a coded ``not_found`` — the link used to be written unchecked, so a
  typo became a dangling reference the audit found much later.
* The audit agrees: check 9 (``orphaned-epic-reference``) run against a
  subproject is told the hub's epic IDs, so a correct upward link is not a
  warning — while a genuinely dangling one still is.
* **Single-project epic behaviour is unchanged**: create with no prefix, link,
  and the same ``not_found`` for an epic that does not exist.

Errors are asserted over the real ``tools/call`` handler wherever the *code* on
the wire is the point; the happy paths drive the Python entry points.
"""

import inspect

import anyio
import mcp.types as types
import pytest
import yaml

from projectman.store import Store, clear_all_caches

from conftest import make_hub_subproject

READY_BODY = (
    "## Implementation\n\nDo the thing properly.\n\n"
    "## Testing\n\nTest the thing properly.\n\n"
    "## Definition of Done\n\n- [ ] Done\n"
)


# ─── fixtures ────────────────────────────────────────────────────


def _reset_caches() -> None:
    from projectman.server import _store_cache

    clear_all_caches()
    _store_cache.clear()


def _on_disk(hub_root, name: str) -> Store:
    """A Store reading *name*'s directory straight from disk, uncached."""
    clear_all_caches()
    return Store(hub_root, project_dir=hub_root / "projects" / name / ".project")


def _epic_files(store_dir) -> list[str]:
    """The epic filenames in one store directory, or ``[]`` if it has none."""
    epics = store_dir / "epics"
    return sorted(p.name for p in epics.glob("*.md")) if epics.exists() else []


def _call_over_the_wire(name: str, arguments: dict) -> tuple[bool, str]:
    """Drive one real ``tools/call`` through the low-level request handler."""
    from projectman.server import mcp as mcp_server

    handler = mcp_server._mcp_server.request_handlers[types.CallToolRequest]

    async def run():
        request = types.CallToolRequest(
            method="tools/call",
            params=types.CallToolRequestParams(name=name, arguments=arguments),
        )
        result = (await handler(request)).root
        text = result.content[0].text if result.content else ""
        return bool(result.isError), text

    return anyio.run(run)


@pytest.fixture
def hub(tmp_hub, monkeypatch):
    """A hub (prefix HUB) with two attached subprojects, API and WEB.

    Each subproject owns one story, so every assertion about "the story's own
    store" has a real item on both sides of the boundary.  No git anywhere:
    epics are plain files and this criterion has nothing to do with worktrees.
    """
    from projectman.server import pm_create_story

    make_hub_subproject(tmp_hub, "api", "API")
    make_hub_subproject(tmp_hub, "web", "WEB")
    monkeypatch.chdir(tmp_hub)
    _reset_caches()
    pm_create_story("API story", "Story body text long enough to matter.", prefix="API")
    pm_create_story("WEB story", "Story body text long enough to matter.", prefix="WEB")
    yield tmp_hub
    _reset_caches()


@pytest.fixture
def single(tmp_project, monkeypatch):
    """An ordinary, non-hub project (prefix TST) as the working directory."""
    monkeypatch.chdir(tmp_project)
    _reset_caches()
    yield tmp_project
    _reset_caches()


# ═══ AC 1 — a hub epic is written to the hub store, and nowhere else ═══


class TestEpicsAreCreatedInTheHubStoreOnly:
    def test_pm_create_epic_writes_under_the_hub_s_own_project(self, hub):
        from projectman.server import pm_create_epic

        created = yaml.safe_load(
            pm_create_epic("Unified Auth", "Cross-service authentication")
        )["created"]

        assert created["id"] == "EPIC-HUB-1"
        assert _epic_files(hub / ".project") == ["EPIC-HUB-1.md"]

    def test_no_subproject_store_gains_an_epic_file(self, hub):
        from projectman.server import pm_create_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_create_epic("Observability", "One dashboard for everything")

        for name in ("api", "web"):
            assert _epic_files(hub / "projects" / name / ".project") == []
            assert _on_disk(hub, name).list_epics() == []

    def test_hub_epics_are_readable_through_pm_epic_by_their_id(self, hub):
        from projectman.server import pm_create_epic, pm_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")

        assert yaml.safe_load(pm_epic("EPIC-HUB-1"))["epic"]["title"] == "Unified Auth"

    def test_pm_create_epic_takes_no_prefix_parameter(self):
        """There is no store to choose, so the argument is gone entirely."""
        from projectman.server import pm_create_epic

        assert "prefix" not in inspect.signature(pm_create_epic).parameters

    def test_the_advertised_schema_has_no_prefix_property(self):
        from projectman.server import mcp as mcp_server

        tools = {tool.name: tool for tool in anyio.run(mcp_server.list_tools)}
        properties = tools["pm_create_epic"].inputSchema.get("properties", {})

        assert "prefix" not in properties
        assert "project" not in properties

    def test_a_stale_caller_that_still_sends_a_prefix_lands_in_the_hub(self, hub):
        """The rule is the hub store, not "whatever the caller last asked for".

        A ``prefix`` is no longer a parameter, so nothing consumes it — the
        epic is written to the hub with the hub's prefix regardless, and the
        named subproject gains nothing.  That is the documented rule rather
        than an error, because there is no project an epic could belong to.
        """
        is_error, text = _call_over_the_wire(
            "pm_create_epic",
            {"title": "An epic", "description": "Epic body text.", "prefix": "API"},
        )

        assert is_error is False, text
        assert yaml.safe_load(text)["created"]["id"] == "EPIC-HUB-1"
        assert _epic_files(hub / ".project") == ["EPIC-HUB-1.md"]
        assert _epic_files(hub / "projects" / "api" / ".project") == []


# ═══ AC 2 — an epic_id link is validated against the hub and own store ═══


class TestASubprojectStoryLinksToAHubEpic:
    def test_pm_update_links_a_subproject_story_up_to_a_hub_epic(self, hub):
        from projectman.server import pm_create_epic, pm_update

        pm_create_epic("Unified Auth", "Cross-service authentication")

        updated = yaml.safe_load(pm_update("US-API-1", epic_id="EPIC-HUB-1"))["updated"]

        assert updated["epic_id"] == "EPIC-HUB-1"
        assert _on_disk(hub, "api").get("US-API-1")[0].epic_id == "EPIC-HUB-1"

    def test_pm_create_story_links_to_a_hub_epic_at_creation(self, hub):
        from projectman.server import pm_create_epic, pm_create_story

        pm_create_epic("Unified Auth", "Cross-service authentication")

        created = yaml.safe_load(
            pm_create_story(
                "Linked from birth",
                "Story body text long enough to matter.",
                epic_id="EPIC-HUB-1",
                prefix="WEB",
            )
        )["created"]

        assert created["epic_id"] == "EPIC-HUB-1"
        assert _on_disk(hub, "web").get(created["id"])[0].epic_id == "EPIC-HUB-1"

    def test_stories_in_different_subprojects_share_one_hub_epic(self, hub):
        """The whole point: one epic, stories from several repos."""
        from projectman.server import pm_create_epic, pm_update

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_update("US-API-1", epic_id="EPIC-HUB-1")
        pm_update("US-WEB-1", epic_id="EPIC-HUB-1")

        assert _on_disk(hub, "api").get("US-API-1")[0].epic_id == "EPIC-HUB-1"
        assert _on_disk(hub, "web").get("US-WEB-1")[0].epic_id == "EPIC-HUB-1"

    def test_an_epic_in_the_story_s_own_store_is_still_a_valid_link(self, hub):
        """Legacy subproject-local epics keep working — this only *adds* the hub."""
        _on_disk(hub, "api").create_epic("Local epic", "Left over from before")
        _reset_caches()

        from projectman.server import pm_update

        updated = yaml.safe_load(pm_update("US-API-1", epic_id="EPIC-API-1"))["updated"]

        assert updated["epic_id"] == "EPIC-API-1"

    @pytest.mark.parametrize(
        "tool,arguments",
        [
            ("pm_update", {"id": "US-API-1", "epic_id": "EPIC-HUB-9"}),
            ("pm_update", {"id": "US-API-1", "epic_id": "EPIC-API-9"}),
            (
                "pm_create_story",
                {
                    "title": "Bad link",
                    "description": "Story body text long enough to matter.",
                    "epic_id": "EPIC-HUB-9",
                    "prefix": "API",
                },
            ),
        ],
    )
    def test_an_epic_in_neither_store_is_a_coded_not_found(self, hub, tool, arguments):
        is_error, text = _call_over_the_wire(tool, arguments)

        assert is_error is True, text
        assert "[code: not_found]" in text
        assert arguments["epic_id"] in text
        # The message says where it looked, in both legitimate places.
        assert "hub" in text.lower()

    def test_a_refused_link_leaves_the_story_untouched(self, hub):
        from projectman.server import pm_update

        pm_update("US-API-1", status="active")
        _call_over_the_wire("pm_update", {"id": "US-API-1", "epic_id": "EPIC-HUB-9"})

        meta, _ = _on_disk(hub, "api").get("US-API-1")
        assert meta.epic_id is None
        assert meta.status.value == "active"

    def test_a_refused_link_on_create_writes_no_story_at_all(self, hub):
        _call_over_the_wire(
            "pm_create_story",
            {
                "title": "Bad link",
                "description": "Story body text long enough to matter.",
                "epic_id": "EPIC-HUB-9",
                "prefix": "API",
            },
        )

        assert {s.id for s in _on_disk(hub, "api").list_stories()} == {"US-API-1"}

    def test_pm_update_many_validates_each_entry_s_epic_id_too(self, hub):
        """The bulk verb shares ``_do_update``; the check must not be bypassable."""
        from projectman.server import pm_create_epic, pm_update_many

        pm_create_epic("Unified Auth", "Cross-service authentication")

        result = yaml.safe_load(
            pm_update_many(
                updates=[
                    {"id": "US-API-1", "epic_id": "EPIC-HUB-1"},
                    {"id": "US-WEB-1", "epic_id": "EPIC-HUB-9"},
                ]
            )
        )

        assert [row["id"] for row in result["updated"]] == ["US-API-1"]
        assert [row["id"] for row in result["failed"]] == ["US-WEB-1"]
        assert "EPIC-HUB-9" in result["failed"][0]["error"]
        # And the good half really landed, per the no-rollback contract.
        assert _on_disk(hub, "api").get("US-API-1")[0].epic_id == "EPIC-HUB-1"
        assert _on_disk(hub, "web").get("US-WEB-1")[0].epic_id is None

    def test_clearing_an_epic_link_is_not_a_lookup(self, hub):
        """``clear`` removes the link; nothing is resolved, nothing raises."""
        from projectman.server import pm_create_epic, pm_get, pm_update

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_update("US-API-1", epic_id="EPIC-HUB-1")

        pm_update("US-API-1", clear=["epic_id"])

        assert yaml.safe_load(pm_get("US-API-1")).get("epic_id") in (None, "")


# ═══ AC 2, audit half — check 9 accepts a hub-prefixed epic_id ═══


class TestTheAuditAcceptsAnUpwardEpicLink:
    def test_a_hub_epic_is_not_an_orphaned_reference_on_a_subproject(self, hub):
        from projectman.server import pm_audit, pm_create_epic, pm_update

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_update("US-API-1", epic_id="EPIC-HUB-1")

        report = pm_audit(include_info=True, prefix="API")

        assert "references non-existent epic" not in report

    def test_a_genuinely_dangling_reference_is_still_reported(self, hub):
        """The suppression is narrow: only epics the hub really owns."""
        from projectman.server import pm_audit

        # Written straight to disk, since the tools now refuse to write it.
        _on_disk(hub, "api").update("US-API-1", epic_id="EPIC-API-9")
        _reset_caches()

        report = pm_audit(include_info=True, prefix="API")

        assert "references non-existent epic" in report
        assert "EPIC-API-9" in report

    def test_known_epic_ids_are_not_part_of_the_state_digest(self, hub):
        """It can only suppress a warning, so it must not perturb the digest."""
        from projectman.audit import run_audit

        project_dir = hub / "projects" / "api" / ".project"
        plain = run_audit(hub, project_dir=project_dir)
        with_known = run_audit(
            hub, project_dir=project_dir, known_epic_ids={"EPIC-HUB-1"}
        )

        def digest(report):
            return next(
                line for line in report.splitlines() if line.startswith("digest:")
            )

        assert digest(plain) == digest(with_known)


# ═══ AC 3 — single-project mode is unchanged ═══


class TestSingleProjectEpicBehaviourIsUnchanged:
    def test_create_and_link_still_work_with_no_prefix_anywhere(self, single):
        from projectman.server import pm_create_epic, pm_create_story, pm_update

        created = yaml.safe_load(pm_create_epic("Epic", "Epic description"))["created"]
        assert created["id"] == "EPIC-TST-1"
        assert _epic_files(single / ".project") == ["EPIC-TST-1.md"]

        pm_create_story("Story", "Story body text long enough to matter.")
        updated = yaml.safe_load(pm_update("US-TST-1", epic_id="EPIC-TST-1"))["updated"]
        assert updated["epic_id"] == "EPIC-TST-1"

        linked = yaml.safe_load(
            pm_create_story(
                "Linked story",
                "Story body text long enough to matter.",
                epic_id="EPIC-TST-1",
            )
        )["created"]
        assert linked["epic_id"] == "EPIC-TST-1"

    def test_pm_epic_rolls_up_the_linked_story_as_it_always_did(self, single):
        from projectman.server import pm_create_epic, pm_create_story, pm_epic

        pm_create_epic("Epic", "Epic description")
        pm_create_story(
            "Story", "Story body text long enough to matter.", epic_id="EPIC-TST-1"
        )

        rollup = yaml.safe_load(pm_epic("EPIC-TST-1"))

        assert [s["id"] for s in rollup["stories"]] == ["US-TST-1"]

    def test_an_epic_that_does_not_exist_is_the_same_coded_not_found(self, single):
        from projectman.server import pm_create_story

        pm_create_story("Story", "Story body text long enough to matter.")

        is_error, text = _call_over_the_wire(
            "pm_update", {"id": "US-TST-1", "epic_id": "EPIC-TST-9"}
        )

        assert is_error is True, text
        assert "[code: not_found]" in text
        assert "EPIC-TST-9" in text

    def test_the_audit_still_flags_an_orphan_with_no_hub_in_sight(self, single):
        from projectman.server import pm_audit, pm_create_story

        pm_create_story("Story", "Story body text long enough to matter.")
        Store(single).update("US-TST-1", epic_id="EPIC-TST-9")
        _reset_caches()

        report = pm_audit(include_info=True)

        assert "references non-existent epic" in report


# ═══ AC 4 — a hub epic rolls up every store's stories, grouped by project ═══


def _link(story_id: str, epic_id: str = "EPIC-HUB-1") -> None:
    from projectman.server import pm_update

    pm_update(story_id, epic_id=epic_id)


def _task(story_id: str, points: int, done: bool = False) -> str:
    """One task under *story_id*, optionally already delivered."""
    from projectman.server import pm_create_task, pm_update

    created = yaml.safe_load(
        pm_create_task(story_id, f"Task on {story_id}", READY_BODY, points=points)
    )["created"]
    if done:
        pm_update(created["id"], status="done")
    return created["id"]


@pytest.fixture
def rolled_up(hub):
    """One hub epic with three linked stories across two subprojects.

    API contributes 6 points (3 delivered) over two stories, WEB 5 points
    (all delivered) over one — so every total, every group and the split
    between them is distinguishable from every other.
    """
    from projectman.server import pm_create_epic, pm_create_story

    pm_create_epic("Unified Auth", "Cross-service authentication")
    pm_create_story(
        "Second API story", "Story body text long enough to matter.", prefix="API"
    )
    _link("US-API-1")
    _link("US-API-2")
    _link("US-WEB-1")
    _task("US-API-1", 3, done=True)
    _task("US-API-1", 2)
    _task("US-API-2", 1)
    _task("US-WEB-1", 5, done=True)
    return hub


class TestAHubEpicRollsUpEveryStore:
    def test_the_rollup_counts_stories_and_points_from_both_subprojects(
        self, rolled_up
    ):
        from projectman.server import pm_epic

        rollup = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]

        assert rollup["story_count"] == 3
        assert rollup["total_points"] == 11
        assert rollup["completed_points"] == 8
        assert rollup["completion"] == "73%"

    def test_by_project_breaks_the_same_numbers_down_per_store(self, rolled_up):
        from projectman.server import pm_epic

        rollup = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]

        assert rollup["by_project"] == [
            {
                "name": "api",
                "prefix": "API",
                "stories": 2,
                "total_points": 6,
                "completed_points": 3,
            },
            {
                "name": "web",
                "prefix": "WEB",
                "stories": 1,
                "total_points": 5,
                "completed_points": 5,
            },
        ]
        assert sum(p["total_points"] for p in rollup["by_project"]) == (
            rollup["total_points"]
        )

    def test_every_story_row_says_which_project_it_came_from(self, rolled_up):
        from projectman.server import pm_epic

        stories = yaml.safe_load(pm_epic("EPIC-HUB-1"))["stories"]

        assert [(s["id"], s["project"]) for s in stories] == [
            ("US-API-1", "api"),
            ("US-API-2", "api"),
            ("US-WEB-1", "web"),
        ]

    def test_a_story_in_the_hub_s_own_store_is_rolled_up_too(self, rolled_up):
        """The hub is a store in the map like any other, and comes first."""
        from projectman.server import pm_create_story, pm_epic

        pm_create_story(
            "Hub story",
            "Story body text long enough to matter.",
            epic_id="EPIC-HUB-1",
            prefix="HUB",
        )
        _task("US-HUB-1", 2)

        result = yaml.safe_load(pm_epic("EPIC-HUB-1"))

        assert result["stories"][0]["id"] == "US-HUB-1"
        assert result["stories"][0]["project"] == "test-hub"
        assert result["rollup"]["story_count"] == 4
        assert result["rollup"]["total_points"] == 13
        assert result["rollup"]["by_project"][0] == {
            "name": "test-hub",
            "prefix": "HUB",
            "stories": 1,
            "total_points": 2,
            "completed_points": 0,
        }

    def test_a_project_with_no_linked_story_is_not_a_group(self, hub):
        from projectman.server import pm_create_epic, pm_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")
        _link("US-WEB-1")

        rollup = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]

        assert [p["name"] for p in rollup["by_project"]] == ["web"]


class TestPaginationRunsAcrossProjects:
    def test_a_page_can_stop_in_the_middle_of_one_project(self, rolled_up):
        from projectman.server import pm_epic

        page = yaml.safe_load(pm_epic("EPIC-HUB-1", limit=1, offset=1))

        assert [s["id"] for s in page["stories"]] == ["US-API-2"]
        assert page["has_more"] is True
        assert page["next_offset"] == 2

    def test_the_next_page_continues_into_the_next_project(self, rolled_up):
        from projectman.server import pm_epic

        page = yaml.safe_load(pm_epic("EPIC-HUB-1", limit=2, offset=2))

        assert [(s["id"], s["project"]) for s in page["stories"]] == [
            ("US-WEB-1", "web")
        ]
        assert page["has_more"] is False
        assert "next_offset" not in page

    def test_the_rollup_is_the_whole_epic_on_every_page(self, rolled_up):
        """Paging is a window on the detail list, never on the totals."""
        from projectman.server import pm_epic

        whole = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]
        pages = [
            yaml.safe_load(pm_epic("EPIC-HUB-1", limit=2, offset=off))["rollup"]
            for off in (0, 2, 4)
        ]

        assert all(page == whole for page in pages)

    def test_walking_the_pages_visits_every_story_once(self, rolled_up):
        from projectman.server import pm_epic

        seen, offset = [], 0
        while True:
            page = yaml.safe_load(pm_epic("EPIC-HUB-1", limit=2, offset=offset))
            seen += [s["id"] for s in page["stories"]]
            if not page["has_more"]:
                break
            offset = page["next_offset"]

        assert seen == ["US-API-1", "US-API-2", "US-WEB-1"]


class TestAnUnattachedSubprojectIsNamedNotSkipped:
    def test_the_rollup_lists_it_by_name_with_the_attach_hint(self, rolled_up):
        from projectman.hub.stores import NOT_ATTACHED
        from projectman.server import pm_epic

        make_hub_subproject(rolled_up, "ops", "OPS", attached=False)
        _reset_caches()

        rollup = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]

        assert [row["name"] for row in rollup["not_attached"]] == ["ops"]
        assert rollup["not_attached"][0]["status"] == NOT_ATTACHED
        assert "add-project ops" in rollup["not_attached"][0]["hint"]

    def test_the_attached_stores_still_contribute_their_numbers(self, rolled_up):
        from projectman.server import pm_epic

        make_hub_subproject(rolled_up, "ops", "OPS", attached=False)
        _reset_caches()

        rollup = yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]

        assert rollup["story_count"] == 3
        assert rollup["total_points"] == 11
        assert [p["name"] for p in rollup["by_project"]] == ["api", "web"]

    def test_a_fully_attached_hub_carries_no_not_attached_key(self, rolled_up):
        from projectman.server import pm_epic

        assert "not_attached" not in yaml.safe_load(pm_epic("EPIC-HUB-1"))["rollup"]


class TestASubprojectEpicIsUnchanged:
    def test_a_legacy_subproject_epic_rolls_up_its_own_store_only(self, hub):
        """Its shape is the single-project one: no `project`, no `by_project`."""
        from projectman.server import pm_epic

        _on_disk(hub, "api").create_epic("Local epic", "Left over from before")
        _reset_caches()
        _link("US-API-1", "EPIC-API-1")
        _task("US-API-1", 3, done=True)

        result = yaml.safe_load(pm_epic("EPIC-API-1"))

        assert set(result["rollup"]) == {
            "story_count",
            "total_points",
            "completed_points",
            "completion",
        }
        assert result["rollup"]["story_count"] == 1
        assert result["rollup"]["completed_points"] == 3
        assert "project" not in result["stories"][0]


class TestSingleProjectEpicViewIsByteIdentical:
    """The whole payload, pinned key by key, for an ordinary install."""

    def test_the_payload_has_exactly_the_keys_it_always_had(self, single):
        from projectman.server import pm_create_epic, pm_create_story, pm_epic

        pm_create_epic("Epic", "Epic description")
        pm_create_story(
            "Story", "Story body text long enough to matter.", epic_id="EPIC-TST-1"
        )
        _task("US-TST-1", 3, done=True)
        _task("US-TST-1", 5)

        result = yaml.safe_load(pm_epic("EPIC-TST-1"))

        assert list(result) == [
            "epic",
            "body",
            "stories",
            "rollup",
            "limit",
            "offset",
            "has_more",
        ]
        assert result["limit"] == 10
        assert result["offset"] == 0
        assert result["has_more"] is False
        assert result["rollup"] == {
            "story_count": 1,
            "total_points": 8,
            "completed_points": 3,
            "completion": "38%",
        }
        assert result["stories"] == [
            {
                "id": "US-TST-1",
                "title": "Story",
                "status": "backlog",
                "points": None,
                "tasks": [
                    {
                        "id": "US-TST-1-1",
                        "title": "Task on US-TST-1",
                        "status": "done",
                        "points": 3,
                    },
                    {
                        "id": "US-TST-1-2",
                        "title": "Task on US-TST-1",
                        "status": "todo",
                        "points": 5,
                    },
                ],
                "task_points": 8,
                "done_points": 3,
            }
        ]

    def test_pagination_keys_are_unchanged_too(self, single):
        from projectman.server import pm_create_epic, pm_create_story, pm_epic

        pm_create_epic("Epic", "Epic description")
        for n in range(3):
            pm_create_story(
                f"Story {n}",
                "Story body text long enough to matter.",
                epic_id="EPIC-TST-1",
            )

        page = yaml.safe_load(pm_epic("EPIC-TST-1", limit=2, offset=0))

        assert [s["id"] for s in page["stories"]] == ["US-TST-1", "US-TST-2"]
        assert page["has_more"] is True
        assert page["next_offset"] == 2
        assert all("project" not in s for s in page["stories"])


# ═══ Epics are counted once — rollup, pm_status and the dashboards ═══


class TestEpicsAreCountedOnce:
    def test_the_hub_rollup_adds_the_hub_s_own_epics_to_the_total(self, hub):
        from projectman.hub.rollup import rollup
        from projectman.server import pm_create_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_create_epic("Observability", "One dashboard for everything")

        data = rollup(hub)

        assert data["hub_epics"] == 2
        assert data["total_epics"] == 2
        assert [p.get("epics") for p in data["projects"]] == [0, 0]

    def test_a_not_yet_migrated_subproject_epic_still_counts(self, hub):
        """Hub epics plus subproject epics — the sum holds mid-migration."""
        from projectman.hub.rollup import rollup
        from projectman.server import pm_create_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")
        _on_disk(hub, "api").create_epic("Local epic", "Left over from before")
        _reset_caches()

        data = rollup(hub)

        assert data["hub_epics"] == 1
        assert data["total_epics"] == 2
        assert [p.get("epics") for p in data["projects"]] == [1, 0]

    def test_pm_status_with_no_prefix_reports_the_hub_s_own_epics_once(self, hub):
        from projectman.server import pm_create_epic, pm_status

        pm_create_epic("Unified Auth", "Cross-service authentication")
        pm_create_epic("Observability", "One dashboard for everything")

        status = yaml.safe_load(pm_status())

        assert status["project"] == "test-hub"
        assert status["epics"] == 2

    def test_the_status_dashboard_does_not_double_count_the_hub_s_epics(self, hub):
        from projectman.hub.dashboards import generate_dashboards
        from projectman.server import pm_create_epic

        pm_create_epic("Unified Auth", "Cross-service authentication")
        _on_disk(hub, "api").create_epic("Local epic", "Left over from before")
        _reset_caches()

        generate_dashboards(hub)
        text = (hub / ".project" / "dashboards" / "status.md").read_text()

        assert "**Total Epics:** 2" in text
        # The per-project column is that project's own epics, never the hub's.
        rows = [ln for ln in text.splitlines() if ln.startswith("| api |")]
        assert rows and all(ln.split("|")[2].strip() == "1" for ln in rows)
        assert not [ln for ln in text.splitlines() if ln.startswith("| test-hub |")]
