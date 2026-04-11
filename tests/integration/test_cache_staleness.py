"""Integration tests for cache staleness detection.

These tests use the STDIO transport to create items, then externally
modify the files on disk to verify the cache staleness detection works.
"""

import json
import subprocess
import threading
import time
from pathlib import Path

import pytest
import yaml


@pytest.fixture
def project_dir(tmp_path, monkeypatch):
    """Create a minimal project directory and cd to it."""
    proj = tmp_path / ".project"
    proj.mkdir()
    (proj / "stories").mkdir()
    (proj / "tasks").mkdir()
    (proj / "epics").mkdir()

    config = {
        "name": "test-project",
        "prefix": "TST",
        "description": "A test project",
        "hub": False,
        "next_story_id": 1,
        "next_epic_id": 1,
        "projects": [],
    }
    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    monkeypatch.chdir(tmp_path)
    return tmp_path


class StdioClient:
    """JSON-RPC client over stdio for the MCP server."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.proc: subprocess.Popen | None = None
        self.request_id = 0
        self.lock = threading.Lock()
        self._output_thread: threading.Thread | None = None
        self._responses: dict = {}
        self._response_event = threading.Event()

    def start(self):
        from pathlib import Path

        local_venv = Path(__file__).resolve().parents[2] / ".venv" / "bin"
        env = {**__import__("os").environ, "PROJECTMAN_ROOT": str(self.project_dir)}
        if local_venv.exists():
            env["PATH"] = f"{local_venv}:{env.get('PATH', '')}"
        self.proc = subprocess.Popen(
            ["projectman", "serve", "--transport", "stdio"],
            cwd=str(self.project_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )
        self._output_thread = threading.Thread(target=self._read_output, daemon=True)
        self._output_thread.start()
        time.sleep(0.5)

    def _read_output(self):
        while self.proc and self.proc.stdout:
            line = self.proc.stdout.readline()
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                resp = json.loads(line)
                rid = resp.get("id")
                if rid is not None:
                    with self.lock:
                        self._responses[rid] = resp
                    self._response_event.set()
            except json.JSONDecodeError:
                pass

    def send_request(self, method: str, params: dict | None = None) -> dict:
        if not self.proc:
            raise RuntimeError("Server not started")
        with self.lock:
            self.request_id += 1
            req_id = self.request_id
        message = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params or {},
        }
        with self.lock:
            self.proc.stdin.write(json.dumps(message) + "\n")
            self.proc.stdin.flush()
        self._response_event.clear()
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if req_id in self._responses:
                    return self._responses.pop(req_id)
            time.sleep(0.05)
        raise TimeoutError(f"No response for request {req_id}")

    def call_tool(self, tool_name: str, arguments: dict | None = None) -> dict:
        result = self.send_request(
            "tools/call",
            {"name": tool_name, "arguments": arguments or {}},
        )
        content = result.get("result", {}).get("content", [])
        text = ""
        for block in content:
            if block.get("type") == "text":
                text += block.get("text", "")
        return text

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


@pytest.fixture
def stdio_client(project_dir):
    client = StdioClient(project_dir)
    client.start()
    yield client
    client.stop()


class TestCacheStalenessIntegration:
    """Integration tests verifying cache staleness detection via STDIO transport."""

    def test_external_file_change_picked_up_by_pm_get(self, stdio_client, project_dir):
        """External file modification is reflected in subsequent pm_get calls."""
        # Create a story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Original body"},
        )

        # Verify it was created
        result = stdio_client.call_tool("pm_get", {"id": "US-TST-1"})
        data = yaml.safe_load(result)
        assert data["title"] == "Story"
        assert "Original body" in data["body"]

        # Externally modify the story file (simulate git pull or direct edit)
        story_path = project_dir / ".project" / "stories" / "US-TST-1.md"
        content = story_path.read_text().replace(
            "Original body", "Modified by external edit"
        )
        story_path.write_text(content)
        time.sleep(0.1)  # ensure mtime differs

        # pm_get should reflect the external change
        result = stdio_client.call_tool("pm_get", {"id": "US-TST-1"})
        data = yaml.safe_load(result)
        assert "Modified by external edit" in data["body"]

    def test_external_file_change_picked_up_by_pm_status(
        self, stdio_client, project_dir
    ):
        """External file addition is reflected in pm_status counts."""
        # Create one story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story 1", "description": "Desc"},
        )

        # Verify status
        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["stories"] == 1

        # Externally add a second story file
        (project_dir / ".project" / "stories" / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\ntitle: External Story\nstatus: backlog\npriority: should\npoints: 5\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nExternally created story\n"
        )
        time.sleep(0.1)

        # pm_status should show 2 stories
        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["stories"] == 2

    def test_external_file_deletion_picked_up(self, stdio_client, project_dir):
        """External file deletion is reflected in subsequent reads."""
        # Create a story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "To Be Deleted", "description": "Desc"},
        )

        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["stories"] == 1

        # Externally delete the story file
        (project_dir / ".project" / "stories" / "US-TST-1.md").unlink()
        time.sleep(0.1)

        # pm_status should show 0 stories
        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["stories"] == 0

    def test_external_task_change_picked_up(self, stdio_client, project_dir):
        """External task file modifications are reflected in pm_board."""
        # Create story and task via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc"},
        )
        stdio_client.call_tool(
            "pm_create_task",
            {
                "story_id": "US-TST-1",
                "title": "Task",
                "description": "Do it",
                "points": 3,
            },
        )

        # Externally modify the task status
        task_path = project_dir / ".project" / "tasks" / "US-TST-1-1.md"
        content = task_path.read_text().replace("status: todo", "status: in-progress")
        task_path.write_text(content)
        time.sleep(0.1)

        # pm_board should show the externally changed status
        result = stdio_client.call_tool("pm_board")
        data = yaml.safe_load(result)
        # The task should appear as in_progress, not available
        task_ids = [t["id"] for t in data["board"].get("in_progress", [])]
        assert "US-TST-1-1" in task_ids

    def test_pm_reindex_picks_up_all_external_changes(self, stdio_client, project_dir):
        """pm_reindex rebuilds the index reflecting all external changes."""
        # Create story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story 1", "description": "Desc", "points": 3},
        )

        # Externally add story 2 and story 3
        for i, pts in [(2, 5), (3, 8)]:
            (project_dir / ".project" / "stories" / f"US-TST-{i}.md").write_text(
                f"---\nid: US-TST-{i}\ntitle: External Story {i}\nstatus: backlog\n"
                f"priority: should\npoints: {pts}\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nBody\n"
            )

        # pm_reindex should pick up all 3 stories (the external ones AND update index)
        result = stdio_client.call_tool("pm_reindex")
        assert "reindexed" in result.lower()

        # Verify index.yaml has all 3 stories
        index_path = project_dir / ".project" / "index.yaml"
        index_data = yaml.safe_load(index_path.read_text())
        entry_ids = [e["id"] for e in index_data["entries"]]
        assert "US-TST-1" in entry_ids
        assert "US-TST-2" in entry_ids
        assert "US-TST-3" in entry_ids
        assert index_data["total_points"] == 16  # 3 + 5 + 8

    def test_external_file_change_via_git_pull_simulation(
        self, stdio_client, project_dir, tmp_path
    ):
        """Simulate git pull adding files externally (most common real-world scenario)."""
        # Create initial story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Original", "description": "Original story", "points": 2},
        )

        # Simulate: another process (or git pull) adds a file
        (project_dir / ".project" / "stories" / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\ntitle: Pulled Story\nstatus: backlog\npriority: could\npoints: 3\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nThis story came from a git pull\n"
        )
        time.sleep(0.1)

        # pm_status should immediately reflect the pulled story
        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["stories"] == 2
        assert data["total_points"] == 5  # 2 + 3

    def test_stale_cache_after_external_delete_then_create(
        self, stdio_client, project_dir
    ):
        """After external deletion, cache correctly handles new items."""
        # Create story via MCP
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc", "points": 3},
        )

        # Externally delete it
        (project_dir / ".project" / "stories" / "US-TST-1.md").unlink()
        time.sleep(0.1)

        # Externally create a new story with same ID slot
        (project_dir / ".project" / "stories" / "US-TST-2.md").write_text(
            "---\nid: US-TST-2\ntitle: New Story\nstatus: backlog\npriority: should\npoints: 5\ntags: []\ncreated: 2026-01-01\nupdated: 2026-01-01\n---\nNew body\n"
        )

        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        # Should see 1 story with points=5, not the old 3-point one
        assert data["stories"] == 1
        assert data["total_points"] == 5
