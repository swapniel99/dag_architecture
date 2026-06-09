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

---

# New Changes (vs e79bd433)

## browser/dom.py

**Increase DOM element name limit** (Feature)
- Increased character limit for sliced element names under `_ENUMERATE_JS` from 80 to 200 to preserve more descriptive context.

---

## browser/driver.py

**System Prompts Action Constraints & Critical Rules** (Feature / Improvement)
- Reorganized `SYSTEM_PROMPT_VISION` and `SYSTEM_PROMPT_A11Y` to explicitly structure `AVAILABLE ACTIONS` and `CRITICAL RULES`.
- Added critical rule to never bundle `done` with other actions in the same turn.
- Added critical rule to never declare `done` with placeholder/incomplete values when concrete values are required to satisfy the goal.
- Capped actions per turn to at most 2, preferring a single action for most turns.

---

## flow.py — Executor & Graph

**Logging & Verbosity Improvements** (Improvement)
- Added logging of target paths for `browser` skill nodes in the execution trace.
- Removed truncation on the final printed answer, printing the full content instead of slicing to 600 characters.

---

## prompts/distiller.md

**Metric Extraction and Sorting Guidelines** (Improvement)
- Added explicit warnings to be extremely careful when extracting numeric metrics to avoid confusing different metrics.
- Instructed distiller to verify sort, filter, and other settings against the data.

---

## prompts/indexer.md

**Directory Indexing Support** (Feature)
- Updated Indexer role to support indexing directories recursively in addition to single files.
- Updated tool guidelines to explicitly state `index_document` natively supports directory paths.
- Updated Output schema JSON to support multiple `indexed` paths and track `failed` paths.

---

## prompts/planner.md

**Label Constraints and Skill Critic Notes** (Improvement)
- Added instruction to always use short, lowercase alphanumeric IDs (e.g. r1, c1) for labels.
- Added distillery critic notes warning not to manually emit a critic if the writing node is a distiller, and to wire formatter inputs correctly to the writing node.

---

## skills.py — Prompt rendering & dispatch

**Dynamic Tool Payload Delegation** (Refactoring)
- Removed the static hardcoded `_TOOL_CATALOG` and `tool_payload` helper function.
- Updated `run_skill` node execution to pass the list of allowed tool names (`skill.tools_allowed`) to `run_with_tools`.

---

## mcp_runner.py

**Dynamic MCP Tool Fetching** (Feature / Improvement)
- Changed `run_with_tools` to take a list of `allowed_names` instead of a static `tools_payload`.
- Queries the MCP server dynamically with `list_tools()` and filters them against `allowed_names`.

---

## browser/driver.py

**OS-aware select-all keyboard shortcut** (Bugfix)
- Changed input `clear` sequence to detect system platform (`sys.platform`). Uses `Meta+A` on macOS (Darwin) and `Control+A` on Windows/Linux. This avoids cursor-jumping issues that previously broke text clearing on Mac.

---

## browser/skill.py

**Resilient Page Navigation & Interaction Cascade** (Bugfix / Improvement)
- Changed `page.goto` to use `wait_until="load"` instead of `"domcontentloaded"`. This ensures client-side redirects finish loading before the driver runs, preventing context-destruction crashes.
- Added `search`, `set`, and `enter` to `interactive_verbs` in `_is_useful_extract` to prevent the browser skill from short-circuiting on raw HTML extraction when the goal requires input interactions.

---

## browser/dom.py

**Context-destruction recovery in DOM enumeration** (Bugfix)
- Wrapped `enumerate_interactives` in a retry loop (up to 3 attempts with linear backoff) when catching `"Execution context was destroyed"` errors during `page.evaluate`.

