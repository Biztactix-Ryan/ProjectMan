---
created: '2026-02-15'
epic_id: EPIC-PRJ-1
id: US-PRJ-4
points: 2
priority: must
status: done
tags: []
title: CLI entry point for web server
updated: '2026-02-15'
---

As a user, I want to run `projectman web` to start the web server so that I can access the UI from my browser.

**Implementation:**
- Add `web` command to `cli.py` using Click
- Options: `--port` (default 8000), `--host` (default 127.0.0.1)
- Starts Uvicorn with the FastAPI app
- Add `web` optional dependency group to `pyproject.toml`:
  ```toml
  web = ["fastapi>=0.115", "uvicorn[standard]>=0.34"]
  ```

**Acceptance criteria:**
- `projectman web` starts server on http://localhost:8000
- `projectman web --port 3000` uses custom port
- `projectman web --host 0.0.0.0` exposes on network
- Graceful error if FastAPI/Uvicorn not installed (suggest `pip install projectman[web]`)