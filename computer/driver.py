"""Computer-use drivers: AXDriver (Layer 2b), VisionDriver (Layer 3),
ElectronDriver (Electron/CDP path).

Each driver implements the scan-act-verify loop for one cascade layer.
All share CUAClient (subprocess calls to cua-driver daemon) and V9Client
(HTTP calls to the LLM gateway).

Scan-act-verify invariant per turn:
  1. get_window_state  → builds element-index cache in daemon
  2. dispatch action   → click / type_text / press_key / etc.
  3. get_window_state  → confirms state changed (verify)

element_index values are turn-scoped tokens. Re-scan after every
state-changing action or the next click will hit a stale index.
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import aiohttp

from browser.client import V9Client

from .cua import CUAClient

# ── prompts (read once at import time) ───────────────────────────────────────
_PROMPTS = Path(__file__).parent.parent / "prompts"
_AX_SYS  = (_PROMPTS / "computer.md").read_text()
_VIS_SYS = (_PROMPTS / "computer_vision.md").read_text()

_EL_SYS = """You are a CDP (Chrome DevTools Protocol) automation agent for Electron apps.

Each turn you receive the current page text and recent action history.
Emit exactly ONE action per turn as a JSON object with keys: type, selector/javascript/seconds, success, note.

## Action types
execute_javascript(javascript)  — run JS expression; return value is shown next turn
click_element(selector)         — click a CSS-selected DOM element
query_dom(selector)             — list elements matching CSS selector
wait(seconds)                   — pause
done(success, note)             — finish; note = what you did or extracted

## Obsidian-specific (when driving Obsidian)
- Write/create a note (works for new AND existing files):
    app.vault.adapter.write('NoteName.md', 'content').then(()=>'ok').catch(e=>e.message)
- NEVER use app.vault.create — it fails if file already exists.
- After adapter.write returns 'ok': emit done(success=true, note=<content written>).
- Do NOT call write more than once.
- Verify: app.vault.read(app.vault.getAbstractFileByPath('NoteName.md')).then(c=>c)

## Rules
- One action per turn.
- STOP RULE: if the recent actions history shows adapter.write(...) → js returned: ok — the write SUCCEEDED. Your ONLY valid next action is done(success=true, note=<content written>). Do NOT call write again. Do NOT verify. Emit done immediately.
- If an action fails twice in a row, try a different approach.
- done must come ALONE — never bundle with other actions."""


# ── action schemas ────────────────────────────────────────────────────────────
_AX_SCHEMA: dict = {
    "type": "object",
    "required": ["thinking", "actions"],
    "additionalProperties": False,
    "properties": {
        "thinking": {"type": "string"},
        "actions": {
            "type": "array", "minItems": 1, "maxItems": 1,
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string",
                             "enum": ["click", "type", "key", "hotkey",
                                      "scroll", "wait", "done", "escalate"]},
                    "element_index": {"type": "integer"},
                    "value":     {"type": "string"},
                    "direction": {"type": "string"},
                    "amount":    {"type": "integer"},
                    "seconds":   {"type": "number"},
                    "success":   {"type": "boolean"},
                    "note":      {"type": "string"},
                },
            },
        },
    },
}

_VIS_SCHEMA: dict = {
    "type": "object",
    "required": ["thinking", "actions"],
    "additionalProperties": False,
    "properties": {
        "thinking": {"type": "string"},
        "actions": {
            "type": "array", "minItems": 1, "maxItems": 1,
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string",
                             "enum": ["click", "click_xy", "type", "key",
                                      "scroll", "wait", "done"]},
                    "mark":    {"type": "integer"},
                    "x":       {"type": "integer"},
                    "y":       {"type": "integer"},
                    "value":   {"type": "string"},
                    "direction": {"type": "string"},
                    "amount":  {"type": "integer"},
                    "seconds": {"type": "number"},
                    "success": {"type": "boolean"},
                    "note":    {"type": "string"},
                },
            },
        },
    },
}

_EL_SCHEMA: dict = {
    "type": "object",
    "required": ["thinking", "actions"],
    "additionalProperties": False,
    "properties": {
        "thinking": {"type": "string"},
        "actions": {
            "type": "array", "minItems": 1, "maxItems": 1,
            "items": {
                "type": "object",
                "required": ["type"],
                "additionalProperties": False,
                "properties": {
                    "type": {"type": "string",
                             "enum": ["click_element", "execute_javascript",
                                      "query_dom", "wait", "done"]},
                    "selector":   {"type": "string"},   # click_element / query_dom
                    "javascript": {"type": "string"},   # execute_javascript
                    "seconds":    {"type": "number"},   # wait
                    "success":    {"type": "boolean"},
                    "note":       {"type": "string"},
                },
            },
        },
    },
}


# ── shared records ────────────────────────────────────────────────────────────
@dataclass
class DriverConfig:
    goal: str
    max_steps: int = 15
    max_failures: int = 3
    artifacts_dir: Optional[str] = None
    provider: Optional[str] = "gemini"


@dataclass
class StepRecord:
    turn: int
    thinking: str
    actions: list[dict]
    outcome: str


@dataclass
class DriverResult:
    success: bool
    note: str = ""
    steps: list[StepRecord] = field(default_factory=list)


# ── helpers ───────────────────────────────────────────────────────────────────
def _to_data_url(path: str) -> str:
    with open(path, "rb") as f:
        data = f.read()
    ext = Path(path).suffix.lower().lstrip(".")
    mime = "image/png" if ext in ("png", "") else f"image/{ext}"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _parse_response(result) -> dict:
    """Extract parsed dict from GatewayResult, falling back to text parse."""
    if result.parsed:
        return result.parsed
    text = result.text.strip()
    if text.startswith("```"):
        parts = text.split("```")
        text = parts[1] if len(parts) > 1 else parts[0]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


# ── Layer 2b: AX driver ───────────────────────────────────────────────────────
class AXDriver:
    LAYER_NAME = "a11y"

    def __init__(self, cua: CUAClient, client: V9Client,
                 pid: int, window_id: int, cfg: DriverConfig):
        self.cua = cua
        self.client = client
        self.pid = pid
        self.window_id = window_id
        self.cfg = cfg
        self.steps: list[StepRecord] = []

    async def run(self) -> DriverResult:
        failures = 0
        history: list[str] = []

        for turn in range(1, self.cfg.max_steps + 1):
            # ── Scan ──────────────────────────────────────────────────────────
            state = await self.cua.call("get_window_state", {
                "pid": self.pid,
                "window_id": self.window_id,
                "capture_mode": "ax",
            })
            if state.get("element_count", 0) == 0:
                return DriverResult(
                    success=False,
                    note="element_count=0 after scan — escalate to vision",
                    steps=self.steps,
                )

            tree_md = state.get("tree_markdown", "")
            hist_str = "\n".join(history[-5:]) if history else "none"
            prompt = (
                f"Goal: {self.cfg.goal}\n\n"
                f"AX Tree:\n{tree_md}\n\n"
                f"Recent actions:\n{hist_str}"
            )

            # ── Decide ────────────────────────────────────────────────────────
            try:
                res = await self.client.chat(
                    prompt,
                    system=_AX_SYS,
                    schema=_AX_SCHEMA,
                    schema_name="ax_action",
                    max_tokens=512,
                    provider=self.cfg.provider,
                )
                decision = _parse_response(res)
            except Exception as e:
                failures += 1
                history.append(f"turn {turn}: decide_error: {e}")
                if failures >= self.cfg.max_failures:
                    return DriverResult(success=False, note=str(e), steps=self.steps)
                continue

            thinking = decision.get("thinking", "")
            actions = decision.get("actions", [])

            # ── Dispatch each action ──────────────────────────────────────────
            outcomes: list[str] = []
            early_exit: DriverResult | None = None

            for act in actions:
                atype = act.get("type", "")
                outcome = "ok"

                if atype == "done":
                    result = DriverResult(
                        success=act.get("success", True),
                        note=act.get("note") or act.get("value", ""),
                        steps=self.steps,
                    )
                    self.steps.append(StepRecord(turn, thinking, actions, "done"))
                    return result

                if atype == "escalate":
                    early_exit = DriverResult(
                        success=False,
                        note=act.get("note", "escalate requested"),
                        steps=self.steps,
                    )
                    break

                try:
                    outcome = await self._dispatch_one(act)
                    await asyncio.sleep(0.25)
                except Exception as e:
                    outcome = f"failed: {e}"
                    failures += 1

                outcomes.append(outcome)
                history.append(f"turn {turn}: {atype} → {outcome}")

            self.steps.append(StepRecord(turn, thinking, actions, "; ".join(outcomes) or "ok"))

            if early_exit:
                return early_exit

            if any(o.startswith("failed") for o in outcomes):
                if failures >= self.cfg.max_failures:
                    return DriverResult(success=False, note="too many failures", steps=self.steps)

        return DriverResult(success=False, note=f"max_steps={self.cfg.max_steps} reached", steps=self.steps)

    async def _dispatch_one(self, act: dict) -> str:
        atype  = act.get("type", "")
        elem   = act.get("element_index")
        value  = act.get("value", "")
        base   = {"pid": self.pid, "window_id": self.window_id}

        if atype == "click":
            await self.cua.call("click", {**base, "element_index": elem})
        elif atype == "type":
            # type_text silently fails for Catalyst (Notes) and Electron apps.
            # Use clipboard + Cmd+V workaround. Click-to-focus is best-effort:
            # Notes editors (AXWebArea) don't support AXPress so we soft-fail
            # the click and always proceed to paste — the cursor is already
            # focused after cmd+n anyway.
            text = value or ""
            if text:
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
                await asyncio.sleep(0.05)
                if elem is not None:
                    try:
                        await self.cua.call("click", {**base, "element_index": elem})
                        await asyncio.sleep(0.1)
                    except Exception:
                        pass  # element may not support click; proceed to paste
                await self.cua.call("hotkey", {
                    "pid": self.pid, "window_id": self.window_id, "keys": ["cmd", "v"]
                })
        elif atype == "key":
            await self.cua.call("press_key", {"pid": self.pid, "key": value})
        elif atype == "hotkey":
            keys = value.split("+") if isinstance(value, str) else value
            await self.cua.call("hotkey", {"pid": self.pid, "window_id": self.window_id, "keys": keys})
        elif atype == "scroll":
            await self.cua.call("scroll", {
                **base,
                "direction": act.get("direction", "down"),
                "amount": act.get("amount", 300),
            })
        elif atype == "wait":
            await asyncio.sleep(act.get("seconds", 1.0))
        return "ok"


# ── Layer 3: Vision driver ────────────────────────────────────────────────────
class VisionDriver:
    LAYER_NAME = "vision"

    def __init__(self, cua: CUAClient, client: V9Client,
                 pid: int, window_id: int, cfg: DriverConfig):
        self.cua = cua
        self.client = client
        self.pid = pid
        self.window_id = window_id
        self.cfg = cfg
        self.steps: list[StepRecord] = []

    async def run(self) -> DriverResult:
        failures = 0

        for turn in range(1, self.cfg.max_steps + 1):
            # ── Scan (SOM mode: screenshot with numbered marks) ───────────────
            # screenshot_file_path only returned by CLI when screenshot_out_file
            # is explicitly passed — otherwise screenshot is inline base64 only.
            shot_path = os.path.join(
                tempfile.gettempdir(),
                f"cua_{self.pid}_{self.window_id}_{turn}.png"
            )
            state = await self.cua.call("get_window_state", {
                "pid": self.pid,
                "window_id": self.window_id,
                "capture_mode": "som",
                "screenshot_out_file": shot_path,
            })
            screenshot_path = state.get("screenshot_file_path")
            if not screenshot_path and os.path.exists(shot_path):
                screenshot_path = shot_path
            if not screenshot_path:
                return DriverResult(
                    success=False,
                    note="no screenshot returned by cua-driver (check Screen Recording permission)",
                    steps=self.steps,
                )

            image_url = _to_data_url(screenshot_path)
            tree_md = state.get("tree_markdown", "")

            prompt = f"Goal: {self.cfg.goal}"
            if tree_md:
                prompt += f"\n\nAX Tree / element legend:\n{tree_md}"

            # ── Decide ────────────────────────────────────────────────────────
            try:
                res = await self.client.vision(
                    image_data_url=image_url,
                    prompt=prompt,
                    system=_VIS_SYS,
                    schema=_VIS_SCHEMA,
                    schema_name="vis_action",
                    max_tokens=768,
                    provider=self.cfg.provider,
                )
                decision = _parse_response(res)
            except Exception as e:
                failures += 1
                if failures >= self.cfg.max_failures:
                    return DriverResult(success=False, note=str(e), steps=self.steps)
                continue

            thinking = decision.get("thinking", "")
            actions = decision.get("actions", [])

            # ── Dispatch ──────────────────────────────────────────────────────
            outcomes: list[str] = []
            for act in actions:
                atype = act.get("type", "")

                if atype == "done":
                    self.steps.append(StepRecord(turn, thinking, actions, "done"))
                    return DriverResult(
                        success=act.get("success", True),
                        note=act.get("note") or act.get("value", ""),
                        steps=self.steps,
                    )

                try:
                    outcome = await self._dispatch_one(act)
                    await asyncio.sleep(0.8)
                except Exception as e:
                    outcome = f"failed: {e}"
                    failures += 1

                outcomes.append(outcome)

            self.steps.append(StepRecord(turn, thinking, actions, "; ".join(outcomes) or "ok"))
            if failures >= self.cfg.max_failures:
                return DriverResult(success=False, note="too many failures", steps=self.steps)

        return DriverResult(success=False, note=f"max_steps={self.cfg.max_steps} reached", steps=self.steps)

    async def _dispatch_one(self, act: dict) -> str:
        atype = act.get("type", "")
        base  = {"pid": self.pid, "window_id": self.window_id}

        if atype == "click":
            await self.cua.call("click", {**base, "element_index": act["mark"]})
        elif atype == "click_xy":
            await self.cua.call("click", {**base, "x": act["x"], "y": act["y"]})
        elif atype == "type":
            text = act.get("value", "")
            mark = act.get("mark")
            if mark is not None:
                try:
                    await self.cua.call("click", {**base, "element_index": mark})
                    await asyncio.sleep(0.1)
                except Exception:
                    pass
            if text:
                subprocess.run(["pbcopy"], input=text.encode(), check=True)
                await asyncio.sleep(0.05)
                await self.cua.call("hotkey", {
                    "pid": self.pid, "window_id": self.window_id, "keys": ["cmd", "v"]
                })
        elif atype == "key":
            await self.cua.call("press_key", {"pid": self.pid, "key": act.get("value", "")})
        elif atype == "scroll":
            await self.cua.call("scroll", {
                **base,
                "direction": act.get("direction", "down"),
                "amount": act.get("amount", 300),
            })
        elif atype == "wait":
            await asyncio.sleep(act.get("seconds", 1.0))
        return "ok"


# ── Raw CDP client (bypasses cua-driver page tool) ────────────────────────────
class RawCDPClient:
    """Direct WebSocket CDP client — port 9222.

    cua-driver page tool times out in 0.5.7; raw WS works fine.
    One connection per call; stateless across turns.
    """

    def __init__(self, port: int = 9222, timeout: float = 10.0):
        self.port = port
        self.timeout = timeout
        self._ws_url: str | None = None
        self._msg_id = 0

    async def _ws_url_for(self) -> str:
        if self._ws_url:
            return self._ws_url
        # Retry for up to 8s — freshly-launched Electron apps take 2-5s to open CDP.
        deadline = asyncio.get_event_loop().time() + 8.0
        last_err: Exception = RuntimeError("CDP not ready")
        while asyncio.get_event_loop().time() < deadline:
            try:
                t = aiohttp.ClientTimeout(total=3)
                async with aiohttp.ClientSession() as s:
                    r = await s.get(f"http://localhost:{self.port}/json", timeout=t)
                    pages = await r.json(content_type=None)
                for p in pages:
                    if p.get("type") == "page":
                        self._ws_url = p["webSocketDebuggerUrl"]
                        return self._ws_url
                if pages:
                    self._ws_url = pages[0].get("webSocketDebuggerUrl", "")
                    if self._ws_url:
                        return self._ws_url
            except Exception as e:
                last_err = e
            await asyncio.sleep(1.0)
        raise RuntimeError(f"CDP port {self.port} not ready after 8s: {last_err}")

    async def _send(self, method: str, params: dict) -> Any:
        ws_url = await self._ws_url_for()
        self._msg_id += 1
        msg_id = self._msg_id
        t = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession() as s:
            async with s.ws_connect(ws_url, timeout=t) as ws:
                await ws.send_json({"id": msg_id, "method": method, "params": params})
                async for raw in ws:
                    if raw.type == aiohttp.WSMsgType.TEXT:
                        data = json.loads(raw.data)
                        if data.get("id") == msg_id:
                            return data.get("result", {})
        return {}

    async def evaluate(self, expression: str) -> Any:
        result = await self._send("Runtime.evaluate", {
            "expression": expression,
            "returnByValue": True,
            "awaitPromise": True,
        })
        return result.get("result", {}).get("value")

    async def get_text(self) -> str:
        val = await self.evaluate("document.body ? document.body.innerText : ''")
        return str(val or "")[:4000]

    async def click(self, selector: str) -> str:
        val = await self.evaluate(
            f"(function(){{var e=document.querySelector({json.dumps(selector)});"
            f"if(!e)return 'not found';e.click();return 'ok';}})()"
        )
        return str(val or "ok")

    async def query(self, selector: str) -> str:
        val = await self.evaluate(
            f"Array.from(document.querySelectorAll({json.dumps(selector)}))"
            f".map(e=>e.textContent||e.value||e.tagName).join('\\n')"
        )
        return str(val or "")

    async def execute_js(self, js: str) -> str:
        val = await self.evaluate(js)
        return str(val) if val is not None else ""


# ── Electron / CDP driver ─────────────────────────────────────────────────────
class ElectronDriver:
    """Drives Electron apps via Chrome DevTools Protocol through cua-driver's
    `page` tool. Requires the app to have been launched with
    electron_debugging_port set."""
    LAYER_NAME = "electron"

    def __init__(self, cua: CUAClient, client: V9Client,
                 pid: int, cfg: DriverConfig, port: int = 9222):
        self.cua = cua
        self.client = client
        self.pid = pid
        self.cfg = cfg
        self.cdp = RawCDPClient(port=port)
        self.steps: list[StepRecord] = []

    async def run(self) -> DriverResult:
        failures = 0
        history: list[str] = []

        for turn in range(1, self.cfg.max_steps + 1):
            # ── Scan: get current page text via raw CDP ───────────────────────
            try:
                content = await self.cdp.get_text()
            except Exception as _scan_err:
                content = f"(page content unavailable: {_scan_err})"

            hist_str = "\n".join(history[-5:]) if history else "none"
            prompt = (
                f"Goal: {self.cfg.goal}\n\n"
                f"Current page text:\n{content}\n\n"
                f"Recent actions:\n{hist_str}"
            )

            # ── Decide ────────────────────────────────────────────────────────
            try:
                res = await self.client.chat(
                    prompt,
                    system=_EL_SYS,
                    schema=_EL_SCHEMA,
                    schema_name="el_action",
                    max_tokens=512,
                    provider=self.cfg.provider,
                )
                decision = _parse_response(res)
            except Exception as e:
                failures += 1
                history.append(f"turn {turn}: decide_error: {e}")
                if failures >= self.cfg.max_failures:
                    return DriverResult(success=False, note=str(e), steps=self.steps)
                continue

            thinking = decision.get("thinking", "")
            actions = decision.get("actions", [])
            outcomes: list[str] = []

            for act in actions:
                atype = act.get("type", "")

                if atype == "done":
                    self.steps.append(StepRecord(turn, thinking, actions, "done"))
                    return DriverResult(
                        success=act.get("success", True),
                        note=act.get("note") or act.get("value", ""),
                        steps=self.steps,
                    )

                try:
                    outcome = await self._dispatch_one(act)
                    await asyncio.sleep(1.0)
                except Exception as e:
                    outcome = f"failed: {e}"
                    failures += 1

                outcomes.append(outcome)
                js_val = act.get("javascript", act.get("selector", ""))[:80]
                history.append(f"turn {turn}: {atype}({js_val!r}) → {outcome}")

            self.steps.append(StepRecord(turn, thinking, actions, "; ".join(outcomes) or "ok"))
            if failures >= self.cfg.max_failures:
                return DriverResult(success=False, note="too many failures", steps=self.steps)

        return DriverResult(success=False, note=f"max_steps={self.cfg.max_steps} reached", steps=self.steps)

    async def _dispatch_one(self, act: dict) -> str:
        atype = act.get("type", "")

        if atype == "click_element":
            result = await self.cdp.click(act.get("selector", ""))
            return f"click returned: {result}"
        elif atype == "execute_javascript":
            result = await self.cdp.execute_js(act.get("javascript", ""))
            return f"js returned: {result}"
        elif atype == "query_dom":
            result = await self.cdp.query(act.get("selector", ""))
            return f"query returned: {result}"
        elif atype == "wait":
            await asyncio.sleep(act.get("seconds", 1.0))
            return "waited"
        return "ok"
