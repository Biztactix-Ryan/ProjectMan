# Hub Mode Setup

## Initialize a Hub

```bash
mkdir my-hub && cd my-hub
git init
projectman init --name "My Hub" --prefix HUB --hub
```

## Add Projects

```bash
projectman add-project my-api https://github.com/user/my-api.git
projectman add-project my-frontend https://github.com/user/my-frontend.git
```

Projects are added as git submodules under `projects/`.

## Structure

```
my-hub/
├── .project/
│   ├── config.yaml
│   ├── VISION.md
│   ├── ARCHITECTURE.md
│   ├── DECISIONS.md
│   ├── PROJECT.md
│   ├── INFRASTRUCTURE.md
│   ├── SECURITY.md
│   ├── index.yaml
│   ├── epics/
│   ├── stories/
│   ├── tasks/
│   ├── dashboards/
│   ├── projects/
│   └── roadmap/
└── projects/
    ├── my-api/
    │   └── .project/
    └── my-frontend/
        └── .project/
```

## Hub Context Documents

During `projectman init --hub`, three context documents are created in `.project/`:

- **VISION.md** — system-wide product vision, guiding principles, and roadmap
- **ARCHITECTURE.md** — system architecture overview and service map
- **DECISIONS.md** — architectural decision log (ADRs)

These documents provide shared context that applies across all subprojects. Update them with the `pm_update_doc` tool:

```
pm_update_doc("vision", content="Updated vision text...")
pm_update_doc("architecture", content="Updated architecture text...")
pm_update_doc("decisions", content="New decision entry...")
```

Read them at any time with `pm_docs`:

```
pm_docs("vision")
pm_docs("architecture")
pm_docs("decisions")
```

## Loading Combined Context

Use `pm_context(project)` to load the hub-level vision and architecture documents together with a specific project's docs and active epics/stories. This gives an agent or contributor full context in one call:

```
pm_context("my-api")
```

This returns the hub's VISION.md, ARCHITECTURE.md, the project's own docs, and all active epics and stories for that project.

## Syncing and Repairing

Pull the latest submodule changes before running audits or dashboards:

```bash
projectman sync
```

If you have added new project directories that are not yet tracked, or need to discover and initialize projects:

```bash
projectman repair
```
