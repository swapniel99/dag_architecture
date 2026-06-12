# Code Changes Summary (vs df68e4e)

## flow.py — Executor & Graph

**Critic auto-insertion scope fix** (Bugfix)
- Previously guarded only newly-added children (`added` list).
- Now guards ALL non-critic successors of `src_nid` — including planner-pre-wired ones — iterating `graph.g.successors(src_nid)` directly.
- Adds `USER_QUERY` to auto-inserted critic inputs so critic evaluates against real user ask, not stale FAISS memory hits.

**Internal successor re-wiring restored** (Bugfix)
- When coder completes with `internal_successors: [sandbox_executor]`, pending coder successors (e.g. formatter) re-wire to depend on sandbox_executor. Without this, formatter runs parallel with sandbox_executor, never sees execution results.
- `last_internal` tracks final internal successor; re-wiring swaps edges and updates `inputs` lists.

**Fan-out empty-inputs fix** (Bugfix)
- `for inp in raw_inputs or [src_nid]` → `for inp in raw_inputs` — empty inputs no longer fall back to parent node.
- When planner emits fan-out worker with `inputs=[]`, structural parent edge still added so `ready_nodes` ordering stays correct, but parent output doesn't leak into worker's INPUTS block.

**Recovery planner amnesia fix — upstream failures** (Improvement)
- On upstream failure (`plan_recovery` → replan), recovery planner receives `["USER_QUERY"] + prior_complete` as graph inputs, where `prior_complete` = every already-completed non-planner/non-critic node.
- `resolve_inputs` pulls those nodes' outputs into planner's INPUTS block; `planner.md` recovery section instructs wire by id instead of re-running.

---

## recovery.py — Critic failure handling

**Empty output treated as fail** (Bugfix)
- Critic returning empty/unparseable output previously defaulted to `pass` (missing key → `"pass"`).
- Now: empty output logs warning and falls through to fail handling so branch retries.

**Default verdict flipped** (Bugfix)
- `output.get("verdict", "pass")` → `output.get("verdict", "fail")` — safer default when key absent.

**Multi-successor skip on critic fail** (Bugfix)
- Planner-emitted critics with multiple successors previously only skipped `succs[0]` on fail. Remaining children stayed pending, could block graph termination or run with unvalidated data.
- Now all successors beyond first marked skipped in `succs[1:]` loop.

**Recovery planner amnesia fix — critic failures** (Improvement)
- On critic fail, recovery planner receives `["USER_QUERY"] + prior_complete` as graph inputs (same mechanism as upstream failure path).
- `prior_complete` excludes `target_nid` (node whose output was rejected) so planner cannot reuse bad output.
- `planner.md` recovery section teaches planner to wire prior results by `n:<id>` instead of re-running.

---

## prompts/planner.md — Major rewrite

**Browser skill added** (Feature)
- Full docs for `browser` skill: when to prefer over `researcher`, how to set `metadata.url` and `metadata.goal`, cascade behaviour.

**Fan-out scoping instructions** (Improvement)
- Explicit rules: fan-out workers must NOT list `USER_QUERY` in inputs; use `metadata.question` for sub-question scoping. Formatter SHOULD list `USER_QUERY`.

**Recovery section rewritten** (Improvement)
- New recovery instructions: when FAILURE present and INPUTS contain `n:*` entries, those are prior successful results. Wire by id, do not re-run. Includes worked example: 3-researcher run where 2 succeeded.

---

## skills.py — Prompt rendering & dispatch

**`render_prompt` USER_QUERY scoping** (Improvement)
- `USER_QUERY:` line injected only when `USER_QUERY` actually in resolved inputs, not unconditionally. Prevents fan-out workers from seeing full multi-item query.

**`question` injected into prompt** (Improvement)
- `run_skill` reads `metadata.question` from node, passes into rendered prompt as `QUESTION:` block — per-worker sub-question for fan-out.

**Browser skill dispatch** (Feature)
- `run_skill` detects `skill.name == "browser"`, hands off to `BrowserSkill.run(NodeSpec)` directly, bypassing LLM gateway chat channel.

---

## browser/ — New module

New 5-file browser module: `__init__.py`, `client.py`, `dom.py`, `driver.py`, `highlight.py`, `skill.py`.
Four-layer cascade: extract → deterministic → a11y → vision. Registered as `browser` skill.

---

## tests/ — New and updated test files

**test_critic_autoinsert.py** (New)
- 4 tests: pre-planned distiller→formatter edge gets critic spliced, existing critic children not re-gated, multi-edge fan-out each guarded, non-critic skills skipped.

**test_recovery_amnesia.py** (New)
- 3 tests covering `prior_complete` in critic-fail recovery: siblings carried, critics/planners excluded, empty prior_complete falls back to USER_QUERY only.

**test_recovery.py** (Updated)
- Critic-fail tests use `dict[str, bool]` for `recovered_branches` — matching current per-target bool cap in `handle_critic_verdict`.

---

# New Changes (vs e79bd433)

## browser/dom.py

**Increase DOM element name limit** (Feature)
- Character limit for sliced element names under `_ENUMERATE_JS` increased 80 → 200 to preserve more descriptive context.

---

## browser/driver.py

**System Prompts Action Constraints & Critical Rules** (Feature / Improvement)
- Reorganized `SYSTEM_PROMPT_VISION` and `SYSTEM_PROMPT_A11Y` to explicitly structure `AVAILABLE ACTIONS` and `CRITICAL RULES`.
- Critical rule: never bundle `done` with other actions same turn.
- Critical rule: never declare `done` with placeholder/incomplete values when concrete values required.
- Capped actions per turn to at most 2, preferring single action most turns.

---

## flow.py — Executor & Graph

**Logging & Verbosity Improvements** (Improvement)
- Added logging of target paths for `browser` skill nodes in execution trace.
- Removed truncation on final printed answer; prints full content instead of slicing to 600 chars.

**Avoid Duplicate Critic Auto-insertion** (Improvement)
- Checks if critic node already successor before auto-attaching. If planner manually attached critic, auto-insertion skipped.

---

## prompts/distiller.md

**Metric Extraction and Sorting Guidelines** (Improvement)
- Added explicit warnings: be extremely careful extracting numeric metrics to avoid confusing different metrics.
- Instructs distiller to verify sort, filter, and other settings against data.

---

## prompts/indexer.md

**Directory Indexing Support** (Feature)
- Updated Indexer role to support recursive directory indexing in addition to single files.
- Updated tool guidelines: `index_document` natively supports directory paths.
- Updated Output schema JSON to support multiple `indexed` paths and track `failed` paths.

---

## prompts/planner.md

**Label Constraints** (Improvement)
- Added instruction: always use short, lowercase alphanumeric IDs (e.g. r1, c1) for labels.

---

## skills.py — Prompt rendering & dispatch

**Dynamic Tool Payload Delegation** (Refactoring)
- Removed static hardcoded `_TOOL_CATALOG` and `tool_payload` helper.
- `run_skill` now passes list of allowed tool names (`skill.tools_allowed`) to `run_with_tools`.

---

## mcp_runner.py

**Dynamic MCP Tool Fetching** (Feature / Improvement)
- `run_with_tools` takes list of `allowed_names` instead of static `tools_payload`.
- Queries MCP server dynamically with `list_tools()`, filters against `allowed_names`.

---

## browser/driver.py

**OS-aware select-all keyboard shortcut** (Bugfix)
- Input `clear` sequence detects `sys.platform`. Uses `Meta+A` on macOS (Darwin), `Control+A` on Windows/Linux. Fixes cursor-jumping that broke text clearing on Mac.

---

## browser/skill.py

**Resilient Page Navigation & Interaction Cascade** (Bugfix / Improvement)
- Added `search`, `set`, `enter` to `interactive_verbs` in `_is_useful_extract` to prevent browser skill short-circuiting on raw HTML extraction when goal requires input interactions.

---

## browser/dom.py

**Context-destruction recovery in DOM enumeration** (Bugfix)
- Wrapped `enumerate_interactives` in retry loop (up to 3 attempts, linear backoff) catching `"Execution context was destroyed"` errors during `page.evaluate`.

---

## New Changes (vs commit 4ae18fe)

### prompts/planner.md

**Explicit Constraint Propagation in Scoped Workers** (Improvement)
- Added scoping guidelines in `Scoping a worker — IMPORTANT`: `metadata.question` or `metadata.goal` must explicitly carry all qualifiers and constraints (weights, purity, filters) from original user query.
- Added distiller instruction: list all required fields and filters in `metadata.question` on first plan to avoid vague extraction targets.

---

### browser/driver.py

**Turn-by-turn Page Settling** (Improvement)
- Added `page.wait_for_load_state("domcontentloaded")` and `1.0` second sleep at start of `step()` before `enumerate_interactives`. Ensures client-side hydration and animations settle after actions before capturing snapshots.

---

## New Changes (vs commit 5c2d7f8)

### flow.py — Executor & Graph

**Propagate Target Question to Auto-critic** (Improvement)
- Auto-inserted critic nodes inherit target node's scoped sub-question if present.
- Sub-question formatted as validation instruction.

---

## New Changes (vs commit 30518bf)

### flow.py — Executor & Graph

**Enforce USER_QUERY on planner-emitted critic nodes** (Bugfix)
- Recovery planners sometimes omitted `USER_QUERY` from manually-emitted critic inputs, preventing critics from checking budget/count constraints from original query.
- After Pass 2 input resolution, any critic node lacking `USER_QUERY` in resolved inputs has it prepended automatically.

**Planner-emitted critic now gates downstream nodes** (Bugfix)
- When `critic:true` skill (e.g. distiller) completed and planner already manually attached critic, old `has_critic=True` branch skipped auto-insertion but did NOT rewire non-critic successors through existing critic. Formatters ran immediately after distiller, ignoring critic verdict entirely.
- Replaced boolean `has_critic` check with `existing_critic` lookup. When critic exists, non-critic successors re-wired: `src_nid → child` edge replaced with `existing_critic → child`. Execution gated by critic; data inputs still reference distiller.

### browser/driver.py

**Done-note fallback to `value` field** (Bugfix)
- LLMs occasionally write `value` instead of `note` in `done` actions. `step()` only read `a.get("note", "")`, silently dropping extraction summary. Fix: `a.get("note", "") or a.get("value", "")`.

**Action repetition loop guard** (Bugfix)
- Driver had no mechanism to detect spinning loops (e.g. repeatedly typing same search term). Added fingerprint check in `run()`: if last 3 consecutive turns have identical action lists, bail with `DriverResult(success=False, note="stuck in action loop...")` instead of burning all remaining steps.

**Count and filter verification instructions** (Improvement)
- Both `SYSTEM_PROMPT_VISION` and `SYSTEM_PROMPT_A11Y`: added instructions to verify filter state after each filter click (URL params/badges), verify visible result count matches goal before calling `done(success=True)`, use `note` (not `value`) in done actions.

### browser/skill.py

**Surface driver done-note in output** (Bugfix)
- `_pack_driver` discarded `drv_result.note` (LLM's extraction summary from `done(note=...)`) and only used raw trafilatura page extract. Downstream distillers received full page HTML with no signal about what driver actually found.
- Now prepends `[driver extracted: <note>]` to trafilatura content when note non-empty, giving distillers ground-truth signal alongside raw page text.