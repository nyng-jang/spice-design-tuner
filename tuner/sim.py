"""Run one ngspice simulation of a circuit folder with given parameter values.

A circuit folder holds:
  netlist.cir      circuit, tunable values as .param
  measure.control  .control block that prints 'MEAS <name> <value>'
  spec.yaml        target specs and constraints
  tunables.yaml    which .params may change, and their ranges
"""
import re, subprocess, tempfile, os, shutil

# Windows ships a console build named ngspice_con.exe; set NGSPICE to override.
NGSPICE = os.environ.get("NGSPICE") or shutil.which("ngspice_con") or "ngspice"
from pathlib import Path

def _set_params(netlist: str, params: dict) -> str:
    for name, val in params.items():
        pat = re.compile(rf"(^\.param\b.*?\b{name}\s*=\s*)(\S+)", re.I | re.M)
        if not pat.search(netlist):
            raise KeyError(f".param {name} not found in netlist")
        netlist = pat.sub(lambda m: m.group(1) + f"{float(val):.6g}", netlist, count=1)
    return netlist

def _set_models(netlist: str, models: dict) -> str:
    """models: device name -> model name, e.g. {"Q2": "Q2", "M1": "M2N7000"}. Replaces last token of the device line."""
    for dev, mname in models.items():
        pat = re.compile(rf"(^{dev}\s.*\s)(\S+)[ \t]*$", re.I | re.M)
        if not pat.search(netlist):
            raise KeyError(f"device {dev} not found in netlist")
        netlist = pat.sub(lambda m: m.group(1) + mname, netlist, count=1)
    return netlist

def model_names(lib_text: str):
    return re.findall(r"^\.model\s+(\S+)\s+(\w+)", lib_text, re.I | re.M)

def _deck(d, params, lib_text, models, control_text):
    """Return (deck text, temp lib path or None)."""
    net = _set_params((d / "netlist.cir").read_text(), params)
    libpath = None
    if lib_text is not None:
        with tempfile.NamedTemporaryFile("w", suffix=".lib", dir=d, delete=False) as f:
            f.write(lib_text); libpath = f.name
        net = re.sub(r"^\.include\s+.*\.lib\s*$", f".include {libpath}", net, flags=re.I | re.M)
    if models:
        net = _set_models(net, models)
    body = net.rstrip()
    if body.lower().endswith(".end"):
        body = body[:-4]
    return body + "\n" + control_text + "\n.end\n", libpath

def _run(d, deck, timeout):
    with tempfile.NamedTemporaryFile("w", suffix=".sp", dir=d, delete=False) as f:
        f.write(deck); path = f.name
    try:
        return subprocess.run([NGSPICE, "-b", path], capture_output=True, text=True,
                              timeout=timeout, cwd=d).stdout
    finally:
        os.unlink(path)

def curves(circuit_dir, params: dict, timeout=60, lib_text=None, models=None) -> dict:
    """Frequency response and output waveform for plotting (uses curves.control)."""
    import numpy as np
    d = Path(circuit_dir).resolve()
    tmp = tempfile.mkdtemp()
    ctrl = (d / "curves.control").read_text().replace("{OUT}", os.path.join(tmp, "c"))
    deck, libpath = _deck(d, params, lib_text, models, ctrl)
    try:
        _run(d, deck, timeout)
        ac = np.loadtxt(os.path.join(tmp, "c_ac.dat"))
        tr = np.loadtxt(os.path.join(tmp, "c_tran.dat"))
    finally:
        if libpath: os.unlink(libpath)
        shutil.rmtree(tmp, ignore_errors=True)
    return {"freq": ac[:, 0], "gain_db": ac[:, 1], "phase": ac[:, 3],
            "t": tr[:, 0], "vin_uv": tr[:, 1], "vout_mv": tr[:, 3]}

def simulate(circuit_dir, params: dict, timeout=30, lib_text=None, models=None) -> dict:
    """lib_text: optional model library text that replaces the netlist's .include line.
    models: optional device -> model-name mapping."""
    d = Path(circuit_dir).resolve()
    deck, libpath = _deck(d, params, lib_text, models, (d / "measure.control").read_text())
    try:
        out = _run(d, deck, timeout)
    finally:
        if libpath:
            os.unlink(libpath)
    meas = {m.group(1): float(m.group(2))
            for m in re.finditer(r"^MEAS (\w+) ([-+\d.eE]+)", out, re.M)}
    if not meas:
        raise RuntimeError("ngspice produced no measurements:\n" + out[-2000:])
    return meas

if __name__ == "__main__":
    import sys, yaml, json
    c = sys.argv[1] if len(sys.argv) > 1 else "circuits/three_stage"
    base = yaml.safe_load(open(Path(c) / "tunables.yaml"))["baseline"]
    print(json.dumps(simulate(c, base), indent=1))
