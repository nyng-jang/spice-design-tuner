"""SVG schematic of the 3-stage amplifier with live values.

Colors: tuned element = orange, user-fixed = blue, others = gray, element being changed now = red.
"""
FONT = "font-family='Pretendard, Noto Sans KR, sans-serif'"

def fmt(v):
    v = float(v)
    for div, suf in ((1e6, "M"), (1e3, "k")):
        if abs(v) >= div:
            s = f"{v/div:.4g}"; return s + suf
    return f"{v:.4g}"

class _S:
    def __init__(self, values, roles, active):
        self.v, self.roles, self.active, self.out = values, roles, active or set(), []

    def color(self, name):
        if name in self.active: return "#d62728"
        return {"tune": "#e67e22", "fixed": "#1f77b4"}.get(self.roles.get(name), "#666")

    def line(self, x1, y1, x2, y2, c="#222", w=2):
        self.out.append(f"<line x1='{x1}' y1='{y1}' x2='{x2}' y2='{y2}' stroke='{c}' stroke-width='{w}'/>")

    def text(self, x, y, s, c="#222", size=12, anchor="start", bold=False):
        b = " font-weight='700'" if bold else ""
        self.out.append(f"<text x='{x}' y='{y}' fill='{c}' font-size='{size}' text-anchor='{anchor}' {FONT}{b}>{s}</text>")

    def dot(self, x, y):
        self.out.append(f"<circle cx='{x}' cy='{y}' r='3' fill='#222'/>")

    def _hit(self, name, x0, y0, w, h):
        self.out.append(f"<g class='el' data-name='{name}' data-value='{self.v[name]}' data-role='{self.roles.get(name, '')}'>"
                        f"<rect class='hit' x='{x0}' y='{y0}' width='{w}' height='{h}' rx='6'/>")

    def res_v(self, x, y1, y2, name, label_side=1):
        c = self.color(name); m = (y1 + y2) / 2; h = 18
        self._hit(name, x - 18 if label_side > 0 else x - 62, m - 26, 80, 52)
        self.line(x, y1, x, m - h); self.line(x, m + h, x, y2)
        pts = [(x, m - h)] + [(x + (7 if i % 2 else -7), m - h + 3 + i * 6) for i in range(6)] + [(x, m + h)]
        self.out.append("<polyline fill='none' stroke='%s' stroke-width='2.4' points='%s'/>" % (c, " ".join(f"{a},{b}" for a, b in pts)))
        tx = x + 12 * label_side; anc = "start" if label_side > 0 else "end"
        self.text(tx, m - 3, name, c, 14, anc, bold=True)
        self.text(tx, m + 14, fmt(self.v[name]) + "Ω", c, 13, anc)
        self.out.append("</g>")

    def res_h(self, x1, x2, y, name):
        c = self.color(name); m = (x1 + x2) / 2; w = 18
        self._hit(name, m - 45, y - 30, 90, 42)
        self.line(x1, y, m - w, y); self.line(m + w, y, x2, y)
        pts = [(m - w, y)] + [(m - w + 3 + i * 6, y + (7 if i % 2 else -7)) for i in range(6)] + [(m + w, y)]
        self.out.append("<polyline fill='none' stroke='%s' stroke-width='2.4' points='%s'/>" % (c, " ".join(f"{a},{b}" for a, b in pts)))
        self.text(m, y - 14, f"{name} {fmt(self.v[name])}Ω", c, 14, "middle", bold=True)
        self.out.append("</g>")

    def cap_v(self, x, y1, y2, label):
        m = (y1 + y2) / 2
        self.line(x, y1, x, m - 4); self.line(x, m + 4, x, y2)
        self.line(x - 10, m - 4, x + 10, m - 4); self.line(x - 10, m + 4, x + 10, m + 4)
        self.text(x + 13, m + 4, label, "#888", 10)

    def cap_h(self, x1, x2, y, label):
        m = (x1 + x2) / 2
        self.line(x1, y, m - 4, y); self.line(m + 4, y, x2, y)
        self.line(m - 4, y - 10, m - 4, y + 10); self.line(m + 4, y - 10, m + 4, y + 10)
        self.text(m, y + 24, label, "#888", 10, "middle")

    def gnd(self, x, y):
        self.line(x - 9, y, x + 9, y); self.line(x - 6, y + 4, x + 6, y + 4); self.line(x - 3, y + 8, x + 3, y + 8)

    def npn(self, x, y, name, model):
        """Base bar at x, collector up to (x+25, y-30), emitter down to (x+25, y+30)."""
        self.out.append(f"<circle cx='{x+12}' cy='{y}' r='24' fill='none' stroke='#bbb'/>")
        self.line(x, y - 14, x, y + 14, w=3)
        self.line(x, y - 6, x + 25, y - 22); self.line(x + 25, y - 22, x + 25, y - 30)
        self.line(x, y + 6, x + 25, y + 22); self.line(x + 25, y + 22, x + 25, y + 30)
        self.out.append(f"<polygon points='{x+25},{y+22} {x+15},{y+20} {x+20},{y+13}' fill='#222'/>")
        self.text(x + 40, y - 4, name, "#222", 12, bold=True); self.text(x + 40, y + 11, model, "#888", 10)

    def nmos(self, x, y, name, model):
        """Gate at x, drain up to (x+20, y-30), source down to (x+20, y+30)."""
        self.line(x, y - 14, x, y + 14, w=3); self.line(x + 6, y - 16, x + 6, y + 16, w=3)
        self.line(x + 6, y - 12, x + 20, y - 12); self.line(x + 20, y - 12, x + 20, y - 30)
        self.line(x + 6, y + 12, x + 20, y + 12); self.line(x + 20, y + 12, x + 20, y + 30)
        self.out.append(f"<polygon points='{x+7},{y+12} {x+14},{y+8} {x+14},{y+16}' fill='#222'/>")
        self.text(x + 28, y - 4, name, "#222", 12, bold=True); self.text(x + 28, y + 11, model, "#888", 10)

def _tag(s, x, y, txt):
    s.out.append(f"<g class='tag'><rect x='{x}' y='{y-11}' width='{len(txt)*6.6+10}' height='16' rx='8' fill='#eef4ff' stroke='#c9dafc'/>"
                 f"<text x='{x+5}' y='{y+1}' fill='#3056b8' font-size='11' {FONT}>{txt}</text></g>")

def schematic_svg(values, roles=None, active=None, models=None, nodes=None):
    """nodes: optional dict of DC node voltages {"d1":..,"c2":..,"e2":..,"e3":..} to tag on the drawing."""
    s = _S(values, roles or {}, set(active or []))
    models = models or {}
    TOP, BOT = 50, 420
    s.line(150, TOP, 900, TOP); s.text(900, TOP - 10, "VCC 15V", "#222", 12, "end", bold=True)
    for x0, x1, lab in ((150, 395, "C-S"), (405, 655, "C-E"), (665, 905, "C-C")):
        s.out.append(f"<rect x='{x0}' y='18' width='{x1-x0}' height='{BOT+28-18}' fill='none' stroke='#ddd' stroke-dasharray='5,4'/>")
        s.text(x0 + 8, 34, lab + " amplifier", "#999", 11)
    # source
    s.out.append("<circle cx='50' cy='300' r='18' fill='none' stroke='#222' stroke-width='2'/>")
    s.text(50, 305, "~", "#222", 16, "middle"); s.text(50, 340, "v_s", "#555", 11, "middle")
    s.line(50, 282, 50, 230); s.line(50, 318, 50, BOT); s.gnd(50, BOT)
    s.res_h(50, 125, 230, "RSIG"); s.cap_h(125, 175, 230, "C1")
    # stage 1
    s.line(175, 230, 240, 230); s.dot(195, 230)
    s.res_v(195, TOP, 230, "RG1", -1); s.res_v(195, 230, BOT, "RG2", -1); s.gnd(195, BOT)
    s.nmos(240, 230, "M1", models.get("M1", ""))
    s.res_v(260, TOP, 200, "RD1"); s.dot(260, 170)
    s.res_v(260, 260, BOT, "RS1"); s.gnd(260, BOT); s.dot(260, 300)
    s.line(260, 300, 330, 300); s.cap_v(330, 300, BOT, "C2"); s.line(260, BOT, 330, BOT)
    # stage 2
    s.line(260, 170, 345, 170); s.cap_h(345, 385, 170, "C3"); s.line(385, 170, 440, 170)
    s.line(440, 170, 440, 230); s.dot(440, 230)
    s.res_v(440, TOP, 170, "R1", -1); s.dot(440, 170); s.res_v(440, 230, BOT, "R2", -1); s.gnd(440, BOT)
    s.line(440, 230, 480, 230); s.npn(480, 230, "Q2", models.get("Q2", ""))
    s.res_v(505, TOP, 200, "RC2"); s.dot(505, 150)
    s.res_v(505, 260, BOT, "RE2"); s.gnd(505, BOT); s.dot(505, 300)
    s.line(505, 300, 590, 300); s.cap_v(590, 300, BOT, "C4"); s.line(505, BOT, 590, BOT)
    # stage 3
    s.line(505, 150, 600, 150); s.cap_h(600, 640, 150, "C5"); s.line(640, 150, 700, 150)
    s.line(700, 150, 700, 230); s.dot(700, 230)
    s.res_v(700, TOP, 150, "R3", -1); s.dot(700, 150); s.res_v(700, 230, BOT, "R4", -1); s.gnd(700, BOT)
    s.line(700, 230, 740, 230); s.npn(740, 230, "Q3", models.get("Q3", ""))
    s.line(765, TOP, 765, 200)
    s.line(765, 260, 765, 290); s.dot(765, 290)
    s.res_v(765, 290, BOT, "RE3", -1); s.gnd(765, BOT)
    s.line(765, 290, 815, 290); s.cap_h(815, 855, 290, "C6"); s.line(855, 290, 870, 290); s.dot(870, 290)
    s.res_v(870, 290, BOT, "RL"); s.gnd(870, BOT)
    s.text(880, 280, "v_out", "#555", 11)
    if nodes:
        for key, x, y in (("d1", 275, 185), ("c2", 515, 165), ("e2", 515, 285), ("e3", 775, 305)):
            if key in nodes:
                _tag(s, x, y, f"{key} {nodes[key]:.2f}V")
    legend = [("#e67e22", "조정 대상"), ("#1f77b4", "고정 (직접 입력)"), ("#d62728", "지금 바꾸는 중")]
    for i, (c, t) in enumerate(legend):
        s.out.append(f"<rect x='{20+i*150}' y='{BOT+40}' width='12' height='12' fill='{c}'/>")
        s.text(38 + i * 150, BOT + 51, t, "#444", 12)
    body = "\n".join(s.out)
    style = ("<style>.el .hit{fill:transparent;cursor:pointer}.el:hover .hit{fill:rgba(37,99,235,.08);stroke:#2563eb;stroke-dasharray:3,3}"
             ".el{cursor:pointer}</style>")
    return f"<svg viewBox='0 0 920 {BOT+60}' xmlns='http://www.w3.org/2000/svg' style='width:100%;background:#fff'>{style}{body}</svg>"
