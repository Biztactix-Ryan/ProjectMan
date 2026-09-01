"""Tests for config discovery and loading."""

import pytest
from pathlib import Path

from projectman.config import find_project_root, load_config, save_config, project_dir
from projectman.models import ProjectConfig


def test_find_project_root(tmp_project):
    root = find_project_root(tmp_project)
    assert root == tmp_project


def test_find_project_root_from_subdir(tmp_project):
    subdir = tmp_project / "src" / "deep"
    subdir.mkdir(parents=True)
    root = find_project_root(subdir)
    assert root == tmp_project


def test_find_project_root_not_found(tmp_path):
    with pytest.raises(FileNotFoundError):
        find_project_root(tmp_path)


def test_load_config(tmp_project):
    config = load_config(tmp_project)
    assert config.name == "test-project"
    assert config.prefix == "TST"


def test_save_config(tmp_project):
    config = load_config(tmp_project)
    config.next_story_id = 5
    save_config(config, tmp_project)
    reloaded = load_config(tmp_project)
    assert reloaded.next_story_id == 5


def test_project_dir(tmp_project):
    pdir = project_dir(tmp_project)
    assert pdir == tmp_project / ".project"


def test_auto_commit_config_default(tmp_project):
    """auto_commit defaults to False when not in config.yaml."""
    config = load_config(tmp_project)
    assert config.auto_commit is False


def test_auto_commit_config_roundtrip(tmp_project):
    """auto_commit can be enabled and persists through save/load."""
    config = load_config(tmp_project)
    assert config.auto_commit is False

    config.auto_commit = True
    save_config(config, tmp_project)

    reloaded = load_config(tmp_project)
    assert reloaded.auto_commit is True


def test_auto_commit_config_disable_roundtrip(tmp_project):
    """auto_commit can be toggled back to False."""
    config = load_config(tmp_project)
    config.auto_commit = True
    save_config(config, tmp_project)

    config = load_config(tmp_project)
    config.auto_commit = False
    save_config(config, tmp_project)

    reloaded = load_config(tmp_project)
    assert reloaded.auto_commit is False


def test_find_project_root_env_var(tmp_project, tmp_path, monkeypatch):
    """PROJECTMAN_ROOT pins the root regardless of cwd."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_project))
    assert find_project_root() == tmp_project.resolve()


def test_find_project_root_env_var_invalid(tmp_path, monkeypatch):
    """PROJECTMAN_ROOT pointing at a non-project raises a clear error."""
    monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_path))
    with pytest.raises(FileNotFoundError, match="PROJECTMAN_ROOT"):
        find_project_root()


def test_find_project_root_explicit_start_ignores_env(tmp_project, tmp_path, monkeypatch):
    """An explicit start argument takes precedence over PROJECTMAN_ROOT."""
    monkeypatch.setenv("PROJECTMAN_ROOT", str(tmp_path))
    assert find_project_root(tmp_project) == tmp_project.resolve()


# --- config caching (US-PRJ-30) -------------------------------------------
#
# ``load_config`` memoises the parsed ProjectConfig per resolved project root
# and reuses it while config.yaml's (mtime_ns, size) stamp is unchanged.  The
# tests below pin the three properties that makes it safe: a hit really is the
# same object and skips the parse, every writer invalidates, and one root's
# entry never answers for another's.  ``tests/conftest.py`` clears the cache
# around every test, so each of these starts cold.


def _count_parses(monkeypatch):
    """Wrap ``yaml.safe_load`` as config.py sees it and count the calls."""
    from projectman import config as config_module

    calls = []
    real = config_module.yaml.safe_load

    def counting(*args, **kwargs):
        calls.append(1)
        return real(*args, **kwargs)

    monkeypatch.setattr(config_module.yaml, "safe_load", counting)
    return calls


def test_load_config_returns_cached_instance(tmp_project):
    first = load_config(tmp_project)
    second = load_config(tmp_project)
    assert first is second


def test_load_config_does_not_reparse_on_cache_hit(tmp_project, monkeypatch):
    load_config(tmp_project)  # warm the cache before counting
    parses = _count_parses(monkeypatch)

    load_config(tmp_project)
    load_config(tmp_project)

    assert parses == [], "cached config.yaml should not be re-parsed"


def test_load_config_parses_once_for_two_cold_loads(tmp_project, monkeypatch):
    parses = _count_parses(monkeypatch)

    first = load_config(tmp_project)
    second = load_config(tmp_project)

    assert len(parses) == 1
    assert first is second


def test_clear_config_cache_forces_a_reparse(tmp_project, monkeypatch):
    from projectman.config import clear_config_cache

    first = load_config(tmp_project)
    parses = _count_parses(monkeypatch)
    clear_config_cache(tmp_project)
    second = load_config(tmp_project)

    assert len(parses) == 1
    assert second is not first
    assert second.name == first.name


def test_save_config_invalidates_the_cache(tmp_project):
    cached = load_config(tmp_project)
    cached.next_story_id = 42
    save_config(cached, tmp_project)

    reloaded = load_config(tmp_project)
    assert reloaded is not cached
    assert reloaded.next_story_id == 42


def test_store_save_config_invalidates_the_cache(tmp_project):
    """A Store bumping next_story_id must be visible to the next load."""
    from projectman.store import Store

    before = load_config(tmp_project)
    starting_id = before.next_story_id

    store = Store(tmp_project)
    store.create_story("A story", "body")

    after = load_config(tmp_project)
    assert after is not before
    assert after.next_story_id == starting_id + 1


def test_store_save_config_evicts_the_cache_key(tmp_project):
    """``Store._save_config`` must drop the entry, not lean on the stamp.

    ``test_store_save_config_invalidates_the_cache`` only proves the next
    ``load_config`` sees fresh data, which the mtime/size stamp would also
    deliver.  This asserts the eviction itself: the key ``load_config``
    stores under — ``str(Path(root).resolve())`` — is gone from
    ``_CONFIG_CACHE`` the moment the write returns, before any reload.
    """
    from projectman.config import _CONFIG_CACHE
    from projectman.store import Store

    key = str(tmp_project.resolve())
    load_config(tmp_project)
    assert key in _CONFIG_CACHE, "cache should be warm before the write"

    store = Store(tmp_project)
    store._save_config()

    assert key not in _CONFIG_CACHE


def test_external_edit_of_config_yaml_is_picked_up(tmp_project):
    """The mtime/size stamp stands in for a TTL: a hand-edit wins."""
    import os
    import yaml as yaml_module

    config_path = tmp_project / ".project" / "config.yaml"
    first = load_config(tmp_project)
    assert first.description == "A test project"

    data = yaml_module.safe_load(config_path.read_text())
    data["description"] = "Edited by hand, outside the process"
    config_path.write_text(yaml_module.dump(data))
    stat = config_path.stat()
    os.utime(config_path, ns=(stat.st_atime_ns + 10**9, stat.st_mtime_ns + 10**9))

    second = load_config(tmp_project)
    assert second is not first
    assert second.description == "Edited by hand, outside the process"


def test_cache_entries_are_independent_per_root(tmp_project, tmp_path_factory):
    """Two project roots cache separately; clearing one keeps the other."""
    import yaml as yaml_module
    from projectman.config import clear_config_cache

    other_root = tmp_path_factory.mktemp("other_project")
    other_proj = other_root / ".project"
    other_proj.mkdir()
    with open(other_proj / "config.yaml", "w") as f:
        yaml_module.dump(
            {
                "name": "other-project",
                "prefix": "OTH",
                "description": "Another project",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            },
            f,
        )

    a1 = load_config(tmp_project)
    b1 = load_config(other_root)
    assert a1.name == "test-project"
    assert b1.name == "other-project"
    assert a1 is not b1

    clear_config_cache(tmp_project)

    a2 = load_config(tmp_project)
    b2 = load_config(other_root)
    assert a2 is not a1, "cleared root should re-read"
    assert b2 is b1, "the other root's entry should survive"


def test_clear_config_cache_with_no_args_empties_everything(tmp_project, tmp_path_factory):
    import yaml as yaml_module
    from projectman.config import _CONFIG_CACHE, clear_config_cache

    second_root = tmp_path_factory.mktemp("second_project")
    second_proj = second_root / ".project"
    second_proj.mkdir()
    with open(second_proj / "config.yaml", "w") as f:
        yaml_module.dump(
            {
                "name": "second-project",
                "prefix": "SEC",
                "description": "Yet another project",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            },
            f,
        )

    load_config(tmp_project)
    load_config(second_root)
    assert len(_CONFIG_CACHE) == 2

    clear_config_cache()
    assert _CONFIG_CACHE == {}


def test_cache_is_module_level_and_shared_across_call_sites(tmp_project):
    """The cache lives on the module, so every caller hits the same entry.

    A per-instance (or per-call-site) cache would give ``Store`` its own
    parse; a module-level dict keyed by root means the Store's load and a
    direct ``load_config`` are literally the same object.
    """
    from projectman.config import _CONFIG_CACHE
    from projectman.store import Store

    assert _CONFIG_CACHE == {}, "conftest should hand us a cold cache"

    direct = load_config(tmp_project)
    assert list(_CONFIG_CACHE) == [str(tmp_project.resolve())]
    assert _CONFIG_CACHE[str(tmp_project.resolve())][1] is direct

    store = Store(tmp_project)
    assert store.config is direct, "Store must reuse the module-level entry"
    assert len(_CONFIG_CACHE) == 1


def test_repeated_loads_never_reopen_config_yaml(tmp_project, tmp_path_factory, monkeypatch):
    """N warm calls, interleaved across two roots, touch the disk zero times.

    The parse-counting tests above stop at two calls against one root; the
    story's claim is about a hub tool call that loads ~20 configs in a row.
    This counts ``open()`` rather than ``yaml.safe_load`` so it also pins
    that a hit costs no file read at all, not merely no parse.
    """
    import builtins
    import yaml as yaml_module

    other_root = tmp_path_factory.mktemp("interleaved_project")
    other_proj = other_root / ".project"
    other_proj.mkdir()
    with open(other_proj / "config.yaml", "w") as f:
        yaml_module.dump(
            {
                "name": "interleaved-project",
                "prefix": "ILV",
                "description": "Another project",
                "hub": False,
                "next_story_id": 1,
                "projects": [],
            },
            f,
        )

    warm_a = load_config(tmp_project)
    warm_b = load_config(other_root)

    opened = []
    real_open = builtins.open

    def counting_open(file, *args, **kwargs):
        if str(file).endswith("config.yaml"):
            opened.append(str(file))
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", counting_open)

    for _ in range(5):
        assert load_config(tmp_project) is warm_a
        assert load_config(other_root) is warm_b

    assert opened == [], f"warm cache hits should not open config.yaml: {opened}"


def test_same_size_external_rewrite_is_caught_by_the_mtime_half(tmp_project):
    """The stamp's mtime half alone catches an edit that changes no bytes count.

    ``test_external_edit_of_config_yaml_is_picked_up`` changes the file's
    length too, so a size-only check would also pass it.  This rewrite keeps
    st_size identical, leaving mtime as the only thing that can mark the
    cache stale — and no ``clear_config_cache`` is called.
    """
    import os
    import yaml as yaml_module

    config_path = tmp_project / ".project" / "config.yaml"
    first = load_config(tmp_project)
    assert first.description == "A test project"
    size_before = config_path.stat().st_size

    data = yaml_module.safe_load(config_path.read_text())
    data["description"] = "B test project"  # same length, so same file size
    config_path.write_text(yaml_module.dump(data))
    stat = config_path.stat()
    assert stat.st_size == size_before, "rewrite must not change the file size"
    os.utime(config_path, ns=(stat.st_atime_ns + 10**9, stat.st_mtime_ns + 10**9))

    second = load_config(tmp_project)
    assert second is not first
    assert second.description == "B test project"
