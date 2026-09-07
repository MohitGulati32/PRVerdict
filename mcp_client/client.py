import os
import httpx
from typing import Any


class MCPClient:
    """Thin HTTP client for an MCP server."""

    def __init__(self, base_url: str | None = None, token: str | None = None):
        self.base_url = (base_url or os.getenv("MCP_SERVER_URL", "")).rstrip("/")
        self.token = token or os.getenv("MCP_SERVER_TOKEN", "")
        self._headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> Any:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{self.base_url}/tools/{tool_name}",
                json={"arguments": arguments},
                headers=self._headers,
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()

    async def list_tools(self) -> list[dict[str, Any]]:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{self.base_url}/tools",
                headers=self._headers,
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json().get("tools", [])
