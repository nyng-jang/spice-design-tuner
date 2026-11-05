"""Capacitor sizing from f_c = 1 / (2*pi*Req*C).

For each coupling/bypass capacitor, Req is measured in ngspice: that capacitor is removed,
all others are shorted (1 F), the signal source is zeroed, and a 1 A AC test current is
injected across its two nodes; |V| across them is Req.
One capacitor (the one with the largest Req, so the smallest C) sets the low cut-off
(dominant pole, f_dom = f_min / margin); the others are placed a further decade lower.
"""
import re, sys
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).parent))
from sim import run_control, curves

E6 = [1.0, 1.5, 2.2, 3.3, 4.7, 6.8]

def cap_nodes(circuit_dir):
    net = (Path(circuit_dir) / "netlist.cir").read_text()
    return {m.group(1): (m.group(2), m.group(3))
            for m in re.finditer(r"^(C\d+)\s+(\S+)\s+(\S+)\s+\{(C\d+)\}", net, re.M)}

def e6_up(c):
    dec = 10 ** np.floor(np.log10(c))
    for m in E6 + [10.0]:
        if m * dec >= c * (1 - 1e-9):
            return float(m * dec)

def measure_req(circuit_dir, params, sim_kwargs=None):
    caps = cap_nodes(circuit_dir); out = {}
    for c, (n1, n2) in caps.items():
        p = {**params, **{k: 1.0 for k in caps}, c: 1e-18}
        vdiff = f"v({n1})" if n2 == "0" else f"v({n1})-v({n2})"
        ctrl = (".control\nalter vi acmag=0\nac lin 1 1k 1k\n"
                f"let z = mag({vdiff})\necho \"MEAS req $&z\"\n.endc")
        m = run_control(circuit_dir, p, ctrl, extra=f"IREQ {n2} {n1} DC 0 AC 1", **(sim_kwargs or {}))
        out[c] = m["req"]
    return out

def low_cutoff(cv):
    g = cv["gain_db"]; f = cv["freq"]; i = np.where(g >= g.max() - 3)[0][0]
    return float(f[i]), float(g.max())

def design(circuit_dir, params, f_min=1e3, margin=10.0, spread=10.0, sim_kwargs=None):
    """Returns table rows, designed caps (standard values) and a verification."""
    req = measure_req(circuit_dir, params, sim_kwargs)
    dom = max(req, key=req.get)
    f_dom = f_min / margin
    rows, caps = [], {}
    for c, r in req.items():
        fc = f_dom if c == dom else f_dom / spread
        cval = 1 / (2 * np.pi * r * fc)
        caps[c] = e6_up(cval)
        rows.append({"cap": c, "req": r, "fc": fc, "c_calc": cval, "c_std": caps[c], "dominant": c == dom})
    cv = curves(circuit_dir, {**params, **caps}, **(sim_kwargs or {}))
    fl, gmid = low_cutoff(cv)
    i = np.argmin(abs(cv["freq"] - f_min))
    return {"rows": rows, "caps": caps, "f_L": fl, "mid_gain_db": gmid, "gain_db_at_fmin": float(cv["gain_db"][i]),
            "f_dom_target": f_dom}

if __name__ == "__main__":
    import json
    C = "circuits/three_stage"
    params = {"RE2": float(sys.argv[1]) if len(sys.argv) > 1 else 24310, "RE3": float(sys.argv[2]) if len(sys.argv) > 2 else 965.3}
    old = curves(C, params); fl, gm = low_cutoff(old)
    print(f"현재 (모두 10uF): f_L = {fl:.0f} Hz, 중역 {10**(gm/20):.0f} V/V")
    r = design(C, params)
    for row in r["rows"]:
        print(f"{row['cap']}: Req {row['req']:.4g} ohm, fc {row['fc']:.3g} Hz, C 계산 {row['c_calc']*1e6:.4g} uF -> {row['c_std']*1e6:.4g} uF"
              + ("  (주극점)" if row["dominant"] else ""))
    print(f"설계 후: f_L = {r['f_L']:.0f} Hz, 중역 {10**(r['mid_gain_db']/20):.0f} V/V, 1kHz {10**(r['gain_db_at_fmin']/20):.0f} V/V")

def tune_with_caps(circuit_dir, start, tunables=None, fixed=None, spec=None, f_min=1e3, sim_kwargs=None,
                   max_iter=4, budget=150, on_eval=None):
    """Alternate: size capacitors from Req at the current resistor values -> re-tune resistors
    with those capacitors -> repeat until the standard capacitor values stop changing."""
    from optimize import Tuner
    caps, res, log = {}, dict(start), []
    for it in range(max_iter):
        d = design(circuit_dir, {**(fixed or {}), **res}, f_min=f_min, sim_kwargs=sim_kwargs)
        log.append({"iter": it, "caps": d["caps"], "f_L": d["f_L"]})
        if d["caps"] == caps:
            break
        caps = d["caps"]
        t = Tuner(circuit_dir, spec=spec, tunables=tunables, fixed={**(fixed or {}), **caps},
                  sim_kwargs=sim_kwargs, on_eval=on_eval)
        t.budget = budget
        t.local({k: res[k] for k in t.names}, budget)
        b = t.best(); res = {k: b[k] for k in t.names}
        log[-1].update({"res": res, "pass": b["pass"], "n_sims": len(t.history)})
    return {"res": res, "caps": caps, "design": d, "log": log}
