---
assignee: claude
created: '2026-02-15'
id: US-PRJ-5-1
points: 1
status: done
story_id: US-PRJ-5
title: Set up test infrastructure with conftest fixtures and TestClient
updated: '2026-02-15'
---

Create test setup for web API tests:
- `tests/web/conftest.py` with fixtures for temporary `.project/` directory, FastAPI TestClient, and sample data (epic, story, task)
- Reuse patterns from existing `conftest.py` for temp project setup
- Verify TestClient can hit a basic endpoint (e.g., GET `/api/status`)