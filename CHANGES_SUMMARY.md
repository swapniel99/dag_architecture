# Code Changes Summary (vs df68e4e)

## flow.py — Executor & Graph

**Internal successor re-wiring** (Bugfix)
- Tracks `last_internal` node from `internal_successors` chain.
- Pending successors of `src_nid` that were pre-wired by the planner are now re-wired to wait for `last_internal` instead (e.g. `formatter` waits for `sandbox_executor`, not `coder` directly).
- Fixes DAG ordering so pre-wired children don't skip intermediate steps.

**Critic auto-insertion scope fix** (Bugfix)
- Previously only guarded newly-added children (`added` list).
- Now guards ALL pending, non-critic successors of `src_nid` — including planner-pre-wired ones.

**`recovered_branches` type change** (Improvement)
- Changed from `dict[str, bool]` to `dict[str, int]` to support the multi-retry cap in `recovery.py`.

**Global critic-fail recovery counter** (Bugfix)
- Replaced `recovered_branches: dict[str, int]` with `critic_recovery_counter: list = [0]` — a mutable single-element list.
- Old per-target cap (`MAX_PER_TARGET=2`) was keyed by target node id. Each recovery cycle produces fresh node ids, so the cap never fired in practice.
- New global cap (`MAX_CRITIC_RECOVERIES=5` in `recovery.py`) fires correctly regardless of how many distinct nodes are targeted across cycles.

**Critic auto-insertion inputs/edges comment** (Documentation)
- Added comment explaining that `child_nid.inputs` intentionally still references `src_nid` (not `critic_nid`) after auto-insertion — critic enforces execution order via edges; data flows directly from the evaluated node.
- Added TODO: propagate `child_nid.metadata.question` into auto-inserted critic metadata, and update `critic.md` to use the QUESTION field for fitness-for-purpose evaluation.

---

## recovery.py — Critic failure handling

**Empty output treated as fail** (Bugfix)
- Critic returning empty/unparseable output previously defaulted to `pass` (missing key → `"pass"`).
- Now: empty output logs a warning and falls through to fail handling so the branch retries.

**Default verdict flipped** (Bugfix)
- `output.get("verdict", "pass")` → `output.get("verdict", "fail")` — safer default when key absent.

**Multi-retry cap (was bool, now int)** (Improvement)
- `recovered_branches[target]` now counts retries (int) instead of a boolean flag.
- `MAX_PER_TARGET = 2` — allows up to 2 recovery re-plans per target before capping.

**Multi-successor skip on critic fail** (Bugfix)
- Planner-emitted critics with multiple successors previously only skipped `succs[0]` on fail. Remaining children stayed pending and could block graph termination or run with unvalidated data.
- Now all successors beyond the first are marked skipped in the `succs[1:]` loop.

**AVAILABLE_NODES and FAILED_NODE in failure report** (Improvement)
- On critic fail, `handle_critic_verdict` now injects two new fields into the recovery planner's `failure_report`:
  - `AVAILABLE_NODES` — all session-completed nodes with labels (excluding critics, planners, and the failed target). Sorted for determinism. Prevents recovery planner from re-running work already done.
  - `FAILED_NODE` — label of the node whose output was rejected by the critic. Prevents recovery planner from reusing bad output.
- Root-cause: ancestor-scoping was tried first (ancestors of `child_nid`) but proved too narrow — parallel completed branches dropped out of scope after the first recovery cycle. Switched to session-wide completed nodes.

---

## prompts/planner.md — Recovery planner instructions

**AVAILABLE_NODES and FAILED_NODE handling** (Improvement)
- Added 3 instruction lines: if `AVAILABLE_NODES` appears in FAILURE block, reference those nodes via `n:<label>` instead of re-running them. If `FAILED_NODE` appears, do not use that node's output — find an alternative approach.

---

## tests/test_recovery.py — Test suite updates

**Counter signature update** (Maintenance)
- Updated 3 critic-fail tests to pass `[0]` (list) instead of `{}` (dict) as the recovery counter argument, matching the new `handle_critic_verdict` signature.
- Cap test updated: `{"n:t": 2}` → `[5]` (counter at MAX), `cap == ["n:t"]` → `cap == [True]`.

---

## skills.py — Tool discovery & prompt rendering

**Static tool catalog removed** (Improvement)
- `_TOOL_CATALOG` dict and `tool_payload()` helper deleted (~45 lines).
- Tool schemas are now fetched live from MCP via `mcp_runner.run_with_tools(tool_names=...)`.

**`question` injected into prompt** (Improvement)
- `render_prompt` accepts new `question` kwarg.
- `run_skill` reads `metadata.question` from the node and passes it into the rendered prompt as `QUESTION: ...`.

---

## mcp_runner.py — Live schema discovery

**`tools_payload` → `tool_names`** (Improvement)
- `run_with_tools` signature changed: takes `tool_names: list[str]` instead of pre-built `tools_payload: list[dict]`.
- On startup, calls `mcp.list_tools()`, filters by `allowed = set(tool_names)`, builds payload dynamically.
- Eliminates need for static catalog; schema always matches the running MCP server.
