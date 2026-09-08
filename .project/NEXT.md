Sprint 14 "Remove the Hub, Ship 0.9" (SPRINT-PM-14) completed 2026-09-08 by run orch-2026-09-08-8293: 21/21 points, 35/35 tasks accepted, 5 stories closed (US-PM-44, US-PM-45, US-PM-46, US-PM-47, US-PM-42). Hub mode is gone; ADR-004 supersedes ADR-003; CHANGELOG has [0.9.0] - 2026-09-08. Final suite: 5015 passed, 18 skipped, 0 failed (tests/integration still env-blocked).

Release 0.9.0 is fully shipped as of 2026-09-08: code committed (8f1a03e) and tagged v0.9.0 on origin, .project committed (b496801), pipx reinstalled at 0.9.0, `refresh-skills --keep-local` run, EPIC-PM-6 closed (4/4 stories, 31/31 pts).

Next time:

1. No active sprint. Before planning Sprint 15: US-PRJ-60 (pm_tags/pm_rename_tag/pm_export) and US-PM-22 (API auth stub) still need a product call; the story-with-archived-todo-tasks auto-close bug is the only new candidate; EPIC-PRJ-6 is the other epic still active.

2. Candidate small story from the hub removal: single-store pm_context no longer returns VISION/ARCHITECTURE at all (they were only ever emitted from a hub root as hub_vision/hub_architecture). If pm_context should surface the project's own VISION.md/ARCHITECTURE.md, scope it.

3. This repo's .project/config.yaml still carries hub: false / projects: []. The next PM write through save_config drops them silently; that diff is expected and harmless.

4. Known env-blocked: tests/integration (mcp 2.x in .venv). Runner: uv run --extra dev --with "mcp[cli]<2" --with fastapi --with httpx --with numpy python -m pytest tests -q -p no:cacheprovider --ignore=tests/integration.
