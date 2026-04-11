"""Integration tests for STDIO transport.

These tests start the MCP server as a subprocess and send JSON-RPC
messages over stdio to verify the full transport layer works.
"""

import json
import subprocess
import threading
import time
from pathlib import Path
from typing import Optional

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
    import yaml

    with open(proj / "config.yaml", "w") as f:
        yaml.dump(config, f)

    # Create docs
    (proj / "PROJECT.md").write_text("# test-project\nA test project.\n")
    (proj / "INFRASTRUCTURE.md").write_text("# Infrastructure\nLocal only.\n")
    (proj / "SECURITY.md").write_text("# Security\nNo auth.\n")
    (proj / "VISION.md").write_text("# Vision\nTest vision.\n")
    (proj / "ARCHITECTURE.md").write_text("# Architecture\nSimple.\n")
    (proj / "DECISIONS.md").write_text("# Decisions\nNone yet.\n")

    monkeypatch.chdir(tmp_path)
    return tmp_path


class StdioClient:
    """JSON-RPC client over stdio for the MCP server."""

    def __init__(self, project_dir: Path):
        self.project_dir = project_dir
        self.proc: Optional[subprocess.Popen] = None
        self.request_id = 0
        self.lock = threading.Lock()
        self._output_thread: Optional[threading.Thread] = None
        self._responses: dict = {}
        self._response_event = threading.Event()

    def start(self):
        """Start the MCP server process."""
        self.proc = subprocess.Popen(
            ["projectman", "serve", "--transport", "stdio"],
            cwd=str(self.project_dir),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={**__import__("os").environ, "PROJECTMAN_ROOT": str(self.project_dir)},
        )
        self._output_thread = threading.Thread(target=self._read_output, daemon=True)
        self._output_thread.start()
        time.sleep(0.5)  # Wait for server to start

    def _read_output(self):
        """Read stdout in a background thread, dispatching responses."""
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

    def send_request(self, method: str, params: Optional[dict] = None) -> dict:
        """Send a JSON-RPC request and wait for the response."""
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

        # Wait for response with this ID
        self._response_event.clear()
        timeout = 10
        start = time.time()
        while time.time() - start < timeout:
            with self.lock:
                if req_id in self._responses:
                    resp = self._responses.pop(req_id)
                    return resp
            time.sleep(0.05)

        raise TimeoutError(f"No response for request {req_id}")

    def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> dict:
        """Call an MCP tool and return the result."""
        result = self.send_request(
            "tools/call",
            {
                "name": tool_name,
                "arguments": arguments or {},
            },
        )
        if "error" in result:
            raise RuntimeError(f"Tool call failed: {result['error']}")
        content = result.get("result", {}).get("content", [])
        text = ""
        for block in content:
            if block.get("type") == "text":
                text += block.get("text", "")
        return text

    def stop(self):
        """Stop the server."""
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
            self.proc = None


@pytest.fixture
def stdio_client(project_dir):
    """Start and stop the MCP server via STDIO transport."""
    client = StdioClient(project_dir)
    client.start()
    yield client
    client.stop()


class TestStdioTransport:
    """Tests that verify the STDIO transport works end-to-end."""

    def test_server_starts(self, stdio_client):
        """Server starts without error on stdio transport."""
        # If we got here, the server started and is responding
        assert stdio_client.proc is not None
        assert stdio_client.proc.poll() is None

    def test_pm_status_tool(self, stdio_client):
        """pm_status tool returns valid project status over stdio."""
        result = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(result)
        assert data["project"] == "test-project"
        assert data["stories"] == 0
        assert data["tasks"] == 0
        assert data["epics"] == 0

    def test_pm_create_story(self, stdio_client):
        """pm_create_story tool creates a story over stdio."""
        result = stdio_client.call_tool(
            "pm_create_story",
            {"title": "My Story", "description": "As a user, I want things"},
        )
        data = yaml.safe_load(result)
        assert "created" in data
        assert data["created"]["id"] == "US-TST-1"
        assert data["created"]["title"] == "My Story"

    def test_pm_create_and_get(self, stdio_client):
        """Create a story then retrieve it via pm_get."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Test Story", "description": "Test description body"},
        )
        result = stdio_client.call_tool("pm_get", {"id": "US-TST-1"})
        data = yaml.safe_load(result)
        assert data["title"] == "Test Story"
        assert "Test description body" in data["body"]

    def test_pm_create_task(self, stdio_client):
        """pm_create_task tool creates a task over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc"},
        )
        result = stdio_client.call_tool(
            "pm_create_task",
            {"story_id": "US-TST-1", "title": "My Task", "description": "Do it"},
        )
        data = yaml.safe_load(result)
        assert "created" in data
        assert data["created"]["id"] == "US-TST-1-1"
        assert data["created"]["title"] == "My Task"

    def test_pm_update_story(self, stdio_client):
        """pm_update tool updates a story over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc"},
        )
        result = stdio_client.call_tool(
            "pm_update",
            {"id": "US-TST-1", "status": "active", "points": 5},
        )
        data = yaml.safe_load(result)
        assert data["updated"]["status"] == "active"
        assert data["updated"]["points"] == 5

    def test_pm_board(self, stdio_client):
        """pm_board tool returns the task board over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc"},
        )
        stdio_client.call_tool(
            "pm_update",
            {"id": "US-TST-1", "status": "active"},
        )
        result = stdio_client.call_tool("pm_board")
        data = yaml.safe_load(result)
        assert "board" in data
        assert "summary" in data
        assert data["summary"]["available"] >= 0

    def test_pm_search(self, stdio_client):
        """pm_search tool searches stories over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Authentication system", "description": "Login and signup"},
        )
        result = stdio_client.call_tool("pm_search", {"query": "auth"})
        # Should return results (falls back to keyword search if embeddings unavailable)
        data = yaml.safe_load(result)
        assert isinstance(data, list)

    def test_pm_burndown(self, stdio_client):
        """pm_burndown tool returns burndown data over stdio."""
        result = stdio_client.call_tool("pm_burndown")
        data = yaml.safe_load(result)
        assert "total_points" in data
        assert "completion" in data

    def test_pm_reindex(self, stdio_client):
        """pm_reindex tool rebuilds the index over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story", "description": "Desc"},
        )
        result = stdio_client.call_tool("pm_reindex")
        # Should succeed (embeddings may or may not be available)
        assert "reindexed" in result.lower()

    def test_multiple_requests_in_sequence(self, stdio_client):
        """Multiple sequential tool calls work over stdio."""
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story 1", "description": "Desc 1"},
        )
        stdio_client.call_tool(
            "pm_create_story",
            {"title": "Story 2", "description": "Desc 2"},
        )
        stdio_client.call_tool(
            "pm_create_task",
            {"story_id": "US-TST-1", "title": "Task 1", "description": "Do it"},
        )

        # All items should exist
        status = stdio_client.call_tool("pm_status")
        data = yaml.safe_load(status)
        assert data["stories"] == 2
        assert data["tasks"] == 1

    def test_error_handling_invalid_id(self, stdio_client):
        """Invalid item ID returns an error response."""
        result = stdio_client.call_tool("pm_get", {"id": "INVALID-ID"})
        # Should contain error in the text output
        assert "error" in result.lower() or "not found" in result.lower()
