"""Three ways to drive the same optimizer, for a fair comparison under one simulation budget.

  A  optimizer        : one least_squares run from the start point
  B  optimizer+random : when a run stalls, restart from a random point in the allowed range
  C  optimizer+LLM    : when a run stalls, ask the LLM reviewer for new start points
"""
import time
import numpy as np
from optimize import Tuner

def _stalled_round(t, start, round_sims):
    t.local(start, round_sims)
    return t.passed()

def run_strategy(kind, circuit, init, budget=60, round_sims=25, seed=0, out=None):
    t = Tuner(circuit, out); t.budget = budget; t.stop_on_pass = True
    t0 = time.time()
    if kind == "A":
        t.local(init, budget)
        return t.summary(init, t0)
    rng = np.random.default_rng(seed)
    start = init
    while len(t.history) < budget:
        if _stalled_round(t, start, round_sims):
            break
        if len(t.history) >= budget:
            break
        if kind == "B":
            start = dict(zip(t.names, np.exp(rng.uniform(t.lo, t.hi))))
            t.notes.append({"at": len(t.history), "restart": start})
        elif kind == "C":
            from advisor import advise
            adv = advise(circuit, t.spec, t.tun, t.history)
            t.notes.append({"at": len(t.history), **adv})
            for p in adv["proposals"]:          # every proposal is checked in SPICE
                if len(t.history) >= budget: break
                t.evaluate(p["values"], source="llm")
                if t.history[-1]["pass"]: break
            if t.passed(): break
            best_llm = min((h for h in t.history if h["source"] == "llm"), key=lambda h: h["cost"])
            start = {n: best_llm[n] for n in t.names}
    return t.summary(init, t0)
