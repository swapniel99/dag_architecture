# Session 10: Computer-Use Agent — Detailed Notes

---

## Overview

**Session Title:** Computer-Use Agent
**Nature:** A charter/blueprint session — no complete code is released. Code samples are "shapes" of what you will write. The actual implementation is the assignment.

**Why no shipped code?**
- Computer-use is OS-dependent (Mac ≠ Windows ≠ Linux)
- The real lessons only come from hitting the failure traps yourself

---

## 1. How the World Changed (Context)

In **2024**, building a computer-use agent required a heavy custom perception pipeline: icon detection, OCR, button classifiers, and a VLM on top. This was expensive, brittle, and slow.

By **2026**, three things changed:
- OS **accessibility APIs** got mature Python bindings on all major platforms
- Frontier **VLMs became reliable** on UI screenshots
- A unified driver called **`cua-driver`** exposes all three OS accessibility APIs behind one JSON tool surface

The old 2024 stack collapses into just **two paths**:
1. Read the **accessibility (AX) tree** → ask a cheap text model what to click
2. **Screenshot** → ask a vision model

---

## 2. Key Terms & Glossary

| Term | Meaning |
|---|---|
| **AX tree** | Accessibility tree — a semantic, screen-reader-shaped view of a window's UI elements |
| **cua-driver** | A Rust binary that reads AX trees and synthesises clicks/keystrokes on macOS, Linux, Windows |
| **Daemon** | Long-running `cua-driver serve` process that holds the element-index cache |
| **element_index** | A turn-scoped integer assigned to each actionable AX node |
| **TCC** | macOS Transparency, Consent, Control — gates Accessibility and Screen Recording grants |
| **UAC** | Windows User Account Control — elevation prompt some apps require |
| **Portal** | Linux `org.freedesktop.portal.*` services — how Wayland gates input |
| **CDP** | Chrome DevTools Protocol — drives any Chromium window through CSS selectors |
| **Electron** | Apps that ship a Chromium runtime as their UI (VS Code, Slack, Notion, Discord, Cursor) |
| **Set-of-marks** | A screenshot with numbered boxes over UI regions for a vision model to pick from (from Session 9) |
| **AppleScript activation** | A one-line `osascript` call that brings a macOS app to the foreground |

---

## 3. What `cua-driver` Gives You

- Launches apps, walks AX trees, synthesises **clicks, keystrokes, drags, scrolls, hotkeys, screenshots**, records trajectories
- Speaks **JSON over a Unix socket**
- **34 tools** with uniform control across macOS, Linux, Windows
- Full reference is in `CUA_DRIVER_GUIDE.md`

**What it does NOT do:** planning, goal decomposition, perception interpretation, error recovery, vision. **That is your job.**

You always talk to a running **daemon** — start it once per session:

```python
def ensure_daemon():
    if subprocess.run(["cua-driver", "status"]).returncode != 0:
        subprocess.Popen(["cua-driver", "serve"])
        time.sleep(0.5)
```

---

## 4. What You Can and Cannot Drive

| Target Category | Driveable? | Via What |
|---|---|---|
| Native productivity apps (Calculator, Notes, Mail, Settings, Office) | ✅ Yes | AX tree |
| Electron apps (VS Code, Slack, Discord, Notion, Cursor, Obsidian, Linear, 1Password) | ✅ Yes (with a flag) | CDP, relaunch with `electron_debugging_port` |
| Chrome / Safari / Firefox (rendered page) | ✅ Yes (with a flag) | CDP / Safari Remote Automation |
| Games (OpenGL / Metal / Vulkan / DirectX) | Vision only | Screenshot + click by coordinate |
| Canvas-rendered web (Figma, Google Maps, Photopea) | Vision only | Same |
| DRM-protected players, banking apps, login screens, Touch ID | ❌ No | Deliberately disable AX and forbid synthetic input |
| Elevated apps (installers, system settings on Windows) | Only if agent runs elevated | Match privilege level |

**Two general rules:**
- Apps built with standard platform UI toolkits → full AX tree available
- Apps that paint their own pixels (games, canvas, custom renderers) → no AX tree

---

## 5. The Four Layers (The Cascade)

This mirrors the browser cascade from Session 9, applied to desktop.

```
Layer 1: Extract
  → AX text / clipboard / file contents ($0 cost)

Layer 2a: Deterministic
  → Known hotkeys, fixed sequences ($0 cost)

Layer 2b: A11y Tree
  → AX tree + cheap text LLM (cents)

Layer 3: Vision
  → Screenshot + set-of-marks + vision LLM (dollars)

Precondition: Permissions (TCC / Wayland portal / UAC)
```

**Layer 1 — Extract:** Read content directly from the AX tree, clipboard, or a file. For "what does this email say" or "what's in cell B3," no click is needed. Zero LLM cost. Try this first.

**Layer 2a — Deterministic:** When the goal and hotkeys are known (e.g., "compute 42 × 18 in Calculator"), use `press_key` sequences with no LLM in the loop. Students skip this because it's boring — but it's what keeps the assignment cheap.

**Layer 2b — A11y Tree:** `get_window_state` returns the AX tree as Markdown with actionable elements tagged `[element_index N]`. A cheap text LLM (e.g., free-tier Gemini Flash-Lite via V9 gateway from Session 9) reads the markdown + goal and emits a JSON action. You dispatch by element_index. **This is the workhorse layer — most runs should land here.**

**Layer 3 — Vision:** When AX tree is empty, the target element is missing, or the goal is inherently visual, capture a screenshot → draw numbered marks → send to V9's `/v1/vision` endpoint → click by (x, y). Vision costs ~10× Layer 2b per turn. **Use it as a genuine last resort.** The most common cost mistake is escalating to vision when AX would have worked.

---

## 6. The Scan-Act-Verify Loop

Every turn runs three phases:

1. **Scan** → `get_window_state(pid, window_id)` builds the element index cache
2. **Act** → `click / type_text / press_key / hotkey` addressed by `element_index`
3. **Verify** → `get_window_state(pid, window_id)` confirms state changed

**⚠️ Two Critical Invariants:**

**Invariant 1:** Call `get_window_state` once per turn per window **before** any element-indexed action. Without this, every click fails with `"element_index N not found in cache for pid=..."`.

**Invariant 2:** Every new `get_window_state` snapshot **replaces** the previous index map. UIs reflow (dialogs open, menus pop up, lists re-sort), so element indices shift. An `element_index` from snapshot N is a **turn-scoped token** — re-scan after every state-changing action.

**The verify step is the most important pattern.** A click returning "success" does NOT mean the action achieved its intent — the button might have been disabled, the form might have silently rejected input, or the window may have backgrounded between scan and act.

---

## 7. The Traps That Look the Same

Four different causes all produce the same symptom (`element_count: 0` or a cache miss):

| Symptom | Likely Cause | Guard |
|---|---|---|
| `element_count: 0` on first scan | Permissions not granted (TCC / portal / UAC) | Raise `PermissionsError` immediately |
| `element_count: 0` after launching on macOS | App launched in background, window not realised yet | AppleScript activation + sleep 0.5s + re-scan |
| `element_count: 0` on a Qt app on Linux | `QT_ACCESSIBILITY=1` not set at launch | Set that env var when launching |
| Cache miss on a click that worked last turn | UI reflowed, indices shifted | Re-scan before any element-indexed action |
| `element_count: 0` on Electron apps | Window is one opaque `AXWebArea` to AX | Relaunch with `electron_debugging_port`, use `page` tool |
| `element_count: 0` on games, Figma, Photopea | Renderer paints its own pixels, no AX nodes | Layer 3 vision only, no recovery |

**The single guard that saves the most time:**
```python
state = call("get_window_state", {...})
if state["element_count"] == 0:
    raise PreconditionError(
        "cua-driver returned an empty AX tree. "
        "Check: (1) permissions granted, (2) app activated, "
        "(3) QT_ACCESSIBILITY=1 if Linux/Qt, (4) Electron debugging port if Electron."
    )
```

### 7.1 Permissions

**macOS:** Two TCC grants required — **Accessibility** and **Screen Recording** — attached to `cua-driver`'s bundle ID. Run `cua-driver permissions grant` and accept both dialogs. Granting through terminal binds the grant to the terminal; the driver silently fails later.

**Linux:** X11 needs nothing. Wayland needs a portal grant per session (interactive, not persistent).

**Windows:** Most apps need no special setup. Apps that elevate require the agent to run elevated too.

### 7.2 The Background-Launch Trap (macOS)

`launch_app` uses LaunchServices and **does not steal focus** from the user's foreground app. The response field `self_activation_suppressed: true` confirms this. A backgrounded app's main window is not yet built in the AX hierarchy → first `get_window_state` returns system menu bar and zero app buttons.

**Note:** `bring_to_front` is Windows-only and errors on macOS.

**The workaround:**
```python
subprocess.run(
    ["osascript", "-e", f'tell application "{app_name}" to activate'],
    check=True,
)
time.sleep(0.5)
```
After activation, `get_window_state` returns the full UI (e.g., 237 elements for Calculator).

---

## 8. The Electron Escape Hatch

Many modern desktop apps (VS Code, Cursor, Slack, Discord, Notion, Linear, 1Password, Obsidian) are Chromium browsers in disguise. To AX, they appear as a single opaque `AXWebArea`.

**Solution:** Launch the app with a debugging port → drive its DOM through CDP:

```bash
cua-driver call launch_app '{
  "bundle_id": "com.microsoft.VSCode",
  "electron_debugging_port": 9222
}'

cua-driver call page '{
  "pid": <vscode_pid>,
  "action": "click",
  "selector": ".tabs-container .tab.active"
}'
```

The `page` tool gives you full CDP: CSS selectors, JavaScript evaluation, element waiting, navigation. For Tauri or WebKit-based apps, use `webkit_inspector_port` instead.

**Planner tip:** Read `list_apps`, pattern-match against known Electron apps, and relaunch with debugging port when the target matches. This unlocks the entire CDP path — and the Browser cascade from Session 9 already understands CDP.

**For browsers directly:** Chrome supports `--remote-debugging-port` natively; Safari needs Develop → Allow Remote Automation; recent Firefox builds support CDP.

---

## 9. The Five Layers You Will Build

`cua-driver` gives you perception and action. The five layers above it are yours to implement:

| Layer | What It Does | Cost Knob |
|---|---|---|
| **Goal decomposition** | Maps natural-language goal to ordered app-level subgoals | Frontier vs cheap model for the planner |
| **Perception interpretation** | Filters AX tree markdown into something an LLM can act on | Pre-filter with query arg, summarise with cheap model, regex-extract. **Biggest knob.** |
| **Action sequencing** | Translates subgoals into the scan-act-verify loop | How aggressively you re-scan vs cache |
| **Error recovery** | Handles element gone, permission denied, unexpected modal, app crash | How much state you carry across the failure |
| **Vision fallback** | Screenshot → set-of-marks → V9 vision → parse verdict | Trigger threshold for escalation |

The **Layer 2b judgment LLM** emits a structured action with one of two verdicts:
- `act` — with an `element_index`
- `escalate` — with a reason

Your dispatch reads the verdict and routes accordingly. This mirrors Browser's `output.path` field from Session 9.

---

## 10. Recording and Replay

`cua-driver` ships `start_recording` and `replay_trajectory`. **Use them.**

Every run records to a turn-numbered directory of `(tool, args)` pairs. When the agent fails, the trajectory is the evidence. When it succeeds, it's a regression test.

```python
call("start_recording", {"output_dir": f"/tmp/run-{session_id}"})
try:
    run_agent(goal)
finally:
    call("stop_recording", {})
```

Replay against the same starting UI state:
```python
call("replay_trajectory", {"trajectory_dir": f"/tmp/run-{session_id}"})
```

**The assignment requires recording every submitted run.** The trajectory directory + YouTube demo are your submission evidence.

---

## 11. Wiring into the Session 9 Runtime

Your Computer-Use skill drops into the catalogue alongside Browser from Session 9. Integration is minimal:
- Same catalogue shape: a prompt file, a description, no provider pin
- Add one `if skill.name == "computer"` branch in `skills.py`
- No new gateway — V9 from Session 9 handles all LLM and vision calls
- The replay viewer shows your chosen layer the same way as Browser
- The cost ledger tags calls under `agent: computer`

**Takeaway: Integration is one line. The interesting work is the five layers above the driver.**

---

## 12. Safety (Important — Read Before Any Real Run)

`cua-driver` runs on the **real host** and controls actual apps, sees your files, can read clipboard, navigate authenticated browser sessions. An agent bug can close the wrong file or send the wrong email.

**Recommended safe setup for enterprise/important data:**
- Use a **fresh user account** on the machine for any agent run
- Grant permissions to `cua-driver` under that account
- Agent operates only on **test files** inside that account's home directory
- **Backup** any data the agent might touch
- Use the **verify step** on every action, especially destructive ones
- `kill_app` and `Cmd-Z` are the two recovery primitives — test them before recording
- `cua-driver shutdown` kills the daemon and stops the agent within a second

**Full sandbox path:** `cua` Python SDK with `Sandbox.ephemeral(Image.macos())` — boots a macOS VM. Heavyweight (GBs of disk, slow startup), macOS-only. Covered properly in Session 12.

---

## 13. The Assignment

**Goal:** Build a Computer-Use skill that drops into the Session 9 catalogue and solves **three real tasks** on your primary OS.

### Requirements
- Respect the **five-layer architecture** so the cascade discipline is visible in code
- **Record every run** with `start_recording`; submit the trajectory directory as evidence

### Pick Three Tasks From:
1. A **Calculator or simple-arithmetic** task using deterministic hotkeys (Layer 2a)
2. A **spreadsheet or notes-app** task using AX tree + cheap text LLM (Layer 2b)
3. A task in an **Electron app** (VS Code, Slack, Cursor, Notion, Discord) using `page` tool with `electron_debugging_port`
4. A task in a **canvas-rendered or game-style** target that forces Layer 3 vision (browser game, Figma desktop, sketching app with no ARIA)
5. An **email or message draft** composition exercising Layer 2b with strong verification
6. A **multi-app workflow** that switches between two apps and moves data between them

### Hard Constraints on Task Selection:
- ✅ At least one task uses **vision**
- ✅ At least one task uses the **Electron page path**
- ✅ At least one task completes with **zero vision calls**

### Constraints on Implementation:
- No paid APIs
- No third-party agentic frameworks
- V9 gateway from Session 9 for all LLM and vision calls
- `cua-driver` as the substrate
- Read `CUA_DRIVER_GUIDE.md` before starting

### Submission:
- **GitHub repository README** covering: the five layers architecture, the three tasks, cascade decisions made, failure modes encountered
- **YouTube demo** showing the agent operating live for at least one task with the **agent-cursor overlay visible**

---

## 14. Coming Up in Session 11

Session 11 introduces **channels**. The Computer-Use skill becomes one input among many to an agent that reads from WhatsApp, Slack, voice, and email — and writes back through the same channels. From Session 10 onwards, you own your own code!

---

## Quick Reference Checklist for the Assignment

- [ ] Read `CUA_DRIVER_GUIDE.md`
- [ ] Set up a fresh user account (recommended for safety)
- [ ] Grant TCC permissions (Accessibility + Screen Recording) to `cua-driver`
- [ ] Implement the `ensure_daemon()` function
- [ ] Implement the `element_count == 0` guard and `PreconditionError`
- [ ] Implement AppleScript activation workaround for macOS
- [ ] Implement scan-act-verify loop (re-scan after every state change!)
- [ ] Wire Layer 2b LLM judgment with `act` / `escalate` routing
- [ ] Implement Electron escape hatch with `electron_debugging_port`
- [ ] Implement vision fallback (Layer 3) with set-of-marks
- [ ] Plug skill into Session 9 catalogue (`skills.py` one-liner)
- [ ] Use V9 gateway for all LLM/vision calls
- [ ] Record all runs with `start_recording`
- [ ] Satisfy the three hard constraints (vision ✓, Electron ✓, zero-vision ✓)
- [ ] Write GitHub README covering architecture, tasks, decisions, failures
- [ ] Record YouTube demo with agent-cursor overlay visible
