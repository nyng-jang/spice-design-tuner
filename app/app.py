"""3-stage amplifier tuning app.  Run:  streamlit run app/app.py"""
import re, sys
from pathlib import Path
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st
import streamlit.components.v1 as components
import yaml

ROOT = Path(__file__).resolve().parent.parent
APP = ROOT / "app"
sys.path.insert(0, str(ROOT / "tuner")); sys.path.insert(0, str(APP))
from sim import simulate, curves, model_names
from optimize import Tuner, check
from schematic import schematic_svg, fmt

CIRCUIT = ROOT / "circuits" / "three_stage"
_course = ROOT / "models" / "course_project.lib"          # local only, not in the public repo
DEFAULT_LIB = (_course if _course.exists() else ROOT / "models" / "generic.lib").read_text()
DEFAULT_LIB_NAME = "과목 라이브러리" if _course.exists() else "일반 모델 (β=100)"
BUILTIN_NMOS = "M2N7000"          # defined inside netlist.cir
ELEMENTS = ["RSIG", "RG1", "RG2", "RD1", "RS1", "R1", "R2", "RC2", "RE2", "R3", "R4", "RE3", "RL"]
LABEL = {"gain": "Gain", "rin": "Rin", "rout": "Rout", "vce2": "VCE2", "vce3": "VCE3"}
UNIT = {"gain": "V/V", "rin": "Ω", "rout": "Ω", "vce2": "V", "vce3": "V"}
E96 = np.array([100,102,105,107,110,113,115,118,121,124,127,130,133,137,140,143,147,150,154,158,162,165,169,174,178,182,
                187,191,196,200,205,210,215,221,226,232,237,243,249,255,261,267,274,280,287,294,301,309,316,324,332,340,
                348,357,365,374,383,392,402,412,422,432,442,453,464,475,487,499,511,523,536,549,562,576,590,604,619,634,
                649,665,681,698,715,732,750,768,787,806,825,845,866,887,909,931,953,976])
schematic_component = components.declare_component("schematic", path=str(APP / "schematic_component"))

def e96(x):
    dec = 10 ** np.floor(np.log10(x) - 2); m = x / dec
    return float(E96[np.argmin(np.abs(np.log(E96 / m)))] * dec)

def netlist_defaults():
    vals = {}
    for line in re.findall(r"^\.param (.*)$", (CIRCUIT / "netlist.cir").read_text(), re.M):
        for k, v in re.findall(r"(\w+)=(\S+)", line):
            vals[k] = float(v.lower().replace("meg", "e6").replace("k", "e3"))
    return vals

@st.cache_data(show_spinner=False, max_entries=500)
def run_sim(vals: tuple, lib_text: str, models: tuple):
    return simulate(CIRCUIT, dict(vals), lib_text=lib_text, models=dict(models))

@st.cache_data(show_spinner=False, max_entries=100)
def run_curves(vals: tuple, lib_text: str, models: tuple):
    return curves(CIRCUIT, dict(vals), lib_text=lib_text, models=dict(models))

st.set_page_config(page_title="SPICE Design Tuner", page_icon="⚡", layout="wide")
st.markdown("""<style>
.block-container{padding-top:2.2rem;padding-bottom:2rem;max-width:1500px}
h1{font-size:1.75rem !important;margin-bottom:0 !important}
.cards{display:grid;grid-template-columns:repeat(2,1fr);gap:10px;margin:4px 0 10px}
.card{border:1px solid #e5e7eb;border-radius:14px;padding:12px 14px;background:#fff}
.card .k{font-size:12px;color:#6b7280}
.card .v{font-size:24px;font-weight:700;margin-top:2px}
.card .t{font-size:12px;color:#6b7280;margin-top:2px}
.card.ok{border-color:#bbf7d0;background:#f0fdf4} .card.ok .v{color:#15803d}
.card.bad{border-color:#fecaca;background:#fef2f2} .card.bad .v{color:#b91c1c}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:8px}
.chip{font-size:12px;background:#f3f4f6;border-radius:999px;padding:3px 10px;color:#374151}
.badge{display:inline-block;font-size:12px;padding:3px 10px;border-radius:999px;font-weight:600}
.badge.ok{background:#dcfce7;color:#166534} .badge.bad{background:#fee2e2;color:#991b1b}
</style>""", unsafe_allow_html=True)

ss = st.session_state
if "vals" not in ss:
    ss.vals = netlist_defaults()                      # starts at the 2023 hand-tuned answer
    ss.roles = {e: "" for e in ELEMENTS}; ss.roles.update({"RE2": "tune", "RE3": "tune"})
    ss.ranges = {e: (ss.vals[e] / 10, ss.vals[e] * 10) for e in ELEMENTS}
    ss.ranges.update({"RE2": (1e3, 30e3), "RE3": (100.0, 10e3)})
    ss.reco = None; ss.last_nonce = None

# apply an edit made by clicking the schematic (arrives as the component's value)
ev = ss.get("schem")
if ev and ev.get("nonce") != ss.last_nonce:
    ss.last_nonce = ev["nonce"]
    ss.vals[ev["name"]] = float(ev["value"]); ss.roles[ev["name"]] = ev.get("role", "")
    lo, hi = ss.ranges[ev["name"]]
    if not lo <= ss.vals[ev["name"]] <= hi:
        ss.ranges[ev["name"]] = (min(lo, ss.vals[ev["name"]] / 3), max(hi, ss.vals[ev["name"]] * 3))
    ss.pop("table", None)

# ---------------- sidebar ----------------
with st.sidebar:
    st.subheader("목표 사양")
    spec0 = yaml.safe_load(open(CIRCUIT / "spec.yaml"))
    tg = {}
    for k, t in spec0["targets"].items():
        c1, c2 = st.columns([3, 2])
        v = c1.number_input(f"{LABEL[k]} ({UNIT[k]})", value=float(t["value"]), format="%g", key=f"t_{k}")
        tol = c2.number_input("허용 ±%", value=float(t["tol"]) * 100, min_value=0.1, step=0.5, key=f"tol_{k}")
        tg[k] = {"value": v, "tol": tol / 100}
    vmin = st.number_input("BJT 포화 여유: VCE 최소 (V)", value=1.0, step=0.1)
    spec = {"targets": tg, "constraints": {"vce2": {"min": vmin}, "vce3": {"min": vmin}}}
    st.divider()
    st.subheader("소자 라이브러리")
    up = st.file_uploader(f"PSpice .lib (없으면 {DEFAULT_LIB_NAME})", type=["lib", "txt", "mod"])
    lib_text = up.getvalue().decode("utf-8", "ignore") if up else DEFAULT_LIB
    names = model_names(lib_text)
    npn = [n for n, t in names if t.upper() == "NPN"] or ["(없음)"]
    nmos = [BUILTIN_NMOS] + [n for n, t in names if t.upper() == "NMOS"]
    q2 = st.selectbox("Q2 모델", npn, index=npn.index("Q2") if "Q2" in npn else 0)
    q3 = st.selectbox("Q3 모델", npn, index=npn.index("Q3") if "Q3" in npn else 0)
    m1 = st.selectbox("M1 모델", nmos, index=0, help="M2N7000은 내장 대체 모델 (OrCAD 원본 아님)")
    models = {"Q2": q2, "Q3": q3, "M1": m1}
    sim_kwargs = {"lib_text": lib_text, "models": models}
    st.divider()
    if st.button("2023 손 계산 값으로 되돌리기", use_container_width=True):
        for k in list(ss.keys()): del ss[k]
        st.rerun()

key = lambda v: tuple(sorted(v.items()))
MK = tuple(sorted(models.items()))

st.title("⚡ SPICE Design Tuner · 3단 증폭기 (CS–CE–CC)")
st.caption("회로도의 저항을 클릭해 값을 바꾸면 바로 ngspice로 다시 시뮬레이션해요. 일부 값을 고정하고 나머지를 추천받을 수도 있어요.")

left, right = st.columns([1.7, 1], gap="large")
with left:
    schem_slot = st.empty()

def static_schematic(values, active):
    schem_slot.markdown(f"<div style='border:1px solid #e5e7eb;border-radius:14px;padding:8px'>"
                        f"{schematic_svg(values, ss.roles, active, models)}</div>", unsafe_allow_html=True)

# ---------------- results ----------------
try:
    m = run_sim(key(ss.vals), lib_text, MK)
except Exception as ex:
    m = None; right.error(f"시뮬레이션 실패: {ex}")

with right:
    if m:
        ok = check(m, spec); allok = all(ok.values())
        st.markdown(f"#### 시뮬레이션 결과 <span class='badge {'ok' if allok else 'bad'}'>"
                    f"{'모든 사양 만족' if allok else '사양 미달'}</span>", unsafe_allow_html=True)
        cards = []
        for k in ["gain", "rin", "rout", "vce2"]:
            tgt = (f"목표 {fmt(spec['targets'][k]['value'])} ±{spec['targets'][k]['tol']*100:g}%" if k in spec["targets"]
                   else f"목표 ≥ {spec['constraints'][k]['min']:g}V (포화 여유)")
            val = f"{m[k]:.2f}" if k == "vce2" else fmt(m[k])
            cards.append(f"<div class='card {'ok' if ok[k] else 'bad'}'><div class='k'>{LABEL[k]} ({UNIT[k]})</div>"
                         f"<div class='v'>{val}</div><div class='t'>{tgt}</div></div>")
        st.markdown("<div class='cards'>" + "".join(cards) + "</div>", unsafe_allow_html=True)
        chips = [f"Av1 {m['av1']:.3g}", f"Av2 {m['av2']:.3g}", f"Av3 {m['av3']:.3g}",
                 f"ID1 {m['id1']*1e3:.3g}mA", f"IC2 {m['ic2']*1e3:.3g}mA", f"IC3 {m['ic3']*1e3:.3g}mA", f"VCE3 {m['vce3']:.2f}V"]
        st.markdown("<div class='chips'>" + "".join(f"<span class='chip'>{c}</span>" for c in chips) + "</div>",
                    unsafe_allow_html=True)
        if m["vce2"] < 0.3:
            st.warning("Q2가 포화 상태예요 (VCE2 < 0.3V). 이득과 Rout이 소자값에 매우 민감합니다.")
        cv = run_curves(key(ss.vals), lib_text, MK)
        t1, t2 = st.tabs(["주파수 응답", "출력 파형 (1kHz, 0.1mV 입력)"])
        with t1:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            fig.add_trace(go.Scatter(x=cv["freq"], y=cv["gain_db"], name="이득 (dB)", line=dict(color="#2563eb", width=2.5),
                                     hovertemplate="%{x:.4s}Hz<br>%{y:.2f} dB<extra></extra>"))
            fig.add_trace(go.Scatter(x=cv["freq"], y=cv["phase"], name="위상 (°)", line=dict(color="#9ca3af", width=1.5, dash="dot"),
                                     hovertemplate="%{x:.4s}Hz<br>%{y:.1f}°<extra></extra>"), secondary_y=True)
            gt = 20 * np.log10(spec["targets"]["gain"]["value"])
            fig.add_hline(y=gt, line_dash="dash", line_color="#16a34a", annotation_text=f"목표 {gt:.1f} dB")
            fig.update_xaxes(type="log", title="주파수 (Hz)", showspikes=True, spikemode="across", spikethickness=1)
            fig.update_yaxes(title="이득 (dB)", secondary_y=False); fig.update_yaxes(title="위상 (°)", secondary_y=True, showgrid=False)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                              legend=dict(orientation="h", y=1.12), plot_bgcolor="#fff")
            st.plotly_chart(fig, use_container_width=True)
        with t2:
            fig = make_subplots(specs=[[{"secondary_y": True}]])
            tm = (cv["t"] - cv["t"][0]) * 1e3
            fig.add_trace(go.Scatter(x=tm, y=cv["vout_mv"], name="v_out (mV)", line=dict(color="#2563eb", width=2.5),
                                     hovertemplate="%{x:.3f} ms<br>%{y:.2f} mV<extra></extra>"))
            fig.add_trace(go.Scatter(x=tm, y=cv["vin_uv"], name="v_s (µV)", line=dict(color="#f59e0b", width=1.5),
                                     hovertemplate="%{x:.3f} ms<br>%{y:.2f} µV<extra></extra>"), secondary_y=True)
            fig.update_xaxes(title="시간 (ms)", showspikes=True, spikemode="across", spikethickness=1)
            fig.update_yaxes(title="v_out (mV)", secondary_y=False); fig.update_yaxes(title="v_s (µV)", secondary_y=True, showgrid=False)
            fig.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10), hovermode="x unified",
                              legend=dict(orientation="h", y=1.12), plot_bgcolor="#fff")
            st.plotly_chart(fig, use_container_width=True)
            pk = cv["vout_mv"].max(); tr = cv["vout_mv"].min()
            if abs(pk + tr) > 0.1 * (pk - tr):
                st.caption(f"출력이 비대칭이에요 (+{pk:.0f} / {tr:.0f} mV): 파형 왜곡 가능성")

# ---------------- tools ----------------
tab_rec, tab_sw, tab_tbl = left.tabs(["🎯 추천: 고정값 유지하고 나머지 찾기", "📈 Sweep: 한 소자 바꿔보기", "🧾 소자 표 · 탐색 범위"])

with tab_tbl:
    df = pd.DataFrame([{"소자": e, "값 (Ω)": ss.vals[e],
                        "역할": {"tune": "조정", "fixed": "고정"}.get(ss.roles[e], "-"),
                        "최소": ss.ranges[e][0], "최대": ss.ranges[e][1]} for e in ELEMENTS])
    ed = st.data_editor(df, hide_index=True, use_container_width=True, key="table", height=35 * len(ELEMENTS) + 40,
                        column_config={"소자": st.column_config.TextColumn(disabled=True),
                                       "값 (Ω)": st.column_config.NumberColumn(format="%.6g"),
                                       "역할": st.column_config.SelectboxColumn(options=["-", "고정", "조정"]),
                                       "최소": st.column_config.NumberColumn(format="%.4g"),
                                       "최대": st.column_config.NumberColumn(format="%.4g")})
    changed = False
    for _, r in ed.iterrows():
        e = r["소자"]; nv = float(r["값 (Ω)"]); nr = {"조정": "tune", "고정": "fixed"}.get(r["역할"], "")
        if nv != ss.vals[e] or nr != ss.roles[e]: changed = True
        ss.vals[e] = nv; ss.roles[e] = nr; ss.ranges[e] = (float(r["최소"]), float(r["최대"]))
    if changed: st.rerun()

with tab_rec:
    tune = [e for e in ELEMENTS if ss.roles[e] == "tune"]
    fixed = [e for e in ELEMENTS if ss.roles[e] == "fixed"]
    c0, c1, c2 = st.columns([2, 1, 1])
    c0.markdown(f"**조정할 소자** &nbsp; {' '.join(f'`{e}`' for e in tune) or '없음 (회로도에서 저항을 클릭해 \"조정\"으로)'}  \n"
                f"**고정한 소자** &nbsp; {' '.join(f'`{e}={fmt(ss.vals[e])}`' for e in fixed) or '없음'}")
    budget = c1.number_input("최대 시뮬레이션 횟수", value=80, min_value=10, max_value=500)
    restarts = c2.number_input("막혔을 때 재시작 횟수", value=3, min_value=0, max_value=10)
    if st.button("추천 실행", type="primary", disabled=not tune):
        tun = {e: {"min": ss.ranges[e][0], "max": ss.ranges[e][1]} for e in tune}
        hold = {e: ss.vals[e] for e in ELEMENTS if e not in tune}
        log = []; live = st.empty()
        def on_eval(rec):
            static_schematic({**ss.vals, **{e: rec[e] for e in tune}}, tune)
            log.append({"#": rec["n"], **{e: fmt(rec[e]) for e in tune}, "gain": f"{rec['gain']:.4g}",
                        "Rout": f"{rec['rout']:.3g}", "VCE2": f"{rec['vce2']:.2f}", "통과": "✅" if rec["pass"] else ""})
            live.dataframe(pd.DataFrame(log[-6:]), hide_index=True, use_container_width=True)
        t = Tuner(CIRCUIT, spec=spec, tunables=tun, fixed=hold, sim_kwargs=sim_kwargs, on_eval=on_eval)
        t.budget = int(budget)
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
        b = t.best()
        e96v = {e: e96(b[e]) for e in tune}
        me = simulate(CIRCUIT, {**hold, **e96v}, **sim_kwargs)
        ss.reco = {"values": {e: b[e] for e in tune}, "pass": b["pass"], "n": len(t.history),
                   "meas": {k: b[k] for k in b if k not in tune}, "e96_meas": me, "e96_pass": all(check(me, spec).values())}
        live.empty()
    if ss.reco:
        r = ss.reco
        (st.success if r["pass"] else st.warning)(
            f"{r['n']}번 시뮬레이션 · " + ("모든 사양 만족" if r["pass"] else "사양을 모두 만족하는 값을 못 찾음 (가장 가까운 값)"))
        rm, me = r["meas"], r["e96_meas"]
        rows = [{"소자": e, "추천값": fmt(v) + "Ω", "E96 표준값": fmt(e96(v)) + "Ω"} for e, v in r["values"].items()]
        rows += [{"소자": "→ 결과", "추천값": f"gain {rm['gain']:.4g} · Rout {rm['rout']:.3g}Ω · VCE2 {rm['vce2']:.2f}V",
                  "E96 표준값": f"gain {me['gain']:.4g} · Rout {me['rout']:.3g}Ω · VCE2 {me['vce2']:.2f}V "
                                + ("✅" if r["e96_pass"] else "❌")}]
        st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
        c1, c2, _ = st.columns([1, 1.3, 2])
        if c1.button("추천값 적용", use_container_width=True):
            ss.vals.update(r["values"]); ss.pop("table", None); st.rerun()
        if c2.button("E96 표준값 적용", use_container_width=True):
            ss.vals.update({e: e96(v) for e, v in r["values"].items()}); ss.pop("table", None); st.rerun()

with tab_sw:
    c1, c2, c3, c4 = st.columns(4)
    el = c1.selectbox("바꿀 소자", ELEMENTS, index=ELEMENTS.index("RE2"))
    lo = c2.number_input("시작 (Ω)", value=float(ss.ranges[el][0]), format="%g", key=f"swlo_{el}")
    hi = c3.number_input("끝 (Ω)", value=float(ss.ranges[el][1]), format="%g", key=f"swhi_{el}")
    npts = c4.number_input("점 개수", value=60, min_value=5, max_value=300)
    if st.button("Sweep 실행", type="primary"):
        xs = np.geomspace(lo, hi, int(npts)); recs = []; bar = st.progress(0.0)
        for i, x in enumerate(xs):
            vals = {**ss.vals, el: float(x)}
            static_schematic(vals, [el])
            mm = run_sim(key(vals), lib_text, MK)
            recs.append({el: x, **mm, "pass": all(check(mm, spec).values())})
            bar.progress((i + 1) / len(xs), text=f"{el} = {fmt(x)}Ω → gain {mm['gain']:.4g}, Rout {mm['rout']:.3g}Ω")
        bar.empty()
        ss.sweep = (el, pd.DataFrame(recs))
    if "sweep" in ss:
        el_s, d = ss.sweep
        fig = make_subplots(rows=1, cols=3, subplot_titles=("Gain (V/V)", "Rout (Ω)", "VCE2 (V)"), horizontal_spacing=0.07)
        for j, k in enumerate(["gain", "rout", "vce2"], start=1):
            colr = np.where(d["pass"], "#16a34a", "#2563eb")
            fig.add_trace(go.Scatter(x=d[el_s], y=d[k], mode="lines+markers", marker=dict(size=5, color=colr),
                                     line=dict(color="#93c5fd"), name=LABEL[k], showlegend=False,
                                     hovertemplate=f"{el_s} = %{{x:.4s}}Ω<br>{LABEL[k]} = %{{y:.4g}}<extra></extra>"), row=1, col=j)
            if k in spec["targets"]:
                t = spec["targets"][k]
                fig.add_hrect(y0=t["value"] * (1 - t["tol"]), y1=t["value"] * (1 + t["tol"]), fillcolor="#16a34a",
                              opacity=0.15, line_width=0, row=1, col=j)
            else:
                fig.add_hline(y=vmin, line_dash="dash", line_color="#dc2626", row=1, col=j)
            fig.add_vline(x=ss.vals[el_s], line_dash="dot", line_color="#6b7280", row=1, col=j)
            fig.update_xaxes(type="log", title_text=f"{el_s} (Ω)", showspikes=True, spikemode="across", spikethickness=1, row=1, col=j)
        fig.update_layout(height=340, margin=dict(l=10, r=10, t=40, b=10), hovermode="closest", plot_bgcolor="#fff")
        st.plotly_chart(fig, use_container_width=True)
        good = d[d["pass"]]
        if len(good):
            st.success(f"{el_s}만 바꿔서 모든 사양을 만족하는 범위: {fmt(good[el_s].min())} ~ {fmt(good[el_s].max())}Ω (초록 점)")
        else:
            best = d.iloc[(d["gain"] / spec["targets"]["gain"]["value"]).apply(lambda v: abs(np.log(v))).argmin()]
            st.info(f"{el_s} 하나만으로는 모든 사양을 동시에 만족하지 못해요. gain이 목표에 가장 가까운 값은 "
                    f"{fmt(best[el_s])}Ω (gain {best['gain']:.4g}, Rout {best['rout']:.3g}Ω, VCE2 {best['vce2']:.2f}V). "
                    f"추천 탭에서 여러 소자를 함께 조정해보세요.")

# interactive schematic last, so loops above could draw progress into the same slot
nodes = {k: m[f"v_{k}"] for k in ("d1", "c2", "e2", "e3")} if m else None
with schem_slot.container():
    schematic_component(svg=schematic_svg(ss.vals, ss.roles, None, models, nodes), key="schem", default=None)
