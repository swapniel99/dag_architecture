"""Thin async wrapper around the `cua-driver` CLI.

Each tool call proxies through the daemon socket so the element-index
cache persists across calls. Every call dispatches one subprocess:
    cua-driver call <tool_name> '<json_args>'
and returns the parsed JSON response.

Invariant: ensure_daemon() MUST be called before any get_window_state
+ element-indexed action sequence, or the cache is gone between calls.
"""
from __future__ import annotations

import asyncio
import json

class CUAClient:
    def __init__(self):
        self._mcp_proc: asyncio.subprocess.Process | None = None
        self._mcp_id: int = 0
        self._lock = asyncio.Lock()

    async def _ensure_mcp(self) -> None:
        if self._mcp_proc is None or self._mcp_proc.returncode is not None:
            self._mcp_proc = await asyncio.create_subprocess_exec(
                "cua-driver", "mcp",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=10485760,  # 10MB limit for large MCP payloads
            )

    async def call(self, tool: str, args: dict) -> dict:
        async with self._lock:
            await self._ensure_mcp()
            self._mcp_id += 1
            req = {
                "jsonrpc": "2.0",
                "id": self._mcp_id,
                "method": "tools/call",
                "params": {"name": tool, "arguments": args}
            }
            if not (self._mcp_proc and self._mcp_proc.stdin and self._mcp_proc.stdout):
                raise RuntimeError("cua-driver mcp process unavailable")
            try:
                self._mcp_proc.stdin.write(json.dumps(req).encode() + b"\n")
                await self._mcp_proc.stdin.drain()
            except Exception:
                self._mcp_proc = None
                raise

            while True:
                try:
                    line = await asyncio.wait_for(
                        self._mcp_proc.stdout.readline(), timeout=60
                    )
                except asyncio.TimeoutError:
                    self._mcp_proc = None
                    raise RuntimeError(f"cua-driver {tool}: timed out waiting for response")
                except Exception:
                    self._mcp_proc = None
                    raise
                if not line:
                    self._mcp_proc = None
                    raise RuntimeError("cua-driver mcp died")
                try:
                    resp = json.loads(line)
                except json.JSONDecodeError:
                    continue

                if resp.get("id") == self._mcp_id:
                    if "error" in resp:
                        raise RuntimeError(f"cua-driver {tool}: {resp['error']}")

                    result = resp.get("result", {})
                    content = result.get("content", [])

                    if "structuredContent" in result:
                        return result["structuredContent"]

                    if not content:
                        return {"success": True}
                    raw = content[0].get("text", "")

                    try:
                        return json.loads(raw)
                    except Exception:
                        if raw.startswith("AX action failed") or (not raw.startswith("✅") and "failed" in raw.lower()):
                            raise RuntimeError(f"cua-driver {tool}: {raw}")
                        return {"success": True, "message": raw}

    async def ensure_daemon(self) -> None:
        """Start cua-driver daemon if not already running."""
        proc = await asyncio.create_subprocess_exec(
            "cua-driver", "status",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        if proc.returncode != 0:
            await asyncio.create_subprocess_exec("cua-driver", "serve")
            await asyncio.sleep(1.5)

    async def activate_app(self, app_name: str) -> None:
        """Bring app to foreground via AppleScript (macOS only).

        Required because launch_app uses LaunchServices and does NOT
        steal focus. A backgrounded app's AX window subtree is not
        realized yet, so get_window_state returns element_count=0.
        """
        proc = await asyncio.create_subprocess_exec(
            "osascript", "-e",
            f'tell application "{app_name}" to activate',
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await proc.wait()
        await asyncio.sleep(1.5)
