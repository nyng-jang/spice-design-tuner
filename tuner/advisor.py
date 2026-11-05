"""LLM design reviewer: reads the simulation log and proposes the next points to try.

The numerical optimizer remains the main engine. The advisor is called only when the
optimizer stalls, and every point it proposes is verified by ngspice like any other.
Needs ANTHROPIC_API_KEY in the environment.
"""
import json
from pathlib import Path
import anthropic

MODEL = "claude-opus-5-5"

SCHEMA = {
    "type": "object",
    "properties": {
        "diagnosis": {"type": "string",
                      "description": "What is going wrong, in circuit terms (operating region, which stage limits which spec)."},
        "proposals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "values": {"type": "object", "additionalProperties": {"type": "number"},
                               "description": "Tunable name -> value in ohms"},
                    "reason": {"type": "string"},
                },
                "required": ["values", "reason"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["diagnosis", "proposals"],
    "additionalProperties": False,
}

SYSTEM = """You are an analog circuit design reviewer working beside a numerical optimizer.
You get the circuit description, the target specs, the tunable elements with their allowed ranges,
and the log of SPICE simulations run so far. The optimizer has stalled.
Diagnose why in circuit terms (bias point, saturation, which stage sets which spec), then propose
up to 3 new starting points for the optimizer. Proposals must stay inside the allowed ranges.
Prefer points that are physically well-behaved (transistors in the active region with margin),
not just points that might hit the numbers. Be concise."""

def _fmt_history(history, names, keys, last=25):
    rows = history[-last:]
    cols = ["n", "source"] + names + keys + ["pass"]
    lines = [",".join(cols)]
    for h in rows:
        lines.append(",".join(f"{h[c]:.4g}" if isinstance(h[c], float) else str(h[c]) for c in cols))
    return "\n".join(lines)

def advise(circuit_dir, spec, tunables, history, n_max=3):
    d = Path(circuit_dir)
    names = list(tunables)
    keys = [k for k in history[0] if k not in names and k not in ("n", "source", "pass")]
    user = (
        f"## Circuit\n{(d / 'description.md').read_text()}\n"
        f"## Target specs and constraints\n{json.dumps(spec, indent=1)}\n"
        f"## Tunable elements (ohms)\n{json.dumps(tunables, indent=1)}\n"
        f"## Simulation log (most recent last)\n{_fmt_history(history, names, keys)}\n"
        f"Propose at most {n_max} new starting points."
    )
    client = anthropic.Anthropic()
    resp = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if resp.stop_reason == "refusal":
        raise RuntimeError("advisor request was declined")
    text = next(b.text for b in resp.content if b.type == "text")
    out = json.loads(text)
    # clip to allowed ranges; drop unknown names
    clean = []
    for p in out["proposals"][:n_max]:
        v = {n: min(max(float(p["values"].get(n, tunables[n]["init"])), float(tunables[n]["min"])),
                    float(tunables[n]["max"])) for n in names}
        clean.append({"values": v, "reason": p["reason"]})
    return {"diagnosis": out["diagnosis"], "proposals": clean,
            "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens}}
