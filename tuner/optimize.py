"""Numerical tuner: adjust tunable elements until ngspice results meet spec.yaml.

usage: python tuner/optimize.py circuits/three_stage [--init RE2=5000,RE3=200] [--out runs/name]
"""
import argparse, csv, json, math, time
from pathlib import Path
import numpy as np, yaml
from scipy.optimize import least_squares
from sim import simulate

def load(circuit):
    c = Path(circuit)
    spec = yaml.safe_load(open(c / "spec.yaml"))
    tun = yaml.safe_load(open(c / "tunables.yaml"))
    return spec, tun

def residuals(meas, spec):
    """One residual per target (1.0 = exactly at tolerance edge) and per violated constraint."""
    r = []
    for k, t in spec["targets"].items():
        r.append(math.log(meas[k] / float(t["value"])) / math.log(1 + float(t["tol"])))
    for k, c in spec.get("constraints", {}).items():
        lo = float(c.get("min", -1e30)); hi = float(c.get("max", 1e30))
        r.append(10 * max(0.0, lo - meas[k], meas[k] - hi))   # 0 when satisfied
    return np.array(r)

def check(meas, spec):
    ok = {}
    for k, t in spec["targets"].items():
        ok[k] = abs(meas[k] / float(t["value"]) - 1) <= float(t["tol"])
    for k, c in spec.get("constraints", {}).items():
        ok[k] = float(c.get("min", -1e30)) <= meas[k] <= float(c.get("max", 1e30))
    return ok

class _Stop(Exception):
    pass

class Tuner:
    def __init__(self, circuit, out=None, spec=None, tunables=None, fixed=None,
                 sim_kwargs=None, on_eval=None):
        """spec/tunables override the yaml files; fixed = values held constant;
        sim_kwargs go to simulate() (lib_text, models); on_eval(record) is called after each sim."""
        self.circuit = circuit
        spec0, tun = load(circuit)
        self.spec = spec or spec0
        self.tun = tunables or tun["tunables"]
        self.fixed = fixed or {}
        self.sim_kwargs = sim_kwargs or {}
        self.on_eval = on_eval
        self.names = list(self.tun)
        self.lo = np.log([float(self.tun[n]["min"]) for n in self.names])
        self.hi = np.log([float(self.tun[n]["max"]) for n in self.names])
        self.history = []
        self.out = Path(out) if out else None
        self.budget = None          # max total simulations
        self.stop_on_pass = False
        self.notes = []             # advisor diagnoses etc.
        self.round_end = None       # stop the current local run after this many total sims

    def evaluate(self, params: dict, source="optimizer"):
        """Run one simulation; every call is logged (source = who proposed the point)."""
        params = {k: float(v) for k, v in params.items()}
        meas = simulate(self.circuit, {**self.fixed, **params}, **self.sim_kwargs)
        r = residuals(meas, self.spec)
        rec = {"n": len(self.history) + 1, "source": source, **params, **meas,
               "cost": float(np.sum(r ** 2)), "pass": all(check(meas, self.spec).values())}
        self.history.append(rec)
        if self.on_eval:
            self.on_eval(rec)
        return meas, r

    def _f(self, x):
        if self.budget and len(self.history) >= self.budget:
            raise _Stop("budget")
        if self.round_end and len(self.history) >= self.round_end:
            raise _Stop("round")
        params = dict(zip(self.names, np.exp(x)))
        r = self.evaluate(params)[1]
        if self.stop_on_pass and self.history[-1]["pass"]:
            raise _Stop("pass")
        return r

    def local(self, start: dict, max_sims=200):
        """Run least_squares from one starting point for at most max_sims simulations
        (Jacobian evaluations included). Returns quietly on pass/budget."""
        self.round_end = len(self.history) + max_sims
        x0 = np.clip(np.log([float(start[n]) for n in self.names]), self.lo + 1e-9, self.hi - 1e-9)
        try:
            least_squares(self._f, x0, bounds=(self.lo, self.hi), diff_step=1e-3, max_nfev=max_sims)
        except _Stop:
            pass

    def best(self):
        return min(self.history, key=lambda h: h["cost"])

    def passed(self):
        return any(h["pass"] for h in self.history)

    def summary(self, init, t0):
        best = self.best()
        s = {"init": init, "best": {n: best[n] for n in self.names},
             "meas": {k: best[k] for k in list(self.spec["targets"]) + list(self.spec.get("constraints", {}))},
             "pass": best["pass"], "n_sims": len(self.history),
             "first_pass_at": next((h["n"] for h in self.history if h["pass"]), None),
             "seconds": round(time.time() - t0, 1), "notes": self.notes}
        if self.out:
            self.out.mkdir(parents=True, exist_ok=True)
            with open(self.out / "history.csv", "w", newline="") as f:
                w = csv.DictWriter(f, fieldnames=list(self.history[0])); w.writeheader(); w.writerows(self.history)
            json.dump(s, open(self.out / "result.json", "w"), indent=1)
        return s

    def run(self, init: dict, max_sims=200):
        t0 = time.time()
        self.local(init, max_sims)
        return self.summary(init, t0)

def parse_init(s, tun):
    init = {n: float(v["init"]) for n, v in tun["tunables"].items()}
    if s:
        for kv in s.split(","):
            k, v = kv.split("="); init[k] = float(v)
    return init

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("circuit"); ap.add_argument("--init"); ap.add_argument("--out")
    a = ap.parse_args()
    t = Tuner(a.circuit, a.out)
    print(json.dumps(t.run(parse_init(a.init, yaml.safe_load(open(Path(a.circuit) / "tunables.yaml")))), indent=1))
