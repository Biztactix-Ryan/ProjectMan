"""No create path may write over a file that is already on disk (US-PM-24).

Criterion under verification:

    Every create path raises instead of overwriting when the target file
    already exists.

``tests/test_store.py::TestCreateRefusesAnExistingTarget`` and
``tests/test_server.py::TestCreateCollisionIsAnErrorNotACrash`` cover the
individual methods US-PM-24-7 touched.  This module is the *criterion-level*
proof, and it is deliberately built so that it cannot quietly go out of date:

* every ``Store.create_*`` method is driven from one parametrised table, and
  :class:`TestTheEnumerationIsComplete` reflects over ``Store`` and fails if a
  future ``create_*`` method is not in that table;
* the same table shape is repeated at the MCP tool layer, both by calling the
  tool function and by going through the real ``tools/call`` handler, so a
  refusal that crashed the transport instead of returning ``isError`` would be
  caught;
* the refusal is asserted three ways — the exception, the bytes on disk, and
  the two side effects a create would otherwise leave behind (an
  ``activity.jsonl`` event and an in-memory cache entry for the ID).

Collisions are forced by stubbing the ID allocator.  Since US-PM-24-5/-6 the
allocators reconcile with disk, so they will not hand out a taken number on
their own; the stub stands in for the case they cannot cover — another process
writing the file between our allocation and our write.  What is under test is
the consequence, not the allocator.

Two paths that write a *new* item file live outside ``Store.create_*`` —
``pm_fix_malformed`` and ``pm_restore``, which lift a file out of the
quarantine into ``stories/`` or ``tasks/``.  They were found not to refuse
(recorded here as strict xfails by US-PM-24-3) and were fixed by US-PM-24-8;
:class:`TestTheQuarantinePathsRefuseAnExistingTarget` is their coverage.
"""

import hashlib
import inspect
import json

import pytest

from projectman.store import Store, _cache


SENTINEL = "---\nid: SENTINEL\n---\nDo not overwrite me. Byte-exact.\n"


# ─── helpers ─────────────────────────────────────────────────────────


def _proj(tmp_project):
    """The .project dir with every item subdirectory present."""
    proj = tmp_project / ".project"
    for sub in ("stories", "tasks", "epics", "sprints"):
        (proj / sub).mkdir(parents=True, exist_ok=True)
    return proj


def _log_ids(tmp_project) -> list[str]:
    """Every ``item_id`` recorded in the activity log, in order."""
    log = tmp_project / ".project" / "activity.jsonl"
    if not log.exists():
        return []
    ids = []
    for line in log.read_text().splitlines():
        if not line.strip():
            continue
        try:
            ids.append(json.loads(line).get("item_id"))
        except json.JSONDecodeError:
            continue
    return ids


def _cache_ids(store: Store, item_type: str) -> list[str]:
    """IDs currently held in the module-level cache for *item_type*."""
    return [m.id for m, _ in _cache.get((str(store.project_dir), item_type), [])]


def _prime_caches(store: Store) -> None:
    """Populate the caches so a stray ``_cache_append`` would be visible.

    ``Store._cache_append`` is a no-op while the key is unpopulated, so
    asserting "no cache entry" against an empty cache would prove nothing.
    Priming happens *before* the sentinel is written, so the target ID can
    only appear in the cache if the refused create put it there.
    """
    store.list_stories()
    store.list_tasks()
    store.list_epics()
    for item_type in ("stories", "tasks", "epics"):
        assert (str(store.project_dir), item_type) in _cache, (
            f"{item_type} cache did not populate; the no-cache-entry assertion "
            "would be vacuous"
        )


def _tree_digest(root) -> dict[str, str]:
    """md5 of every file under *root*, keyed by relative path."""
    return {
        str(p.relative_to(root)): hashlib.md5(p.read_bytes()).hexdigest()
        for p in sorted(root.rglob("*"))
        if p.is_file()
    }


# ─── the Store create table ──────────────────────────────────────────
#
# Each builder runs against a primed store and returns a Case: the file it
# pre-seeded with SENTINEL, the ID that file belongs to, the cache bucket that
# ID would land in (None when the item type is not cached), and a zero-arg
# callable that performs the create which must refuse.


class Case:
    def __init__(self, target, item_id, cache_bucket, call, extra_check=None):
        self.target = target
        self.item_id = item_id
        self.cache_bucket = cache_bucket
        self.call = call
        self.extra_check = extra_check


def _seed_story(store) -> str:
    meta, _ = store.create_story("Parent story", "Parent body")
    return meta.id


def _build_create_story(store, proj, monkeypatch):
    _prime_caches(store)
    target = proj / "stories" / "US-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_story_id", lambda: "US-TST-77")
    return Case(
        target,
        "US-TST-77",
        "stories",
        lambda: store.create_story("Clobberer", "Body"),
    )


def _build_create_story_auto_test_task(store, proj, monkeypatch):
    """The test task ``create_story`` auto-generates per acceptance criterion.

    A second create path hiding inside the first: the story lands, then one
    ``create_task`` per criterion.  That inner create must refuse too, or a
    story with criteria could destroy an unrelated task.
    """
    _prime_caches(store)
    target = proj / "tasks" / "US-TST-5-1.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_story_id", lambda: "US-TST-5")
    monkeypatch.setattr(store, "_next_task_id", lambda story_id: "US-TST-5-1")
    return Case(
        target,
        "US-TST-5-1",
        "tasks",
        lambda: store.create_story(
            "Story with criteria",
            "Body",
            acceptance_criteria=["The system refuses to clobber"],
        ),
    )


def _build_create_epic(store, proj, monkeypatch):
    _prime_caches(store)
    target = proj / "epics" / "EPIC-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_epic_id", lambda: "EPIC-TST-77")
    return Case(
        target,
        "EPIC-TST-77",
        "epics",
        lambda: store.create_epic("Clobberer", "Body"),
    )


def _build_create_task(store, proj, monkeypatch):
    story_id = _seed_story(store)
    _prime_caches(store)
    target = proj / "tasks" / f"{story_id}-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_task_id", lambda sid: f"{story_id}-77")
    return Case(
        target,
        f"{story_id}-77",
        "tasks",
        lambda: store.create_task(story_id, "Clobberer", "Body"),
    )


def _build_create_tasks(store, proj, monkeypatch):
    """A batch whose *middle* ID is taken must land none of its members.

    A half-written batch is the worst outcome available here, so the extra
    check asserts the siblings either side were never created.
    """
    story_id = _seed_story(store)
    _prime_caches(store)
    target = proj / "tasks" / f"{story_id}-2.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_task_id", lambda sid: f"{story_id}-1")

    def extra_check():
        for suffix in (1, 3):
            sibling = proj / "tasks" / f"{story_id}-{suffix}.md"
            assert not sibling.exists(), (
                f"batch partially landed: {sibling.name} was written even though "
                "the batch was refused"
            )

    return Case(
        target,
        f"{story_id}-2",
        "tasks",
        lambda: store.create_tasks(
            story_id,
            [
                {"title": "One", "description": "a"},
                {"title": "Two", "description": "b"},
                {"title": "Three", "description": "c"},
            ],
        ),
        extra_check,
    )


def _build_create_sprint(store, proj, monkeypatch):
    """Reachable without a stub — sprint IDs come from the counter alone."""
    _prime_caches(store)
    target = proj / "sprints" / "SPRINT-TST-1.md"
    target.write_text(SENTINEL)
    return Case(
        target,
        "SPRINT-TST-1",
        None,  # sprints are not held in the item cache
        lambda: store.create_sprint("Clobberer"),
    )


#: Maps each builder to the ``Store.create_*`` method it exercises.  The
#: method names are what :class:`TestTheEnumerationIsComplete` checks against
#: ``Store`` itself, so adding a create method without adding a row here is a
#: test failure, not a silent gap.
STORE_CASES = {
    "create_story": _build_create_story,
    "create_story:auto_test_task": _build_create_story_auto_test_task,
    "create_epic": _build_create_epic,
    "create_task": _build_create_task,
    "create_tasks": _build_create_tasks,
    "create_sprint": _build_create_sprint,
}

#: The ``Store.create_*`` methods the table above covers, with the synthetic
#: ":"-suffixed variants collapsed back onto their method.
COVERED_METHODS = {name.split(":", 1)[0] for name in STORE_CASES}


class TestEveryStoreCreateRefusesAnExistingTarget:
    @pytest.mark.parametrize("case_name", sorted(STORE_CASES))
    def test_refuses(self, case_name, store, tmp_project, monkeypatch):
        proj = _proj(tmp_project)
        case = STORE_CASES[case_name](store, proj, monkeypatch)

        log_before = _log_ids(tmp_project)
        assert case.item_id not in log_before, "setup already logged the target ID"
        assert case.target.read_text() == SENTINEL

        with pytest.raises(FileExistsError, match=f"{case.item_id} already exists"):
            case.call()

        assert case.target.read_text() == SENTINEL, (
            f"{case_name} overwrote {case.target.name}"
        )
        assert case.item_id not in _log_ids(tmp_project), (
            f"{case_name} logged a create event for {case.item_id} it never made"
        )
        if case.cache_bucket is not None:
            assert case.item_id not in _cache_ids(store, case.cache_bucket), (
                f"{case_name} left {case.item_id} in the {case.cache_bucket} cache"
            )
        if case.extra_check is not None:
            case.extra_check()


class TestTheEnumerationIsComplete:
    """The table above must cover every ``create_*`` method ``Store`` has.

    Without this the parametrised suite would keep passing while a newly
    added create path went untested.  A new ``Store.create_thing`` fails here
    until a row is added for it.
    """

    def test_every_store_create_method_has_a_case(self):
        found = {
            name
            for name, _ in inspect.getmembers(Store, inspect.isfunction)
            if name.startswith("create_")
        }
        assert found == COVERED_METHODS, (
            "Store.create_* methods and the covered set disagree.\n"
            f"  uncovered: {sorted(found - COVERED_METHODS)}\n"
            f"  stale rows: {sorted(COVERED_METHODS - found)}"
        )

    def test_the_covered_methods_are_the_expected_five(self):
        """A second, literal statement of the same fact.

        The reflective check compares two things that could drift together if
        someone edited the table to match a mistake.  This pins the answer.
        """
        assert COVERED_METHODS == {
            "create_story",
            "create_epic",
            "create_task",
            "create_tasks",
            "create_sprint",
        }

    def test_every_covered_method_actually_guards_its_target(self):
        """Each create body must contain an ``exists()`` refusal.

        Source-level backstop: the behavioural tests above stub the allocator,
        so a guard that was moved *after* the write would still raise. This
        asserts the guard is textually present and mentions FileExistsError.
        """
        for name in sorted(COVERED_METHODS):
            src = inspect.getsource(getattr(Store, name))
            assert ".exists()" in src, f"{name} has no exists() check"
            assert "FileExistsError" in src, f"{name} does not raise FileExistsError"


# ─── the tool layer ──────────────────────────────────────────────────


@pytest.fixture
def server_project(tmp_project, monkeypatch):
    """Point the MCP tools at *tmp_project*, with a guard rail.

    ``PROJECTMAN_ROOT`` beats cwd in ``find_project_root``, so an ambient
    value would send these writes at a real project.  It is removed and the
    resolution asserted before any tool runs.
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


def _tool_story(store, proj, monkeypatch):
    target = proj / "stories" / "US-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_story_id", lambda: "US-TST-77")
    return target, "US-TST-77", {"title": "Clobberer", "description": "Body"}


def _tool_epic(store, proj, monkeypatch):
    target = proj / "epics" / "EPIC-TST-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_epic_id", lambda: "EPIC-TST-77")
    return target, "EPIC-TST-77", {"title": "Clobberer", "description": "Body"}


def _tool_task(store, proj, monkeypatch):
    story_id = _seed_story(store)
    target = proj / "tasks" / f"{story_id}-77.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_task_id", lambda sid: f"{story_id}-77")
    return (
        target,
        f"{story_id}-77",
        {"story_id": story_id, "title": "Clobberer", "description": "Body"},
    )


def _tool_tasks(store, proj, monkeypatch):
    story_id = _seed_story(store)
    target = proj / "tasks" / f"{story_id}-2.md"
    target.write_text(SENTINEL)
    monkeypatch.setattr(store, "_next_task_id", lambda sid: f"{story_id}-1")
    return (
        target,
        f"{story_id}-2",
        {
            "story_id": story_id,
            "tasks": [
                {"title": "One", "description": "a"},
                {"title": "Two", "description": "b"},
            ],
        },
    )


def _tool_sprint(store, proj, monkeypatch):
    target = proj / "sprints" / "SPRINT-TST-1.md"
    target.write_text(SENTINEL)
    return target, "SPRINT-TST-1", {"name": "Clobberer"}


#: tool name -> builder.  Mirrors STORE_CASES at the MCP boundary.
TOOL_CASES = {
    "pm_create_story": _tool_story,
    "pm_create_epic": _tool_epic,
    "pm_create_task": _tool_task,
    "pm_create_tasks": _tool_tasks,
    "pm_create_sprint": _tool_sprint,
}


class TestEveryCreateToolReturnsAnErrorNotACrash:
    """The refusal must reach the caller as a tool error, twice over.

    Once by calling the tool function (``ToolError``, the server's convention
    via ``_failed``) and once through the real ``tools/call`` handler, where
    the only acceptable outcome is ``isError=True`` — an escaping
    ``FileExistsError`` would be a transport crash, not a result.
    """

    @pytest.mark.parametrize("tool_name", sorted(TOOL_CASES))
    def test_tool_function_raises_toolerror(
        self, tool_name, server_project, monkeypatch
    ):
        from mcp.server.fastmcp.exceptions import ToolError

        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        target, item_id, kwargs = TOOL_CASES[tool_name](store, proj, monkeypatch)

        tool = getattr(srv, tool_name)
        with pytest.raises(ToolError) as excinfo:
            tool(**kwargs)

        message = str(excinfo.value)
        assert f"{item_id} already exists" in message
        assert not message.startswith("error:"), (
            "a refusal must be a real error, not a successful result whose "
            "body happens to start with 'error:'"
        )
        assert target.read_text() == SENTINEL, f"{tool_name} overwrote {target.name}"
        assert item_id not in _log_ids(server_project)

    @pytest.mark.parametrize("tool_name", sorted(TOOL_CASES))
    def test_the_wire_marks_the_refusal_as_an_error(
        self, tool_name, server_project, monkeypatch
    ):
        import anyio
        import mcp.types as types

        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        target, item_id, kwargs = TOOL_CASES[tool_name](store, proj, monkeypatch)

        async def call():
            handler = srv.mcp._mcp_server.request_handlers[types.CallToolRequest]
            request = types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name=tool_name, arguments=kwargs),
            )
            return await handler(request)

        # Nothing may propagate out of the MCP layer: the call itself must
        # return, carrying the failure in the result.
        result = anyio.run(call)

        assert result.root.isError is True, f"{tool_name} did not report isError"
        assert f"{item_id} already exists" in str(result.root.content)
        assert target.read_text() == SENTINEL


class TestPathsThatCreateNothing:
    """Paths named in the audit that turn out not to create item files.

    Recorded so the enumeration is auditable: if ``pm_auto_scope`` ever grows
    a write, or ``init`` stops refusing, that is a new create path and these
    tests say so.
    """

    def test_pm_auto_scope_writes_nothing(self, server_project):
        """Auto-scope returns instructions; the agent then calls the create tools."""
        from projectman import server as srv

        store = srv._store(None)
        proj = server_project / ".project"
        before = _tree_digest(proj)
        try:
            srv.pm_auto_scope()
        except Exception:
            pass  # a failure is also "wrote nothing" — the digest decides
        assert _tree_digest(proj) == before, "pm_auto_scope modified the store"

    def test_scoper_module_contains_no_writes(self):
        """Backstop for the above: no write call exists in the source at all."""
        from projectman import scoper

        src = inspect.getsource(scoper)
        for forbidden in ("write_text(", "create_story(", "create_task(", "open("):
            assert forbidden not in src, f"scoper.py now calls {forbidden}"

    def test_cli_init_refuses_an_existing_project_byte_for_byte(self, tmp_path):
        """``init`` is a create path for the whole store; it must refuse too."""
        from click.testing import CliRunner

        from projectman.cli import cli

        runner = CliRunner()
        with runner.isolated_filesystem(temp_dir=tmp_path) as fs:
            from pathlib import Path

            assert runner.invoke(cli, ["init", "--name", "proj", "--no-attach"]).exit_code == 0
            proj = Path(fs) / ".project"
            before = _tree_digest(proj)

            result = runner.invoke(cli, ["init", "--name", "other", "--no-attach"])

            assert result.exit_code == 1
            assert "already exists" in result.output
            assert _tree_digest(proj) == before, "a refused init still touched the store"


class TestTheQuarantinePathsRefuseAnExistingTarget:
    """The two create paths that live outside ``Store.create_*`` (US-PM-24-8).

    Both write a *new* item file into ``stories/`` or ``tasks/`` at a
    caller-supplied ID: ``pm_fix_malformed`` at the ``id`` argument,
    ``pm_restore`` at the quarantined file's own name.  Either could destroy an
    unrelated story or task, so both now refuse — and, because the target they
    would have clobbered is not the only file at stake, the refusal must also
    leave the quarantined source where it is, so the caller can retry with a
    free id instead of losing the broken file too.

    Recorded as strict xfails when the gap was found (US-PM-24-3); fixed here.
    """

    @staticmethod
    def _existing_story(store, proj):
        meta, _ = store.create_story("Original story", "Original body")
        path = proj / "stories" / f"{meta.id}.md"
        return meta.id, path, path.read_text()

    def test_pm_fix_malformed_refuses_an_existing_target(
        self, server_project, monkeypatch
    ):
        from mcp.server.fastmcp.exceptions import ToolError

        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        story_id, path, original = self._existing_story(store, proj)

        malformed = proj / "malformed"
        malformed.mkdir(parents=True, exist_ok=True)
        source = malformed / "broken.md"
        source_text = "no frontmatter here, just prose\n"
        source.write_text(source_text)

        with pytest.raises(ToolError) as excinfo:
            srv.pm_fix_malformed(
                filename="broken.md",
                id=story_id,
                title="Clobberer",
                item_type="story",
            )

        assert f"{story_id} already exists" in str(excinfo.value)
        assert path.read_text() == original
        assert source.read_text() == source_text, (
            "the refused fix consumed the malformed file, so the caller has "
            "lost it as well as failing"
        )

    def test_pm_restore_refuses_an_existing_target(self, server_project):
        from mcp.server.fastmcp.exceptions import ToolError

        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        story_id, path, original = self._existing_story(store, proj)

        malformed = proj / "malformed"
        malformed.mkdir(parents=True, exist_ok=True)
        source = malformed / f"{story_id}.md"
        source_text = original.replace("Original story", "From quarantine")
        source.write_text(source_text)

        with pytest.raises(ToolError) as excinfo:
            srv.pm_restore(f"{story_id}.md")

        assert f"{story_id} already exists" in str(excinfo.value)
        assert path.read_text() == original
        assert source.read_text() == source_text, (
            "the refused restore still moved the quarantined file"
        )

    @pytest.mark.parametrize(
        "tool_name, arguments",
        [
            (
                "pm_fix_malformed",
                {
                    "filename": "broken.md",
                    "id": "REPLACED",
                    "title": "Clobberer",
                    "item_type": "story",
                },
            ),
            ("pm_restore", {"filename": "REPLACED.md"}),
        ],
    )
    @pytest.mark.usefixtures("all_tool_families")
    def test_the_wire_marks_the_refusal_as_an_error(
        self, tool_name, arguments, server_project
    ):
        """The same two refusals as seen by a client, not by Python.

        A ``ToolError`` raised out of the function proves nothing about what
        crosses the transport; an escaping exception here would be a crash.
        Both tools are in the gated maintenance family, so the gate is opened
        for this test — ``tests/test_tool_gating.py`` owns the gate itself.
        """
        import anyio
        import mcp.types as types

        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        story_id, path, original = self._existing_story(store, proj)

        malformed = proj / "malformed"
        malformed.mkdir(parents=True, exist_ok=True)
        (malformed / "broken.md").write_text("no frontmatter here, just prose\n")
        (malformed / f"{story_id}.md").write_text(
            original.replace("Original story", "From quarantine")
        )

        arguments = {
            key: value.replace("REPLACED", story_id) if isinstance(value, str) else value
            for key, value in arguments.items()
        }

        async def call():
            handler = srv.mcp._mcp_server.request_handlers[types.CallToolRequest]
            request = types.CallToolRequest(
                method="tools/call",
                params=types.CallToolRequestParams(name=tool_name, arguments=arguments),
            )
            return await handler(request)

        result = anyio.run(call)

        assert result.root.isError is True, f"{tool_name} did not report isError"
        assert f"{story_id} already exists" in str(result.root.content)
        assert path.read_text() == original

    def test_a_free_target_is_still_written(self, server_project):
        """The refusal is narrow: neither tool's happy path changed.

        Without this, "refuse when the target exists" could be satisfied by a
        tool that refuses always.
        """
        from projectman import server as srv

        store = srv._store(None)
        proj = _proj(server_project)
        _prime_caches(store)

        malformed = proj / "malformed"
        malformed.mkdir(parents=True, exist_ok=True)
        (malformed / "broken.md").write_text("just prose, no frontmatter\n")

        srv.pm_fix_malformed(
            filename="broken.md",
            id="US-TST-41",
            title="Fixed up",
            item_type="story",
        )

        fixed = proj / "stories" / "US-TST-41.md"
        assert fixed.exists(), "a fix onto a free id no longer writes"
        assert "just prose, no frontmatter" in fixed.read_text()
        assert not (malformed / "broken.md").exists(), (
            "a successful fix must still consume the malformed file"
        )

        malformed.mkdir(parents=True, exist_ok=True)
        (malformed / "US-TST-42.md").write_text(
            fixed.read_text().replace("US-TST-41", "US-TST-42")
        )

        srv.pm_restore("US-TST-42.md")

        restored = proj / "stories" / "US-TST-42.md"
        assert restored.exists(), "a restore onto a free id no longer moves the file"
        assert not (malformed / "US-TST-42.md").exists()
