Sprint 9 closed 2026-09-06 at 23/23. Sprint 10 (PM Data Moves Home, SPRINT-PM-10, 23 pts) was planned and activated the same day. EPIC-PM-5 (hub redesign) now exists with US-PM-31, 34, 35, 36, 37; US-PM-31 and 34 are in Sprint 10, the rest are Sprint 11.

Next time:
1. The .project changes from the close-out and planning are NOT committed. Review `git -C .project status` and commit them (pm_commit or a `pm:` commit).
2. The installed MCP server is still stale (no pm_next, no store guards). Reinstall before orchestrating: `pipx install --force "/mnt/repos/ProjectMan[all]"` then `projectman refresh-skills --keep-local`, then restart Claude Code (docs/installation.md#upgrading).
3. Run Sprint 10 with `/pm-orchestrate`. Order: US-PM-29 (indexes derived) and US-PM-32 (windowed telemetry; capture from a clean tree) are independent and can go first. US-PM-31 (stores at projects/{name}/.project) must land before US-PM-34 (prefix routing): US-PM-34-6 depends on US-PM-31-6. US-PM-34-7 touches all 44 project-param sites in server.py, so run it alone.
4. Open design decision recorded in US-PM-34's body: ID-less verbs take an optional `prefix`; omitted in a hub means the hub store for reads and is an error for creates. Change it there before US-PM-34-8 runs if you disagree.
5. Sprint 11 candidates: US-PM-33 (2 pts, agent.md ordering + web 409), then US-PM-35, US-PM-36, US-PM-37 in that dependency order. EPIC-PM-4 can close once US-PM-29 and US-PM-32 are done.
