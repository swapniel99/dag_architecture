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
