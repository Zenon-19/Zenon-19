#!/usr/bin/env python3
"""
render_cards.py - renders the GitHub profile README as a stack of animated SVG cards.

    python render_cards.py              # animated cards -> cards/  (+ README.md)
    STATIC=1 python render_cards.py     # final frame, no animation -> cards-static/ + preview.html

Cards are displayed through <img>, so only these techniques are used:
  * an inline <style> block with CSS @keyframes
  * SMIL <animate> elements (always paired with a static twin, see Card.dual)
  * fonts subset with pyftsubset, embedded as base64 WOFF data URIs
Everything animated is switched off under prefers-reduced-motion.

Needs:  pip install fonttools      (pyftsubset must be on PATH)
Data:   data/contributions.json    (refreshed daily by .github/workflows/cards.yml)
"""
import base64, calendar, datetime as dt, glob, html, json, math, os, pathlib
import subprocess, sys, tempfile
from fontTools.ttLib import TTFont

# =============================================================================
# CONFIG - everything you are likely to want to change lives in this block
# =============================================================================
USER = "Zenon-19"
NAME = "Lakshya Lohani"
ALIAS = "a.k.a. Zenon"
EYEBROW = "SOFTWARE ENGINEER & PRODUCT BUILDER"
TAGLINE = ("Building thoughtful software, exploring AI, and turning ideas "
           "into useful products.")
SITE = "https://vibe-coding-portfolio.ai.studio"

# Palette, taken from the colours your current README already uses.
THEME = dict(
    bg="#282828",        # card background
    border="#414141",
    ink="#F4F0E8",       # primary text
    muted="#96948E",     # secondary text
    accent="#F15534",    # BRAND COLOUR
)

# Fonts: your README's typing banner uses JetBrains Mono, so use it for
# mono.ttf. Drop your site's font files in fonts/ as display.ttf, body.ttf, mono.ttf
# (.otf also fine). If missing, a system font is used and a warning is printed.
FONT_ROLES = ("display", "body", "mono")
CSS_STACK = {
    "display": "Georgia,'Times New Roman',serif",
    "body": "-apple-system,'Segoe UI',Helvetica,Arial,sans-serif",
    "mono": "ui-monospace,SFMono-Regular,Menlo,Consolas,monospace",
}
SYSTEM_FALLBACK = {"display": "serif", "body": "sans", "mono": "monospace"}  # fc-match names

# Three tiles: (title, subtitle, url)
TILES = [
    ("Portfolio", "vibe-coding-portfolio.ai.studio", SITE),
    ("LinkedIn", "in/lakshyalohani", "https://www.linkedin.com/in/lakshyalohani"),
    ("Email", "lakshyalohani1811@gmail.com", "mailto:lakshyalohani1811@gmail.com"),
]

# Optional portrait for the hero (square-ish PNG/JPG, keep it under ~150 KB).
PORTRAIT = pathlib.Path(__file__).resolve().parent / "assets" / "portrait.png"

# Featured repos by name. Empty list -> your pinned repos from the JSON.
FEATURED = []
# Used only when the JSON has no repos at all (e.g. first local run).
FALLBACK_REPOS = [
    dict(name="Flownest", description="AI-enabled CRM and client onboarding platform.",
         url=f"https://github.com/{USER}/Flownest"),
    dict(name="Ikiru", description="Task management with an AI assistant and productivity integrations.",
         url=f"https://github.com/{USER}/Ikiru"),
    dict(name="AortaML", description="Heart disease prediction using machine learning.",
         url=f"https://github.com/{USER}/AortaML"),
]
MAX_REPOS = 6
# =============================================================================

ROOT = pathlib.Path(__file__).resolve().parent
STATIC = os.environ.get("STATIC") == "1"
OUT = ROOT / ("cards-static" if STATIC else "cards")
DATA = pathlib.Path(os.environ.get("DATA", ROOT / "data" / "contributions.json"))
T = THEME
W = 900


# ------------------------------------------------------------------ helpers --
def esc(s):
    return html.escape(str(s), quote=True)


def mix(a, b, t):
    """Blend hex colour a toward b by t (0..1)."""
    ca = [int(a[i:i + 2], 16) for i in (1, 3, 5)]
    cb = [int(b[i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(x + (y - x) * t):02X}" for x, y in zip(ca, cb))


def nice_step(v):
    """Smallest 'round' integer >= v, for chart gridlines."""
    v = max(v, 1)
    e = 10 ** math.floor(math.log10(v))
    for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        s = m * e
        if s >= v and s == int(s):
            return int(s)
    return int(10 * e)


def num(n):
    return f"{int(n):,}"


# -------------------------------------------------------------------- fonts --
_fonts = {}


class Font:
    def __init__(self, role):
        self.role = role
        self.path = self._find(role)
        self.tt = TTFont(self.path, fontNumber=0, lazy=True)
        self.cmap = self.tt.getBestCmap()
        self.upm = self.tt["head"].unitsPerEm
        self.hmtx = self.tt["hmtx"]
        self.mime = "woff"
        self._warned = set()

    @staticmethod
    def _find(role):
        for ext in ("ttf", "otf", "woff2", "woff"):
            p = ROOT / "fonts" / f"{role}.{ext}"
            if p.exists():
                return p
        try:
            out = subprocess.run(["fc-match", "-f", "%{file}", SYSTEM_FALLBACK[role]],
                                 capture_output=True, text=True).stdout.strip()
            if out and pathlib.Path(out).exists():
                print(f"WARNING: fonts/{role}.ttf not found, using system font {out}",
                      file=sys.stderr)
                return pathlib.Path(out)
        except FileNotFoundError:
            pass
        for p in glob.glob("/usr/share/fonts/**/*.ttf", recursive=True):
            print(f"WARNING: fonts/{role}.ttf not found, using {p}", file=sys.stderr)
            return pathlib.Path(p)
        sys.exit(f"No font for role '{role}'. Add fonts/{role}.ttf")

    def width(self, text, size):
        total = 0
        for ch in text:
            g = self.cmap.get(ord(ch), ".notdef")
            total += self.hmtx[g][0] if g in self.hmtx.metrics else self.upm * 0.5
        return total * size / self.upm

    def check(self, text):
        for ch in text:
            if ch not in " \n" and ord(ch) not in self.cmap and ch not in self._warned:
                self._warned.add(ch)
                print(f"WARNING: {self.role} font has no glyph for {ch!r}; "
                      f"browser fallback will be used", file=sys.stderr)

    def subset_b64(self, chars):
        chars = "".join(sorted(set(chars) | set("0123456789 ")))
        with tempfile.TemporaryDirectory() as d:
            d = pathlib.Path(d)
            (d / "t.txt").write_text(chars, encoding="utf-8")
            out = d / "s.woff"
            subprocess.run(
                ["pyftsubset", str(self.path), f"--text-file={d / 't.txt'}",
                 "--flavor=woff", "--layout-features=*", "--no-hinting",
                 f"--output-file={out}"],
                check=True, capture_output=True)
            return base64.b64encode(out.read_bytes()).decode()


def font(role):
    if role not in _fonts:
        _fonts[role] = Font(role)
    return _fonts[role]


def wrap(role, text, size, maxw, maxlines):
    f = font(role)
    lines, cur = [], ""
    for w in text.split():
        t = f"{cur} {w}".strip()
        if f.width(t, size) <= maxw or not cur:
            cur = t
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    if len(lines) > maxlines:
        lines = lines[:maxlines]
        last = lines[-1]
        while last and f.width(last + "...", size) > maxw:
            last = last[:-1].rstrip()
        lines[-1] = last + "..."
    return lines


# --------------------------------------------------------------------- card --
CLS = {"display": "fd", "body": "fb", "mono": "fm"}

ANIM_CSS = (
    "@keyframes rise{from{opacity:0;transform:translateY(10px)}}"
    "@keyframes grow{from{transform:scaleX(0)}}"
    ".in{animation:rise .8s cubic-bezier(.22,.8,.24,1) backwards;animation-delay:var(--d,0s)}"
    ".grow{transform-box:fill-box;transform-origin:0 50%;"
    "animation:grow .9s cubic-bezier(.22,.8,.24,1) backwards;animation-delay:var(--d,0s)}"
    ".still{display:none}"
    "@media (prefers-reduced-motion:reduce){"
    "*{animation:none!important;transition:none!important}"
    ".smil{display:none}.still{display:inline}}"
)

SPLINE = 'calcMode="spline" keyTimes="0;1" keySplines=".22 .8 .24 1"'


class Card:
    """One SVG. `base` is the page-level delay so cards play top to bottom."""

    def __init__(self, name, w, h, label, base=0.0):
        self.name, self.w, self.h, self.label, self.base = name, w, h, label, base
        self.parts, self.defs = [], []
        self.used = {r: set() for r in FONT_ROLES}
        self.n = 0

    # staggered delay: each call is a little later than the last
    def d(self, step=0.09, extra=0.0):
        self.n += 1
        return round(self.base + extra + self.n * step, 2)

    def add(self, markup):
        self.parts.append(markup)

    def g(self, inner, d):
        return inner if STATIC else f'<g class="in" style="--d:{d}s">{inner}</g>'

    def text(self, x, y, t, role, size, fill, weight=400, anchor="start",
             d=None, ls=0):
        font(role).check(t)
        self.used[role].update(t)
        animate = d is not None and not STATIC
        cls = CLS[role] + (" in" if animate else "")
        style = f' style="--d:{d}s"' if animate else ""
        spacing = f' letter-spacing="{ls}"' if ls else ""
        return (f'<text class="{cls}"{style} x="{x}" y="{y}" font-size="{size}" '
                f'font-weight="{weight}" fill="{fill}" text-anchor="{anchor}"{spacing}>'
                f"{esc(t)}</text>")

    def grow(self, x, y, w, h, fill, d, rx=2):
        cls = "" if STATIC else f' class="grow" style="--d:{d}s"'
        return f'<rect{cls} x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{fill}"/>'

    @staticmethod
    def dual(smil, still):
        """SMIL ignores CSS animation toggles, so every SMIL element has a static
        twin; prefers-reduced-motion swaps them (display:none halts SMIL)."""
        if STATIC:
            return still
        return f'<g class="smil">{smil}</g><g class="still">{still}</g>'

    def render(self):
        css = ""
        for role in FONT_ROLES:
            if self.used[role]:
                b64 = font(role).subset_b64(self.used[role])
                css += (f"@font-face{{font-family:'Z{role}';"
                        f"src:url(data:font/woff;base64,{b64}) format('woff');}}")
            css += f".{CLS[role]}{{font-family:'Z{role}',{CSS_STACK[role]}}}"
        if not STATIC:
            css += ANIM_CSS
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        w, h = self.w, self.h
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
            f'viewBox="0 0 {w} {h}" width="{w}" height="{h}" role="img" aria-label="{esc(self.label)}">'
            f"<title>{esc(self.label)}</title><style>{css}</style>{defs}"
            f'<rect width="{w}" height="{h}" rx="20" fill="{T["bg"]}"/>'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="19.5" fill="none" stroke="{T["border"]}"/>'
            f'{"".join(self.parts)}</svg>')


def arrow(x, y, d, size=1.0, stroke=None):
    """Diagonal 'open' arrow that nudges up-right (SMIL) - static twin included."""
    path = (f'<path d="M0 14 L14 0 M5 0 H14 V9" fill="none" stroke="{stroke or T["accent"]}" '
            f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    smil = (f'<g>{path}<animateTransform attributeName="transform" type="translate" '
            f'values="0 0;3 -3;0 0" dur="2.4s" begin="{d + 1.0}s" repeatCount="indefinite"/></g>')
    return f'<g transform="translate({x} {y}) scale({size})">{Card.dual(smil, path)}</g>'


# --------------------------------------------------------------------- data --
def load_data():
    if not DATA.exists():
        sys.exit(f"{DATA} not found. Run the 'cards' workflow once (or set DATA=...).")
    data = json.loads(DATA.read_text(encoding="utf-8"))
    days = sorted((dt.date.fromisoformat(d["date"]), int(d["count"])) for d in data["days"])
    if not days:
        sys.exit("contributions.json has no days")
    return data, days


def streaks(days):
    i, cur = len(days) - 1, 0
    if days[i][1] == 0:          # today may simply not have happened yet
        i -= 1
    while i >= 0 and days[i][1] > 0:
        cur += 1
        i -= 1
    best = run = 0
    for _, c in days:
        run = run + 1 if c > 0 else 0
        best = max(best, run)
    return cur, best


def pick_repos(data):
    pool = {r["name"]: r for r in (data.get("pinned", []) + data.get("recent", []))}
    if FEATURED:
        repos = [pool[n] for n in FEATURED if n in pool]
    else:
        repos = data.get("pinned") or []
    return (repos or FALLBACK_REPOS)[:MAX_REPOS]


# -------------------------------------------------------------------- cards --
def card_hero(base):
    c = Card("hero", W, 300, f"{NAME}, {EYEBROW.title()}. {TAGLINE}", base)
    L = 56
    has_portrait = PORTRAIT.exists()
    maxw = W - 2 * L - (240 if has_portrait else 0)

    d = c.d(extra=0.0)
    dot_smil = (f'<circle cx="{L + 5}" cy="66" r="4" fill="{T["accent"]}">'
                f'<animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{L + 5}" cy="66" r="4" fill="none" stroke="{T["accent"]}">'
                f'<animate attributeName="r" values="4;12" dur="2.4s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values=".6;0" dur="2.4s" repeatCount="indefinite"/></circle>')
    dot_still = f'<circle cx="{L + 5}" cy="66" r="4" fill="{T["accent"]}"/>'
    c.add(c.g(Card.dual(dot_smil, dot_still), d))
    c.add(c.text(L + 24, 71, EYEBROW, "mono", 13, T["muted"], d=d, ls=2))

    size = 68
    nw = font("display").width(NAME, size)
    if nw > maxw:
        size = size * maxw / nw
    c.add(c.text(L, 152, NAME, "display", round(size, 1), T["ink"], 600, d=c.d()))
    c.add(c.text(L, 182, ALIAS, "mono", 14, T["accent"], d=c.d()))
    d = c.d()
    for i, line in enumerate(wrap("body", TAGLINE, 21, maxw, 2)):
        c.add(c.text(L, 220 + i * 29, line, "body", 21, T["muted"], d=d + i * 0.06))
    c.add(c.grow(L, 270, 72, 4, T["accent"], c.d()))

    if has_portrait:
        cx, cy, r = W - L - 100, 150, 100
        mime = "image/jpeg" if PORTRAIT.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        b64 = base64.b64encode(PORTRAIT.read_bytes()).decode()
        c.defs.append(f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r - 10}"/></clipPath>')
        d = c.d()
        img = (f'<image href="data:{mime};base64,{b64}" x="{cx - r}" y="{cy - r}" '
               f'width="{2 * r}" height="{2 * r}" clip-path="url(#pc)" '
               f'preserveAspectRatio="xMidYMid slice"/>')
        circ = 2 * math.pi * r
        ring = lambda off, anim: (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{T["accent"]}" '
            f'stroke-width="3" stroke-linecap="round" stroke-dasharray="{circ:.1f}" '
            f'stroke-dashoffset="{off}" transform="rotate(-90 {cx} {cy})">{anim}</circle>')
        ring_anim = (f'<animate attributeName="stroke-dashoffset" from="{circ:.1f}" to="0" '
                     f'begin="{d}s" dur="1.6s" fill="freeze" {SPLINE}/>')
        c.add(c.g(img, d))
        c.add(Card.dual(ring(f"{circ:.1f}", ring_anim), ring(0, "")))
    return c


def card_tile(i, title, sub, base):
    c = Card(f"tile-{i + 1}", 290, 150, f"{title}: {sub}", base)
    d = c.d(extra=i * 0.12)
    c.add(c.text(28, 40, f"0{i + 1}", "mono", 13, T["accent"], d=d, ls=2))
    c.add(arrow(290 - 28 - 14, 26, d))
    size = 30
    c.add(c.text(28, 94, title, "display", size, T["ink"], 600, d=c.d()))
    ssize = 13
    sw = font("mono").width(sub, ssize)
    if sw > 290 - 56:
        ssize = round(ssize * (290 - 56) / sw, 1)
    c.add(c.text(28, 120, sub, "mono", ssize, T["muted"], d=c.d()))
    c.add(c.grow(28, 134, 36, 3, T["accent"], c.d()))
    return c


def card_chart(days, base):
    last = days[-1][0]
    months = []
    y, m = last.year, last.month
    for _ in range(12):
        months.append((y, m))
        m -= 1
        if m == 0:
            y, m = y - 1, 12
    months.reverse()
    by_month = {k: 0 for k in months}
    for d, n in days:
        if (d.year, d.month) in by_month:
            by_month[(d.year, d.month)] += n
    vals = [by_month[k] for k in months]
    total = sum(vals)
    cur, best = streaks(days)
    active = sum(1 for _, n in days if n > 0)
    busiest = max(days, key=lambda t: (t[1], t[0]))

    c = Card("contributions", W, 372,
             f"Contributions per month: {num(total)} in the last 12 months. "
             f"Current streak {cur} days, {active} active days, busiest day {busiest[1]} contributions.", base)
    c.add(c.text(40, 58, "Contributions per month", "display", 26, T["ink"], 600, d=c.d()))
    c.add(c.text(40, 84, f"{num(total)} contributions in the last 12 months", "body", 14,
                 T["muted"], d=c.d()))

    x0, x1, top, basey = 76, 590, 140, 300
    step = nice_step(max(max(vals), 1) / 4)
    ymax = step * 4
    for k in range(5):
        gy = basey - k * (basey - top) / 4
        c.add(f'<line x1="{x0}" x2="{x1}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{T["border"]}" '
              f'stroke-width="1"/>')
        c.add(c.text(x0 - 10, round(gy + 4, 1), num(k * step), "mono", 11, T["muted"], anchor="end"))

    slot = (x1 - x0) / 12
    bw = 26
    peak = vals.index(max(vals))
    smil_bars, still_bars, labels = [], [], []
    t0 = c.d(0.0, 0.1)
    for i, v in enumerate(vals):
        h = max(v / ymax * (basey - top), 3 if v else 2)
        bx = round(x0 + i * slot + (slot - bw) / 2, 1)
        by = round(basey - h, 1)
        col = T["accent"] if i == peak else mix(T["bg"], T["accent"], 0.5)
        b = round(t0 + i * 0.06, 2)
        still_bars.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{h:.1f}" rx="4" fill="{col}"/>')
        smil_bars.append(
            f'<rect x="{bx}" y="{basey}" width="{bw}" height="0" rx="4" fill="{col}">'
            f'<animate attributeName="height" from="0" to="{h:.1f}" begin="{b}s" dur=".9s" fill="freeze" {SPLINE}/>'
            f'<animate attributeName="y" from="{basey}" to="{by}" begin="{b}s" dur=".9s" fill="freeze" {SPLINE}/></rect>')
        labels.append(c.text(round(bx + bw / 2, 1), round(by - 8, 1), num(v), "mono", 11,
                             T["ink"] if i == peak else T["muted"], anchor="middle",
                             d=round(b + 0.7, 2)))
        mlabel = calendar.month_abbr[months[i][1]].upper()
        c.add(c.text(round(bx + bw / 2, 1), basey + 22, mlabel, "mono", 11, T["muted"], anchor="middle"))
    c.add(Card.dual("".join(smil_bars), "".join(still_bars)))
    for lab in labels:
        c.add(lab)

    # stat panel
    px = 640
    c.add(f'<line x1="{px - 28}" x2="{px - 28}" y1="112" y2="{basey + 40}" stroke="{T["border"]}"/>')
    stats = [
        ("CURRENT STREAK", str(cur), "days" if cur != 1 else "day", f"longest: {best} days"),
        ("ACTIVE DAYS", str(active), "days", f"{round(100 * active / len(days))}% of the last {len(days)} days"),
        ("BUSIEST DAY", num(busiest[1]), "contributions" if busiest[1] != 1 else "contribution",
         f"{busiest[0].day} {calendar.month_abbr[busiest[0].month]} {busiest[0].year}"),
    ]
    for i, (lab, big, unit, sub) in enumerate(stats):
        y = 118 + i * 84
        d = c.d(0.0, 0.5 + i * 0.15)
        c.add(c.text(px, y, lab, "mono", 11, T["accent"], d=d, ls=1.5))
        c.add(c.text(px, y + 36, big, "display", 38, T["ink"], 600, d=d + 0.05))
        bwid = font("display").width(big, 38)
        c.add(c.text(round(px + bwid + 8, 1), y + 36, unit, "body", 14, T["muted"], d=d + 0.05))
        c.add(c.text(px, y + 56, sub, "body", 13, T["muted"], d=d + 0.1))
    return c


def card_repo(i, repo, base):
    name = repo["name"]
    c = Card(f"repo-{i + 1}", W, 168, f"{name}: {repo.get('description') or ''}", base)
    d0 = c.d(extra=i * 0.25)
    c.add(c.text(40, 38, f"FEATURED 0{i + 1}", "mono", 11, T["accent"], d=d0, ls=2))
    c.add(c.text(40, 74, name, "display", 30, T["ink"], 600, d=c.d()))
    dd = c.d()
    desc = repo.get("description") or "No description yet."
    for k, line in enumerate(wrap("body", desc, 15, 640, 2)):
        c.add(c.text(40, 102 + k * 22, line, "body", 15, T["muted"], d=round(dd + k * 0.05, 2)))

    # meta row
    my, dm = 146, c.d()
    x = 40
    parts = []
    lang = repo.get("language")
    if lang:
        col = repo.get("color") or T["accent"]
        parts.append(f'<circle cx="{x + 5}" cy="{my - 4}" r="5" fill="{col}"/>')
        parts.append(c.text(x + 18, my, lang, "mono", 12, T["muted"]))
        x += 18 + font("mono").width(lang, 12) + 24
    stars, forks = int(repo.get("stars", 0) or 0), int(repo.get("forks", 0) or 0)
    sx, sy = x + 7, my - 5
    pts = " ".join(
        f"{sx + (7 if k % 2 == 0 else 3) * math.sin(k * math.pi / 5):.1f},"
        f"{sy - (7 if k % 2 == 0 else 3) * math.cos(k * math.pi / 5):.1f}" for k in range(10))
    parts.append(f'<polygon points="{pts}" fill="none" stroke="{T["muted"]}" stroke-width="1.4" stroke-linejoin="round"/>')
    parts.append(c.text(x + 20, my, num(stars), "mono", 12, T["muted"]))
    x += 20 + font("mono").width(num(stars), 12) + 24
    fx, fy = x + 5, my - 5
    parts.append(
        f'<g fill="none" stroke="{T["muted"]}" stroke-width="1.4" stroke-linecap="round">'
        f'<circle cx="{fx - 4}" cy="{fy - 6}" r="2"/><circle cx="{fx + 4}" cy="{fy - 6}" r="2"/>'
        f'<circle cx="{fx}" cy="{fy + 6}" r="2"/>'
        f'<path d="M{fx - 4} {fy - 4} V{fy - 1} Q{fx - 4} {fy + 1} {fx} {fy + 1} Q{fx + 4} {fy + 1} {fx + 4} {fy - 1} V{fy - 4} M{fx} {fy + 1} V{fy + 4}"/></g>')
    parts.append(c.text(x + 18, my, num(forks), "mono", 12, T["muted"]))
    c.add(c.g("".join(parts), dm))

    # open button
    d = c.d()
    c.add(c.g(f'<circle cx="{W - 70}" cy="84" r="30" fill="none" stroke="{T["border"]}" stroke-width="1.5"/>', d))
    c.add(arrow(W - 70 - 8, 84 - 8, d, 1.15))
    return c


def card_graph(days, total, base):
    c = Card("graph", W, 268, f"Contribution graph: {num(total)} contributions in the last year", base)
    c.add(c.text(40, 54, "Contribution graph", "display", 26, T["ink"], 600, d=c.d()))
    c.add(c.text(W - 40, 54, f"{num(total)} contributions in the last year", "body", 14, T["muted"],
                 anchor="end", d=c.d()))

    first = days[0][0]
    off = (first.weekday() + 1) % 7                     # GitHub weeks start on Sunday
    ncols = (len(days) + off - 1) // 7 + 1
    x0, right = 80, W - 40
    pitch = (right - x0) / ncols
    cell = round(pitch * 0.8, 1)
    ytop = 112

    nz = sorted(n for _, n in days if n > 0)
    q = [nz[int(len(nz) * f)] for f in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]
    ramp = [mix(T["bg"], "#FFFFFF", 0.07)] + [mix(T["bg"], T["accent"], t) for t in (0.3, 0.55, 0.78, 1.0)]

    def level(n):
        if n == 0:
            return 0
        return 1 + sum(n > t for t in q) if n > q[0] else 1

    cols = {}
    for i, (d, n) in enumerate(days):
        col, row = (i + off) // 7, (i + off) % 7
        cols.setdefault(col, []).append(
            f'<rect x="{x0 + col * pitch:.1f}" y="{ytop + row * pitch:.1f}" width="{cell}" height="{cell}" '
            f'rx="3" fill="{ramp[level(n)]}"/>')
    t0 = c.d(0.0, 0.1)
    for col in sorted(cols):
        c.add(c.g("".join(cols[col]), round(t0 + col * 0.014, 3)))

    last_m = -9
    for i, (d, _) in enumerate(days):
        col = (i + off) // 7
        if (d.day <= 7 and d.weekday() == 6 or i == 0) and col - last_m >= 3:
            c.add(c.text(round(x0 + col * pitch, 1), ytop - 12, calendar.month_abbr[d.month],
                         "mono", 11, T["muted"], d=round(t0 + 0.3, 2)))
            last_m = col
    for row, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.add(c.text(40, round(ytop + row * pitch + cell - 2, 1), lab, "mono", 10, T["muted"], d=round(t0, 2)))

    ly = ytop + 7 * pitch + 22
    lx = right - 5 * (cell + 4) - 70
    c.add(c.text(lx, ly + cell - 2, "Less", "mono", 11, T["muted"], anchor="end", d=round(t0 + 0.5, 2)))
    sw = "".join(f'<rect x="{lx + 10 + k * (cell + 4):.1f}" y="{ly:.1f}" width="{cell}" height="{cell}" rx="3" fill="{ramp[k]}"/>'
                 for k in range(5))
    c.add(c.g(sw, round(t0 + 0.5, 2)))
    c.add(c.text(lx + 16 + 5 * (cell + 4), ly + cell - 2, "More", "mono", 11, T["muted"], d=round(t0 + 0.5, 2)))
    return c


# ------------------------------------------------------------------- output --
def readme(repos):
    def img(f, alt, w="100%"):
        return f'<img src="cards/{f}.svg" width="{w}" alt="{esc(alt)}">'

    tiles = "\n".join(
        f'<a href="{esc(u)}">{img("tile-%d" % (i + 1), t + ": " + s, "32.5%")}</a>'
        for i, (t, s, u) in enumerate(TILES))
    reps = []
    for i, r in enumerate(repos):
        url = r.get("url") or f"https://github.com/{USER}/{r['name']}"
        alt = r["name"] + ": " + (r.get("description") or "")
        reps.append(f'<p align="center"><a href="{esc(url)}">{img("repo-%d" % (i + 1), alt)}</a></p>')
    return (
        f'<p align="center"><a href="{SITE}">{img("hero", NAME + " - " + TAGLINE)}</a></p>\n\n'
        f'<p align="center">\n{tiles}\n</p>\n\n'
        f'<p align="center">{img("contributions", "Contributions per month, streak, active days and busiest day")}</p>\n\n'
        + "\n\n".join(reps) + "\n\n"
        f'<p align="center">{img("graph", "Contribution graph")}</p>\n\n'
        '<!-- Generated by render_cards.py - edit the CONFIG block in that file, not this README. -->\n')


def main():
    data, days = load_data()
    total = int(data.get("total") or sum(n for _, n in days))
    repos = pick_repos(data)
    OUT.mkdir(exist_ok=True)

    # Page-level start times so the stack plays top to bottom.
    t_tiles, t_chart = 0.5, 1.1
    t_repos = 1.8
    t_graph = t_repos + 0.25 * len(repos) + 0.3

    cards = [card_hero(0.0)]
    cards += [card_tile(i, *t[:2], t_tiles) for i, t in enumerate(TILES)]
    cards.append(card_chart(days, t_chart))
    cards += [card_repo(i, r, t_repos) for i, r in enumerate(repos)]
    cards.append(card_graph(days, total, t_graph))

    for c in cards:
        svg = c.render()
        (OUT / f"{c.name}.svg").write_text(svg, encoding="utf-8")
        print(f"  {OUT.name}/{c.name}.svg  {len(svg) / 1024:.1f} KB")

    if STATIC:
        names = [c.name for c in cards]
        body = ['<img src="hero.svg" width="100%">',
                "<div>" + "".join(f'<img src="tile-{i + 1}.svg" style="width:32.5%">' for i in range(3)) + "</div>"]
        body += [f'<img src="{n}.svg" width="100%">' for n in names if n not in ("hero",) and not n.startswith("tile")]
        (OUT / "preview.html").write_text(
            '<!doctype html><meta charset="utf-8"><body style="margin:0;background:#0d1117;display:flex;justify-content:center">'
            '<div style="width:880px;padding:24px 0;display:grid;gap:16px;text-align:center">'
            + "".join(body) + "</div>", encoding="utf-8")
        print(f"STATIC preview -> {OUT / 'preview.html'} (README not touched)")
    elif os.environ.get("README", "1") != "0":
        (ROOT / "README.md").write_text(readme(repos), encoding="utf-8")
        print("  README.md")


if __name__ == "__main__":
    main()
