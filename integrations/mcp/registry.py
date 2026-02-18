"""MCP server registry – manage multiple MCP server connections.

Allows both agents to discover and use tools from a configurable set
of MCP servers.  Servers can be added via config or at runtime.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from integrations.mcp.client import MCPClient, MCPTool, MCPTransport

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "mcp_servers.json"


@dataclass
class MCPServerConfig:
    """Configuration for a single MCP server."""

    name: str
    transport: str = "stdio"  # "stdio" or "sse"

    # stdio
    command: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)

    # sse
    url: str = ""
    headers: dict[str, str] = field(default_factory=dict)

    # metadata
    enabled: bool = True
    description: str = ""
    tags: list[str] = field(default_factory=list)  # e.g. ["deals", "investors", "both"]

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "transport": self.transport,
            "command": self.command,
            "env": self.env,
            "url": self.url,
            "headers": self.headers,
            "enabled": self.enabled,
            "description": self.description,
            "tags": self.tags,
        }

    @classmethod
    def from_dict(cls, data: dict) -> MCPServerConfig:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class MCPRegistry:
    """Manages a fleet of MCP server connections.

    Usage::

        registry = MCPRegistry()
        registry.load_config()   # reads mcp_servers.json

        # Or add servers programmatically
        registry.add_server(MCPServerConfig(
            name="filesystem",
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/data"],
            tags=["deals"],
        ))

        # Connect to all enabled servers
        registry.connect_all()

        # Discover all tools across all servers
        all_tools = registry.all_tools()

        # Call a tool (auto-routes to the right server)
        result = registry.call_tool("read_file", {"path": "/data/leads.csv"})

        # Disconnect
        registry.disconnect_all()
    """

    def __init__(self) -> None:
        self._configs: dict[str, MCPServerConfig] = {}
        self._clients: dict[str, MCPClient] = {}

    # -- config persistence ---------------------------------------------------

    def load_config(self, path: Optional[Path] = None) -> int:
        """Load server configs from a JSON file.  Returns count loaded."""
        p = path or CONFIG_PATH
        if not p.exists():
            logger.info("MCPRegistry: no config at %s – starting empty", p)
            return 0
        with open(p, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        servers = data if isinstance(data, list) else data.get("servers", [])
        for entry in servers:
            cfg = MCPServerConfig.from_dict(entry)
            self._configs[cfg.name] = cfg
        logger.info("MCPRegistry: loaded %d server configs from %s", len(servers), p)
        return len(servers)

    def save_config(self, path: Optional[Path] = None) -> None:
        p = path or CONFIG_PATH
        with open(p, "w", encoding="utf-8") as fh:
            json.dump(
                {"servers": [c.to_dict() for c in self._configs.values()]},
                fh, indent=2, ensure_ascii=False,
            )

    # -- server management ----------------------------------------------------

    def add_server(self, config: MCPServerConfig) -> None:
        self._configs[config.name] = config
        logger.info("MCPRegistry: registered server '%s'", config.name)

    def remove_server(self, name: str) -> None:
        self.disconnect(name)
        self._configs.pop(name, None)

    def get_configs(self, tag: Optional[str] = None) -> list[MCPServerConfig]:
        """Return configs, optionally filtered by tag."""
        configs = [c for c in self._configs.values() if c.enabled]
        if tag:
            configs = [c for c in configs if tag in c.tags or "both" in c.tags]
        return configs

    # -- connection lifecycle -------------------------------------------------

    def connect(self, name: str) -> MCPClient:
        """Connect to a single server by name."""
        if name in self._clients:
            return self._clients[name]

        cfg = self._configs.get(name)
        if not cfg:
            raise KeyError(f"Unknown MCP server: {name}")
        if not cfg.enabled:
            raise RuntimeError(f"MCP server '{name}' is disabled")

        transport = MCPTransport(cfg.transport)
        client = MCPClient(
            transport=transport,
            command=cfg.command or None,
            env=cfg.env or None,
            url=cfg.url or None,
            headers=cfg.headers or None,
            name=name,
        )
        client.initialize()
        client.list_tools()
        self._clients[name] = client
        logger.info(
            "MCPRegistry: connected to '%s' (%d tools)",
            name, len(client.tools),
        )
        return client

    def connect_all(self, tag: Optional[str] = None) -> int:
        """Connect to all enabled servers (optionally filtered by tag).

        Returns the number of servers successfully connected.
        """
        connected = 0
        for cfg in self.get_configs(tag):
            try:
                self.connect(cfg.name)
                connected += 1
            except Exception as exc:
                logger.warning(
                    "MCPRegistry: failed to connect to '%s': %s", cfg.name, exc
                )
        return connected

    def disconnect(self, name: str) -> None:
        client = self._clients.pop(name, None)
        if client:
            client.shutdown()

    def disconnect_all(self) -> None:
        for name in list(self._clients):
            self.disconnect(name)

    # -- tool access ----------------------------------------------------------

    def all_tools(self) -> dict[str, list[MCPTool]]:
        """Return {server_name: [tools]} for all connected servers."""
        return {name: client.tools for name, client in self._clients.items()}

    def find_tool(self, tool_name: str) -> Optional[tuple[str, MCPTool]]:
        """Find which server provides a given tool.

        Returns (server_name, MCPTool) or None.
        """
        for name, client in self._clients.items():
            for tool in client.tools:
                if tool.name == tool_name:
                    return (name, tool)
        return None

    def call_tool(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        server: Optional[str] = None,
    ) -> Any:
        """Call a tool, auto-routing to the correct server.

        If *server* is specified, call that server directly.  Otherwise,
        find the first server that advertises the tool.
        """
        if server:
            client = self._clients.get(server)
            if not client:
                raise KeyError(f"Server '{server}' not connected")
            return client.call_tool(tool_name, arguments)

        found = self.find_tool(tool_name)
        if not found:
            raise KeyError(f"No connected server provides tool '{tool_name}'")

        server_name, _ = found
        return self._clients[server_name].call_tool(tool_name, arguments)

    def call_tool_safe(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
        server: Optional[str] = None,
        default: Any = None,
    ) -> Any:
        try:
            return self.call_tool(tool_name, arguments, server)
        except Exception as exc:
            logger.warning("MCPRegistry: tool '%s' failed: %s", tool_name, exc)
            return default

    # -- broadcast ------------------------------------------------------------

    def broadcast_tool(
        self,
        tool_name: str,
        arguments: Optional[dict] = None,
    ) -> dict[str, Any]:
        """Call a tool on *every* connected server that provides it.

        Returns {server_name: result}.  Useful for aggregating data from
        multiple sources.
        """
        results: dict[str, Any] = {}
        for name, client in self._clients.items():
            if client.has_tool(tool_name):
                try:
                    results[name] = client.call_tool(tool_name, arguments)
                except Exception as exc:
                    logger.warning(
                        "MCPRegistry: broadcast '%s' failed on '%s': %s",
                        tool_name, name, exc,
                    )
        return results

    @property
    def connected_servers(self) -> list[str]:
        return list(self._clients.keys())

    def __enter__(self) -> MCPRegistry:
        return self

    def __exit__(self, *args: Any) -> None:
        self.disconnect_all()
