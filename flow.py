"""Session 8 — growing-graph orchestrator.

The agent's loop becomes a NetworkX DiGraph. Each node is a skill; edges
carry typed AgentResult payloads. The graph GROWS at runtime via five
actors: the Planner's seed plan, dynamic successors from any skill,
static `internal_successors` from the yaml, Critic auto-insertion on
edges out of `critic:true` skills, and Planner re-invocation on node
failure (gated by `recovery.plan_recovery`). Perception's tool-blindness
contract from S7 is preserved — Planner names skills, never tools.

Persistence lives in persistence.py; skill execution in skills.py;
failure-policy in recovery.py; sandbox in sandbox.py.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid

import networkx as nx

import memory as memory_svc
from gateway import ensure_gateway
from persistence import SessionStore
from recovery import handle_critic_verdict, plan_recovery
from schemas import AgentResult, NodeState
from skills import SkillRegistry, run_skill

MAX_NODES = 60  # hard cap so a Planner loop cannot grow forever


# ── Graph ────────────────────────────────────────────────────────────────────

class Graph:
    """NetworkX DiGraph wrapper. Nodes are str ids `n:<i>`; each node carries
    `skill`, `inputs` (list of str), and `status`."""

    def __init__(self):
        self.g = nx.DiGraph()
        self._counter = 0

    def add_node(self, skill: str, inputs: list[str], metadata: dict | None = None) -> str:
        self._counter += 1
        nid = f"n:{self._counter}"
        self.g.add_node(nid, skill=skill, inputs=list(inputs),
                        metadata=dict(metadata or {}), status="pending")
        for inp in inputs:
            if inp.startswith("n:") and inp in self.g.nodes:
                self.g.add_edge(inp, nid)
        return nid

    def mark(self, nid: str, status: str) -> None:
        self.g.nodes[nid]["status"] = status

    def ready_nodes(self) -> list[str]:
        # A predecessor counts as "satisfied" when it is either complete or
        # skipped (the latter is how a Critic-fail removes a child from the
        # critical path without blocking unrelated branches downstream).
        out = []
        for nid, d in self.g.nodes(data=True):
            if d["status"] != "pending":
                continue
            preds = list(self.g.predecessors(nid))
            if all(self.g.nodes[p]["status"] in ("complete", "skipped") for p in preds):
                out.append(nid)
        return out

    def has_running(self) -> bool:
        return any(d["status"] == "running" for _, d in self.g.nodes(data=True))

    def extend_from(self, src_nid: str, result: AgentResult,
                    *, registry: SkillRegistry) -> list[str]:
        """Splice in dynamic successors, static internal_successors, and
        critic auto-insertion. Returns the list of new node ids.

        Resolves label-based input references (`n:<label>`) against the
        `metadata.label` of nodes added in the same batch. The Planner is
        encouraged to name its nodes by label so it can reference them
        without knowing the integer ids the orchestrator will hand out."""
        added: list[str] = []
        src_def = registry.get(self.g.nodes[src_nid]["skill"])

        # Pass 1: add the new nodes; build a label → assigned-id map.
        label_to_id: dict[str, str] = {}
        pending: list[tuple[str, list[str]]] = []
        for spec in result.successors:
            label = (spec.metadata or {}).get("label")
            new_id = self.add_node(spec.skill, inputs=[],
                                   metadata=spec.metadata)
            added.append(new_id)
            if isinstance(label, str) and label:
                label_to_id[label] = new_id
            pending.append((new_id, list(spec.inputs)))

        # Pass 2: resolve inputs now that every sibling has an id. Translate
        # `n:<label>` to `n:<assigned-id>` if the label matches; pass numeric
        # `n:<i>` references through; pass anything else through unchanged.
        for new_id, raw_inputs in pending:
            resolved: list[str] = []
            for inp in raw_inputs or [src_nid]:
                # `n:<label>` or `n:<int>` form (preferred).
                if inp.startswith("n:"):
                    suffix = inp[2:]
                    if suffix in label_to_id:
                        resolved.append(label_to_id[suffix])
                        continue
                    if suffix.isdigit() and inp in self.g.nodes:
                        resolved.append(inp)
                        continue
                # Bare label form — the Planner sometimes drops the n: prefix.
                if inp in label_to_id:
                    resolved.append(label_to_id[inp])
                    continue
                # Special literal — the user query is always available.
                if inp == "USER_QUERY":
                    resolved.append(inp)
                    continue
                # Artifact handle — pass through, the input renderer handles it.
                if inp.startswith("art:"):
                    resolved.append(inp)
                    continue
                # Unknown — fall back to the parent so the child has at
                # least one upstream dependency to wait on.
                resolved.append(src_nid)
            self.g.nodes[new_id]["inputs"] = resolved
            for inp in resolved:
                if inp.startswith("n:") and inp in self.g.nodes:
                    self.g.add_edge(inp, new_id)

        last_internal: str | None = None
        for child_skill in src_def.internal_successors:
            nid = self.add_node(child_skill, inputs=[src_nid])
            added.append(nid)
            last_internal = nid

        # Re-wire pending successors of src_nid to wait for the last internal
        # successor instead (e.g. formatter waits for sandbox_executor, not coder).
        if last_internal:
            for other_nid in list(self.g.successors(src_nid)):
                if other_nid == last_internal:
                    continue
                if self.g.nodes[other_nid].get("status") != "pending":
                    continue
                self.g.nodes[other_nid]["inputs"] = [
                    last_internal if i == src_nid else i
                    for i in self.g.nodes[other_nid]["inputs"]
                ]
                self.g.remove_edge(src_nid, other_nid)
                self.g.add_edge(last_internal, other_nid)

        # Critic auto-insertion: place a Critic before each pending child
        # (both newly-added and pre-wired by planner) so the child only
        # runs after Critic passes.
        if src_def.critic:
            to_guard = [n for n in self.g.successors(src_nid)
                        if self.g.nodes[n].get("status") == "pending"
                        and self.g.nodes[n].get("skill") != "critic"]
            for child_nid in to_guard:
                self.g.remove_edge(src_nid, child_nid)
                critic_nid = self.add_node(
                    "critic", inputs=[src_nid],
                    metadata={"target": src_nid, "child": child_nid},
                )
                self.g.add_edge(critic_nid, child_nid)
                added.append(critic_nid)
                # child_nid.inputs intentionally still references src_nid (not
                # critic_nid) so resolve_inputs fetches the distiller's data.
                # The critic→child edge enforces execution order; inputs
                # carries the data dependency.
                # TODO: propagate child's metadata.question into this critic's
                # metadata so the LLM can evaluate fitness-for-purpose, not
                # just internal consistency. Also requires updating critic.md
                # to instruct the LLM to use the QUESTION field.

        return added


# ── Executor ─────────────────────────────────────────────────────────────────

class Executor:
    def __init__(self, registry: SkillRegistry | None = None):
        ensure_gateway()
        self.registry = registry or SkillRegistry()

    async def run(self, query: str, *, session_id: str | None = None,
                  resume: bool = False) -> str:
        sid = session_id or f"s8-{uuid.uuid4().hex[:8]}"
        store = SessionStore(sid)
        if resume:
            existing = store.read_graph()
            if existing is None:
                raise RuntimeError(f"cannot resume {sid}: no graph.pkl on disk")
            graph_obj = existing
            graph = Graph.__new__(Graph)
            graph.g = graph_obj
            graph._counter = max(
                [int(n.split(":")[1]) for n in graph.g.nodes if n.startswith("n:")] or [0]
            )
            for _, d in graph.g.nodes(data=True):
                if d["status"] == "running":
                    d["status"] = "pending"
            if not query:
                query = store.read_query()
        else:
            store.write_query(query)
            graph = Graph()
            graph.add_node("planner", inputs=["USER_QUERY"])

        session_start = time.time()
        print(f"\n{'═' * 78}\nsession {sid}  ─  query: {query}\n{'═' * 78}")
        # Read memory ONCE at session start; the same hits flow into every
        # skill's prompt. The S7 contract is that every cognitive role sees
        # memory; carrying that forward verbatim here is what makes S7's
        # indexing investment continue to pay off in S8.
        memory_hits = memory_svc.read(query) or []
        if memory_hits:
            print(f"[memory.read] {len(memory_hits)} hit(s) visible to every skill this run")
        try:
            memory_svc.remember(query, source="user_query", run_id=sid)
        except Exception as e:
            print(f"[memory.remember] skipped: {e!r}")

        formatter_answer: str | None = None
        executed_count = 0
        # Global counter for critic-fail recoveries; see recovery.MAX_CRITIC_RECOVERIES.
        # Single-element list so handle_critic_verdict can mutate it in place.
        critic_recovery_counter: list = [0]
        critic_cap_hit: list = []

        while True:
            ready = graph.ready_nodes()
            if not ready and not graph.has_running():
                break
            if executed_count + len(ready) > MAX_NODES:
                print(f"[flow] node cap {MAX_NODES} hit at {executed_count}; stopping")
                break

            for nid in ready:
                graph.mark(nid, "running")
            store.write_graph(graph.g)

            outcomes = await asyncio.gather(*[self._run_one(nid, graph, sid, query, store, memory_hits)
                                              for nid in ready])

            for nid, result, prompt in outcomes:
                executed_count += 1
                graph.g.nodes[nid]["result"] = result
                graph.mark(nid, "complete" if result.success else "failed")
                store.write_node(NodeState(
                    node_id=nid, skill=graph.g.nodes[nid]["skill"],
                    status=graph.g.nodes[nid]["status"],
                    inputs=graph.g.nodes[nid]["inputs"],
                    result=result, prompt_sent=prompt,
                    started_at=time.time() - result.elapsed_s,
                    completed_at=time.time(),
                ))
                q = (graph.g.nodes[nid].get("metadata") or {}).get("question")
                out = result.output or {}
                rationale = out.get("rationale")
                verdict = out.get("verdict")
                found = out.get("found")
                summary = out.get("summary")
                exit_code = out.get("exit_code")
                stdout = out.get("stdout", "")
                stdout_preview = stdout.split("\n")[0][:80] if stdout else ""
                print(f"{time.strftime('%H:%M:%S')} +{time.time()-session_start:6.1f}s [{nid:3s}] {graph.g.nodes[nid]['skill']:20s} "
                      f"{graph.g.nodes[nid]['status']:8s} "
                      f"({result.elapsed_s:.1f}s)"
                      + (f"  q={q[:80]}" if q and not verdict and not found else "")
                      + (f"  rationale={rationale[:80]}" if rationale and not q and not verdict else "")
                      + (f"  verdict={verdict}" if verdict else "")
                      + (f"  reason={out.get('rationale','')[:80]}" if verdict else "")
                      + (f"  found={found}" if found is not None else "")
                      + (f"  summary={summary[:80]}" if summary else "")
                      + (f"  stdout={stdout_preview}" if exit_code is not None else "")
                      + (f"  err={result.error[:80]}" if result.error else ""))

                if result.success:
                    if graph.g.nodes[nid]["skill"] == "critic":
                        if handle_critic_verdict(nid, result, graph,
                                                 critic_recovery_counter,
                                                 critic_cap_hit):
                            continue
                        # verdict == pass: the child is now ready to run.
                    graph.extend_from(nid, result, registry=self.registry)
                    if graph.g.nodes[nid]["skill"] == "formatter":
                        fa = result.output.get("final_answer")
                        if isinstance(fa, str) and fa.strip():
                            formatter_answer = fa
                else:
                    failed_skill = graph.g.nodes[nid]["skill"]
                    decision = plan_recovery(
                        failed_skill=failed_skill,
                        error_text=result.error or "",
                        failed_node_id=nid,
                    )
                    if decision.action == "skip":
                        print(f"  ↪ {nid} failed ({decision.reason}, "
                              f"skill={failed_skill}): {decision.note}")
                        continue
                    # action == "replan"
                    rec_nid = graph.add_node(
                        "planner", inputs=["USER_QUERY"],
                        metadata={"failure_report": decision.failure_report,
                                  "recovers": nid,
                                  "recovery_reason": decision.reason},
                    )
                    print(f"  ↪ recovery ({decision.reason}): planner node "
                          f"{rec_nid} queued for {nid}")

            store.write_graph(graph.g)

        if formatter_answer is None:
            for nid in reversed(list(graph.g.nodes)):
                d = graph.g.nodes[nid]
                if d["status"] == "complete" and isinstance(d.get("result"), AgentResult):
                    formatter_answer = json.dumps(d["result"].output)[:2000]
                    break

        if critic_cap_hit:
            print(f"\n[flow] WARNING: global critic-fail recovery cap "
                  f"({len(critic_cap_hit)}x hit) — one or more branches "
                  f"skipped after {critic_recovery_counter[0]} recovery attempts. "
                  f"Final answer may reflect missing data.")
        print(f"\n{'═' * 78}\nFINAL: {formatter_answer or ''}\n{'═' * 78}\n")
        return formatter_answer or ""

    async def _run_one(self, nid: str, graph: Graph, sid: str, query: str,
                       store: SessionStore, memory_hits: list) -> tuple[str, AgentResult, str]:
        skill_name = graph.g.nodes[nid]["skill"]
        skill = self.registry.get(skill_name)
        fr = graph.g.nodes[nid].get("metadata", {}).get("failure_report")
        store.write_node(NodeState(node_id=nid, skill=skill_name, status="running",
                                   inputs=graph.g.nodes[nid]["inputs"],
                                   started_at=time.time()))
        try:
            result, prompt = await run_skill(skill, nid, graph.g.nodes, sid, query, fr,
                                             memory_hits=memory_hits)
        except Exception as e:  # pragma: no cover - dispatcher fault path
            result = AgentResult(success=False, agent_name=skill_name,
                                 error=f"exception: {type(e).__name__}: {e}")
            prompt = "(exception before prompt-render)"
        return nid, result, prompt


# ── CLI ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = sys.argv[1:]
    resume_sid: str | None = None
    if args and args[0] == "--resume":
        resume_sid = args[1] if len(args) > 1 else None
        query = " ".join(args[2:])
    else:
        query = " ".join(args) or "Say hello in one short sentence."
    asyncio.run(Executor().run(query, session_id=resume_sid, resume=bool(resume_sid)))


if __name__ == "__main__":
    main()
