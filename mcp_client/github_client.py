# Convention for MCP clients in this project: speak the server's real
# protocol (JSON-RPC 2.0 over stdio, per the MCP spec) by launching its
# published container, not a hand-rolled REST guess against a made-up
# HTTP API. incident_client.py (Phase 6) should follow this same pattern.

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

DOCKER_IMAGE = "ghcr.io/github/github-mcp-server"
PROTOCOL_VERSION = "2024-11-05"


class GitHubMCPError(RuntimeError):
    """Raised when the GitHub MCP server reports a JSON-RPC or tool-call error."""


class GitHubMCPClient:
    """Async JSON-RPC/stdio client for the official GitHub MCP server.

    Speaks the real MCP protocol to `docker run -i ghcr.io/github/github-mcp-server`:
    an `initialize` request, an `initialized` notification, then `tools/call`
    requests. Use as an async context manager so the container is cleaned up:

        async with GitHubMCPClient() as client:
            snapshot = await client.get_pr_snapshot("owner", "repo", 123)
    """

    def __init__(self, token: str | None = None, docker_image: str = DOCKER_IMAGE):
        self.token = token or os.environ["GITHUB_PERSONAL_ACCESS_TOKEN"]
        self.docker_image = docker_image
        self._proc: asyncio.subprocess.Process | None = None
        self._next_id = 0

    async def __aenter__(self) -> "GitHubMCPClient":
        await self._start()
        return self

    async def __aexit__(self, *exc: Any) -> None:
        await self.close()

    async def _start(self) -> None:
        self._proc = await asyncio.create_subprocess_exec(
            "docker", "run", "-i", "--rm",
            "-e", "GITHUB_PERSONAL_ACCESS_TOKEN",
            self.docker_image,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, "GITHUB_PERSONAL_ACCESS_TOKEN": self.token},
        )
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "shippable", "version": "0.1"},
            },
        )
        self._notify("notifications/initialized")

    async def close(self) -> None:
        if self._proc is None:
            return
        if self._proc.stdin and not self._proc.stdin.is_closing():
            self._proc.stdin.close()
        try:
            await asyncio.wait_for(self._proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            self._proc.kill()
        self._proc = None

    def _write(self, message: dict[str, Any]) -> None:
        assert self._proc and self._proc.stdin
        self._proc.stdin.write((json.dumps(message) + "\n").encode())

    async def _request(self, method: str, params: dict[str, Any] | None = None) -> Any:
        assert self._proc and self._proc.stdin and self._proc.stdout
        self._next_id += 1
        request_id = self._next_id
        self._write({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params or {}})
        await self._proc.stdin.drain()

        line = await self._proc.stdout.readline()
        if not line:
            raise GitHubMCPError(f"github-mcp-server closed stdout before responding to {method!r}")
        response = json.loads(line)
        if response.get("id") != request_id:
            raise GitHubMCPError(f"expected response id {request_id}, got {response.get('id')!r}")
        if "error" in response:
            raise GitHubMCPError(response["error"].get("message", str(response["error"])))
        return response.get("result")

    def _notify(self, method: str, params: dict[str, Any] | None = None) -> None:
        self._write({"jsonrpc": "2.0", "method": method, "params": params or {}})

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        result = await self._request("tools/call", {"name": name, "arguments": arguments})
        content = result.get("content", [])
        text = "".join(block.get("text", "") for block in content if block.get("type") == "text")
        if result.get("isError"):
            raise GitHubMCPError(text or f"tool {name!r} failed")
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    async def get_pr_snapshot(self, owner: str, repo: str, pull_number: int) -> dict[str, Any]:
        """Pull the data the readiness rubric needs for one PR.

        Covers metadata (title, body, diff stats), CI check runs, changed
        files, and reviews. Service criticality and incident history come
        from elsewhere (a local config file and, eventually, incident_client.py).
        """
        pr_args = {"owner": owner, "repo": repo, "pullNumber": pull_number}
        details = await self.call_tool("pull_request_read", {"method": "get", **pr_args})
        check_runs = await self.call_tool("pull_request_read", {"method": "get_check_runs", **pr_args})
        files = await self.call_tool("pull_request_read", {"method": "get_files", **pr_args})
        reviews = await self.call_tool("pull_request_read", {"method": "get_reviews", **pr_args})
        return {
            "pull_request": details,
            "check_runs": check_runs,
            "files": files,
            "reviews": reviews,
        }
