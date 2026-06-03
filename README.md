# EAGV3 Session 8 — Growing-Graph Multi-Agent Orchestrator

A NetworkX-based multi-agent system where the agent loop is a DAG of typed skill nodes that grows at runtime. Nodes execute in parallel via `asyncio.gather`; the graph is extended by five actors: Planner seed, dynamic successors, static `internal_successors`, Critic auto-insertion, and recovery re-planning.

---

## Quickstart

```bash
# Install
uv sync

# Gateway (separate terminal) — auto-started by flow.py if not running
cd ../gateway && uv run main.py

# Run
uv run python flow.py "your query here"

# Predefined queries
./run_query.sh hello
./run_all.sh
```

---

## Part 1 — Five Base Queries

All five pass in a single `./run_all.sh` run. Logs: `logs.txt`.

### hello — Greeting (2 nodes, 4.8 s)

```
session s8-36d24a12  ─  query: Say hello.
22:45:32 +  4.2s [n:1] planner    complete (0.8s)
22:45:32 +  4.8s [n:2] formatter  complete (0.6s)

FINAL: Hello! How can I help you today?
```

### A — Claude Shannon bio-fetch (5 nodes, 22.7 s)

```
session s8-4ec5ac5c  ─  query: Fetch https://en.wikipedia.org/wiki/Claude_Shannon ...
22:45:38 +  2.7s  [n:1] planner    complete (1.2s)
22:45:55 + 19.9s  [n:2] researcher complete (17.2s)  q=Fetch the Claude Shannon Wikipedia page
22:45:56 + 20.8s  [n:3] distiller  complete (0.9s)
22:45:57 + 21.9s  [n:5] critic     complete (1.1s)   verdict=pass
22:45:58 + 22.7s  [n:4] formatter  complete (0.8s)

FINAL: Claude Shannon was born on April 30, 1916, and passed away on February 24, 2001.
       Three key contributions: (1) establishing communication as message reproduction;
       (2) introducing the bit as information measure; (3) separating source from channel.
```

### I — City populations + closest pair (7 nodes, 18.9 s)

```
session s8-d82de70b  ─  query: Find the populations of London, Paris, Berlin ...
22:46:03 +  2.8s  [n:1] planner     complete (1.3s)
22:46:17 + 16.7s  [n:2] researcher  complete (12.8s)  q=Population of London?
22:46:17 + 16.7s  [n:3] researcher  complete (5.6s)   q=Population of Paris?
22:46:17 + 16.7s  [n:4] researcher  complete (13.7s)  q=Population of Berlin?
22:46:18 + 18.0s  [n:5] coder       complete (1.2s)
22:46:19 + 18.0s  [n:7] sandbox     complete (0.0s)   stdout=London:9100000 Paris:2100000 Berlin:3900000
22:46:19 + 18.9s  [n:6] formatter   complete (0.9s)

FINAL: Paris and Berlin are closest in size (difference: 1,800,000).
```

### J — Graceful failure on nonexistent path (2 nodes, 2.6 s)

```
session s8-035ac57a  ─  query: Read /nonexistent/path.txt and tell me what's in it.
22:46:24 +  1.9s [n:1] planner    complete (0.8s)
22:46:25 +  2.6s [n:2] formatter  complete (0.7s)

FINAL: I am unable to read the file at /nonexistent/path.txt because it does not exist.
```

Planner correctly short-circuits — no indexer or retriever emitted; formatter answers directly.

### K — African city growth rates (7 nodes, 19.0 s)

```
session s8-10e3cf24  ─  query: For Lagos, Cairo, and Kinshasa, find current populations ...
22:46:30 +  2.9s  [n:1] planner     complete (1.4s)
22:46:44 + 16.6s  [n:2] researcher  complete (13.4s)  q=Population and growth rate for Lagos
22:46:44 + 16.6s  [n:3] researcher  complete (6.6s)   q=Population and growth rate for Cairo
22:46:44 + 16.6s  [n:4] researcher  complete (13.5s)  q=Population and growth rate for Kinshasa
22:46:45 + 18.0s  [n:5] coder       complete (1.4s)
22:46:45 + 18.1s  [n:7] sandbox     complete (0.0s)   stdout=Lagos:3.78% Cairo:2.0% Kinshasa:5.85%
22:46:46 + 19.0s  [n:6] formatter   complete (1.0s)

FINAL: Kinshasa is the fastest-growing city with an annual growth rate of 5.85%.
```

---

## Part 2 — Parallel Fan-Out

**Query:** `What is the current unemployment rate in the US, Germany, and Japan? Which country has the lowest rate and by how much?`

**Run:** `./run_query.sh parallel`

The Planner emits three independent Researcher nodes that fire in the same `asyncio.gather` batch:

```
session s8-48b52d29
22:46:52 +  2.9s  [n:1] planner     complete (1.4s)
                         ┌─ n:2 researcher  US        (14.2s) ─┐
           +  2.9s       ├─ n:3 researcher  Germany   ( 7.0s) ─┤  all complete at +17.1s
                         └─ n:4 researcher  Japan     ( 6.6s) ─┘
22:47:06 + 17.1s  [n:2] researcher  complete (14.2s)
22:47:06 + 17.1s  [n:3] researcher  complete (7.0s)
22:47:06 + 17.1s  [n:4] researcher  complete (6.6s)
22:47:07 + 18.3s  [n:5] coder       complete (1.2s)
22:47:07 + 18.3s  [n:7] sandbox     complete (0.0s)   stdout=US:4.3 Germany:3.8 Japan:2.5
22:47:08 + 19.1s  [n:6] formatter   complete (0.8s)

FINAL: Japan has the lowest rate at 2.5% — 1.8pp below the US, 1.3pp below Germany.
```

**Wall-clock proof:**

| Metric | Value |
|--------|-------|
| Parallel layer start | +2.9 s (planner done) |
| Parallel layer end | +17.1 s |
| Parallel layer wall-clock | **14.2 s** (= max branch) |
| Sequential equivalent | 14.2 + 7.0 + 6.6 = **27.8 s** |
| Speedup | **1.96×** |

All three researchers share the same completion timestamp (+17.1s), confirming concurrent execution.

---

## Part 3 — Critic Verdict: Fail → Recovery → Pass

**Query:** `Compute the first 15 Fibonacci numbers and give just the even ones along with their square roots as a csv only and verify the format only.`

**Run:** `./run_query.sh coder_test`

The Planner inserts a Critic between the Coder/Sandbox and the Formatter. The Critic verifies the CSV contains all correct even Fibonacci numbers — a property it can check purely from the output text without tools.

### Attempt 1 — FAIL (missing Fibonacci number 610)

```
22:47:14 +  3.4s  [n:2] coder            complete (1.1s)
22:47:14 +  3.5s  [n:5] sandbox_executor complete (0.0s)  stdout=Number,SquareRoot\n2,...
22:47:17 +  5.8s  [n:3] critic           complete (2.3s)  verdict=fail
                         reason=The CSV omits 610 (and its square root) which should be included
  ↪ critic-fail recovery: planner node n:6 for n:5
```

### Attempt 2 — FAIL (missing Fibonacci number 0)

```
22:47:18 +  6.9s  [n:6]  planner          complete (1.1s)  [recovery]
22:47:19 +  8.0s  [n:7]  coder            complete (1.1s)
22:47:19 +  8.1s  [n:10] sandbox_executor complete (0.0s)  stdout=Fibonacci,SquareRoot\n2,...
22:47:20 +  9.1s  [n:8]  critic           complete (1.0s)  verdict=fail
                          reason=The CSV omits 0 (with square root 0) which should be included
  ↪ critic-fail recovery: planner node n:11 for n:10
```

### Attempt 3 — PASS

```
22:47:21 + 10.3s  [n:11] planner          complete (1.2s)  [recovery]
                          rationale=Generate sequence including 0, filter even, calculate sqrt
22:47:22 + 11.2s  [n:12] coder            complete (0.9s)
22:47:22 + 11.3s  [n:15] sandbox_executor complete (0.0s)  stdout=number,square_root\n0,...
22:47:23 + 12.2s  [n:13] critic           complete (1.0s)  verdict=pass
                          reason=CSV includes all even Fibonacci numbers (0,2,8,34,144) with correct sqrt
22:47:24 + 13.0s  [n:14] formatter        complete (0.8s)

FINAL:
Fibonacci Number,Square Root
0,0.0
2,1.41421356
8,2.82842712
34,5.83095189
144,12.0
```

**Recovery mechanics:** each `verdict=fail` triggers `handle_critic_verdict`, which marks the child formatter `skipped` and splices a new Planner node. That Planner re-reads the failure rationale and emits a corrected Coder prompt. Capped at `MAX_PER_TARGET = 2` re-plans.

---

## Part 4 — Coder Skill

**Prompt:** [`prompts/coder.md`](prompts/coder.md)

The prompt instructs the Coder to:
1. Read `QUESTION` from node metadata for the exact computation task
2. Check `INPUTS` for upstream data to operate on directly (no re-fetching)
3. Write a single self-contained stdlib-only Python script
4. Print the result clearly to stdout for sandbox capture

**Output contract:**
```json
{"code": "<complete python source>", "rationale": "<one short line>"}
```

The orchestrator auto-chains `sandbox_executor` via `internal_successors` in `agent_config.yaml`. No code change needed.

**Demonstration — query I (London/Paris/Berlin):**

The Formatter cannot reliably compute "which two are closest" from three numbers stated in prose — off-by-one errors and misread thousands separators are common. The Coder computes exact absolute differences:

```
[n:5] coder         complete (1.2s)  q=Calculate absolute differences between city populations
[n:7] sandbox       complete (0.0s)  stdout=Populations: {'London':9100000,'Paris':2100000,'Berlin':3900000}
                                            Closest pair: Paris and Berlin (diff=1800000)
```

Same pattern in query K (growth rate comparison) and the parallel query (lowest unemployment by margin).

---

## Part 5 — New Skill: Indexer

**Skill:** `indexer` — indexes local files into the FAISS vector knowledge base so downstream Retriever nodes can search them.

Added to [`agent_config.yaml`](agent_config.yaml):

```yaml
indexer:
  prompt: prompts/indexer.md
  tools_allowed: [list_dir, index_document]
  temperature: 0.1
  max_tokens: 1500
  description: Indexes local files into the vector knowledge base so downstream retriever nodes can search them.
```

**No orchestrator modification required.** The skill uses the existing `tools_allowed` + MCP tool-use path in `mcp_runner.py` — same mechanism as `researcher` and `retriever`.

**Query:** `Index all markdown files in the papers/ directory, then search the knowledge base for three contributions of attention.`

**Run:** `./run_query.sh indexer_test`

```
session s8-4f6e9820
22:47:29 +  2.2s  [n:1] planner   complete (0.9s)
22:47:32 +  5.5s  [n:2] indexer   complete (3.4s)  summary=Indexed papers/attention.md into 2 chunks
22:47:59 + 32.8s  [n:3] retriever complete (27.3s) found=True
                         summary=Three key contributions of the attention Transformer architecture
22:48:00 + 33.9s  [n:4] formatter complete (1.1s)

FINAL: Three key contributions of 'Attention Is All You Need':
       1. Attention-only architecture — first to replace RNN/CNN with pure self-attention.
       2. Parallelizability — no recurrence enables much faster training.
       3. Generalization — state-of-the-art on translation and parsing without task-specific design.
```

The Planner correctly sequences Indexer → Retriever (dependency edge) rather than running them in parallel, since the Retriever needs the index to exist first.

---

## Architecture Summary

```
flow.py (Graph + Executor + CLI)
    ↓ spawns
skills.py (SkillRegistry + run_skill)
    ↓ dispatches via
gateway.py → llm_gatewayV8 :8108
mcp_runner.py → mcp_server.py (tool-use loop)
sandbox.py (subprocess Python runner)
    ↓ persists to
state/sessions/<sid>/graph.json + nodes/n_*.json
```

**Five graph-growth actors:** Planner seed · dynamic successors · static `internal_successors` · Critic auto-insertion · recovery re-plan

**Recovery policy:** transient → skip · validation_error → skip · upstream_failure + planner → skip · upstream_failure + other → replan · critic-fail → replan (cap: 2 per branch)

---

## Running the Full Benchmark

```bash
./run_all.sh 2>&1 | tee logs.txt
```

Runs all 8 queries sequentially (hello, a, i, j, k, parallel, coder_test, indexer_test) and writes the full session log.
