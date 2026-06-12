"""Enhanced replay viewer for S9 sessions.

Prints a structured report covering all 8 required submission fields:
  1. Original user goal
  2. Planner DAG
  3. Browser path chosen (extract / deterministic / a11y / vision / blocked)
  4. Browser actions taken
  5. Screenshots / page-state logs
  6. Extracted data
  7. Final comparison table
  8. Turn count and cost summary

Usage:
    uv run python replay_enhanced.py <session_id>
    uv run python replay_enhanced.py           # lists available sessions
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

from persistence import SessionStore, list_sessions
from schemas import NodeState

GATEWAY_URL = "http://localhost:8109"


def _fetch_gateway_costs(session_id: str) -> dict[str, dict]:
    """Fetch per-agent cost breakdown from gateway for this session.
    Returns {agent_name: {calls, in_tok, out_tok, dollars, provider}} or {}."""
    try:
        r = httpx.get(f"{GATEWAY_URL}/v1/cost/by_agent",
                      params={"session": session_id}, timeout=5.0)
        r.raise_for_status()
        data = r.json()
        # Response shape: {agent_name: [list of per-provider rows]}
        result: dict[str, dict] = {}
        for agent, rows in data.items():
            agg = {"calls": 0, "in_tok": 0, "out_tok": 0, "dollars": 0.0,
                   "providers": []}
            for row in rows:
                agg["calls"] += row.get("calls", 0)
                agg["in_tok"] += row.get("in_tok", 0)
                agg["out_tok"] += row.get("out_tok", 0)
                agg["dollars"] += row.get("dollars", 0.0)
                agg["providers"].append(row.get("provider", "?"))
            result[agent] = agg
        return result
    except Exception:
        return {}

W = 78
DIV = "─" * W
THICK = "═" * W


def _hdr(title: str) -> None:
    print()
    print(THICK)
    print(f"  {title}")
    print(THICK)


def _sec(title: str) -> None:
    print()
    print(f"── {title} {'─' * max(0, W - len(title) - 4)}")


def _planner_dag(states: list[NodeState]) -> None:
    """Reconstruct DAG from planner nodes (graph.json edges are empty)."""
    _hdr("2. PLANNER DAG")
    planners = [s for s in states if s.skill == "planner"]
    if not planners:
        print("  (no planner nodes found)")
        return
    for pidx, ps in enumerate(planners, 1):
        if pidx > 1:
            print(f"\n  [recovery planner #{pidx}]")
        out = (ps.result.output if ps.result else {}) or {}
        nodes_list = out.get("nodes") or out.get("successors") or []
        rationale = out.get("rationale", "")
        if rationale:
            print(f"  rationale: {rationale[:200]}")
        if not nodes_list:
            print("  (no nodes emitted)")
            continue
        print()
        print(f"  {'NODE':<8} {'SKILL':<20} {'INPUTS':<30} LABEL")
        print(f"  {'----':<8} {'-----':<20} {'------':<30} -----")
        for i, n in enumerate(nodes_list, 1):
            skill = n.get("skill", "?")
            inputs = ", ".join(n.get("inputs", [])) or "(none)"
            label = n.get("metadata", {}).get("label", "")
            url = n.get("metadata", {}).get("url", "")
            goal = n.get("metadata", {}).get("goal", "")
            print(f"  {i:<8} {skill:<20} {inputs:<30} {label}")
            if url:
                print(f"  {'':>8}   url:   {url[:60]}")
            if goal:
                print(f"  {'':>8}   goal:  {goal[:80]}")


def _browser_sections(states: list[NodeState], session_dir: Path) -> None:
    browser_nodes = [s for s in states if s.skill == "browser"]
    if not browser_nodes:
        print("\n  (no browser nodes in this session)")
        return

    for bidx, bn in enumerate(browser_nodes, 1):
        out = (bn.result.output if bn.result else {}) or {}
        path = out.get("path", "unknown")
        turns = out.get("turns", 0)
        url = out.get("url", "")
        final_url = out.get("final_url", "")
        goal = out.get("goal", "")
        actions = out.get("actions", [])

        _hdr(f"3. BROWSER PATH  [browser node #{bidx}: {bn.node_id}]")
        print(f"  path chosen : {path}")
        print(f"  url         : {url[:80]}")
        if final_url and final_url != url:
            print(f"  final url   : {final_url[:80]}")
        print(f"  goal        : {goal[:120]}")
        print(f"  turns taken : {turns}")

        _hdr(f"4. BROWSER ACTIONS  [browser node #{bidx}]")
        if not actions:
            print("  (no actions recorded)")
        else:
            for step in actions:
                t = step.get("turn", "?")
                acts = step.get("actions", [])
                outcome = step.get("outcome", "")
                for a in acts:
                    atype = a.get("type", "?")
                    if atype == "click":
                        detail = f"click mark={a.get('mark','?')}"
                    elif atype == "fill":
                        detail = f"fill mark={a.get('mark','?')} value={str(a.get('value',''))[:40]!r}"
                    elif atype == "scroll":
                        detail = f"scroll direction={a.get('direction','?')} value={a.get('value','?')}"
                    elif atype == "done":
                        success = a.get("success", "?")
                        val = str(a.get("value", ""))[:120]
                        detail = f"done success={success}  summary: {val}"
                    else:
                        detail = json.dumps(a)[:100]
                    print(f"  turn {t:>2}  {detail}  [{outcome}]")

        # Screenshots — browser dirs are named browser_<int(t0)>, sorted
        # chronologically. Match the Nth browser node to the Nth dir.
        _hdr(f"5. SCREENSHOTS / PAGE-STATE  [browser node #{bidx}]")
        browser_base = session_dir / "browser"
        screenshots: list[Path] = []
        legends: list[Path] = []
        if browser_base.exists():
            browser_dirs = sorted(browser_base.iterdir())
            node_dir = browser_dirs[bidx - 1] if bidx - 1 < len(browser_dirs) else None
            if node_dir:
                for png in sorted(node_dir.rglob("*.png")):
                    screenshots.append(png)
                for txt in sorted(node_dir.rglob("*.txt")):
                    legends.append(txt)
        if not screenshots and not legends:
            print("  (no screenshots saved — layer 1 extract path used no Playwright)")
        for p in screenshots:
            rel = p.relative_to(session_dir)
            print(f"  [screenshot] state/sessions/{session_dir.name}/{rel}")
        for p in legends:
            rel = p.relative_to(session_dir)
            print(f"  [legend    ] state/sessions/{session_dir.name}/{rel}")

        # Extracted data
        _hdr(f"6. EXTRACTED DATA  [browser node #{bidx}]")
        content = out.get("content") or ""
        if content:
            preview = content[:1200]
            print(preview)
            if len(content) > 1200:
                print(f"\n  … ({len(content) - 1200} more chars truncated)")
        else:
            print("  (no extracted content)")


def _final_table(states: list[NodeState]) -> None:
    _hdr("7. FINAL COMPARISON TABLE")
    formatter = next((s for s in reversed(states) if s.skill == "formatter"), None)
    if not formatter or not formatter.result:
        print("  (no formatter node found)")
        return
    answer = formatter.result.output.get("final_answer", "")
    if answer:
        print(answer)
    else:
        print("  (formatter produced no final_answer)")


def _load_graph_nodes(session_dir: Path) -> list[dict]:
    """Return all nodes from graph.json sorted by numeric id, or []."""
    graph_path = session_dir / "graph.json"
    if not graph_path.exists():
        return []
    try:
        g = json.loads(graph_path.read_text())
        nodes = g.get("nodes", [])
        def _sort_key(n: dict) -> int:
            try:
                return int(n["id"].split(":")[-1])
            except (KeyError, ValueError):
                return 0
        return sorted(nodes, key=_sort_key)
    except Exception:
        return []


def _summary(states: list[NodeState], session_dir: Path, session_id: str) -> None:
    _hdr("8. TURN COUNT AND COST SUMMARY")

    state_map = {s.node_id: s for s in states}

    graph_nodes = _load_graph_nodes(session_dir)
    if not graph_nodes:
        graph_nodes = [{"id": s.node_id, "skill": s.skill, "status": s.status}
                       for s in states]

    # Fetch real costs from gateway (keyed by agent/skill name)
    gw_costs = _fetch_gateway_costs(session_id)
    gw_source = "gateway" if gw_costs else "AgentResult (gateway unreachable)"

    total_elapsed = 0.0
    total_browser_turns = 0
    browser_count = 0
    rows = []

    for gn in graph_nodes:
        node_id = gn["id"]
        skill = gn.get("skill", "?")
        graph_status = gn.get("status", "?")
        s = state_map.get(node_id)
        r = s.result if s else None
        status = s.status if s else graph_status
        elapsed = (r.elapsed_s if r else 0.0) or 0.0
        total_elapsed += elapsed
        notes = ""
        if skill == "browser" and r:
            bt = r.output.get("turns", 0) or 0
            total_browser_turns += bt
            browser_count += 1
            notes = f"browser_turns={bt}"
        rows.append((node_id, skill, status, f"{elapsed:.1f}s", notes))

    print(f"  {'NODE':<8} {'SKILL':<20} {'STATUS':<10} {'ELAPSED':>8}  NOTES")
    print(f"  {'----':<8} {'-----':<20} {'------':<10} {'-------':>8}")
    for node_id, skill, status, el, notes in rows:
        print(f"  {node_id:<8} {skill:<20} {status:<10} {el:>8}  {notes}")

    # Per-agent cost table from gateway
    print()
    print(f"  cost source: {gw_source}")
    if gw_costs:
        print(f"  {'AGENT':<20} {'PROVIDER':<12} {'CALLS':>6}  {'IN_TOK':>8}  {'OUT_TOK':>8}  {'DOLLARS':>10}")
        print(f"  {'-----':<20} {'--------':<12} {'-----':>6}  {'------':>8}  {'-------':>8}  {'-------':>10}")
        total_dollars = 0.0
        total_in = 0
        total_out = 0
        for agent in sorted(gw_costs):
            c = gw_costs[agent]
            providers = ", ".join(sorted(set(c["providers"])))
            print(f"  {agent:<20} {providers:<12} {c['calls']:>6}  {c['in_tok']:>8}  {c['out_tok']:>8}  ${c['dollars']:>9.6f}")
            total_dollars += c["dollars"]
            total_in += c["in_tok"]
            total_out += c["out_tok"]
        print(f"  {'TOTAL':<20} {'':<12} {'':>6}  {total_in:>8}  {total_out:>8}  ${total_dollars:>9.6f}")

    print()
    print(f"  total nodes (graph)  : {len(graph_nodes)}")
    print(f"  nodes on disk        : {len(states)}")
    print(f"  skipped (no file)    : {len(graph_nodes) - len(states)}")
    print(f"  browser nodes        : {browser_count}")
    print(f"  total browser turns  : {total_browser_turns}")
    print(f"  total elapsed        : {total_elapsed:.1f}s")


def replay_enhanced(session_id: str) -> int:
    store = SessionStore(session_id)
    states = store.read_all_nodes()
    if not states:
        print(f"replay_enhanced: no nodes under state/sessions/{session_id}/",
              file=sys.stderr)
        return 2

    session_dir = store.dir
    query = store.read_query() or ""

    print(THICK)
    print(f"  SESSION REPLAY REPORT")
    print(THICK)
    print(f"  session id : {session_id}")

    # 1. User goal
    _hdr("1. ORIGINAL USER GOAL")
    print(f"  {query}")

    # 2. Planner DAG
    _planner_dag(states)

    # 3-6. Browser path, actions, screenshots, extracted data
    _browser_sections(states, session_dir)

    # 7. Final comparison table
    _final_table(states)

    # 8. Summary
    _summary(states, session_dir, session_id)

    print()
    print(THICK)
    print("  END OF REPORT")
    print(THICK)
    return 0


def main() -> int:
    args = sys.argv[1:]
    if not args:
        sessions = list_sessions()
        if not sessions:
            print("replay_enhanced: no sessions under state/sessions/", file=sys.stderr)
            return 2
        print("available sessions:")
        for s in sessions:
            print(f"  {s}")
        print("\nusage: uv run python replay_enhanced.py <session_id>")
        return 0
    return replay_enhanced(args[0])


if __name__ == "__main__":
    sys.exit(main())
