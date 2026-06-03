# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Prerequisites

The orchestrator bridges to **llm_gatewayV8** on `localhost:8108`. The gateway must be built and reachable before running `flow.py`. `gateway.py` auto-starts it from the sibling `../gateway/` directory on first run. Override the location with `EAGV3_GATEWAY_DIR=<path>`.

Copy `.env` with required API keys (Tavily, provider credentials, etc.) — `gateway.py` calls `load_dotenv()` at import time.

## Commands

```bash
# Install dependencies
uv sync

# Run the agent
uv run python flow.py "your query here"

# Run a predefined query from queries/
./run_query.sh <query_id>          # clears state first
./run_query.sh <query_id> --no-clear

# Run all predefined queries sequentially
./run_all.sh

# Replay a session trace
uv run python replay.py <session_id>

# Clear state (sessions + artifacts)
./clear_state.sh

# Resume a crashed session
uv run python flow.py --resume <session_id>
```

Pytest markers: `network` (needs internet), `embed` (needs gateway V8 embedding endpoint). Skip them with `-m "not network and not embed"`.

## Architecture

This is a **growing-graph multi-agent orchestrator**. The agent loop is a `networkx.DiGraph` where each node is a typed skill and edges carry `AgentResult` payloads. Ready nodes execute in parallel via `asyncio.gather`. Hard cap: `MAX_NODES = 60` (flow.py).

### Key files (read in this order)

| File | Role |
|---|---|
| `flow.py` | `Graph` + `Executor` + CLI. The orchestrator loop lives here. Read first. |
| `schemas.py` | `AgentResult`, `NodeSpec`, `NodeState`, `MemoryItem` — the typed boundary between all layers |
| `skills.py` | `SkillRegistry`, input resolution, prompt rendering, `run_skill` dispatcher |
| `agent_config.yaml` | Skills catalogue: prompt path, tools, temperature, `internal_successors`, `critic` flag |
| `recovery.py` | `classify_failure` + `plan_recovery` + `handle_critic_verdict` |
| `sandbox.py` | Subprocess Python runner (usability boundary, NOT security isolation) |
| `gateway.py` | Bridge to LLM Gateway V8 on `localhost:8108`; auto-starts the gateway if not running |
| `persistence.py` | Session writes: `graph.json` + per-node JSON in `state/sessions/<sid>/` |
| `mcp_runner.py` | Multi-turn tool-use loop for skills with `tools_allowed` |

### How the graph grows (5 actors)

1. **Planner seed** — first node always; emits initial DAG via `nodes` list in JSON output
2. **Dynamic successors** — any skill can emit `successors` in its `AgentResult.output`
3. **Static `internal_successors`** — wired in `agent_config.yaml` (e.g., `coder → sandbox_executor`)
4. **Critic auto-insertion** — when a `critic: true` skill (Distiller) completes, a Critic node is auto-inserted before each child
5. **Recovery re-plan** — on node failure, `plan_recovery` either skips or queues a new Planner node

### Skill contract

Every LLM-backed skill must return a single JSON object (no markdown fences). The orchestrator lifts these fields out:
- `successors` — list of `NodeSpec` dicts `{skill, inputs, metadata}`
- `nodes` — Planner-only alias for `successors`

Everything else in the JSON lands in `AgentResult.output` and flows to downstream nodes.

Per-skill `temperature` and `max_tokens` are tuned in `agent_config.yaml` — no code edits needed.

### Available skills

| Skill | Tools | Notes |
|---|---|---|
| `planner` | — | Decomposes queries into DAG; drives recovery re-plans |
| `retriever` | `search_knowledge` | FAISS + memory search |
| `researcher` | `web_search`, `fetch_url` | Multi-step web research |
| `distiller` | — | Extracts structured fields; `critic: true` → auto-inserts Critic on outgoing edges |
| `summariser` | — | Condenses long content |
| `critic` | — | Pass/fail evaluator; `verdict` in output |
| `formatter` | — | Terminal node; `output.final_answer` is what Executor returns |
| `coder` | — | Emits `{"code": "...", "rationale": "..."}` |
| `sandbox_executor` | — | Runs coder output; auto-chained via `internal_successors` |
| `indexer` | `list_dir`, `read_file`, `index_document` | Populates FAISS index |
| `browser` | — | STUB — reserved for Session 9 |

### Coder skill (student assignment)

`prompts/coder.md` is the stub to implement. Required output:
```json
{"code": "<python source>", "rationale": "<one short line>"}
```
The orchestrator auto-chains `sandbox_executor` after every `coder` node via `internal_successors`. The `sandbox_executor` pulls `output["code"]` from the upstream coder result and runs `sandbox.run_python(code)`.

### Input reference forms (in `skills.py:resolve_inputs`)

- `"USER_QUERY"` — original user query
- `"n:<label>"` — output of a completed upstream node (matched by `metadata.label`)
- `"art:<sha>"` — artifact bytes
- Bare string — passed through as a literal

### Session persistence layout

```
state/sessions/<sid>/
    graph.json        # NetworkX DiGraph serialised via node_link_data (not pickle)
    query.txt
    nodes/
        n_001.json    # NodeState per node
```

Legacy sessions written as `graph.pkl` are tolerated on resume but new sessions always write JSON.

### Recovery policy (`recovery.py`)

| Error class | Action |
|---|---|
| transient (503/502/timeout) | skip — gateway already retried |
| validation_error (malformed NodeSpec) | skip — fix the prompt |
| upstream_failure + skill=planner | skip — would loop |
| upstream_failure + other skill | replan — new Planner queued |

Critic-fail: child node marked `skipped`; recovery Planner queued; capped at `MAX_PER_TARGET = 2` re-plans per branch.

### Do not modify

`perception.py`, `decision.py`, `action.py`, `memory.py`, `vector_index.py`, `artifacts.py`, `mcp_server.py` — S7 carryover, byte-identical contract. Treat `gateway/` as a service; do not patch it.
