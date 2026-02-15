---
created: '2026-02-15'
id: EPIC-PRJ-1
points: null
priority: must
status: done
tags:
- phase-1
- api
- mvp
target_date: null
title: API Layer
updated: '2026-02-15'
---

Phase 1: Build the FastAPI application, REST API endpoints, request/response schemas, CLI entry point, and test suite. This establishes the HTTP adapter over existing ProjectMan core modules — no business logic rewrite needed.

**Success criteria:**
- FastAPI app starts with `projectman web` command
- All Store/MCP tool operations accessible via REST endpoints
- OpenAPI docs auto-generated at `/docs`
- Full test coverage via FastAPI TestClient
- Hub mode supported via `?project=` query param