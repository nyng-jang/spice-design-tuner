"""3-stage amplifier tuning app.  Run:  streamlit run app/app.py"""
import re, sys, time
from pathlib import Path
import numpy as np
import pandas as pd
import streamlit as st
import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tuner")); sys.path.insert(0, str(ROOT / "app"))
from sim import simulate, model_names
from optimize import Tuner, check
from schematic import schematic_svg, fmt

CIRCUIT = ROOT / "circuits" / "three_stage"
_course = ROOT / "models" / "course_project.lib"          # local only, not in the public repo
DEFAULT_LIB = (_course if _course.exists() else ROOT / "models" / "generic.lib").read_text()
DEFAULT_LIB_NAME = "과목 라이브러리" if _course.exists() else "일반 모델 (β=100)"
BUILTIN_NMOS = "M2N7000"          # defined inside netlist.cir
ELEMENTS = ["RSIG", "RG1", "RG2", "RD1", "RS1", "R1", "R2", "RC2", "RE2", "R3", "R4", "RE3", "RL"]
LABEL = {"gain": "Gain (V/V)", "rin": "Rin (Ω)", "rout": "Rout (Ω)", "vce2": "VCE2 (V)", "vce3": "VCE3 (V)"}
E96 = np.array([100,102,105,107,110,113,115,118,121,124,127,130,133,137,140,143,147,150,154,158,162,165,169,174,178,182,
                187,191,196,200,205,210,215,221,226,232,237,243,249,255,261,267,274,280,287,294,301,309,316,324,332,340,
                348,357,365,374,383,392,402,412,422,432,442,453,464,475,487,499,511,523,536,549,562,576,590,604,619,634,
                649,665,681,698,715,732,750,768,787,806,825,845,866,887,909,931,953,976])

def e96(x):
    dec = 10 ** np.floor(np.log10(x) - 2); m = x / dec
    return float(E96[np.argmin(np.abs(np.log(E96 / m)))] * dec)

def netlist_defaults():
    vals = {}
    for line in re.findall(r"^\.param (.*)$", (CIRCUIT / "netlist.cir").read_text(), re.M):
        for k, v in re.findall(r"(\w+)=(\S+)", line):
            vals[k] = float(v.lower().replace("meg", "e6").replace("k", "e3"))
    return vals

st.set_page_config(page_title="3단 증폭기 튜너", layout="wide")
ss = st.session_state
if "vals" not in ss:
    ss.vals = netlist_defaults()                      # starts at the 2023 hand-tuned answer
    ss.roles = {e: "" for e in ELEMENTS}; ss.roles.update({"RE2": "tune", "RE3": "tune"})
    ss.ranges = {e: (ss.vals[e] / 10, ss.vals[e] * 10) for e in ELEMENTS}
    ss.ranges.update({"RE2": (1e3, 30e3), "RE3": (100.0, 10e3)})
    ss.last = None; ss.reco = None

# ---------------- sidebar: specs + library ----------------
with st.sidebar:
    st.header("1. 목표 사양")
    spec0 = yaml.safe_load(open(CIRCUIT / "spec.yaml"))
    tg = {}
    for k, t in spec0["targets"].items():
        c1, c2 = st.columns([3, 2])
        v = c1.number_input(LABEL[k], value=float(t["value"]), format="%g", key=f"t_{k}")
        tol = c2.number_input("허용 ±%", value=float(t["tol"]) * 100, min_value=0.1, step=0.5, key=f"tol_{k}")
        tg[k] = {"value": v, "tol": tol / 100}
    vmin = st.number_input("BJT 포화 여유: VCE 최소 (V)", value=1.0, step=0.1)
    spec = {"targets": tg, "constraints": {"vce2": {"min": vmin}, "vce3": {"min": vmin}}}

    st.header("2. 소자 라이브러리")
    up = st.file_uploader(f"PSpice .lib 파일 (없으면 {DEFAULT_LIB_NAME})", type=["lib", "txt", "mod"])
    lib_text = up.getvalue().decode("utf-8", "ignore") if up else DEFAULT_LIB
    names = model_names(lib_text)
    npn = [n for n, t in names if t.upper() == "NPN"] or ["(없음)"]
    nmos = [BUILTIN_NMOS] + [n for n, t in names if t.upper() == "NMOS"]
    q2 = st.selectbox("Q2 모델", npn, index=npn.index("Q2") if "Q2" in npn else 0)
    q3 = st.selectbox("Q3 모델", npn, index=npn.index("Q3") if "Q3" in npn else 0)
    m1 = st.selectbox("M1 모델", nmos, index=0, help="M2N7000은 내장 대체 모델 (OrCAD 원본 아님)")
    models = {"Q2": q2, "Q3": q3, "M1": m1}
    sim_kwargs = {"lib_text": lib_text, "models": models}

st.title("3단 증폭기 (CS–CE–CC) 자동 튜너")
st.caption("ngspice로 시뮬레이션합니다. 소자값을 직접 넣거나, 일부를 고정하고 나머지 값을 추천받을 수 있어요.")

left, right = st.columns([3, 2], gap="large")

# ---------------- element table ----------------
with left:
    st.subheader("3. 소자값")
    df = pd.DataFrame([{"소자": e, "값 (Ω)": ss.vals[e],
                        "역할": {"tune": "조정", "fixed": "고정"}.get(ss.roles[e], "-"),
                        "최소": ss.ranges[e][0], "최대": ss.ranges[e][1]} for e in ELEMENTS])
    ed = st.data_editor(df, hide_index=True, use_container_width=True, key="table", height=35 * len(ELEMENTS) + 40,
                        column_config={"소자": st.column_config.TextColumn(disabled=True),
                                       "값 (Ω)": st.column_config.NumberColumn(format="%.6g"),
                                       "역할": st.column_config.SelectboxColumn(options=["-", "고정", "조정"],
                                            help="조정: 추천 때 튜너가 바꿈 / 고정: 내가 넣은 값 유지"),
                                       "최소": st.column_config.NumberColumn(format="%.4g"),
                                       "최대": st.column_config.NumberColumn(format="%.4g")})
    for _, r in ed.iterrows():
        e = r["소자"]; ss.vals[e] = float(r["값 (Ω)"])
        ss.roles[e] = {"조정": "tune", "고정": "fixed"}.get(r["역할"], "")
        ss.ranges[e] = (float(r["최소"]), float(r["최대"]))
    schem = st.empty()

def draw(active=None, values=None):
    schem.markdown(schematic_svg(values or ss.vals, ss.roles, active, models), unsafe_allow_html=True)

draw()

# ---------------- results panel ----------------
def show_results(box, m, title):
    ok = check(m, spec)
    box.markdown(f"#### {title}")
    rows = []
    for k in list(spec["targets"]) + ["vce2", "vce3"]:
        tgt = (f"{fmt(spec['targets'][k]['value'])} ±{spec['targets'][k]['tol']*100:g}%" if k in spec["targets"]
               else f"≥ {spec['constraints'][k]['min']:g}")
        rows.append({"항목": LABEL[k], "결과": fmt(m[k]), "목표": tgt, "": "✅" if ok[k] else "❌"})
    box.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
    box.caption(f"단별 이득  Av1 {m['av1']:.3g} · Av2 {m['av2']:.3g} · Av3 {m['av3']:.3g}   |   "
                f"바이어스  ID1 {m['id1']*1e3:.3g}mA · IC2 {m['ic2']*1e3:.3g}mA · IC3 {m['ic3']*1e3:.3g}mA")
    if m["vce2"] < 0.3:
        box.warning("Q2가 포화 상태예요 (VCE2 < 0.3V). 이득과 Rout이 소자값에 매우 민감합니다.")

with right:
    st.subheader("시뮬레이션 결과")
    if st.button("▶ 지금 값으로 시뮬레이션", type="primary", use_container_width=True) or ss.last is None:
        try:
            ss.last = simulate(CIRCUIT, ss.vals, **sim_kwargs)
        except Exception as ex:
            st.error(f"시뮬레이션 실패: {ex}"); ss.last = None
    res_box = st.container()
    if ss.last:
        show_results(res_box, ss.last, "현재 값")
    live = st.empty()

# ---------------- sweep + recommend ----------------
st.divider()
tab_sw, tab_rec = st.tabs(["Sweep: 한 소자를 바꿔보기", "추천: 고정값 유지하고 나머지 찾기"])

with tab_sw:
    c1, c2, c3, c4 = st.columns(4)
    el = c1.selectbox("바꿀 소자", ELEMENTS, index=ELEMENTS.index("RE2"))
    lo = c2.number_input("시작 (Ω)", value=float(ss.ranges[el][0]), format="%g", key=f"swlo_{el}")
    hi = c3.number_input("끝 (Ω)", value=float(ss.ranges[el][1]), format="%g", key=f"swhi_{el}")
    npts = c4.number_input("점 개수", value=40, min_value=5, max_value=200)
    if st.button("Sweep 실행"):
        xs = np.geomspace(lo, hi, int(npts)); recs = []; bar = st.progress(0.0)
        for i, x in enumerate(xs):
            vals = {**ss.vals, el: float(x)}
            draw(active=[el], values=vals)
            m = simulate(CIRCUIT, vals, **sim_kwargs)
            recs.append({el: x, **m, "pass": all(check(m, spec).values())})
            bar.progress((i + 1) / len(xs), text=f"{el} = {fmt(x)}Ω  →  gain {m['gain']:.4g}, Rout {m['rout']:.3g}")
        draw()
        d = pd.DataFrame(recs)
        ss.sweep = (el, d)
    if "sweep" in ss:
        el_s, d = ss.sweep
        import matplotlib; matplotlib.use("Agg"); import matplotlib.pyplot as plt
        fig, ax = plt.subplots(1, 3, figsize=(13, 3.2))
        for a, k in zip(ax, ["gain", "rout", "vce2"]):
            a.plot(d[el_s], d[k], ".-"); a.set_xscale("log"); a.set_xlabel(f"{el_s} [Ω]"); a.set_title(LABEL[k]); a.grid(alpha=.3)
            if k in spec["targets"]:
                t = spec["targets"][k]; a.axhspan(t["value"] * (1 - t["tol"]), t["value"] * (1 + t["tol"]), color="g", alpha=.2)
            else:
                a.axhline(vmin, color="r", ls="--")
            a.axvline(ss.vals[el_s], color="k", ls=":")
        st.pyplot(fig)
        good = d[d["pass"]]
        if len(good):
            st.success(f"{el_s}만 바꿔서 모든 사양을 만족하는 범위: {fmt(good[el_s].min())} ~ {fmt(good[el_s].max())}Ω")
        else:
            best = d.iloc[(d["gain"] / spec["targets"]["gain"]["value"]).apply(lambda r: abs(np.log(r))).argmin()]
            st.info(f"{el_s} 하나만으로는 모든 사양을 동시에 만족하지 못해요. gain이 목표에 가장 가까운 값은 "
                    f"{fmt(best[el_s])}Ω (gain {best['gain']:.4g}, Rout {best['rout']:.3g}Ω, VCE2 {best['vce2']:.2f}V). "
                    f"추천 탭에서 여러 소자를 함께 조정해보세요.")

with tab_rec:
    tune = [e for e in ELEMENTS if ss.roles[e] == "tune"]
    fixed = [e for e in ELEMENTS if ss.roles[e] == "fixed"]
    st.write(f"**조정할 소자:** {', '.join(tune) or '없음 (표에서 역할을 \"조정\"으로 바꿔주세요)'}")
    st.write(f"**내가 고정한 소자:** {', '.join(f'{e}={fmt(ss.vals[e])}Ω' for e in fixed) or '없음'}")
    c1, c2 = st.columns(2)
    budget = c1.number_input("최대 시뮬레이션 횟수", value=80, min_value=10, max_value=500)
    restarts = c2.number_input("막혔을 때 다시 시작할 횟수", value=3, min_value=0, max_value=10)
    if st.button("추천 실행", type="primary", disabled=not tune):
        tun = {e: {"min": ss.ranges[e][0], "max": ss.ranges[e][1]} for e in tune}
        hold = {e: ss.vals[e] for e in ELEMENTS if e not in tune}
        log = []
        def on_eval(rec):
            vals = {**ss.vals, **{e: rec[e] for e in tune}}
            draw(active=tune, values=vals)
            log.append({"#": rec["n"], **{e: fmt(rec[e]) for e in tune}, "gain": f"{rec['gain']:.4g}",
                        "Rout": f"{rec['rout']:.3g}", "VCE2": f"{rec['vce2']:.2f}", "통과": "✅" if rec["pass"] else ""})
            live.dataframe(pd.DataFrame(log[-8:]), hide_index=True, use_container_width=True)
        t = Tuner(CIRCUIT, spec=spec, tunables=tun, fixed=hold, sim_kwargs=sim_kwargs, on_eval=on_eval)
        t.budget = int(budget); t.stop_on_pass = False
        rng = np.random.default_rng(0)
        start = {e: min(max(ss.vals[e], ss.ranges[e][0]), ss.ranges[e][1]) for e in tune}
        per = max(10, int(budget) // (int(restarts) + 1))
        for i in range(int(restarts) + 1):
            t.local(start, per)
            if t.passed() or len(t.history) >= t.budget: break
            start = dict(zip(t.names, np.exp(rng.uniform(t.lo, t.hi))))
        if t.passed():                                   # polish: center the answer inside the spec window
            t.budget = len(t.history) + per
            t.local({e: t.best()[e] for e in tune}, per)
        draw()
        b = t.best()
        e96v = {e: e96(b[e]) for e in tune}
        me = simulate(CIRCUIT, {**hold, **e96v}, **sim_kwargs)
        ss.reco = {"values": {e: b[e] for e in tune}, "pass": b["pass"], "n": len(t.history),
                   "meas": {k: b[k] for k in b if k not in tune}, "e96_meas": me, "e96_pass": all(check(me, spec).values())}
    if ss.reco:
        r = ss.reco
        (st.success if r["pass"] else st.warning)(
            f"{r['n']}번 시뮬레이션 · " + ("모든 사양 만족" if r["pass"] else "사양을 모두 만족하는 값을 못 찾음 (가장 가까운 값)"))
        rows = [{"소자": e, "추천값": fmt(v) + "Ω", "E96 표준값": fmt(e96(v)) + "Ω"} for e, v in r["values"].items()]
        st.dataframe(pd.DataFrame(rows), hide_index=True)
        m, me = r["meas"], r["e96_meas"]
        st.caption(f"추천값: gain {m['gain']:.4g}, Rout {m['rout']:.4g}Ω, VCE2 {m['vce2']:.2f}V   |   "
                   f"E96 적용 시: gain {me['gain']:.4g}, Rout {me['rout']:.4g}Ω, VCE2 {me['vce2']:.2f}V "
                   + ("✅" if r["e96_pass"] else "❌ (표준값 반올림으로 사양 벗어남)"))
        c1, c2 = st.columns(2)
        if c1.button("추천값 적용"):
            ss.vals.update(r["values"]); ss.pop("table", None); ss.last = simulate(CIRCUIT, ss.vals, **sim_kwargs); st.rerun()
        if c2.button("E96 표준값으로 적용"):
            ss.vals.update({e: e96(v) for e, v in r["values"].items()}); ss.pop("table", None); ss.last = simulate(CIRCUIT, ss.vals, **sim_kwargs); st.rerun()
