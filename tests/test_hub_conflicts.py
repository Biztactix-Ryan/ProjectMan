"""Tests for the hub ref log.

The push-with-rebase integration tests that shared this module went with the
cross-project push machinery (US-PM-35-6): the hub no longer pushes on a
subproject's behalf, so there is no hub-side rebase loop left to drive. What
survives is the ref log, which records a submodule ref moving however it moved.
"""

import yaml

from projectman.hub.registry import (
    log_ref_update,
    REF_LOG_MAX_ENTRIES,
)


# ─── Ref log rotation ────────────────────────────────────────────


def test_ref_log_rotation(tmp_hub):
    """501 entries — oldest rotated to archive."""
    log_path = tmp_hub / ".project" / "ref-log.yaml"
    archive_path = tmp_hub / ".project" / "ref-log.archive.yaml"

    # Pre-fill with exactly MAX entries
    seed = [
        {
            "timestamp": f"t{i}",
            "project": "api",
            "old_ref": "o",
            "new_ref": "n",
            "source": "seed",
        }
        for i in range(REF_LOG_MAX_ENTRIES)
    ]
    log_path.write_text(yaml.dump(seed, default_flow_style=False))

    # One more triggers rotation
    log_ref_update("web", "x", "y", "push", tmp_hub)

    entries = yaml.safe_load(log_path.read_text())
    assert len(entries) == REF_LOG_MAX_ENTRIES
    assert entries[-1]["project"] == "web"
    assert entries[-1]["source"] == "push"

    assert archive_path.exists()
    archived = yaml.safe_load(archive_path.read_text())
    assert len(archived) == 1
    assert archived[0]["timestamp"] == "t0"
