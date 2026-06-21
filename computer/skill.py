"""Session 10: Computer-Use skill — cascade wrapper over desktop app drivers.

Mirrors browser/skill.py exactly in structure. Translates the orchestrator's
NodeSpec contract into ComputerOutput / AgentResult, and owns the layer cascade:

    Layer 1  — AX extract   (no LLM: read tree_markdown directly)
    Layer 2a — Deterministic (hotkeys list in metadata; no LLM)
    Layer 2b — AXDriver      (AX tree + V9 /v1/chat)
    Electron  — ElectronDriver (CDP via page tool; electron_debugging_port required)
    Layer 3  — VisionDriver  (screenshot + V9 /v1/vision)

Escalation: each layer escalates when its output is empty or insufficient.
The skill stops at the first layer that produces a useful result.

macOS background-launch trap: launch_app does NOT steal focus, so a freshly
launched app's AX window subtree is not yet realized. We always activate via
AppleScript after launch, then wait 0.8 s before the first scan.

Critical: cua-driver daemon must be running (ensure_daemon()) BEFORE any
get_window_state + element-indexed action pair, or the element-index cache
is gone between subprocess calls.
"""
from __future__ import annotations

import asyncio
import time
from pathlib import Path

from browser.client import V9Client
from schemas import AgentResult, ComputerOutput, NodeSpec

from .cua import CUAClient
from .driver import AXDriver, DriverConfig, DriverResult, ElectronDriver, VisionDriver


# App name → bundle ID lookup so planner only needs app_name, not bundle ID.
_APP_NAME_TO_BUNDLE: dict[str, str] = {
    "obsidian":   "md.obsidian",
    "vscode":     "com.microsoft.VSCode",
    "vs code":    "com.microsoft.VSCode",
    "cursor":     "com.todesktop.230313mzl4w4u92",
    "slack":      "com.tinyspeck.slackmacgap",
    "safari":     "com.apple.Safari",
    "chrome":     "com.google.Chrome",
    "notes":      "com.apple.Notes",
    "calculator": "com.apple.calculator",
    "mail":       "com.apple.mail",
    "finder":     "com.apple.finder",
    "textedit":   "com.apple.TextEdit",
    "terminal":   "com.apple.Terminal",
    "xcode":      "com.apple.dt.Xcode",
    "chess":      "com.apple.Chess",
    "grapher":    "com.apple.grapher",
}

# Known Electron apps — skill auto-enables CDP without planner involvement.
_ELECTRON_BUNDLE_IDS: frozenset[str] = frozenset({
    "md.obsidian",
    "com.microsoft.VSCode",
    "com.todesktop.230313mzl4w4u92",  # Cursor
    "com.tinyspeck.slackmacgap",
})
_ELECTRON_DEFAULT_PORT = 9222


class ComputerSkill:
    NAME = "computer"

    def __init__(
        self,
        *,
        gateway_url: str = "http://localhost:8109",
        agent_tag: str = "computer",
        provider_pin: str | None = "gemini",
        artifacts_root: str | None = None,
        max_steps_ax: int = 15,
        max_steps_vision: int = 10,
        session: str | None = None,
    ):
        self.gateway_url = gateway_url
        self.agent_tag = agent_tag
        self.provider_pin = provider_pin
        self.artifacts_root = Path(artifacts_root) if artifacts_root else None
        self.max_steps_ax = max_steps_ax
        self.max_steps_vision = max_steps_vision
        self.session = session

    # ── public entry point ─────────────────────────────────────────────────────
    async def run(self, node: NodeSpec) -> AgentResult:
        goal        = node.metadata.get("goal") or "complete the desktop task"
        bundle_id   = node.metadata.get("app_bundle_id")
        app_name    = node.metadata.get("app_name")
        force_path  = node.metadata.get("force_path")
        hotkeys     = node.metadata.get("hotkeys")   # list[str] for Layer 2a
        eport       = node.metadata.get("electron_debugging_port")

        # Resolve bundle_id from app_name if not explicitly provided.
        # Planner only needs app_name; skill owns all bundle-ID knowledge.
        if not bundle_id and app_name:
            bundle_id = _APP_NAME_TO_BUNDLE.get(app_name.lower().strip())

        if not eport and bundle_id in _ELECTRON_BUNDLE_IDS:
            eport = _ELECTRON_DEFAULT_PORT
        upstream    = "\n".join(node.metadata.get("_upstream_content") or [])

        if not bundle_id and not app_name:
            return self._pack_error("", goal, "interaction_failed",
                                    "metadata.app_bundle_id or metadata.app_name required")

        t0     = time.time()
        cua    = CUAClient()
        client = V9Client(base_url=self.gateway_url, agent=self.agent_tag,
                          session=self.session)

        # ── ensure daemon is running ───────────────────────────────────────────
        await cua.ensure_daemon()

        # ── launch app ────────────────────────────────────────────────────────
        launch_args: dict = {}
        if bundle_id:
            launch_args["bundle_id"] = bundle_id
        elif app_name:
            launch_args["name"] = app_name
        if eport:
            launch_args["electron_debugging_port"] = int(eport)

        try:
            launch_resp = await cua.call("launch_app", launch_args)
        except Exception as e:
            return self._pack_error(bundle_id or app_name or "", goal,
                                    "interaction_failed", f"launch_app failed: {e}")

        pid = launch_resp.get("pid")
        if not pid:
            return self._pack_error(bundle_id or app_name or "", goal,
                                    "interaction_failed",
                                    f"launch_app returned no pid: {launch_resp}")

        # ── get window_id — retry until window appears (fresh launches are slow) ─
        windows = launch_resp.get("windows") or []
        for _attempt in range(6):  # up to ~5s of retries
            if windows:
                break
            await asyncio.sleep(1.0)
            try:
                wins_resp = await cua.call("list_windows", {"pid": pid})
                windows = wins_resp.get("windows") or []
            except Exception:
                pass

        def _pick_window(wins: list) -> int | None:
            # Prefer on-current-space / on-screen; among those, pick largest by area.
            visible = [w for w in wins if w.get("on_current_space") or w.get("is_on_screen")]
            candidates = visible if visible else wins
            if candidates:
                best = max(candidates, key=lambda w: (
                    (w.get("bounds") or {}).get("width", 0) *
                    (w.get("bounds") or {}).get("height", 0)
                ))
                return best.get("window_id")
            return None

        window_id = _pick_window(windows)

        # Some apps (e.g. Chess, sandboxed games) don't expose windows via the
        # window server list but still respond to AX calls on window_id=1.
        if window_id is None and pid:
            try:
                probe = await cua.call("get_window_state", {
                    "pid": pid, "window_id": 1, "capture_mode": "ax",
                })
                if probe.get("element_count", 0) > 0:
                    window_id = 1
            except Exception:
                pass

        if window_id is None:
            return self._pack_error(bundle_id or app_name or "", goal,
                                    "interaction_failed",
                                    "no windows found after launch — permissions may be missing")

        # ── bring app to foreground so AX window tree is realized ─────────────
        # Hidden-launched apps have no on-screen window; AX tree only returns the
        # menu bar until the window is visible. osascript activate is acceptable here.
        activate_name = app_name or (bundle_id or "").split(".")[-1].capitalize()
        await cua.activate_app(activate_name)

        # Re-fetch window_id after activation — a new visible window may appear
        try:
            wins_resp = await cua.call("list_windows", {"pid": pid})
            new_windows = wins_resp.get("windows") or []
            new_wid = _pick_window(new_windows)
            if new_wid is not None:
                window_id = new_wid
        except Exception:
            pass  # keep original window_id

        app_id = bundle_id or app_name or ""

        # ── start recording ───────────────────────────────────────────────────
        recording_dir: str | None = None
        if self.artifacts_root:
            recording_dir = str(self.artifacts_root / f"rec_{int(t0)}")
            try:
                await cua.call("start_recording", {"output_dir": recording_dir})
            except Exception:
                recording_dir = None

        try:
            result = await self._cascade(
                goal=goal, app_id=app_id, force_path=force_path,
                hotkeys=hotkeys, eport=eport, upstream=upstream,
                cua=cua, client=client,
                pid=pid, window_id=window_id, t0=t0,
                recording_dir=recording_dir,
            )
        finally:
            if recording_dir:
                try:
                    await cua.call("stop_recording", {})
                except Exception:
                    pass

        return result

    # ── cascade ────────────────────────────────────────────────────────────────
    async def _cascade(
        self, *, goal, app_id, force_path, hotkeys, eport, upstream,
        cua, client, pid, window_id, t0, recording_dir,
    ) -> AgentResult:

        cfg_ax  = DriverConfig(goal=goal, max_steps=self.max_steps_ax,
                               provider=self.provider_pin)
        cfg_vis = DriverConfig(goal=goal, max_steps=self.max_steps_vision,
                               provider=self.provider_pin)

        # ── Layer 1: AX extract (no LLM) ──────────────────────────────────────
        if force_path not in ("a11y", "electron", "vision", "deterministic"):
            try:
                state = await cua.call("get_window_state", {
                    "pid": pid, "window_id": window_id, "capture_mode": "ax",
                })
                tree_md = state.get("tree_markdown", "")
                if _is_useful_extract(tree_md, goal):
                    return self._pack(app_id, goal, "extract", turns=0,
                                      content=tree_md, elapsed=time.time() - t0,
                                      recording_dir=recording_dir)
            except Exception:
                pass

        # ── Layer 2a: Deterministic hotkeys (plan-then-execute) ──────────────
        # hotkeys from metadata = planner expert override (kept for compat).
        # No metadata hotkeys + no upstream = self-plan via one-shot LLM.
        # Skip when upstream present: dynamic text can't be pre-planned.
        if force_path not in ("a11y", "electron", "vision"):
            planned = hotkeys
            if not planned and not upstream:
                try:
                    planned = await self._plan_hotkeys(cua, client, pid, window_id, goal)
                except Exception:
                    planned = None
            if planned:
                try:
                    content = await self._run_deterministic(cua, pid, window_id, planned)
                    ctx = goal if not upstream else f"{goal}\n\nUpstream context:\n{upstream}"
                    return self._pack(app_id, ctx, "deterministic",
                                      turns=len(planned), content=content,
                                      elapsed=time.time() - t0,
                                      recording_dir=recording_dir)
                except Exception:
                    pass  # fall through to a11y

        # ── Electron/CDP path ──────────────────────────────────────────────────
        if eport and force_path != "vision":
            el_goal = goal
            if upstream:
                el_goal = f"{goal}\n\nUpstream context:\n{upstream}"
            el_drv = ElectronDriver(cua, client, pid, DriverConfig(
                goal=el_goal, max_steps=self.max_steps_ax,
                provider=self.provider_pin,
            ), port=int(eport))
            el_result = await el_drv.run()
            if el_result.success:
                return self._pack_driver("electron", app_id, goal, el_result,
                                         elapsed=time.time() - t0,
                                         recording_dir=recording_dir)
            # fall through to AX driver on Electron failure

        # ── Layer 2b: AX tree + LLM ───────────────────────────────────────────
        if force_path != "vision":
            ax_goal = goal
            if upstream:
                ax_goal = f"{goal}\n\nUpstream context:\n{upstream}"
            ax_drv = AXDriver(cua, client, pid, window_id, DriverConfig(
                goal=ax_goal, max_steps=self.max_steps_ax,
                provider=self.provider_pin,
            ))
            ax_result = await ax_drv.run()
            if ax_result.success:
                return self._pack_driver("a11y", app_id, goal, ax_result,
                                         elapsed=time.time() - t0,
                                         recording_dir=recording_dir)
            # fall through to vision

        # ── Layer 3: Vision (screenshot + set-of-marks) ────────────────────────
        vis_drv = VisionDriver(cua, client, pid, window_id, cfg_vis)
        vis_result = await vis_drv.run()
        if vis_result.success:
            return self._pack_driver("vision", app_id, goal, vis_result,
                                     elapsed=time.time() - t0,
                                     recording_dir=recording_dir)

        return self._pack_error(
            app_id, goal, "interaction_failed",
            f"all layers exhausted; last: {vis_result.note}",
            path="vision",
            turns=len(vis_result.steps),
            actions=[
                {"turn": s.turn, "thinking": s.thinking,
                 "actions": s.actions, "outcome": s.outcome}
                for s in vis_result.steps
            ],
            recording_dir=recording_dir,
            elapsed=time.time() - t0,
        )

    # ── Layer 2a: one-shot LLM → hotkey sequence ─────────────────────────────
    _HOTKEY_PLAN_SCHEMA: dict = {
        "type": "object",
        "required": ["hotkeys"],
        "additionalProperties": False,
        "properties": {
            "hotkeys": {"type": "array", "items": {"type": "string"}},
        },
    }
    _HOTKEY_PLAN_SYS = (
        "You are a macOS keyboard-sequence generator.\n"
        "Output the exact key sequence that accomplishes the goal in this app.\n\n"
        "Rules:\n"
        "- Keys go to the focused app. Pressing '5' activates AXButton '5' — goal\n"
        "  phrasing like 'click the buttons' does NOT require element clicks; keys\n"
        "  work the same way.\n"
        "- Always include a clear/reset key first when using a calculator or form\n"
        "  that may have prior state.\n"
        "- Return hotkeys=[] ONLY IF the task requires: typing a URL in a browser\n"
        "  address bar, typing arbitrary multi-character text strings, typing dynamic\n"
        "  text you do not yet know, or branching on unknown intermediate state.\n"
        "  Do NOT try to type URLs character by character — return [] instead.\n"
        "  Reading the final result AFTER the sequence is always fine.\n\n"
        "Key format: single key as-is (\"5\", \"=\", \"Return\"),\n"
        "modifier combo as \"mod+key\" (\"shift+8\", \"cmd+n\").\n"
        "macOS Calculator: digits \"0\"-\"9\", multiply=\"shift+8\", divide=\"/\",\n"
        "plus=\"shift+=\", minus=\"-\", equals=\"=\", clear=\"c\", decimal=\".\"."
    )

    async def _plan_hotkeys(
        self, cua: "CUAClient", client: "V9Client",
        pid: int, window_id: int, goal: str,
    ) -> list[str] | None:
        import json as _json
        state = await cua.call("get_window_state", {
            "pid": pid, "window_id": window_id, "capture_mode": "ax",
        })
        if state.get("element_count", 0) == 0:
            return None
        tree_md = state.get("tree_markdown", "")[:3000]
        res = await client.chat(
            f"Goal: {goal}\n\nAX Tree:\n{tree_md}",
            system=self._HOTKEY_PLAN_SYS,
            schema=self._HOTKEY_PLAN_SCHEMA,
            schema_name="hotkey_plan",
            max_tokens=256,
            provider=self.provider_pin,
        )
        if hasattr(res, "parsed") and res.parsed is not None:
            plan = res.parsed
        elif isinstance(res, str):
            plan = _json.loads(res)
        else:
            plan = res
        keys = plan.get("hotkeys") or []
        return keys if keys else None

    # ── Layer 2a: execute hotkey sequence and read result ─────────────────────
    async def _run_deterministic(
        self, cua: CUAClient, pid: int, window_id: int,
        hotkeys: list[str],
    ) -> str:
        import re as _re
        state = await cua.call("get_window_state", {
            "pid": pid, "window_id": window_id, "capture_mode": "ax",
        })
        if state.get("element_count", 0) == 0:
            raise RuntimeError("element_count=0 before hotkey sequence")

        for key in hotkeys:
            if "+" in key:
                # modifier combo e.g. "shift+8", "cmd+n"
                parts = key.split("+")
                await cua.call("hotkey", {"pid": pid, "window_id": window_id, "keys": parts})
            else:
                await cua.call("press_key", {"pid": pid, "key": key})
            await asyncio.sleep(0.08)

        await asyncio.sleep(0.3)
        verify = await cua.call("get_window_state", {
            "pid": pid, "window_id": window_id, "capture_mode": "ax",
        })
        tree = verify.get("tree_markdown", "")
        # Extract display values from AXStaticText (e.g. Calculator result)
        statics = _re.findall(r'AXStaticText\s*=\s*"([^"]+)"', tree)
        if statics:
            cleaned = [s.encode("ascii", "ignore").decode().strip() for s in statics]
            cleaned = [s for s in cleaned if s]
            result = cleaned[-1] if cleaned else tree[:300]
            # Normalize Indian comma grouping (e.g. "1,81,288" → "181288")
            # then re-format as standard Western (e.g. "181,288")
            digits_only = result.replace(",", "").replace(".", "")
            if digits_only.lstrip("-").isdigit():
                try:
                    result = f"{int(digits_only):,}"
                except ValueError:
                    pass
            return result
        return tree[:300]

    # ── packers ────────────────────────────────────────────────────────────────
    def _pack(self, app, goal, path, *, turns, content=None, actions=None,
              elapsed=0.0, recording_dir=None) -> AgentResult:
        out = ComputerOutput(
            app=app, goal=goal, path=path, turns=turns,
            content=content, actions=actions or [],
            recording_dir=recording_dir,
        )
        return AgentResult(
            success=True, agent_name=self.NAME,
            output=out.model_dump(), elapsed_s=elapsed,
        )

    def _pack_driver(self, path, app, goal, drv_result: DriverResult,
                     *, elapsed, recording_dir=None) -> AgentResult:
        note = drv_result.note or ""
        actions = [
            {"turn": s.turn, "thinking": s.thinking,
             "actions": s.actions, "outcome": s.outcome}
            for s in drv_result.steps
        ]
        out = ComputerOutput(
            app=app, goal=goal, path=path,
            turns=len(drv_result.steps),
            content=note,
            actions=actions,
            recording_dir=recording_dir,
        )
        return AgentResult(
            success=True, agent_name=self.NAME,
            output=out.model_dump(), elapsed_s=elapsed,
        )

    def _pack_error(self, app, goal, code, msg, *, path: str = "extract",
                    turns: int = 0, actions: list[dict] = [],
                    recording_dir: str | None = None, elapsed=0.0) -> AgentResult:
        out = ComputerOutput(
            app=app or "", goal=goal, path=path,
            turns=turns, content=None, actions=actions,
            recording_dir=recording_dir,
        )
        return AgentResult(
            success=False, agent_name=self.NAME,
            output=out.model_dump(), error=msg, error_code=code,
            elapsed_s=elapsed,
        )


# ── helpers ───────────────────────────────────────────────────────────────────
def _is_useful_extract(tree_md: str, goal: str) -> bool:
    """True when the AX tree text alone satisfies a read-only goal."""
    if len(tree_md) < 150:
        return False
    interactive_verbs = ("click", "type", "fill", "create", "write",
                         "open", "select", "enter", "compute", "calculate",
                         "navigate", "press", "drag")
    if any(v in goal.lower() for v in interactive_verbs):
        return False
    return True
