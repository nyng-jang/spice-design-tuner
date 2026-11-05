"""Robustness check of a design: E96 rounding and +/-1% resistor Monte Carlo.

usage: python tuner/robustness.py   (compares the designs listed in DESIGNS)
"""
import json, re, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from sim import simulate
from optimize import load, check

C = "circuits/three_stage"
DESIGNS = {
    # one-variable-at-a-time procedure of the 2023 report, redone in ngspice:
    # RE3 for Rout=60 at RE2=8k, then first RE2 (sweeping up) giving gain=1000
    "sequential": {"RE2": 6341.8, "RE3": 682.9},
    "tuner":      {"RE2": 22991, "RE3": 575},
}
E96 = np.array([100,102,105,107,110,113,115,118,121,124,127,130,133,137,140,143,147,150,154,158,162,165,169,
                174,178,182,187,191,196,200,205,210,215,221,226,232,237,243,249,255,261,267,274,280,287,294,301,
                309,316,324,332,340,348,357,365,374,383,392,402,412,422,432,442,453,464,475,487,499,511,523,536,
                549,562,576,590,604,619,634,649,665,681,698,715,732,750,768,787,806,825,845,866,887,909,931,953,976])

def e96(x):
    dec = 10 ** np.floor(np.log10(x) - 2)
    m = x / dec
    return float(E96[np.argmin(np.abs(np.log(E96 / m)))] * dec)

def resistor_params():
    net = (Path(C) / "netlist.cir").read_text()
    vals = {}
    for line in re.findall(r"^\.param (.*)$", net, re.M):
        for k, v in re.findall(r"(\w+)=(\S+)", line):
            if k != "RSIG" and k != "RL":   # source and load are not part of the design
                vals[k] = float(v.lower().replace("meg", "e6").replace("k", "e3"))
    return vals

def monte_carlo(design, n=300, tol=0.01, seed=1):
    spec, _ = load(C)
    base = {**resistor_params(), **design}
    rng = np.random.default_rng(seed)
    rows = []
    for _ in range(n):
        p = {k: v * (1 + rng.uniform(-tol, tol)) for k, v in base.items()}
        m = simulate(C, p)
        rows.append({**m, "pass": all(check(m, spec).values()),
                     **{f"ok_{k}": v for k, v in check(m, spec).items()}})
    return rows

if __name__ == "__main__":
    spec, _ = load(C)
    out = {}
    for name, d in DESIGNS.items():
        nom = simulate(C, d)
        r = {n: e96(v) for n, v in d.items()}
        rm = simulate(C, r)
        mc = monte_carlo(d)
        g = np.array([x["gain"] for x in mc]); ro = np.array([x["rout"] for x in mc])
        out[name] = {
            "design": d, "nominal": {k: nom[k] for k in ["gain", "rin", "rout", "vce2"]},
            "nominal_pass": all(check(nom, spec).values()),
            "e96": r, "e96_meas": {k: rm[k] for k in ["gain", "rin", "rout", "vce2"]},
            "e96_pass": all(check(rm, spec).values()),
            "mc_yield": float(np.mean([x["pass"] for x in mc])),
            "mc_gain_yield": float(np.mean([x["ok_gain"] for x in mc])),
            "mc_gain_min_max": [float(g.min()), float(g.max())],
            "mc_rout_min_max": [float(ro.min()), float(ro.max())],
        }
        json.dump(mc, open(f"runs/mc_{name}.json", "w"))
        print(name, json.dumps(out[name], indent=1))
    json.dump(out, open("runs/robustness.json", "w"), indent=1)
