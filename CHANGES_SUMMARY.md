# Code Changes Summary (vs df68e4e)

## flow.py — Executor & Graph

**Critic auto-insertion scope fix** (Bugfix)
- Previously only guarded newly-added children (`added` list).
- Now guards ALL non-critic successors of `src_nid` — including planner-pre-wired ones — by iterating `graph.g.successors(src_nid)` directly.
- Also adds `USER_QUERY` to auto-inserted critic inputs so the critic evaluates against the real user ask, not stale FAISS memory hits.

**Internal successor re-wiring restored** (Bugfix)
- When coder completes with `internal_successors: [sandbox_executor]`, any pending successors of coder (e.g. formatter) are re-wired to depend on sandbox_executor instead. Without this, formatter runs in parallel with sandbox_executor and never sees execution results.
- `last_internal` tracks the final internal successor; re-wiring swaps edges and updates `inputs` lists.

**Fan-out empty-inputs fix** (Bugfix)
- `for inp in raw_inputs or [src_nid]` → `for inp in raw_inputs` — empty inputs no longer fall back to the parent node.
- When a planner emits a fan-out worker with `inputs=[]`, a structural parent edge is still added so `ready_nodes` ordering stays correct, but the parent's output does not leak into the worker's INPUTS block.

**Recovery planner amnesia fix — upstream failures** (Improvement)
- On upstream failure (`plan_recovery` → replan), recovery planner now receives `["USER_QUERY"] + prior_complete` as graph inputs, where `prior_complete` is every already-completed non-planner/non-critic node.
- `resolve_inputs` pulls those nodes' outputs into the planner's INPUTS block; `planner.md` recovery section instructs it to wire them by id instead of re-running.

---

## recovery.py — Critic failure handling

**Empty output treated as fail** (Bugfix)
- Critic returning empty/unparseable output previously defaulted to `pass` (missing key → `"pass"`).
- Now: empty output logs a warning and falls through to fail handling so the branch retries.

**Default verdict flipped** (Bugfix)
- `output.get("verdict", "pass")` → `output.get("verdict", "fail")` — safer default when key absent.

**Multi-successor skip on critic fail** (Bugfix)
- Planner-emitted critics with multiple successors previously only skipped `succs[0]` on fail. Remaining children stayed pending and could block graph termination or run with unvalidated data.
- Now all successors beyond the first are marked skipped in the `succs[1:]` loop.

**Recovery planner amnesia fix — critic failures** (Improvement)
- On critic fail, recovery planner now receives `["USER_QUERY"] + prior_complete` as graph inputs (same mechanism as upstream failure path).
- `prior_complete` excludes `target_nid` (the node whose output was rejected) so the planner cannot reuse bad output.
- planner.md recovery section teaches the planner to wire prior results by `n:<id>` instead of re-running them.

---

## prompts/planner.md — Major rewrite

**Browser skill added** (Feature)
- Full documentation for the `browser` skill: when to prefer it over `researcher`, how to set `metadata.url` and `metadata.goal`, cascade behaviour.

**Fan-out scoping instructions** (Improvement)
- Explicit rules: fan-out workers must NOT list `USER_QUERY` in inputs; use `metadata.question` for sub-question scoping. Formatter SHOULD list `USER_QUERY`.

**Recovery section rewritten** (Improvement)
- New recovery instructions: when FAILURE is present and INPUTS contain `n:*` entries, those are prior successful results. Wire them by id, do not re-run. Includes worked example showing a 3-researcher run where 2 succeeded.

---

## skills.py — Prompt rendering & dispatch

**`render_prompt` USER_QUERY scoping** (Improvement)
- `USER_QUERY:` line only injected when `USER_QUERY` is actually in the resolved inputs, not unconditionally. Prevents fan-out workers from seeing the full multi-item query.

**`question` injected into prompt** (Improvement)
- `run_skill` reads `metadata.question` from the node and passes it into the rendered prompt as a `QUESTION:` block — the per-worker sub-question for fan-out.

**Browser skill dispatch** (Feature)
- `run_skill` detects `skill.name == "browser"` and hands off to `BrowserSkill.run(NodeSpec)` directly, bypassing the LLM gateway chat channel.

**Static tool catalog re-introduced** (Revert)
- `_TOOL_CATALOG` dict and `tool_payload()` helper re-added. Live MCP schema discovery (from a prior iteration) was reverted; tool schemas are now built from the static catalog.

---

## mcp_runner.py

**`tool_names` → `tools_payload`** (Revert)
- `run_with_tools` signature reverted to accept `tools_payload: list[dict]` (pre-built schemas) instead of `tool_names: list[str]`. Pairs with skills.py static catalog reintroduction.

---

## browser/ — New module

New 5-file browser module: `__init__.py`, `client.py`, `dom.py`, `driver.py`, `highlight.py`, `skill.py`.
Four-layer cascade: extract → deterministic → a11y → vision. Registered as the `browser` skill.

---

## tests/ — New and updated test files

**test_critic_autoinsert.py** (New)
- 4 tests covering auto-insertion: pre-planned distiller→formatter edge gets critic spliced, existing critic children not re-gated, multi-edge fan-out each guarded, non-critic skills skipped.

**test_recovery_amnesia.py** (New)
- 3 tests covering `prior_complete` in critic-fail recovery: siblings carried, critics/planners excluded, empty prior_complete falls back to USER_QUERY only.

**test_recovery.py** (Updated)
- Critic-fail tests use `dict[str, bool]` for `recovered_branches` — matching current per-target bool cap in `handle_critic_verdict`.
