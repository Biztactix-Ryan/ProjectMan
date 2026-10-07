---
acceptance_criteria:
- Every skill, agent and worker-prompt reference to another pm skill or agent uses
  a name that resolves when installed as a plugin
- A test scans the templates for skill and agent references and fails on any name
  the plugin does not provide
- An /pm-orchestrate run on a small sprint dispatches workers and accepts tasks with
  the plugin install
created: '2026-10-07'
depends_on:
- US-PM-56
epic_id: EPIC-PM-8
id: US-PM-58
points: 2
priority: must
status: ready
tags:
- plugin
- skills
title: Skills and the orchestrator resolve each other under the plugin namespace
updated: '2026-10-07'
---

As a user invoking /pm and /pm-orchestrate from the plugin, I want every cross-reference between skills, the pm agent and worker prompts to resolve under the plugin's namespaced names (projectman:pm, projectman:pm-do, ...), so that routing and worker dispatch work exactly as they do today.