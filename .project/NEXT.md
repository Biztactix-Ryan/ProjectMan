Sprint 9 (Quality and Safety, SPRINT-PM-9) was planned and activated on 2026-09-05 at 23 planned points (19 of real work: US-PM-12 only has its 1-pt baseline-gated test task left). Sprint 8's code and .project changes are still NOT committed.

Next time:
1. Commit first: review the Sprint 8 diff plus the planning edits and commit code + `.project/` state. The unit suite was green at 4794 passed with the two known env failures after Sprint 8.
2. Reinstall from the local tree so the running MCP server gains `pm_next`, the store guards and the 9KB orchestrate skill: `pipx install --force "/mnt/repos/ProjectMan[all]"` then `projectman refresh-skills --keep-local`, then restart Claude Code (docs/installation.md#upgrading).
3. Run Sprint 9 with `/pm-orchestrate`. Order: US-PM-30 first (US-PM-30-4 then US-PM-30-5; the capture must run from a clean tree so provenance is not dirty), which unblocks US-PM-12-5; then US-PRJ-49, US-PRJ-31, US-PRJ-50, US-PRJ-58, US-PRJ-48, US-PRJ-54. US-PRJ-49, 48 and 58 all edit server.py, so run them one at a time.
4. Two small leftovers flagged by workers, not yet stories: docs/reference/agent.md line 13 still says "Fetch context" first; web/routes/api.py create endpoints return 500 instead of 409 on an ID collision.
5. After Sprint 9: US-PM-29 (indexes stop dirtying .project, 5 pts, left out for capacity) and the hub redesign as EPIC-PM-5 (memory: hub-redesign-pending).
