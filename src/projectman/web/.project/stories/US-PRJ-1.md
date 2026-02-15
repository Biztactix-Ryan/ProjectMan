---
created: '2026-02-15'
epic_id: EPIC-PRJ-1
id: US-PRJ-1
points: 5
priority: must
status: done
tags: []
title: FastAPI app setup
updated: '2026-02-15'
---

As a developer, I want a FastAPI application scaffold so that the web server can be started and extended with routes.

**Includes:**
- `app.py` with FastAPI app instance
- CORS middleware configuration
- Static files mount (`/static/`)
- Jinja2 template configuration
- Project root resolution (find `.project/` directory)
- Uvicorn startup configuration
- Route registration (empty routers for api and pages)

**File structure:**
```
web/
  __init__.py
  app.py
  routes/
    __init__.py
    api.py
    pages.py
  templates/
  static/
    style.css
    app.js
```

**Acceptance criteria:**
- `python -m projectman.web.app` starts server on localhost:8000
- `/docs` shows empty OpenAPI spec
- Static files served at `/static/`
- Jinja2 templates directory configured