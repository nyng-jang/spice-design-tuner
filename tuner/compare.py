"""Compare strategies A/B/C over several start points. usage: python tuner/compare.py [A,B,C]"""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent))
from strategies import run_strategy

CIRCUIT = "circuits/three_stage"
STARTS = {
    "hand_tuned": {"RE2": 6374, "RE3": 1343.4},     # 2023 report answer (Q2 saturated)
    "low_low":    {"RE2": 2000, "RE3": 200},
    "sat_high":   {"RE2": 5000, "RE3": 8000},
    "default":    {"RE2": 8000, "RE3": 10000},
    "high_high":  {"RE2": 30000, "RE3": 5000},
}
kinds = sys.argv[1].split(",") if len(sys.argv) > 1 else ["A", "B", "C"]
rows = []
for name, init in STARTS.items():
    for k in kinds:
        s = run_strategy(k, CIRCUIT, init, out=f"runs/compare/{k}_{name}")
        rows.append({"start": name, "strategy": k, "pass": s["pass"], "first_pass_at": s["first_pass_at"],
                     "n_sims": s["n_sims"], **{n: round(v) for n, v in s["best"].items()}})
        print(json.dumps(rows[-1]))
Path("runs/compare").mkdir(parents=True, exist_ok=True)
json.dump(rows, open(f"runs/compare/summary_{''.join(kinds)}.json", "w"), indent=1)
