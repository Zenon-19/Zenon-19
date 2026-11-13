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

LOCATION = "Delhi, India"
ABOUT = ("I'm Lakshya Lohani, also known as Zenon - a founder and developer building software "
         "products that solve real problems. I work across full-stack development, AI integrations "
         "and backend systems, and enjoy taking an idea to a working product with clean interfaces "
         "and maintainable engineering.")
AREAS = ["Full-stack development", "AI / ML", "Intelligent applications", "Workflow automation"]
FOCUS = [
    ("Building", "SaaS products, web applications and developer tools"),
    ("Exploring", "AI/ML, LLM integrations and intelligent workflows"),
    ("Engineering", "APIs, databases and full-stack systems"),
    ("Growing", "Learning new technologies and building in public"),
]
QUOTE = "Build with intention. Keep it simple. Make it useful."
STACK = [
    ("Languages", ["Python", "TypeScript", "JavaScript"]),
    ("Frontend", ["React", "Next.js", "HTML", "CSS", "Tailwind", "Figma"]),
    ("Backend / DB", ["Node.js", "Express", "FastAPI", "Flask", "PostgreSQL", "MongoDB", "MySQL", "Supabase"]),
    ("AI / Infra", ["TensorFlow", "PyTorch", "Git", "GitHub", "Docker", "AWS", "Vercel", "Linux"]),
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
    has_portrait = PORTRAIT.exists()
    c = Card("hero", W, 228, f"{NAME}, {EYEBROW.title()}. {TAGLINE}", base)
    L = 44
    maxw = W - 2 * L - (190 if has_portrait else 0)

    d = c.d()
    dot_smil = (f'<circle cx="{L + 4}" cy="46" r="3.5" fill="{T["accent"]}">'
                f'<animate attributeName="opacity" values="1;.35;1" dur="2.4s" repeatCount="indefinite"/></circle>'
                f'<circle cx="{L + 4}" cy="46" r="3.5" fill="none" stroke="{T["accent"]}">'
                f'<animate attributeName="r" values="3.5;10" dur="2.4s" repeatCount="indefinite"/>'
                f'<animate attributeName="opacity" values=".6;0" dur="2.4s" repeatCount="indefinite"/></circle>')
    dot_still = f'<circle cx="{L + 4}" cy="46" r="3.5" fill="{T["accent"]}"/>'
    c.add(c.g(Card.dual(dot_smil, dot_still), d))
    c.add(c.text(L + 20, 50, f"{EYEBROW}  /  {LOCATION.upper()}", "mono", 11, T["muted"], d=d, ls=1.5))

    size = 54
    nw = font("display").width(NAME, size)
    if nw > maxw:
        size = size * maxw / nw
    c.add(c.text(L, 110, NAME, "display", round(size, 1), T["ink"], 600, d=c.d()))
    c.add(c.text(L, 134, ALIAS, "mono", 12, T["accent"], d=c.d()))
    d = c.d()
    for i, line in enumerate(wrap("body", TAGLINE, 16, maxw, 2)):
        c.add(c.text(L, 166 + i * 23, line, "body", 16, T["muted"], d=d + i * 0.06))
    c.add(c.grow(L, 204, 56, 3, T["accent"], c.d()))

    if has_portrait:
        cx, cy, r = W - L - 78, 114, 78
        mime = "image/jpeg" if PORTRAIT.suffix.lower() in (".jpg", ".jpeg") else "image/png"
        b64 = base64.b64encode(PORTRAIT.read_bytes()).decode()
        c.defs.append(f'<clipPath id="pc"><circle cx="{cx}" cy="{cy}" r="{r - 8}"/></clipPath>')
        d = c.d()
        img = (f'<image href="data:{mime};base64,{b64}" x="{cx - r}" y="{cy - r}" '
               f'width="{2 * r}" height="{2 * r}" clip-path="url(#pc)" '
               f'preserveAspectRatio="xMidYMid slice"/>')
        circ = 2 * math.pi * r
        ring = lambda off, anim: (
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{T["accent"]}" '
            f'stroke-width="2.5" stroke-linecap="round" stroke-dasharray="{circ:.1f}" '
            f'stroke-dashoffset="{off}" transform="rotate(-90 {cx} {cy})">{anim}</circle>')
        ring_anim = (f'<animate attributeName="stroke-dashoffset" from="{circ:.1f}" to="0" '
                     f'begin="{d}s" dur="1.6s" fill="freeze" {SPLINE}/>')
        c.add(c.g(img, d))
        c.add(Card.dual(ring(f"{circ:.1f}", ring_anim), ring(0, "")))
    return c


def card_tile(i, title, sub, base):
    c = Card(f"tile-{i + 1}", 290, 100, f"{title}: {sub}", base)
    d = c.d(extra=i * 0.12)
    c.add(c.text(24, 30, f"0{i + 1}", "mono", 11, T["accent"], d=d, ls=2))
    c.add(arrow(290 - 24 - 11.2, 17, d, 0.8))
    c.add(c.text(24, 60, title, "display", 22, T["ink"], 600, d=c.d()))
    ssize = 11
    sw = font("mono").width(sub, ssize)
    if sw > 290 - 48:
        ssize = round(ssize * (290 - 48) / sw, 1)
    c.add(c.text(24, 82, sub, "mono", ssize, T["muted"], d=c.d()))
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

    c = Card("contributions", W, 290,
             f"Contributions per month: {num(total)} in the last 12 months. "
             f"Current streak {cur} days, {active} active days, busiest day {busiest[1]} contributions.", base)
    c.add(c.text(40, 40, "Contributions per month", "display", 20, T["ink"], 600, d=c.d()))
    c.add(c.text(40, 60, f"{num(total)} contributions in the last 12 months", "body", 12,
                 T["muted"], d=c.d()))

    x0, x1, top, basey = 70, 590, 96, 224
    step = nice_step(max(max(vals), 1) / 4)
    ymax = step * 4
    for k in range(5):
        gy = basey - k * (basey - top) / 4
        c.add(f'<line x1="{x0}" x2="{x1}" y1="{gy:.1f}" y2="{gy:.1f}" stroke="{T["border"]}" stroke-width="1"/>')
        c.add(c.text(x0 - 8, round(gy + 3.5, 1), num(k * step), "mono", 10, T["muted"], anchor="end"))

    slot = (x1 - x0) / 12
    bw = 22
    peak = vals.index(max(vals))
    smil_bars, still_bars, labels = [], [], []
    t0 = c.d(0.0, 0.1)
    for i, v in enumerate(vals):
        h = max(v / ymax * (basey - top), 3 if v else 2)
        bx = round(x0 + i * slot + (slot - bw) / 2, 1)
        by = round(basey - h, 1)
        col = T["accent"] if i == peak else mix(T["bg"], T["accent"], 0.5)
        b = round(t0 + i * 0.06, 2)
        still_bars.append(f'<rect x="{bx}" y="{by}" width="{bw}" height="{h:.1f}" rx="3" fill="{col}"/>')
        smil_bars.append(
            f'<rect x="{bx}" y="{basey}" width="{bw}" height="0" rx="3" fill="{col}">'
            f'<animate attributeName="height" from="0" to="{h:.1f}" begin="{b}s" dur=".9s" fill="freeze" {SPLINE}/>'
            f'<animate attributeName="y" from="{basey}" to="{by}" begin="{b}s" dur=".9s" fill="freeze" {SPLINE}/></rect>')
        labels.append(c.text(round(bx + bw / 2, 1), round(by - 6, 1), num(v), "mono", 10,
                             T["ink"] if i == peak else T["muted"], anchor="middle",
                             d=round(b + 0.7, 2)))
        mlabel = calendar.month_abbr[months[i][1]].upper()
        c.add(c.text(round(bx + bw / 2, 1), basey + 17, mlabel, "mono", 10, T["muted"], anchor="middle"))
    c.add(Card.dual("".join(smil_bars), "".join(still_bars)))
    for lab in labels:
        c.add(lab)

    px = 640
    c.add(f'<line x1="{px - 26}" x2="{px - 26}" y1="84" y2="262" stroke="{T["border"]}"/>')
    stats = [
        ("CURRENT STREAK", str(cur), "days" if cur != 1 else "day", f"longest: {best} days"),
        ("ACTIVE DAYS", str(active), "days", f"{round(100 * active / len(days))}% of the last {len(days)} days"),
        ("BUSIEST DAY", num(busiest[1]), "contributions" if busiest[1] != 1 else "contribution",
         f"{busiest[0].day} {calendar.month_abbr[busiest[0].month]} {busiest[0].year}"),
    ]
    for i, (lab, big, unit, sub) in enumerate(stats):
        y = 92 + i * 62
        d = c.d(0.0, 0.5 + i * 0.15)
        c.add(c.text(px, y, lab, "mono", 10, T["accent"], d=d, ls=1.5))
        c.add(c.text(px, y + 28, big, "display", 28, T["ink"], 600, d=d + 0.05))
        bwid = font("display").width(big, 28)
        c.add(c.text(round(px + bwid + 6, 1), y + 28, unit, "body", 12, T["muted"], d=d + 0.05))
        c.add(c.text(px, y + 44, sub, "body", 12, T["muted"], d=d + 0.1))
    return c


def card_repo(i, repo, base):
    name = repo["name"]
    c = Card(f"repo-{i + 1}", W, 120, f"{name}: {repo.get('description') or ''}", base)
    d0 = c.d(extra=i * 0.25)
    c.add(c.text(36, 28, f"FEATURED 0{i + 1}", "mono", 10, T["accent"], d=d0, ls=2))
    c.add(c.text(36, 56, name, "display", 22, T["ink"], 600, d=c.d()))
    dd = c.d()
    desc = repo.get("description") or "No description yet."
    for k, line in enumerate(wrap("body", desc, 13, 700, 2)):
        c.add(c.text(36, 78 + k * 17, line, "body", 13, T["muted"], d=round(dd + k * 0.05, 2)))

    my, dm, x, parts = 108, c.d(), 36, []
    lang = repo.get("language")
    if lang:
        col = repo.get("color") or T["accent"]
        parts.append(f'<circle cx="{x + 4}" cy="{my - 4}" r="4" fill="{col}"/>')
        parts.append(c.text(x + 14, my, lang, "mono", 11, T["muted"]))
        x += 14 + font("mono").width(lang, 11) + 20
    stars, forks = int(repo.get("stars", 0) or 0), int(repo.get("forks", 0) or 0)
    sx, sy = x + 5, my - 4
    pts = " ".join(
        f"{sx + (5 if k % 2 == 0 else 2.2) * math.sin(k * math.pi / 5):.1f},"
        f"{sy - (5 if k % 2 == 0 else 2.2) * math.cos(k * math.pi / 5):.1f}" for k in range(10))
    parts.append(f'<polygon points="{pts}" fill="none" stroke="{T["muted"]}" stroke-width="1.2" stroke-linejoin="round"/>')
    parts.append(c.text(x + 15, my, num(stars), "mono", 11, T["muted"]))
    x += 15 + font("mono").width(num(stars), 11) + 20
    fx, fy = x + 4, my - 4
    parts.append(
        f'<g fill="none" stroke="{T["muted"]}" stroke-width="1.2" stroke-linecap="round">'
        f'<circle cx="{fx - 3}" cy="{fy - 5}" r="1.6"/><circle cx="{fx + 3}" cy="{fy - 5}" r="1.6"/>'
        f'<circle cx="{fx}" cy="{fy + 5}" r="1.6"/>'
        f'<path d="M{fx - 3} {fy - 3.4} V{fy - 1} Q{fx - 3} {fy + 1} {fx} {fy + 1} Q{fx + 3} {fy + 1} {fx + 3} {fy - 1} V{fy - 3.4} M{fx} {fy + 1} V{fy + 3.4}"/></g>')
    parts.append(c.text(x + 13, my, num(forks), "mono", 11, T["muted"]))
    c.add(c.g("".join(parts), dm))

    d = c.d()
    c.add(c.g(f'<circle cx="{W - 50}" cy="58" r="18" fill="none" stroke="{T["border"]}" stroke-width="1.5"/>', d))
    c.add(arrow(W - 50 - 5.6, 58 - 5.6, d, 0.8))
    return c


def chips(c, items, x, y, maxw, d, size=11, h=22, pad=10, gap=7, step=0.03):
    """Flow pill labels left to right, wrapping at maxw. Returns the bottom y."""
    f = font("mono")
    cx, cy, out = x, y, []
    for k, it in enumerate(items):
        w = f.width(it, size) + 2 * pad
        if cx + w > x + maxw and cx > x:
            cx, cy = x, cy + h + gap
        pill = (f'<rect x="{cx:.1f}" y="{cy}" width="{w:.1f}" height="{h}" rx="{h / 2}" '
                f'fill="{mix(T["bg"], T["ink"], 0.05)}" stroke="{T["border"]}"/>')
        label = c.text(round(cx + w / 2, 1), round(cy + h / 2 + size * 0.35, 1), it, "mono", size,
                       T["ink"], anchor="middle")
        out.append(c.g(pill + label, round(d + k * step, 2)))
        cx += w + gap
    c.add("".join(out))
    return cy + h


def card_about(base):
    c = Card("about", W, 100, f"About {NAME}. {ABOUT}", base)
    x, rx = 40, 580
    c.add(c.text(x, 34, f"ABOUT  /  {LOCATION.upper()}", "mono", 10, T["accent"], d=c.d(), ls=2))
    lines = wrap("body", ABOUT, 14, 490, 6)
    d = c.d()
    for i, line in enumerate(lines):
        c.add(c.text(x, 62 + i * 21, line, "body", 14, T["muted"], d=round(d + i * 0.05, 2)))
    y = 62 + (len(lines) - 1) * 21 + 20
    bottom = chips(c, AREAS, x, y, 490, c.d())
    qy = bottom + 32
    c.add(c.g(f'<rect x="{x}" y="{qy - 14}" width="3" height="19" rx="1.5" fill="{T["accent"]}"/>', c.d()))
    qs = 14
    qw = font("display").width(QUOTE, qs)
    if qw > 470:
        qs = round(qs * 470 / qw, 1)
    c.add(c.text(x + 14, qy, QUOTE, "display", qs, T["ink"], d=c.d()))

    rbottom = 0
    for i, (lab, val) in enumerate(FOCUS):
        ry = 34 + i * 50
        d = c.d(0.0, 0.3 + i * 0.12)
        c.add(c.text(rx, ry, lab.upper(), "mono", 10, T["accent"], d=d, ls=2))
        for k, line in enumerate(wrap("body", val, 13, 280, 2)):
            c.add(c.text(rx, ry + 19 + k * 16, line, "body", 13, T["ink"], d=round(d + 0.05, 2)))
            rbottom = ry + 19 + k * 16
    c.h = max(qy + 6, rbottom) + 26
    c.add(f'<line x1="{rx - 24}" x2="{rx - 24}" y1="24" y2="{c.h - 24}" stroke="{T["border"]}"/>')
    return c


def card_stack(base):
    flat = ", ".join(i for _, items in STACK for i in items)
    c = Card("stack", W, 100, f"Tech stack: {flat}", base)
    c.add(c.text(40, 34, "TECH STACK", "mono", 10, T["accent"], d=c.d(), ls=2))
    y = 50
    for gi, (label, items) in enumerate(STACK):
        d = c.d(0.0, 0.1 + gi * 0.12)
        c.add(c.text(40, y + 15, label.upper(), "mono", 10, T["muted"], d=d, ls=1.5))
        y = chips(c, items, 170, y, 690, d + 0.05) + 14
    c.h = y + 12
    return c


def card_graph(days, total, base):
    c = Card("graph", W, 222, f"Contribution graph with an animated snake: {num(total)} contributions in the last year", base)
    c.add(c.text(40, 38, "Contribution graph", "display", 20, T["ink"], 600, d=c.d()))
    c.add(c.text(W - 40, 38, f"{num(total)} contributions in the last year", "body", 12, T["muted"],
                 anchor="end", d=c.d()))

    first = days[0][0]
    off = (first.weekday() + 1) % 7                     # GitHub weeks start on Sunday
    ncols = (len(days) + off - 1) // 7 + 1
    x0, right = 80, W - 40
    pitch = (right - x0) / ncols
    cell = round(pitch * 0.8, 1)
    ytop = 80

    nz = sorted(n for _, n in days if n > 0)
    q = [nz[int(len(nz) * f)] for f in (0.25, 0.5, 0.75)] if nz else [1, 2, 3]
    ramp = [mix(T["bg"], "#FFFFFF", 0.07)] + [mix(T["bg"], T["accent"], t) for t in (0.3, 0.55, 0.78, 1.0)]

    def level(n):
        if n == 0:
            return 0
        return 1 + sum(n > t for t in q) if n > q[0] else 1

    # --- cells --------------------------------------------------------------
    cells = {}                                   # (col,row) -> (x, y, colour, count)
    for i, (d, n) in enumerate(days):
        col, row = (i + off) // 7, (i + off) % 7
        cells[(col, row)] = (round(x0 + col * pitch, 1), round(ytop + row * pitch, 1),
                             ramp[level(n)], n)

    # snake path: down column 0, up column 1, down column 2 ...
    path = []
    for col in range(ncols):
        rows = sorted(r for (cc, r) in cells if cc == col)
        path += [(col, r) for r in (rows if col % 2 == 0 else rows[::-1])]
    N, L, PAUSE, STEP = len(path), 5, 30, 0.06
    S = N + L + PAUSE                            # steps in one loop
    DUR = round(S * STEP, 2)
    t0 = c.d(0.0, 0.1)
    begin = round(t0 + 1.2, 2)                   # starts once the grid has faded in
    eat_at = {p: k for k, p in enumerate(path)}

    still_cols, smil_cols = {}, {}
    for (col, row), (x, y, colr, n) in cells.items():
        base = f'<rect x="{x}" y="{y}" width="{cell}" height="{cell}" rx="3" fill="{colr}"'
        still_cols.setdefault(col, []).append(base + "/>")
        if n > 0:                                # the snake eats active days
            t = round((eat_at[(col, row)] + 0.5) / S, 4)
            smil_cols.setdefault(col, []).append(
                base + f'><animate attributeName="fill" values="{colr};{ramp[0]}" '
                f'keyTimes="0;{t}" calcMode="discrete" dur="{DUR}s" begin="{begin}s" '
                f'repeatCount="indefinite"/></rect>')
        else:
            smil_cols.setdefault(col, []).append(base + "/>")
    for col in sorted(still_cols):
        c.add(c.g(Card.dual("".join(smil_cols[col]), "".join(still_cols[col])),
                  round(t0 + col * 0.014, 3)))

    # --- snake (SMIL only; discrete steps, one cell per STEP seconds) --------
    def track(k, axis):
        vals = []
        for s in range(S):
            j = s - k
            vals.append(str(cells[path[j]][axis]) if 0 <= j < N else "-40")
        return ";".join(vals)

    snake, parked = [], []
    for k in range(L):
        fill = T["ink"] if k == 0 else mix(T["ink"], T["bg"], 0.18 * k)
        snake.append(
            f'<rect x="-40" y="-40" width="{cell}" height="{cell}" rx="3" fill="{fill}">'
            f'<animate attributeName="x" values="{track(k, 0)}" calcMode="discrete" '
            f'dur="{DUR}s" begin="{begin}s" repeatCount="indefinite"/>'
            f'<animate attributeName="y" values="{track(k, 1)}" calcMode="discrete" '
            f'dur="{DUR}s" begin="{begin}s" repeatCount="indefinite"/></rect>')
        px, py = cells[path[N // 3 - k]][0], cells[path[N // 3 - k]][1]
        parked.append(f'<rect x="{px}" y="{py}" width="{cell}" height="{cell}" rx="3" fill="{fill}"/>')
    # STATIC=1 screenshots show the snake mid-grid; reduced-motion shows no snake
    c.add(Card.dual("".join(snake), "".join(parked) if STATIC else ""))

    last_m = -9
    for i, (d, _) in enumerate(days):
        col = (i + off) // 7
        if (d.day <= 7 and d.weekday() == 6 or i == 0) and col - last_m >= 3:
            c.add(c.text(round(x0 + col * pitch, 1), ytop - 12, calendar.month_abbr[d.month],
                         "mono", 11, T["muted"], d=round(t0 + 0.3, 2)))
            last_m = col
    for row, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        c.add(c.text(40, round(ytop + row * pitch + cell - 2, 1), lab, "mono", 10, T["muted"], d=round(t0, 2)))

    ly = ytop + 7 * pitch + 14
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
        f'<p align="center">{img("about", "About " + NAME + ": " + ABOUT)}</p>\n\n'
        f'<p align="center">{img("stack", "Tech stack")}</p>\n\n'
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
    t_tiles, t_about, t_stack, t_chart = 0.5, 1.0, 1.5, 2.0
    t_repos = 2.6
    t_graph = t_repos + 0.25 * len(repos) + 0.3

    cards = [card_hero(0.0)]
    cards += [card_tile(i, *t[:2], t_tiles) for i, t in enumerate(TILES)]
    cards += [card_about(t_about), card_stack(t_stack)]
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
