# EAGV3 Session 10 — Computer-Use Skill

A growing-graph multi-agent orchestrator extended with a **Computer-Use skill** that drives native macOS desktop apps through a five-layer cascade via `cua-driver`, plugging into the same Session 9 runtime without modifying the orchestrator.

**Demo Video:** _[to be added]_

---

## Quickstart

```bash
# Install
uv sync

# Start cua-driver daemon
cua-driver serve &

# Gateway (auto-started by flow.py if not running)
cd ../gateway && uv run main.py

# Run a computer-use task
./run_query.sh task_calc_notes
./run_query.sh task_obsidian        # Obsidian must be pre-launched with CDP port
./run_query.sh task_vision2

# Replay session report
uv run python replay_enhanced.py <session_id>
```

---

## What Was Built

`computer/` — three new files, zero orchestrator modification:

| File | Role |
|---|---|
| `computer/cua.py` | `CUAClient` — wraps `cua-driver call <tool> '<json>'` via asyncio subprocess |
| `computer/driver.py` | `AXDriver` (Layer 2b) + `VisionDriver` (Layer 3) + `ElectronDriver` |
| `computer/skill.py` | `ComputerSkill` — cascade entry point, returns `AgentResult` |

One `if skill.name == "computer"` branch added to `skills.py`. Entry added to `agent_config.yaml`. No other orchestrator files modified.

---

## Five-Layer Architecture

```
Layer 1:  Extract          AX tree read-only → zero LLM cost
Layer 2a: Deterministic    Known hotkey sequences → zero LLM cost
Layer 2b: AX + LLM         get_window_state → tree_markdown → cheap text LLM → element_index action
Electron: CDP              launch_app(electron_debugging_port=9222) → page(selector) via CDP
Layer 3:  Vision           get_window_state(capture_mode=vision) → annotate marks → vision LLM → pixel click
```

Each layer is tried in order. The skill returns as soon as a layer succeeds; vision is a last resort.

**Scan-act-verify invariant:** `get_window_state` is called *before* every element-indexed action (builds the index cache) and *after* every action (confirms state changed). `element_index` values are turn-scoped — they shift on every UI reflow.

**macOS background-launch guard:** `launch_app` does not steal focus. After every `launch_app`, run `osascript activate` + `sleep 0.5` before the first scan, or `element_count` will be 0.

**Recording:** Every run calls `start_recording(output_dir=...)` before the cascade and `stop_recording()` in a `finally` block. Trajectories saved to `state/sessions/<sid>/computer/rec_<ts>/`.

---

## Three Tasks

### Task 1 — Calculator × Notes (multi-app, zero vision)

**Query:** `compute 57 × 83 in the Calculator app using the keypad buttons, then open Notes and create a new note that records the result`

**File:** `queries/task_calc_notes.txt`

**What happens:**
1. Planner emits two `computer` nodes: Calculator node (Layer 2a) → Notes node (Layer 2b), chained via `inputs: ["n:calc"]`.
2. Calculator node uses deterministic hotkeys (`5`, `7`, `×`, `8`, `3`, `=`) — no LLM in the loop.
3. Notes node reads the result from the upstream `AgentResult`, opens Notes via `cmd+n`, types the result into the new note body.

**Layer chosen:** `path=deterministic` (Calculator) + `path=a11y` (Notes)  
**Vision calls:** zero  
**Constraint satisfied:** ✅ zero-vision

---

### Task 2 — Obsidian (Electron / CDP)

**Query:** `find the opening paragraph of the latest AI news article on techcrunch.com and save it as a new Obsidian note titled "AI News"`

**File:** `queries/task_obsidian.txt`

**What happens:**
1. Planner emits a `browser` node for TechCrunch → `distiller` → `computer` node for Obsidian, with distiller output in inputs.
2. Obsidian node detects Electron (`AXWebArea` opaque to AX tree) → launches with `electron_debugging_port=9222` → drives via CDP `page` tool.
3. Creates note via `cmd+n`, sets title, pastes article paragraph via clipboard.

**Layer chosen:** `path=electron` (turns=2)  
**Constraint satisfied:** ✅ Electron

**Setup note:** Obsidian must be launched with the debugging port before the run:
```bash
cua-driver call launch_app '{"bundle_id": "md.obsidian", "electron_debugging_port": 9222}'
```
If Obsidian is already running without the port, the CDP WebSocket is not available and the skill times out on the Electron path.

---

### Task 3 — Chess.app board description (vision, canvas)

**Query:** `open Chess app and describe the current board position — list every visible piece and its square using algebraic notation, and say whose turn it is`

**File:** `queries/task_vision2.txt`

**What happens:**
1. Planner emits one `computer` node for Chess with `force_path="vision"` to bypass AX tree scanning.
2. Skill goes straight to `VisionDriver` (Layer 3).
3. VisionDriver captures screenshot with set-of-marks annotations → vision LLM reads board/pieces and performs the move or describes the position.

**Layer chosen:** `path=vision` (turns=1)  
**Constraint satisfied:** ✅ vision

---

## Cascade Decisions

**When not to escalate to vision:**
- Lichess (`task_vision.txt`) has rich ARIA labels on its board — the a11y path reads piece positions directly. Vision would be 10× more expensive for the same result. The cascade correctly landed on `path=a11y`.
- Notes, Calculator, Mail: full AX trees. Vision never needed.

**When vision is correct:**
- Chess.app 3D board: Metal renderer, no AX nodes for pieces. AXDriver returns `element_count > 0` for window chrome (menu bar, toolbar) but the board area is opaque. `escalate` emitted → VisionDriver.

**Deterministic over AX:**
- Calculator arithmetic is a fixed sequence of button presses. Sending `5`, `7`, `×`, `8`, `3`, `=` via `press_key` is cheaper and more reliable than asking a text LLM to read the AX tree and pick element indices each turn.

**URL typing excluded from Layer 2a:**
- The hotkey planner prompt explicitly excludes URLs and multi-character text from the deterministic path. Attempting to type a URL character-by-character via `press_key` produces double input when Layer 2b also types via clipboard paste (`httpshttps://...`). Layer 2a returns `hotkeys=[]` for any goal requiring text input; Layer 2b handles it with `pbcopy` + `cmd+v`.

---

## Failure Modes Encountered

### 1. Wrong window selected (toolbar vs. main window)

`list_windows` for Safari returned multiple windows. The first window (height=39px, the toolbar strip) was selected instead of the main content window. `get_window_state` on the toolbar returned 0 actionable content elements.

**Fix:** `_pick_window()` in `skill.py` filters for visible windows (on-screen/on-space), and among those candidates, selects the largest by pixel area.

### 2. Chess `list_windows` returns `[]`

Chess is a sandboxed game app. `launch_app` and `list_windows` both return no windows. The standard window-selection code produced `window_id=None` → immediate failure.

**Fix:** After `_pick_window()` returns `None`, probe `window_id=1` directly via `get_window_state(pid, window_id=1, capture_mode="ax")`. If `element_count > 0`, adopt `window_id=1`. Chess responds to AX on window 1 even though the window server doesn't list it.

### 3. Planner split single-app navigation+vision into two nodes

Planner applied the multi-app chaining pattern to tasks like "open Safari, navigate to URL, describe the board." This emitted two `computer` nodes for the same app. The second node re-screenshotted independently (different board state on lichess rotating puzzles) rather than using Layer 1 extract on the first node's output.

**Fix:** Added a "Single-app rule" to `prompts/planner.md`: one computer node per app; the cascade handles AX interaction then escalates to vision internally. Also clarified that `force_path` should not be set just because the final observation is visual.

### 4. VisionDriver `type` action fails for custom input fields

Grapher's equation input field rejects `type_text` from cua-driver (custom renderer). Text was not entered.

**Fix:** VisionDriver's `type` action now uses clipboard paste: `pbcopy` writes the text, then `hotkey(cmd+v)` pastes it. This works for any field that accepts standard paste.

### 5. Obsidian cold-start without CDP port

When Obsidian is not running, `launch_app` without `electron_debugging_port` opens it in normal mode. The CDP WebSocket on port 9222 is never available. The Electron driver times out (~8s) and falls through to the AX path, which returns an opaque `AXWebArea` with no usable elements.

**Root cause:** `launch_app` with `electron_debugging_port` only works if the app is not already running (macOS re-uses the existing process). Pre-launching Obsidian with the port once per session is the reliable workaround.

### 6. Stateless VLM forgets past actions

Chess moves require multi-turn interaction (e.g., click e2 on Turn 1, then click e4 on Turn 2). Since the vision LLM is stateless, it would repeatedly click the starting square without realizing it had already done so.

**Fix:** Pass `Recent actions` (the history of previous actions and their outcomes) into the VisionDriver prompt.

### 7. VLM short-circuits on "describe and move" goals

If a task contains both descriptive and interactive requirements (e.g. "describe board and make a move"), the VLM would call `done` immediately after seeing the initial board, without executing the move.

**Fix:** Clarify in `prompts/computer_vision.md` that for interactive goals, the VLM must perform all required interactions first, and only call `done` on a later turn when all actions are finished.

---

## Architecture

```
flow.py (Graph + Executor + CLI)
    ↓ spawns
skills.py (SkillRegistry + run_skill)
    ├── gateway.py → llm_gatewayV8 :8109   (all LLM skills)
    ├── mcp_runner.py → mcp_server.py       (tool-use loop)
    ├── sandbox.py                          (subprocess Python runner)
    ├── browser/skill.py                   (S9: cascade browser)
    └── computer/skill.py                  (S10: cascade desktop)
            ├── Layer 1:  AX extract (read-only, $0)
            ├── Layer 2a: deterministic hotkeys ($0)
            ├── Layer 2b: AXDriver (AX tree + cheap text LLM)
            ├── Electron: ElectronDriver (CDP via cua-driver page tool)
            └── Layer 3:  VisionDriver (screenshot + set-of-marks + vision LLM)
    ↓ persists to
state/sessions/<sid>/
    graph.json          NetworkX DiGraph (node_link_data)
    query.txt
    nodes/n_*.json      NodeState per node
    computer/           per-turn screenshots + trajectory recordings
```

**Graph growth actors:** Planner seed · dynamic successors · static `internal_successors` · Critic auto-insertion · recovery re-plan

---

## Files

| File | Role |
|---|---|
| `flow.py` | Graph + Executor + CLI |
| `schemas.py` | `AgentResult`, `NodeSpec`, `NodeState`, `BrowserOutput`, `ComputerOutput` |
| `skills.py` | `SkillRegistry`, input resolution, `run_skill` dispatcher |
| `agent_config.yaml` | Skills catalogue — prompt, tools, temperature |
| `recovery.py` | `classify_failure` + `plan_recovery` + `handle_critic_verdict` |
| `computer/cua.py` | `CUAClient` — asyncio subprocess wrapper for cua-driver |
| `computer/driver.py` | `AXDriver` + `VisionDriver` + `ElectronDriver` |
| `computer/skill.py` | `ComputerSkill` — cascade entry point |
| `browser/skill.py` | S9: four-layer browser cascade |
| `browser/driver.py` | `A11yDriver` + `SetOfMarksDriver` |
| `replay_enhanced.py` | Structured 8-section session report |
| `gateway.py` | Bridge to LLM Gateway V9 on `localhost:8109` |
| `persistence.py` | Session writes: `graph.json` + per-node JSON |
| `prompts/computer.md` | System prompt for Layer 2b AX judgment LLM |
| `prompts/computer_vision.md` | System prompt for Layer 3 vision LLM |
| `queries/task_calc_notes.txt` | Task 1: Calculator × Notes (zero vision) |
| `queries/task_obsidian.txt` | Task 2: Obsidian via Electron/CDP |
| `queries/task_vision2.txt` | Task 3: Chess.app board description (vision) |
