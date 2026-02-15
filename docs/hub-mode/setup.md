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
│   ├── dashboards/
│   ├── projects/
│   └── roadmap/
└── projects/
    ├── my-api/
    │   └── .project/
    └── my-frontend/
        └── .project/
```
