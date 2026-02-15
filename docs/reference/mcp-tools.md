# MCP Tools Reference

## Query Tools

### pm_status(project?)
Get project status summary.
- **project** (optional): Project name for hub mode
- **Returns**: Epic/story/task counts, points, completion percentage, status breakdown

### pm_get(id)
Get full details of an epic, story, or task.
- **id**: Epic ID (e.g. `EPIC-PRJ-1`), story ID (e.g. `US-PRJ-1`), or task ID (e.g. `US-PRJ-1-1`)
- **Returns**: Full frontmatter + body content

### pm_docs(doc?, project?)
Read project documentation files.
- **doc** (optional): Specific doc to read — `project`, `infrastructure`, `security`, `vision`, `architecture`, `decisions`
- **project** (optional): Project name for hub mode
- **Returns**: Document content

### pm_active(project?, limit?, offset?)
List active/in-progress items.
- **limit** (optional, default `20`): Max items per list
- **offset** (optional, default `0`): Starting index for pagination
- **Returns**: Active stories and in-progress tasks with totals and `has_more` pagination flag

### pm_search(query, project?)
Search by keyword or semantic similarity.
- **query**: Search string
- **Returns**: Ranked results with scores

### pm_board(project?, assignee?, limit?)
Get the task board grouped by workflow state.
- **project** (optional): Project name for hub mode
- **assignee** (optional): Filter by assignee
- **limit** (optional, default `10`): Max items per board group. Totals are always shown in the summary.
- **Returns**: Tasks grouped by `available`, `not_ready`, `in_progress`, `in_review`, `blocked` with readiness checks, suitability hints, and per-group totals

### pm_burndown(project?)
Get burndown data.
- **Returns**: Total, completed, remaining points with completion percentage

### pm_context(project?, limit?)
Get combined hub and project context.
- **project** (optional): Project name for hub mode
- **limit** (optional, default `20`): Max epics/stories to include
- **Returns**: Hub vision/architecture + project docs + active epics/stories (with totals)

### pm_epic(id, project?, limit?, offset?)
Get epic details with story and task rollup.
- **id**: Epic ID (e.g. `EPIC-PRJ-1`)
- **project** (optional): Project name for hub mode
- **limit** (optional, default `10`): Max stories to return per page
- **offset** (optional, default `0`): Starting index for story pagination
- **Returns**: Epic metadata, paginated linked stories/tasks, completion percentage (rollup always covers all stories), `has_more` and `next_offset` for pagination

## Write Tools

### pm_create_story(title, description, priority?, points?, epic_id?, project?)
Create a new user story.
- **epic_id** (optional): Link story to an epic
- **Returns**: Created story metadata

### pm_create_epic(title, description, priority?, target_date?, tags?, project?)
Create a new epic.
- **Returns**: Created epic metadata

### pm_create_task(story_id, title, description, points?)
Create a task under a story.
- **Returns**: Created task metadata

### pm_create_tasks(story_id, tasks, project?)
Create multiple tasks under a story in a single call.
- **story_id**: Parent story ID (e.g. `US-PRJ-1`)
- **tasks**: List of task objects, each with `title` (str), `description` (str), `points` (int, optional)
- **project** (optional): Project name for hub mode
- **Returns**: List of created task metadata, count, and total points

### pm_update(id, status?, points?, title?, assignee?, epic_id?)
Update an epic, story, or task.
- Epic status values: `draft`, `active`, `done`, `archived`
- Story status values: `backlog`, `ready`, `active`, `done`, `archived`
- Task status values: `todo`, `in-progress`, `review`, `done`, `blocked`
- **Returns**: Updated metadata

### pm_archive(id)
Archive an epic, story, or task.

### pm_grab(task_id, assignee?)
Claim a task with readiness validation.
- Sets assignee and status to `in-progress`
- Validates task readiness before claiming
- Loads task context for implementation
- **Returns**: Task details and context

### pm_update_doc(doc, content, project?)
Update a project documentation file.
- **doc**: Document name — `project`, `infrastructure`, `security`, `vision`, `architecture`, `decisions`
- **content**: New document content
- **project** (optional): Project name for hub mode

## Intelligence Tools

### pm_estimate(id)
Get estimation context with calibration guidelines.

### pm_scope(id)
Get scoping context for story decomposition.

### pm_auto_scope(mode?, project?, limit?, offset?)
Discover what needs scoping — returns codebase signals or undecomposed stories.
- **mode** (optional): `"full"` for codebase scan (new projects) or `"incremental"` for scoping existing stories. Auto-detected if omitted.
- **project** (optional): Project name for hub mode
- **limit** (optional, default `5`): Max stories per batch in incremental mode
- **offset** (optional, default `0`): Starting index for pagination in incremental mode
- **Returns**: Full scan returns documentation, build files, source tree, and creation guidance. Incremental returns a paginated batch of undecomposed story IDs/titles with `has_more` and `next_offset` for pagination.

### pm_audit(project?)
Run project audit for drift detection. Performs 13 checks covering stories, tasks, epics, documentation, hub docs, assignments, and malformed files.

### pm_reindex(project?)
Rebuild project index and embeddings.

### pm_repair()
Scan the hub for unregistered projects, initialize missing PM data directories (`.project/projects/{name}/`), rebuild all indexes and embeddings, and regenerate dashboards. Hub mode only. Writes a `REPAIR.md` report.

## Web Dashboard Tools

### pm_web_start(host?, port?)
Start the ProjectMan web dashboard as a background server.
- **host** (optional, default `127.0.0.1`): Host/IP to bind to. Use `0.0.0.0` to listen on all interfaces.
- **port** (optional, default `8000`): Port to listen on. If the port is in use, the tool returns an error with a suggestion to try the next port.
- **Returns**: `{status, url, pid}` on success, or `{status: "error", error, suggestion}` if the port is taken
- **Requires**: `web` extra (`pip install projectman[web]`)

### pm_web_stop()
Stop the running ProjectMan web server.
- **Returns**: `{status: "stopped", pid}` or `{status: "not_running"}`

### pm_web_status()
Check if the web server is running.
- **Returns**: `{running, url, pid, host, port}` if running, or `{running: false}` if not

## Malformed File Tools

### pm_malformed(project?)
Get the next malformed file from quarantine.
- **Returns**: File content and metadata for the next malformed file, one at a time

### pm_fix_malformed(filename, id, title, item_type, body?, status?, priority?, points?, story_id?, project?)
Fix a malformed file by providing corrected metadata.
- **filename**: Name of the malformed file
- **id**: Corrected ID
- **title**: Corrected title
- **item_type**: `story` or `task`
- **body** (optional): Corrected body content
- **status** (optional): Corrected status
- **priority** (optional): Corrected priority (stories only)
- **points** (optional): Corrected points
- **story_id** (optional): Parent story ID (tasks only)
- **Returns**: Fixed file metadata

### pm_restore(filename, project?)
Restore a malformed file back to its original location without fixes.
- **filename**: Name of the malformed file
- **Returns**: Restored file path
