# Projectman — Testing Guidelines

Projects managed by projectman should implement a simple test harness to minimize token usage when AI assistants run tests.

## Test Harness Requirements

Each project must create `tests/testing.sh` (or equivalent) with this interface:

```bash
./tests/testing.sh <category>
```

### Required Categories

| Category | Purpose |
|----------|---------|
| `all` | Full test suite |
| `fast` | Smoke test (~30s max) — sanity check before deeper testing |
| `unit` | Unit tests — isolated, no external dependencies |
| `integration` | Integration tests — may hit databases, APIs, filesystem |
| `e2e` | End-to-end tests — full workflows |

Projects may add domain-specific categories (e.g., `api`, `web`, `plugins`).

### Options

The harness should pass through common pytest/test options:

```bash
./tests/testing.sh <category> [options]

-v          # Verbose
-x          # Stop on first failure
-k PATTERN  # Filter by pattern
```

## Example Harness

```bash
#!/usr/bin/env bash
set -e

CATEGORY="${1:-all}"
shift 2>/dev/null || true

case "$CATEGORY" in
    all)
        pytest tests/ "$@"
        ;;
    fast)
        pytest tests/ -m "smoke" --maxfail=3 "$@"
        ;;
    unit)
        pytest tests/unit/ "$@"
        ;;
    integration)
        pytest tests/integration/ "$@"
        ;;
    e2e)
        pytest tests/e2e/ "$@"
        ;;
    *)
        echo "Usage: $0 <all|fast|unit|integration|e2e>" >&2
        exit 1
        ;;
esac
```

## Token-Efficient Testing

When AI assistants run tests, token usage matters. The harness design supports this:

1. **Start with `fast`** — Quick sanity check before committing to longer runs
2. **Target categories** — Run only the relevant category for changes made
3. **Use `-x`** — Stop on first failure to reduce output
4. **Use `-k`** — Pattern match to run only specific tests
5. **Avoid `-v`** — Default output is usually sufficient

### Recommended AI Workflow

```bash
# After implementing changes
./tests/testing.sh fast              # Smoke test first
./tests/testing.sh unit -k "feature" # Targeted tests
./tests/testing.sh integration -x    # Broader check, fail fast
```

## Pytest Markers

Use markers to enable flexible test selection:

```python
import pytest

@pytest.mark.smoke
def test_basic_functionality():
    """Included in fast category."""
    ...

@pytest.mark.slow
def test_comprehensive_workflow():
    """Excluded from fast runs."""
    ...
```

Configure in `pyproject.toml`:

```toml
[tool.pytest.ini_options]
markers = [
    "smoke: Quick sanity checks for fast category",
    "slow: Long-running tests excluded from fast",
]
```

## Directory Structure

Recommended test organization:

```
tests/
├── testing.sh          # Test harness
├── conftest.py         # Shared fixtures
├── unit/               # Isolated unit tests
│   └── test_*.py
├── integration/        # Tests with dependencies
│   └── test_*.py
└── e2e/                # Full workflow tests
    └── test_*.py
```

Alternative flat structure with markers:

```
tests/
├── testing.sh
├── conftest.py
├── test_models.py      # @pytest.mark.unit
├── test_api.py         # @pytest.mark.integration
└── test_workflow.py    # @pytest.mark.e2e
```

## Auditing Test Coverage

Projects can use `pm_audit` to verify testing requirements are met. Add to your audit checks:

- Test harness exists at `tests/testing.sh`
- All categories defined and functional
- `fast` category completes in under 30 seconds

---
*Projects using projectman should create their own `tests/testing.sh` following these guidelines.*
