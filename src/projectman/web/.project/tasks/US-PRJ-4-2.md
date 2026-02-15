---
assignee: claude
created: '2026-02-15'
id: US-PRJ-4-2
points: 1
status: done
story_id: US-PRJ-4
title: Add projectman web CLI command with --port/--host options
updated: '2026-02-15'
---

Add `web` command to `cli.py` using Click:
- `projectman web` starts Uvicorn with the FastAPI app on http://localhost:8000
- `--port` option (default 8000)
- `--host` option (default 127.0.0.1)
- Graceful error if FastAPI/Uvicorn not installed (ImportError catch with message: "Install web dependencies: pip install projectman[web]")