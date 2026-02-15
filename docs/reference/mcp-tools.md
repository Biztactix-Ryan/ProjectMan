# MCP Tools Reference

## Query Tools

### pm_status(project?)
Get project status summary.
- **project** (optional): Project name for hub mode
- **Returns**: Story/task counts, points, completion percentage, status breakdown

### pm_get(id)
Get full details of a story or task.
- **id**: Story ID (e.g. PRJ-1) or task ID (e.g. PRJ-1-1)
- **Returns**: Full frontmatter + body content

### pm_active(project?)
List active/in-progress items.
- **Returns**: Active stories and in-progress tasks

### pm_search(query, project?)
Search by keyword or semantic similarity.
- **query**: Search string
- **Returns**: Ranked results with scores

### pm_burndown(project?)
Get burndown data.
- **Returns**: Total, completed, remaining points with completion percentage

## Write Tools

### pm_create_story(title, description, priority?, points?, project?)
Create a new user story.
- **Returns**: Created story metadata

### pm_create_task(story_id, title, description, points?)
Create a task under a story.
- **Returns**: Created task metadata

### pm_update(id, status?, points?, title?, assignee?)
Update a story or task.
- **Returns**: Updated metadata

### pm_archive(id)
Archive a story or task.

## Intelligence Tools

### pm_estimate(id)
Get estimation context with calibration guidelines.

### pm_scope(id)
Get scoping context for story decomposition.

### pm_audit(project?)
Run project audit for drift detection.

### pm_reindex(project?)
Rebuild project index and embeddings.

### pm_repair()
Scan the hub for unregistered projects, initialize missing `.project/` dirs, rebuild all indexes and embeddings, and regenerate dashboards. Hub mode only. Writes a `REPAIR.md` report.
