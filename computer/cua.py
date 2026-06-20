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
import subprocess


class CUAClient:
    async def call(self, tool: str, args: dict) -> dict:
        proc = await asyncio.create_subprocess_exec(
            "cua-driver", "call", tool, json.dumps(args),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode(errors="replace").strip()
            raise RuntimeError(
                f"cua-driver call {tool} failed (rc={proc.returncode}): {err}"
            )
        raw = stdout.decode().strip()
        if not raw:
            return {"success": True}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            # action tools (click, press_key, hotkey) emit plain-text:
            # success lines start with "✅"; anything else is an action failure.
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
