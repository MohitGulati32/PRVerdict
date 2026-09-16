# Convention for MCP clients in this project: speak the server's real
# protocol (JSON-RPC 2.0 over stdio, per the MCP spec) by launching its
# published container, not a hand-rolled REST guess against a made-up
# HTTP API. incident_client.py (Phase 6) should follow this same pattern.

from __future__ import annotations

import asyncio
import json
import os
import re
from typing import Any

DOCKER_IMAGE = "ghcr.io/github/github-mcp-server"
PROTOCOL_VERSION = "2024-11-05"
CODEOWNERS_PATHS = (".github/CODEOWNERS", "CODEOWNERS", "docs/CODEOWNERS")


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
            # Default StreamReader buffer (64KB) is too small for tool
            # responses like tools/list or a file's full contents.
            limit=10 * 1024 * 1024,
        )
        await self._request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "prverdict", "version": "0.1"},
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

    async def _get_file_text(self, owner: str, repo: str, path: str) -> str | None:
        """Fetch one file's text content, or None if it doesn't exist.

        get_file_contents doesn't fit call_tool()'s "single JSON text block"
        shape: a found file comes back as a "resource" content block (not
        "text"), and a missing path isn't always isError=True either — the
        server sometimes replies with a non-error "text" block suggesting
        nearby matches instead. Both of those count as "not found" here.
        """
        result = await self._request(
            "tools/call",
            {"name": "get_file_contents", "arguments": {"owner": owner, "repo": repo, "path": path}},
        )
        if result.get("isError"):
            return None
        for block in result.get("content", []):
            if block.get("type") == "resource":
                return block.get("resource", {}).get("text")
        return None

    async def get_codeowners(self, owner: str, repo: str) -> str | None:
        """Fetch CODEOWNERS content, checking the conventional locations in order."""
        for path in CODEOWNERS_PATHS:
            text = await self._get_file_text(owner, repo, path)
            if text is not None:
                return text
        return None


def _parse_codeowners(content: str) -> list[tuple[str, list[str]]]:
    """Parse CODEOWNERS lines into (pattern, owners) pairs, in file order."""
    rules = []
    for line in content.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        pattern, *owners = line.split()
        if owners:
            rules.append((pattern, owners))
    return rules


def _codeowners_pattern_to_regex(pattern: str) -> re.Pattern[str]:
    """Translate one CODEOWNERS pattern to a regex matched against a repo-relative file path.

    Follows the gitignore-style rules CODEOWNERS documents: a pattern with
    no interior slash (trailing slash aside) matches at any depth; any
    other slash anchors it to the repo root; a trailing slash matches the
    named directory's contents. This covers the patterns real CODEOWNERS
    files use (*, **, ?, directory prefixes) without reimplementing full
    gitignore fidelity (no character classes, no negation - CODEOWNERS
    itself doesn't support negation either).
    """
    dir_only = pattern.endswith("/")
    core = pattern[:-1] if dir_only else pattern
    anchored = "/" in core  # includes a leading slash, an explicit root anchor
    core = core.lstrip("/")

    segments = []
    for segment in core.split("/") if core else []:
        if segment == "**":
            segments.append(".*")
            continue
        piece = []
        for ch in segment:
            if ch == "*":
                piece.append("[^/]*")
            elif ch == "?":
                piece.append("[^/]")
            else:
                piece.append(re.escape(ch))
        segments.append("".join(piece))
    body = "/".join(segments)

    prefix = "^" if anchored else "^(?:.*/)?"
    suffix = "/.*$" if dir_only else "$"
    return re.compile(prefix + body + suffix)


def check_ownership(pr_snapshot: dict[str, Any], codeowners_content: str | None) -> dict[str, Any]:
    """Cross-reference a PR's changed files against CODEOWNERS and its approvals.

    For each file in pr_snapshot["files"], the last CODEOWNERS rule that
    matches wins (matching git's own precedence). matched_owners is the
    union of required owners across all changed files. approving_reviewers
    is who actually left an APPROVED review.

    Team owners (e.g. "@org/team-x") are included in matched_owners but
    can't be checked against approving_reviewers without an extra API call
    to resolve team membership, so a team-only approval will never make
    is_owned True here - only a direct match on an individual owner does.
    """
    rules = [
        (owners, _codeowners_pattern_to_regex(pattern))
        for pattern, owners in _parse_codeowners(codeowners_content or "")
    ]

    matched_owners: set[str] = set()
    for f in pr_snapshot.get("files", []):
        filename = f["filename"]
        winner: list[str] | None = None
        for owners, regex in rules:
            if regex.match(filename):
                winner = owners
        if winner:
            matched_owners.update(winner)

    approving_reviewers = sorted({
        review["user"]["login"]
        for review in pr_snapshot.get("reviews", [])
        if review.get("state") == "APPROVED"
    })

    individual_owners = {o.lower() for o in matched_owners if "/" not in o}
    is_owned = any(f"@{reviewer}".lower() in individual_owners for reviewer in approving_reviewers)

    return {
        "matched_owners": sorted(matched_owners),
        "approving_reviewers": approving_reviewers,
        "is_owned": is_owned,
    }
