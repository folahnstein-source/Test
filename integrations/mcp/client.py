"""MCP (Model Context Protocol) client implementation.

Supports two transports:
  1. **stdio** – spawn a subprocess and communicate over stdin/stdout
  2. **sse** – connect to an HTTP SSE endpoint (Server-Sent Events)

The MCP wire format is JSON-RPC 2.0.  Key lifecycle:

    initialise -> list tools -> call tools -> ... -> shutdown

Reference: https://modelcontextprotocol.io/specification
"""

from __future__ import annotations

import enum
import json
import logging
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Optional

logger = logging.getLogger(__name__)

MCP_PROTOCOL_VERSION = "2024-11-05"


class MCPTransport(str, enum.Enum):
    STDIO = "stdio"
    SSE = "sse"


@dataclass
class MCPTool:
    """Describes a tool advertised by an MCP server."""
    name: str
    description: str = ""
    input_schema: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"MCPTool({self.name!r})"


class MCPClient:
    """Client that speaks MCP over stdio or SSE.

    Usage (stdio)::

        client = MCPClient(
            transport=MCPTransport.STDIO,
            command=["npx", "-y", "@modelcontextprotocol/server-filesystem", "/tmp"],
        )
        client.initialize()
        tools = client.list_tools()
        result = client.call_tool("read_file", {"path": "/tmp/hello.txt"})
        client.shutdown()

    Usage (SSE)::

        client = MCPClient(
            transport=MCPTransport.SSE,
            url="http://localhost:8080/sse",
        )
        client.initialize()
        ...
    """

    def __init__(
        self,
        transport: MCPTransport = MCPTransport.STDIO,
        command: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
        url: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        name: str = "mcp-server",
        timeout: int = 30,
    ) -> None:
        self.transport = transport
        self.name = name
        self._timeout = timeout
        self._request_id = 0
        self._tools: list[MCPTool] = []
        self._initialized = False

        # stdio transport state
        self._command = command
        self._env = env
        self._process: Optional[subprocess.Popen] = None

        # SSE transport state
        self._url = url
        self._sse_headers = headers or {}
        self._sse_endpoint: Optional[str] = None

    # -- JSON-RPC helpers -----------------------------------------------------

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _make_request(self, method: str, params: Optional[dict] = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "id": self._next_id(),
            "method": method,
            "params": params or {},
        }

    def _make_notification(self, method: str, params: Optional[dict] = None) -> dict:
        return {
            "jsonrpc": "2.0",
            "method": method,
            "params": params or {},
        }

    # -- stdio transport ------------------------------------------------------

    def _start_process(self) -> None:
        if not self._command:
            raise ValueError("stdio transport requires 'command'")
        logger.info("MCP [%s]: spawning %s", self.name, self._command)
        self._process = subprocess.Popen(
            self._command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=self._env,
            text=True,
            bufsize=1,
        )

    def _stdio_send(self, message: dict) -> None:
        if not self._process or not self._process.stdin:
            raise RuntimeError("Process not started")
        line = json.dumps(message, ensure_ascii=False) + "\n"
        self._process.stdin.write(line)
        self._process.stdin.flush()
        logger.debug("MCP [%s] -> %s", self.name, line.strip())

    def _stdio_receive(self) -> dict:
        if not self._process or not self._process.stdout:
            raise RuntimeError("Process not started")
        line = self._process.stdout.readline()
        if not line:
            stderr = ""
            if self._process.stderr:
                stderr = self._process.stderr.read()
            raise RuntimeError(
                f"MCP [{self.name}]: process closed stdout. stderr: {stderr}"
            )
        logger.debug("MCP [%s] <- %s", self.name, line.strip())
        return json.loads(line)

    def _stdio_request(self, method: str, params: Optional[dict] = None) -> Any:
        msg = self._make_request(method, params)
        self._stdio_send(msg)
        resp = self._stdio_receive()
        if "error" in resp:
            raise RuntimeError(f"MCP [{self.name}] error: {resp['error']}")
        return resp.get("result")

    # -- SSE transport --------------------------------------------------------

    def _sse_post(self, endpoint: str, payload: dict) -> dict:
        """POST a JSON-RPC message to the SSE server's message endpoint."""
        url = endpoint
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Content-Type": "application/json",
                **self._sse_headers,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self._timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body) if body.strip() else {}
        except (urllib.error.URLError, urllib.error.HTTPError) as exc:
            raise RuntimeError(f"MCP [{self.name}] SSE POST failed: {exc}") from exc

    def _sse_connect(self) -> None:
        """Open SSE connection and discover the message endpoint."""
        if not self._url:
            raise ValueError("SSE transport requires 'url'")

        logger.info("MCP [%s]: connecting to SSE %s", self.name, self._url)
        req = urllib.request.Request(
            self._url,
            headers={
                "Accept": "text/event-stream",
                **self._sse_headers,
            },
        )
        try:
            resp = urllib.request.urlopen(req, timeout=self._timeout)
            # Read the initial SSE event to get the endpoint
            for _ in range(50):  # max lines to scan
                line = resp.readline().decode("utf-8").strip()
                if line.startswith("data:"):
                    data = line[5:].strip()
                    # The SSE server sends the message endpoint URL
                    if data.startswith("http") or data.startswith("/"):
                        self._sse_endpoint = data
                        if not self._sse_endpoint.startswith("http"):
                            # Relative URL — resolve against base
                            parsed = urllib.parse.urlparse(self._url)
                            self._sse_endpoint = (
                                f"{parsed.scheme}://{parsed.netloc}{self._sse_endpoint}"
                            )
                        break
                    # Or it might be a JSON message
                    try:
                        msg = json.loads(data)
                        if "endpoint" in msg:
                            self._sse_endpoint = msg["endpoint"]
                            break
                    except json.JSONDecodeError:
                        pass
            resp.close()
        except Exception as exc:
            logger.warning("MCP [%s]: SSE connect failed: %s", self.name, exc)
            raise

        if not self._sse_endpoint:
            raise RuntimeError(f"MCP [{self.name}]: failed to discover message endpoint from SSE")

        logger.info("MCP [%s]: SSE endpoint = %s", self.name, self._sse_endpoint)

    def _sse_request(self, method: str, params: Optional[dict] = None) -> Any:
        if not self._sse_endpoint:
            raise RuntimeError("SSE not connected")
        payload = self._make_request(method, params)
        resp = self._sse_post(self._sse_endpoint, payload)
        if "error" in resp:
            raise RuntimeError(f"MCP [{self.name}] error: {resp['error']}")
        return resp.get("result")

    # -- transport dispatch ---------------------------------------------------

    def _request(self, method: str, params: Optional[dict] = None) -> Any:
        if self.transport == MCPTransport.STDIO:
            return self._stdio_request(method, params)
        else:
            return self._sse_request(method, params)

    def _send_notification(self, method: str, params: Optional[dict] = None) -> None:
        msg = self._make_notification(method, params)
        if self.transport == MCPTransport.STDIO:
            self._stdio_send(msg)
        elif self._sse_endpoint:
            self._sse_post(self._sse_endpoint, msg)

    # -- MCP lifecycle --------------------------------------------------------

    def initialize(self) -> dict:
        """Perform the MCP initialize handshake."""
        if self.transport == MCPTransport.STDIO:
            self._start_process()
        else:
            self._sse_connect()

        result = self._request("initialize", {
            "protocolVersion": MCP_PROTOCOL_VERSION,
            "capabilities": {},
            "clientInfo": {
                "name": "pe-agents",
                "version": "1.0.0",
            },
        })

        # Send initialized notification
        self._send_notification("notifications/initialized")

        self._initialized = True
        logger.info("MCP [%s]: initialized – server capabilities: %s", self.name, result)
        return result or {}

    def list_tools(self) -> list[MCPTool]:
        """Discover tools offered by the MCP server."""
        result = self._request("tools/list")
        tools_raw = result.get("tools", []) if isinstance(result, dict) else []
        self._tools = [
            MCPTool(
                name=t["name"],
                description=t.get("description", ""),
                input_schema=t.get("inputSchema", {}),
            )
            for t in tools_raw
        ]
        logger.info(
            "MCP [%s]: %d tools available: %s",
            self.name,
            len(self._tools),
            [t.name for t in self._tools],
        )
        return self._tools

    def call_tool(self, tool_name: str, arguments: Optional[dict] = None) -> Any:
        """Invoke a tool on the MCP server and return its result."""
        logger.info("MCP [%s]: calling tool %s(%s)", self.name, tool_name, arguments)
        result = self._request("tools/call", {
            "name": tool_name,
            "arguments": arguments or {},
        })
        # MCP tool results come as a list of content blocks
        if isinstance(result, dict) and "content" in result:
            contents = result["content"]
            texts = [
                c.get("text", "") for c in contents
                if isinstance(c, dict) and c.get("type") == "text"
            ]
            return "\n".join(texts) if texts else result
        return result

    def call_tool_safe(
        self, tool_name: str, arguments: Optional[dict] = None, default: Any = None
    ) -> Any:
        """Like ``call_tool`` but returns *default* on error."""
        try:
            return self.call_tool(tool_name, arguments)
        except Exception as exc:
            logger.warning("MCP [%s]: tool %s failed: %s", self.name, tool_name, exc)
            return default

    @property
    def tools(self) -> list[MCPTool]:
        return list(self._tools)

    def has_tool(self, name: str) -> bool:
        return any(t.name == name for t in self._tools)

    def shutdown(self) -> None:
        """Cleanly shut down the MCP connection."""
        if not self._initialized:
            return
        try:
            self._send_notification("notifications/cancelled", {"reason": "shutdown"})
        except Exception:
            pass

        if self._process:
            self._process.terminate()
            try:
                self._process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self._process.kill()
            self._process = None

        self._initialized = False
        logger.info("MCP [%s]: shut down", self.name)

    def __enter__(self) -> MCPClient:
        self.initialize()
        return self

    def __exit__(self, *args: Any) -> None:
        self.shutdown()

    def __del__(self) -> None:
        self.shutdown()
