"""Tests for estimation support."""

import yaml
from projectman.store import Store
from projectman.estimator import estimate


def test_estimate_story(tmp_project):
    store = Store(tmp_project)
    store.create_story("Story", "As a user, I want login")
    result = estimate(store, "TST-1")
    data = yaml.safe_load(result)
    assert "estimation_guidance" in data
    assert "fibonacci_scale" in data["estimation_guidance"]


def test_estimate_with_history(tmp_project):
    store = Store(tmp_project)
    store.create_story("Done Story", "Desc", points=5)
    store.update("TST-1", status="done")
    store.create_story("New Story", "Desc")
    result = estimate(store, "TST-2")
    data = yaml.safe_load(result)
    assert data["estimation_guidance"]["historical_average"] == 5.0
