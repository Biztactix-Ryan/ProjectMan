---
created: '2026-10-07'
id: EPIC-PM-8
points: null
priority: must
status: active
tags:
- claude-code
- plugin
- distribution
target_date: null
title: ProjectMan as a Claude Code plugin and mod
updated: '2026-10-07'
---

Ship ProjectMan to Claude Code as one versioned plugin installed from this repo's marketplace, then add a mod layer for the things only in-process hooks can do.

Why: ProjectMan runs on many machines with a few other users. Today's install is four separately-managed pieces (pipx binary, skills/agent rendered by setup-claude/refresh-skills, MCP server config, per-project SessionStart settings hook) that drift apart: a release means pipx refresh + refresh-skills + restart on every machine, and skipped machines drift silently (0.11.0 released while pipx sat on 0.9.2). A plugin makes it one install/update unit (`/plugin install`, update + `/reload-plugins`, no restart).

Mod layer (TypeScript hooks module inside the same plugin; terminal + Desktop draw, hooks run everywhere): orchestration tool-call guards enforced in-process instead of as skill text, zero-turn /pm commands and a board pane via $.mcp.call, a live cache-cost pane feeding EPIC-PM-7's measurement work, and a sprint band above the prompt.

Principles: the Python MCP server stays the single source of truth; the mod holds no PM logic and only calls MCP / the web API; everything must still work where mods don't draw (VS Code chat panel, claude -p, cloud). Requires Claude Code >= 2.1.287 for the mod.

Success: a fresh machine is fully set up with one install command; a release reaches a machine with one update and no restart; setup-claude/refresh-skills are retired to a migration helper; the guard and zero-turn board are in daily use.