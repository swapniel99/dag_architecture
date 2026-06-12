# EAGV3 Session 9 — Browser Skill + Enhanced Replay

A growing-graph multi-agent orchestrator extended with a **Browser skill** that performs real interactive web browsing via a four-layer cascade, and an **enhanced replay viewer** that produces a structured session report.

**Demo Video:** [Browser Skill](https://youtu.be/_5K4t9dja5c)

---

## Quickstart

```bash
# Install
uv sync

# Gateway (separate terminal) — auto-started by flow.py if not running
cd ../gateway && uv run main.py

# Run a browser query
uv run python flow.py "compare 3 different brand laptops under Rs. 80000 on amazon"

# Enhanced replay report
uv run python replay_enhanced.py <session_id>
uv run python replay_enhanced.py            # list available sessions
```

---

## Browser Skill

### What was built

`browser/skill.py` — the only new file. Plugs into the orchestrator via `agent_config.yaml` (no orchestrator code modified). Implements a four-layer cascade:

| Layer | Mechanism | When used |
|---|---|---|
| 1 — extract | `trafilatura` over bare HTTP GET | Static pages, no interaction needed |
| 2a — deterministic | Playwright + caller-supplied CSS selectors | When `metadata.selectors` given |
| 2b — a11y | `A11yDriver` — LLM drives accessibility tree | Interactive pages, text-only |
| 3 — vision | `SetOfMarksDriver` — LLM drives screenshots | When a11y insufficient |

Gateway-block detection (CAPTCHA / Cloudflare / login wall) short-circuits all layers immediately and surfaces `error_code="gateway_blocked"` for recovery routing.

### Browser skill contract

Input via `NodeSpec.metadata`:
- `url` — page to open (required)
- `goal` — natural-language task (required)
- `selectors` — list of `{action, selector, value?}` for deterministic path (optional)
- `force_path` — pin to `"a11y"` or `"vision"` (optional, for testing)

Output: `BrowserOutput` in `AgentResult.output`:
```json
{
  "url": "...",
  "goal": "...",
  "path": "a11y",
  "turns": 4,
  "content": "...",
  "actions": [{"turn": 1, "actions": [...], "outcome": "ok"}, ...],
  "final_url": "..."
}
```

### No orchestrator modification

Registered in `agent_config.yaml`:
```yaml
browser:
  prompt: prompts/browser.md
  temperature: 0.0
  max_tokens: 1024
  description: |
    Fetches and interacts with web pages through a four-layer cascade
    (extract, deterministic, a11y, vision). metadata.url + metadata.goal required.
```

The dispatcher in `skills.py` routes `skill == "browser"` to `BrowserSkill.run()` directly — same pattern as every other skill.

---

## Demo — Laptop Comparison

**Query:** `compare 3 different brand laptops under Rs. 80000 on amazon`

**Session:** `s8-1c161eb6`

**Run:** `uv run python replay_enhanced.py s8-1c161eb6`

### 1. Original User Goal

```
compare 3 different brand laptops under Rs. 80000 on amazon
```

### 2. Planner DAG

**Initial plan:**
```
browser  → (none)         url=amazon.in/s?k=laptops+under+80000   [b1]
distiller → n:b1                                                   [d1]
formatter → USER_QUERY, n:d1                                       [out]
```

**Recovery plan** (critic rejected two HP laptops — constraint: 3 *different* brands):
```
browser  → (none)         url=amazon.in/s?k=laptops+under+80000   [b1]
distiller → n:b1                                                   [d1]
critic    → n:d1                                                   [c1]
formatter → USER_QUERY, n:d1                                       [out]
```

### 3. Browser Path Chosen

Both browser nodes used **a11y** (A11yDriver via Playwright). Amazon renders product listings with JavaScript, making bare HTTP extract insufficient.

### 4. Browser Actions

**Browser node #1 (n:2) — 4 turns:**
```
turn  1  click mark=83                      [ok]   ← brand filter panel
turn  2  click mark=72                      [ok]   ← select brand filter
turn  3  scroll direction=down value=500    [ok]   ← reveal more results
turn  4  done success=True  → Lenovo ₹73,999 / HP Victus ₹76,990 / HP 15 ₹67,900
```

**Browser node #2 (n:7) — 4 turns, recovery run:**
```
turn  1  click mark=85                                        [ok]   ← search box
turn  2  type "Dell laptop under 80000" + click search        [ok]
turn  3  type "laptop under 80000 INR"  + click search        [ok]
turn  4  done success=True  → Dell ₹76,990 / HP ₹66,990 / Acer ₹48,900
```

Total visible browser actions: **8 actions across 8 turns**.

### 5. Screenshots / Page-State Logs

Per-turn screenshots and accessibility-tree legends saved under `state/sessions/s8-1c161eb6/browser/`:

```
browser_1781290108/a11y/turn_01_raw.png   turn_01_legend.txt
                        turn_02_raw.png   turn_02_legend.txt
                        turn_03_raw.png   turn_03_legend.txt
                        turn_04_raw.png   turn_04_legend.txt

browser_1781290128/a11y/turn_01_raw.png   turn_01_legend.txt
                        turn_02_raw.png   turn_02_legend.txt
                        turn_03_raw.png   turn_03_legend.txt
                        turn_04_raw.png   turn_04_legend.txt
```

### 6. Extracted Data

**Browser node #1 (driver summary):**
```
1. Lenovo Ideapad Slim 3: ₹73,999, 13th Gen Intel Core i7 13620H, 16GB RAM, 512GB SSD.
2. HP Victus: ₹76,990, AMD Ryzen 7 7445HS, 4GB RTX 2050, 16GB DDR5, 512GB SSD.
3. HP 15: ₹67,900, 13th Gen Intel Core i5-1334U, 16GB DDR4, 512GB SSD.
```

**Browser node #2 (driver summary — recovery, 3 distinct brands):**
```
1. Dell: Dell G Series G15-5530, ₹76,990, 13th Gen Intel Core i5-13450HX, NVIDIA RTX 3050-6GB, 16GB DDR5, 512GB SSD.
2. HP: HP 15 Smartchoice fc1038AU, ₹66,990, AMD Ryzen 7 7735HS, 16GB DDR5, 512GB SSD.
3. Acer: Acer Smartchoice Aspire One A114-43, ₹48,900, AMD Ryzen 3-7320U, 8GB LPDDR5, 256GB SSD.
```

### 7. Final Comparison Table

| Brand | Model | Price | Key Specifications |
| :--- | :--- | :--- | :--- |
| Dell | G Series G15-5530 | ₹76,990 | 13th Gen Intel Core i5-13450HX, NVIDIA RTX 3050-6GB, 16GB DDR5, 512GB SSD |
| HP | 15 Smartchoice fc1038AU | ₹66,990 | AMD Ryzen 7 7735HS, 16GB DDR5, 512GB SSD |
| Acer | Smartchoice Aspire One A114-43 | ₹48,900 | AMD Ryzen 3-7320U, 8GB LPDDR5, 256GB SSD |

### 8. Turn Count and Cost Summary

| Node | Skill | Status | Elapsed | Notes |
|---|---|---|---|---|
| n:1 | planner | complete | 1.5s | |
| n:2 | browser | complete | 15.1s | browser_turns=4 |
| n:3 | distiller | complete | 1.4s | |
| n:4 | formatter | **skipped** | — | critic rejected; recovery re-planned |
| n:5 | critic | complete | 1.4s | verdict=fail (two HP brands) |
| n:6 | planner | complete | 2.0s | recovery planner |
| n:7 | browser | complete | 17.6s | browser_turns=4 |
| n:8 | distiller | complete | 1.3s | |
| n:9 | critic | complete | 0.7s | verdict=pass |
| n:10 | formatter | complete | 1.1s | |

**Gateway cost breakdown (session-scoped via `?session=s8-1c161eb6`):**

| Agent | Provider | Calls | In tokens | Out tokens | Cost |
|---|---|---|---|---|---|
| browser | gemini | 8 | 18,065 | 1,129 | $0.000000 |
| critic | groq | 2 | 1,403 | 492 | $0.000579 |
| distiller | gemini | 2 | 10,924 | 581 | $0.000000 |
| formatter | gemini | 1 | 745 | 228 | $0.000000 |
| planner | gemini | 2 | 9,924 | 712 | $0.000000 |
| **TOTAL** | | **15** | **41,061** | **3,142** | **$0.000579** |

- Total nodes (graph): 10 · on disk: 9 · skipped: 1
- Browser nodes: 2 · Total browser turns: 8
- Total elapsed: **42.2s**

---

## Enhanced Replay Viewer (`replay_enhanced.py`)

Prints a structured 8-section report for any session in one non-interactive pass:

```bash
uv run python replay_enhanced.py <session_id>
```

**How it works:**
- Reads `graph.json` for the authoritative node list (catches skipped nodes that have no `.json` file)
- Reconstructs the Planner DAG from planner node output (graph edges are not populated at runtime)
- Shows browser path, per-turn actions, and screenshot paths per browser node
- Fetches real per-agent token and dollar costs from gateway `GET /v1/cost/by_agent?session=<sid>`
- Falls back gracefully if gateway is unreachable

---

## Architecture

```
flow.py (Graph + Executor + CLI)
    ↓ spawns
skills.py (SkillRegistry + run_skill)
    ├── gateway.py → llm_gatewayV8 :8108   (all LLM skills)
    ├── mcp_runner.py → mcp_server.py       (tool-use loop)
    ├── sandbox.py                          (subprocess Python runner)
    └── browser/skill.py                   (S9: cascade browser)
            ├── Layer 1: trafilatura extract
            ├── Layer 2a: deterministic Playwright selectors
            ├── Layer 2b: A11yDriver (accessibility tree + LLM)
            └── Layer 3: SetOfMarksDriver (screenshot + vision LLM)
    ↓ persists to
state/sessions/<sid>/
    graph.json          NetworkX DiGraph (node_link_data)
    query.txt
    nodes/n_*.json      NodeState per node
    browser/            per-turn screenshots + a11y legends
```

**Five graph-growth actors:** Planner seed · dynamic successors · static `internal_successors` · Critic auto-insertion · recovery re-plan

**Recovery policy:**

| Error class | Action |
|---|---|
| transient (503/502/timeout) | skip — gateway already retried |
| validation_error | skip — fix the prompt |
| upstream_failure + skill=planner | skip — would loop |
| upstream_failure + other | replan — new Planner queued |
| critic-fail | replan (cap: `MAX_PER_TARGET = 2` per branch) |

---

## Files

| File | Role |
|---|---|
| `flow.py` | Graph + Executor + CLI. Orchestrator loop. |
| `schemas.py` | `AgentResult`, `NodeSpec`, `NodeState`, `BrowserOutput` |
| `skills.py` | `SkillRegistry`, input resolution, `run_skill` dispatcher |
| `agent_config.yaml` | Skills catalogue — prompt, tools, temperature |
| `recovery.py` | `classify_failure` + `plan_recovery` + `handle_critic_verdict` |
| `browser/skill.py` | S9: four-layer browser cascade |
| `browser/driver.py` | `A11yDriver` + `SetOfMarksDriver` |
| `browser/client.py` | `V9Client` — gateway HTTP client |
| `replay_enhanced.py` | S9: structured 8-field replay report |
| `replay.py` | S8: interactive node-by-node replay |
| `gateway.py` | Bridge to LLM Gateway V8 on `localhost:8108` |
| `persistence.py` | Session writes: `graph.json` + per-node JSON |
| `sandbox.py` | Subprocess Python runner |
| `mcp_runner.py` | Multi-turn tool-use loop |
