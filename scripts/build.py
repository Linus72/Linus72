#!/usr/bin/env python3
"""
Generates the animated ASCII / HUD style SVGs for the GitHub profile README.

    python3 scripts/build.py        -> writes assets/*-dark.svg and assets/*-light.svg

Everything is plain SVG + CSS/SMIL animation, so it plays inside GitHub's <img>.
"""
import math
import os
import random
from xml.sax.saxutils import escape

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets")
os.makedirs(OUT, exist_ok=True)

FONT = "'JetBrains Mono','SF Mono',SFMono-Regular,Menlo,Consolas,'Liberation Mono','Courier New',monospace"
HEAD_FONT_CANDIDATES = [
    "/Library/Fonts/SF-Pro-Display-Black.otf",
    "/System/Library/Fonts/Helvetica.ttc",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
]

THEMES = {
    "dark": dict(bg="#0a0a0a", fg="#e8e8e6", mid="#9b9b98", dim="#565654", faint="#262625",
                 red="#ff2b1c", line="#ffffff", scan_fill="#000000", scan_op=0.38,
                 vig="#000000", vig_op=0.65, roll_op=0.05, light=False),
    "light": dict(bg="#f0f0ec", fg="#121212", mid="#55554f", dim="#a3a39d", faint="#d6d6d0",
                  red="#e3160b", line="#000000", scan_fill="#000000", scan_op=0.06,
                  vig="#000000", vig_op=0.10, roll_op=0.05, light=True),
}

RAMP = " .:-=+*#%@"


# --------------------------------------------------------------------------- helpers
def f1(v):
    return f"{v:.1f}".rstrip("0").rstrip(".")


def text_line(x, y, s, cw, fill=None, cls=None, extra=""):
    """One monospace line. Leading spaces become an x offset, width is forced with textLength."""
    s = s.rstrip()
    body = s.lstrip(" ")
    if not body:
        return ""
    lead = len(s) - len(body)
    attrs = f'x="{f1(x + lead * cw)}" y="{f1(y)}" textLength="{f1(len(body) * cw)}"'
    if fill:
        attrs += f' fill="{fill}"'
    if cls:
        attrs += f' class="{cls}"'
    return f"<text {attrs}{extra}>{escape(body)}</text>"


def seg_line(x, y, segs, cw, extra=""):
    """A line made of (text, fill) segments rendered as tspans."""
    total = sum(len(t) for t, _ in segs)
    spans = "".join(
        f'<tspan fill="{c}">{escape(t)}</tspan>' if c else escape(t) for t, c in segs
    )
    return f'<text x="{f1(x)}" y="{f1(y)}" textLength="{f1(total * cw)}"{extra}>{spans}</text>'


def grid_lines(x0, y0, rows, cw, ch):
    out = []
    for r, row in enumerate(rows):
        t = text_line(x0, y0 + (r + 1) * ch - ch * 0.18, row, cw)
        if t:
            out.append(t)
    return "".join(out)


def svg_open(w, h, th, css=""):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
        f'xml:space="preserve" font-family="{FONT}" lengthAdjust="spacingAndGlyphs">'
        f"<style>text{{white-space:pre}}"
        f".blink{{animation:blink 1.1s steps(1) infinite}}@keyframes blink{{50%{{opacity:0}}}}"
        f"{css}</style>"
    )


def chrome_defs(w, h, th, uid):
    """Background, scanlines, vignette, rolling CRT band."""
    return (
        "<defs>"
        f'<pattern id="sl{uid}" width="4" height="3" patternUnits="userSpaceOnUse">'
        f'<rect width="4" height="1" fill="{th["scan_fill"]}" opacity="{th["scan_op"]}"/></pattern>'
        f'<radialGradient id="vg{uid}" cx="50%" cy="50%" r="75%">'
        f'<stop offset="55%" stop-color="{th["vig"]}" stop-opacity="0"/>'
        f'<stop offset="100%" stop-color="{th["vig"]}" stop-opacity="{th["vig_op"]}"/></radialGradient>'
        f'<linearGradient id="rb{uid}" x1="0" y1="0" x2="0" y2="1">'
        f'<stop offset="0" stop-color="{th["line"]}" stop-opacity="0"/>'
        f'<stop offset=".5" stop-color="{th["line"]}" stop-opacity="{th["roll_op"]}"/>'
        f'<stop offset="1" stop-color="{th["line"]}" stop-opacity="0"/></linearGradient>'
        "</defs>"
    )


def chrome_bg(w, h, th):
    return f'<rect width="{w}" height="{h}" rx="10" fill="{th["bg"]}"/>'


def chrome_overlay(w, h, th, uid, roll=True):
    o = (f'<rect width="{w}" height="{h}" fill="url(#sl{uid})" pointer-events="none"/>'
         f'<rect width="{w}" height="{h}" rx="10" fill="url(#vg{uid})"/>')
    if roll:
        o += (f'<rect x="0" y="-140" width="{w}" height="140" fill="url(#rb{uid})">'
              f'<animateTransform attributeName="transform" type="translate" from="0 0" to="0 {h + 140}" '
              f'dur="7s" repeatCount="indefinite"/></rect>')
    return o


def corners(w, h, th, pad=16, L=22, col=None):
    c = col or th["mid"]
    p = pad
    d = (f"M{p},{p + L}V{p}H{p + L} M{w - p - L},{p}H{w - p}V{p + L} "
         f"M{w - p},{h - p - L}V{h - p}H{w - p - L} M{p + L},{h - p}H{p}V{h - p - L}")
    return f'<path d="{d}" fill="none" stroke="{c}" stroke-width="1.5"/>'


def frames_css(cls, n, dur):
    pct = 100.0 / n
    return (f".{cls}{{opacity:0;animation:{cls} {dur}s step-end infinite}}"
            f"@keyframes {cls}{{0%{{opacity:1}}{pct:.4f}%{{opacity:0}}100%{{opacity:0}}}}")


def frame_group(cls, i, n, dur, inner):
    return f'<g class="{cls}" style="animation-delay:{i * dur / n:.4f}s">{inner}</g>'


def typed(x, y, segs, cw, begin, speed=0.028, clip_id="", fs=None, h=None):
    """Line that types itself in (discrete reveal via SMIL on a clip rect)."""
    n = sum(len(t) for t, _ in segs)
    hgt = h or (fs * 1.5)
    vals = ";".join(f1(k * cw) for k in range(n + 1))
    dur = max(n * speed, 0.05)
    clip = (f'<clipPath id="{clip_id}"><rect x="{f1(x - 1)}" y="{f1(y - hgt * 0.8)}" height="{f1(hgt)}" width="0">'
            f'<animate attributeName="width" values="{vals}" calcMode="discrete" dur="{dur:.2f}s" '
            f'begin="{begin:.2f}s" fill="freeze"/></rect></clipPath>')
    return clip + f'<g clip-path="url(#{clip_id})">{seg_line(x, y, segs, cw)}</g>', begin + dur


def head_font(size):
    for p in HEAD_FONT_CANDIDATES:
        if os.path.exists(p):
            return ImageFont.truetype(p, size)
    return ImageFont.load_default()


def bitmap_text(text, cols, rows, seed=1, tracking=0.06):
    """Render text with a heavy font and sample it into a cols x rows coverage grid."""
    font = head_font(260)
    # draw char by char to add tracking
    widths = [font.getbbox(c)[2] - font.getbbox(c)[0] for c in text]
    gap = int(260 * tracking)
    W = sum(widths) + gap * (len(text) + 2) + 40
    img = Image.new("L", (W, 400), 0)
    d = ImageDraw.Draw(img)
    x = 20
    for c, wdt in zip(text, widths):
        bb = font.getbbox(c)
        d.text((x - bb[0], 40), c, font=font, fill=255)
        x += wdt + gap
    img = img.crop(img.getbbox())
    img = img.resize((cols * 6, rows * 6), Image.LANCZOS).resize((cols, rows), Image.BOX)
    return np.asarray(img, dtype=np.float32) / 255.0


def hollow_ascii(cov, seed=1, solid=False):
    """Outline-heavy dithered lettering: dense chars on the edge, sparse texture inside."""
    rng = random.Random(seed)
    R, C = cov.shape
    on = cov > 0.42
    rows = []
    for r in range(R):
        line = []
        for c in range(C):
            v = cov[r, c]
            if on[r, c]:
                edge = any(
                    not (0 <= r + dr < R and 0 <= c + dc < C and on[r + dr, c + dc])
                    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1))
                )
                if edge or solid:
                    line.append(rng.choice("#@%#"))
                else:
                    line.append(":" if (r % 2 == 0) else rng.choice(" ..:"))
            elif v > 0.16:
                line.append(rng.choice(".:"))
            else:
                line.append(" ")
        rows.append("".join(line))
    return rows


# --------------------------------------------------------------------------- 3D knot
def knot_geometry():
    T = np.linspace(0, 2 * np.pi, 2400, endpoint=False)
    P = np.linspace(0, 2 * np.pi, 120, endpoint=False)
    C = np.stack([np.sin(T) + 2 * np.sin(2 * T), np.cos(T) - 2 * np.cos(2 * T), -np.sin(3 * T)], -1)
    dT = np.stack([np.cos(T) + 4 * np.cos(2 * T), -np.sin(T) + 4 * np.sin(2 * T), -3 * np.cos(3 * T)], -1)
    Tn = dT / np.linalg.norm(dT, axis=-1, keepdims=True)
    Nn = np.cross(Tn, np.array([0.0, 0.0, 1.0]))
    Nn /= np.linalg.norm(Nn, axis=-1, keepdims=True)
    Bn = np.cross(Tn, Nn)
    nrm = Nn[:, None, :] * np.cos(P)[None, :, None] + Bn[:, None, :] * np.sin(P)[None, :, None]
    pts = C[:, None, :] + 0.45 * nrm
    return pts.reshape(-1, 3), nrm.reshape(-1, 3)


def centerline(t):
    return np.array([math.sin(t) + 2 * math.sin(2 * t), math.cos(t) - 2 * math.cos(2 * t), -math.sin(3 * t)])


TILT = 0.55
DIST = 12.0


def xform(p, a):
    ca, sa = math.cos(a), math.sin(a)
    ct, st = math.cos(TILT), math.sin(TILT)
    x = p[..., 0] * ca - p[..., 1] * sa
    y = p[..., 0] * sa + p[..., 1] * ca
    z = p[..., 2]
    y2 = y * ct - z * st
    z2 = y * st + z * ct
    return np.stack([x, y2, z2], -1)


def project(p, S, cx, cy):
    k = DIST / (DIST - p[..., 2])
    return cx + p[..., 0] * k * S, cy - p[..., 1] * k * S


def knot_frames(n, cols, rows, cw, ch, light, seed=7):
    pts, nrm = knot_geometry()
    W, H = cols * cw, rows * ch
    S = min(W, H) / 2 / 4.05
    cx, cy = W / 2, H / 2
    L = np.array([-0.45, 0.62, 0.65]); L /= np.linalg.norm(L)
    Hv = L + np.array([0, 0, 1.0]); Hv /= np.linalg.norm(Hv)
    rng = np.random.default_rng(seed)

    # tracked point slides along the knot so the loop is seamless (3-fold symmetry)
    t0 = 0.55
    a_end = 2 * math.pi / 3
    ref = xform(centerline(t0), 0)
    best = None
    for sgn in (1, -1):
        d = np.linalg.norm(xform(centerline(t0 + sgn * 2 * math.pi / 3), a_end) - ref)
        if best is None or d < best[0]:
            best = (d, sgn)
    sgn = best[1]

    out = []
    for f in range(n):
        a = a_end * f / n
        P = xform(pts, a)
        Nr = xform(nrm, a)
        px, py = project(P, S, cx, cy)
        col = (px / cw).astype(int)
        row = (py / ch).astype(int)
        ok = (col >= 0) & (col < cols) & (row >= 0) & (row < rows)
        diff = np.clip(Nr @ L, 0, 1)
        spec = np.clip(Nr @ Hv, 0, 1) ** 26
        I = 0.07 + 0.74 * diff + 0.5 * spec
        I *= 0.62 + 0.38 * (P[:, 2] + 4) / 8
        I = np.clip(I + rng.normal(0, 0.045, I.shape), 0, 1)
        order = np.argsort(P[:, 2])
        idx = (row * cols + col)
        sel = order[ok[order]]
        gI = np.full(rows * cols, -1.0)
        gY = np.zeros(rows * cols)
        gI[idx[sel]] = I[sel]
        gY[idx[sel]] = P[sel, 1]
        scan = 4.3 - 8.6 * f / n
        grey, red = [], []
        for r in range(rows):
            gl, rl = [], []
            for c in range(cols):
                v = gI[r * cols + c]
                if v < 0:
                    gl.append(" "); rl.append(" ")
                    continue
                q = (1 - v) if light else v
                k = int(min(max(1 + q * (len(RAMP) - 1), 1), len(RAMP) - 1))
                is_red = abs(gY[r * cols + c] - scan) < 0.17 or rng.random() < 0.008
                if is_red:
                    gl.append(" "); rl.append(RAMP[max(k, 5)])
                else:
                    gl.append(RAMP[k]); rl.append(" ")
            grey.append("".join(gl)); red.append("".join(rl))
        tp = xform(centerline(t0 - sgn * (2 * math.pi / 3) * f / n), a)
        tx, ty = project(tp, S, cx, cy)
        out.append((grey, red, float(tx), float(ty)))
    return out


# --------------------------------------------------------------------------- HERO
def build_hero(th, name):
    W, H = 1200, 640
    uid = "h"
    N, DUR = 40, 5.0
    fs = 11; cw = fs * 0.6; ch = fs
    cols, rows = 76, 46
    kx, ky = 1200 - 52 - 76 * 6.6, 58

    hfs = 8; hcw = hfs * 0.6; hch = hfs
    hcols, hrows = 124, 16
    hx, hy = 52, 92

    css = frames_css("fr", N, DUR) + frames_css("nz", 3, 0.36)
    css += (".gl{animation:gl 4.2s steps(1) infinite;opacity:0}"
            "@keyframes gl{0%{opacity:0;transform:translate(0,0)}84%{opacity:.9;transform:translate(-16px,0)}"
            "86%{opacity:.8;transform:translate(11px,2px)}88%{opacity:.9;transform:translate(-5px,0)}"
            "90%{opacity:0;transform:translate(0,0)}}"
            ".fl{animation:fl 4.2s steps(1) infinite}@keyframes fl{0%{opacity:1}85%{opacity:.35}87%{opacity:1}89%{opacity:.55}91%{opacity:1}}"
            ".wv{animation:wv 3.2s linear infinite}@keyframes wv{to{transform:translateX(-400px)}}")
    s = [svg_open(W, H, th, css), chrome_defs(W, H, th, uid), chrome_bg(W, H, th)]

    # static noise (3 shimmering frames)
    rng = random.Random(3)
    ncols, nrows = int(W / 6), int(H / 10)
    for i in range(3):
        rws = []
        for r in range(nrows):
            rws.append("".join(rng.choice(".:'`") if rng.random() < 0.018 else " " for _ in range(ncols)))
        s.append(frame_group("nz", i, 3, 0.36,
                             f'<g font-size="10" fill="{th["faint"]}">{grid_lines(0, 0, rws, 6, 10)}</g>'))

    # perspective floor
    hz, fy0, vx = 455, 470, 900
    g = []
    for k in range(-26, 27):
        x2 = vx + k * 120
        g.append(f"M{vx + k * 10},{fy0}L{x2},{H}")
    yy = fy0
    step = 4
    while yy < H:
        g.append(f"M0,{yy:.1f}H{W}")
        step *= 1.32
        yy += step
    s.append(f'<path d="{" ".join(g)}" stroke="{th["dim"]}" stroke-width=".7" opacity=".55" fill="none"/>')
    s.append(f'<path d="M0,{fy0}H{W}" stroke="{th["mid"]}" stroke-width="1" opacity=".6"/>')

    # red signal wave (scrolls)
    pts = []
    rr = random.Random(11)
    for x in range(0, 1601, 4):
        ph = x / 400 * 2 * math.pi
        y = 3.2 * math.sin(ph) + 2.2 * math.sin(3 * ph + 1) + 1.4 * math.sin(7 * ph)
        if (x % 400) in (124, 128, 132):
            y += rr.choice([-16, 14, -9])
        y += (rr.random() - .5) * 1.6 if (x % 400) not in (124, 128, 132) else 0
        pts.append(f"{x},{y:.1f}")
    # make it periodic by mirroring the first period
    base = pts[:101]
    full = []
    for rep in range(4):
        for p in base:
            x, y = p.split(",")
            full.append(f"{int(x) + rep * 400},{y}")
    s.append(f'<g transform="translate(0,566)"><g class="wv"><polyline points="{" ".join(full)}" '
             f'fill="none" stroke="{th["red"]}" stroke-width="1.6" opacity=".9"/></g></g>')

    # headline: hollow dithered ASCII, red
    cov = bitmap_text("LINUS72", hcols, hrows)
    hrows_txt = hollow_ascii(cov, seed=5)
    head = f'<g font-size="{hfs}" fill="{th["red"]}">{grid_lines(hx, hy, hrows_txt, hcw, hch)}</g>'
    s.append(f'<g class="fl">{head}</g>')
    # glitch: offset copy of a horizontal slice
    slice_rows = [ln if 4 <= i <= 9 else "" for i, ln in enumerate(hrows_txt)]
    s.append(f'<g class="gl"><g font-size="{hfs}" fill="{th["fg"]}" opacity=".7">{grid_lines(hx, hy, slice_rows, hcw, hch)}</g></g>')

    # small label above headline
    mfs = 11; mcw = mfs * 0.6
    s.append(f'<g font-size="{mfs}" fill="{th["mid"]}">'
             + text_line(hx, hy - 14, "SUBJECT_ID // 0x4C37-72", mcw)
             + text_line(hx + 300, hy - 14, "CLASS: BUILDER", mcw)
             + "</g>")
    s.append(f'<path d="M{hx},{hy + hrows * hch + 10}h560" stroke="{th["red"]}" stroke-width="1.2"/>')
    s.append(f'<path d="M{hx},{hy + hrows * hch + 10}h560" stroke="{th["red"]}" stroke-width="5" stroke-dasharray="2 70" opacity=".8"/>')

    # typed taglines
    tfs = 15; tcw = tfs * 0.6
    ty0 = 268
    lines = [
        [("> ", th["red"]), ("WEBDESIGN & DEVELOPMENT", th["fg"])],
        [("> ", th["red"]), ("WEBSITES · WEB-APPS · KI · SEO/GEO", th["fg"])],
        [("> ", th["red"]), ("OSNABRÜCK, DE", th["fg"]), (" — REMOTE WORLDWIDE", th["mid"])],
    ]
    t = 0.6
    for i, segs in enumerate(lines):
        el, t = typed(hx, ty0 + i * 30, segs, tcw, t, speed=0.035, clip_id=f"tp{i}", fs=tfs)
        s.append(f'<g font-size="{tfs}">{el}</g>')
        t += 0.15
    # cursor line
    cy_ = ty0 + 3 * 30
    s.append(f'<g font-size="{tfs}">' + seg_line(hx, cy_, [("> ", th["red"]), ("STATUS: ", th["mid"]), ("OPEN FOR PROJECTS", th["fg"])], tcw)
             + f'</g><rect class="blink" x="{hx + 27 * tcw + 4}" y="{cy_ - tfs * 0.82}" width="{tcw}" height="{tfs}" fill="{th["red"]}"/>')

    # spec block
    sfs = 11; scw = sfs * 0.6
    spec = [
        [("CONTACT .... ", th["dim"]), ("linus@gekkos.tech", th["red"])],
        [("COORDS ..... ", th["dim"]), ("52.27°N  08.04°E", th["fg"])],
        [("MODE ....... ", th["dim"]), ("BUILD > SHIP > REPEAT", th["fg"])],
    ]
    for i, segs in enumerate(spec):
        s.append(f'<g font-size="{sfs}">{seg_line(hx, 400 + i * 18, segs, scw)}</g>')

    # knot frames with tracking HUD
    frames = knot_frames(N, cols, rows, cw, ch, th["light"])
    for i, (grey, red, tx, ty) in enumerate(frames):
        X, Y = kx + tx, ky + ty
        cx_ = int(abs(X * 7.31 + 1631)) % 10000
        cy2 = int(abs(Y * 11.7 + 2947)) % 10000
        flip = X + 74 + 130 > W - 40
        lx, ly = (X - 74 - 112, Y - 58) if flip else (X + 74, Y - 58)
        bx = X - 21 if flip else X + 21
        lead = (f"M{bx:.1f},{Y - 21:.1f}L{lx + 112:.1f},{ly + 4:.1f}H{lx:.1f}" if flip
                else f"M{bx:.1f},{Y - 21:.1f}L{lx:.1f},{ly + 4:.1f}H{lx + 112:.1f}")
        inner = (
            f'<g font-size="{fs}" fill="{th["fg"]}">{grid_lines(kx, ky, grey, cw, ch)}</g>'
            f'<g font-size="{fs}" fill="{th["red"]}">{grid_lines(kx, ky, red, cw, ch)}</g>'
            f'<rect x="{X - 21:.1f}" y="{Y - 21:.1f}" width="42" height="42" fill="none" stroke="{th["fg"]}" stroke-width="1.2"/>'
            f'<circle cx="{X:.1f}" cy="{Y:.1f}" r="2.6" fill="{th["red"]}"/>'
            f'<path d="{lead}" fill="none" stroke="{th["fg"]}" stroke-width="1"/>'
            f'<rect x="{lx - 2:.1f}" y="{ly - 28:.1f}" width="116" height="30" fill="{th["bg"]}" opacity=".82"/>'
            f'<g font-size="11">'
            + text_line(lx + 2, ly - 16, "LOCK // L72", 6.6, fill=th["fg"])
            + text_line(lx + 2, ly - 2, f"x. {cx_:04d}  y. {cy2:04d}", 6.6, fill=th["fg"])
            + f'</g><path d="M{lx + 2:.1f},{ly + 1:.1f}h52" stroke="{th["red"]}" stroke-width="1.4"/>'
            + f'<g font-size="11" fill="{th["mid"]}">'
            + text_line(W - 160, H - 30, f"FR {i + 1:03d}/{N:03d}", 6.6)
            + "</g>"
        )
        s.append(frame_group("fr", i, N, DUR, inner))

    # top HUD bar
    s.append(f'<g font-size="11" fill="{th["mid"]}">'
             + text_line(52, 40, "REC", 6.6, fill=th["fg"])
             + text_line(84, 40, "L72_SYS // FEED_01 // CH.072", 6.6)
             + text_line(W - 52 - 33 * 6.6, 40, "OSNABRÜCK · 52.27N 08.04E · LIVE", 6.6)
             + "</g>")
    s.append(f'<circle class="blink" cx="44" cy="36" r="4" fill="{th["red"]}"/>')
    s.append(f'<g font-size="11" fill="{th["mid"]}">'
             + text_line(52, H - 30, "SIGNAL ▲ 72.0 dB · ENCODE ASCII/10 · NO SLEEP MODE", 6.6)
             + "</g>")
    s.append(corners(W, H, th))
    s.append(chrome_overlay(W, H, th, uid))
    s.append("</svg>")
    write(f"hero-{name}.svg", "".join(s))


# --------------------------------------------------------------------------- ABOUT
def radar_frames(n, cols, rows, cw, ch, seed=4):
    rng = random.Random(seed)
    R = min(cols * cw, rows * ch) / 2 - 4
    cxp, cyp = cols * cw / 2, rows * ch / 2
    blips = [(rng.uniform(0, 2 * math.pi), rng.uniform(0.25, 0.92)) for _ in range(5)]
    out = []
    for f in range(n):
        sweep = 2 * math.pi * f / n
        g, r_ = [], []
        for r in range(rows):
            gl, rl = [], []
            for c in range(cols):
                dx = (c + .5) * cw - cxp
                dy = (r + .5) * ch - cyp
                d = math.hypot(dx, dy) / R
                ang = math.atan2(dy, dx) % (2 * math.pi)
                lag = (sweep - ang) % (2 * math.pi)
                gc, rc = " ", " "
                if d <= 1.0:
                    ring = min(abs(d - 1.0), abs(d - .66), abs(d - .33)) < 0.045
                    axis = abs(dx) < cw * .5 or abs(dy) < ch * .5
                    if ring:
                        gc = "."
                    if axis:
                        gc = "+" if (abs(dx) < cw * .5 and abs(dy) < ch * .5) else ("|" if abs(dx) < cw * .5 else "-")
                        if d > .98:
                            gc = " "
                    if lag < 0.10:
                        rc, gc = "#", " "
                    elif lag < 0.5:
                        gc = "=+:"[min(2, int(lag / .5 * 3))] if gc == " " or gc == "." else gc
                    for ba, bd in blips:
                        bx, by = math.cos(ba) * bd * R, math.sin(ba) * bd * R
                        if abs(dx - bx) < cw * .9 and abs(dy - by) < ch * .6:
                            bl = (sweep - ba) % (2 * math.pi)
                            if bl < 2.2:
                                rc, gc = ("@" if bl < 0.9 else "o"), " "
                elif abs(d - 1.0) < 0.05:
                    gc = "."
                gl.append(gc); rl.append(rc)
            g.append("".join(gl)); r_.append("".join(rl))
        out.append((g, r_))
    return out


def build_panel(th, name):
    W, H = 1200, 540
    uid = "p"
    N, DUR = 24, 3.0
    css = frames_css("rd", N, DUR)
    s = [svg_open(W, H, th, css), chrome_defs(W, H, th, uid), chrome_bg(W, H, th)]
    x0 = 52
    s.append(section_header(x0, 52, W, "01", "SERVICES // STACK", "ID 0x4C37-72", th))

    t = 0.3
    bfs = 13; bcw = bfs * 0.6
    bullets = [
        ("[WEB]   ", "Webdesign & Development: Websites & Web-Apps, die hängen bleiben."),
        ("[KI]    ", "Chatbots, RAG, Workflow-Automation. DSGVO-konform, EU-gehostet."),
        ("[SEO]   ", "Sichtbar für Menschen und für ChatGPT, Gemini & Perplexity."),
        ("[CRAFT] ", "Motion, Performance & A11y sind Features, keine Nachgedanken."),
    ]
    for i, (tag, txt) in enumerate(bullets):
        el, t = typed(x0, 100 + i * 26, [(tag, th["red"]), (txt, th["fg"])], bcw, t,
                      speed=0.008, clip_id=f"bl{i}", fs=bfs)
        s.append(f'<g font-size="{bfs}">{el}</g>')

    # contact call-to-action
    cfs = 15; ccw = cfs * 0.6
    el, t = typed(x0, 230, [("> ", th["red"]), ("INTERESSE AN EINEM PROJEKT? SCHREIB MIR:", th["fg"])],
                  ccw, t + 0.1, speed=0.02, clip_id="ct0", fs=cfs)
    s.append(f'<g font-size="{cfs}">{el}</g>')
    mail = "linus@gekkos.tech"
    el, t = typed(x0, 258, [("> ", th["red"]), (mail, th["red"])], ccw, t + 0.05, speed=0.03, clip_id="ct1", fs=cfs)
    s.append(f'<g font-size="{cfs}">{el}</g>')
    s.append(f'<path d="M{x0 + 2 * ccw:.1f},{263}h{len(mail) * ccw:.1f}" stroke="{th["red"]}" stroke-width="1.2"/>')
    s.append(f'<rect class="blink" x="{x0 + (len(mail) + 2) * ccw + 5:.1f}" y="{258 - cfs * .82:.1f}" width="{ccw:.1f}" height="{cfs}" fill="{th["red"]}"/>')

    s.append(f'<path d="M{x0},300H{W - x0}" stroke="{th["dim"]}" stroke-width="1" stroke-dasharray="3 5"/>')

    fs = 13; cw = fs * 0.6
    mods = [
        ("/lang    ", "TypeScript · JavaScript · Python · PHP · SQL · HTML · CSS"),
        ("/frontend", "React · Next.js · Tailwind · Framer Motion · GSAP · Three.js · Webflow"),
        ("/backend ", "Node.js · Express · PostgreSQL · MySQL · MongoDB · Redis · Supabase"),
        ("/ai      ", "OpenAI · Claude · RAG · n8n · Make"),
        ("/infra   ", "Docker · Linux · NGINX · Vercel · Cloudflare · Git · GitHub Actions"),
    ]
    for i, (path, items) in enumerate(mods):
        segs = [("$ ", th["red"]), ("mount ", th["mid"]), (path, th["fg"]), ("  [", th["dim"]),
                ("##########", th["fg"]), ("]  ", th["dim"]), ("OK", th["red"]), ("  ", None), (items, th["fg"])]
        el, t = typed(x0, 340 + i * 30, segs, cw, t, speed=0.006, clip_id=f"st{i}", fs=fs)
        s.append(f'<g font-size="{fs}">{el}</g>')
        t += 0.06
    el, t = typed(x0, 340 + len(mods) * 30 + 6, [("$ ", th["red"]), ("all systems nominal", th["fg"]),
                  (" · 5/5 modules online", th["mid"])], cw, t + 0.15, speed=0.025, clip_id="stz", fs=fs)
    s.append(f'<g font-size="{fs}">{el}</g>')

    # radar (top right, next to services)
    rfs = 10; rcw = rfs * 0.6; rch = rfs * 0.92
    rcols, rrows = 46, 22
    rx, ry = W - 52 - rcols * rcw, 66
    for i, (g, r_) in enumerate(radar_frames(N, rcols, rrows, rcw, rch)):
        inner = (f'<g font-size="{rfs}" fill="{th["mid"]}">{grid_lines(rx, ry, g, rcw, rch)}</g>'
                 f'<g font-size="{rfs}" fill="{th["red"]}">{grid_lines(rx, ry, r_, rcw, rch)}</g>')
        s.append(frame_group("rd", i, N, DUR, inner))
    s.append(f'<g font-size="11" fill="{th["mid"]}">'
             + text_line(rx + 10, ry + rrows * rch + 16, "SCAN // CLIENTS", 6.6, fill=th["fg"])
             + text_line(rx + 130, ry + rrows * rch + 16, "SLOTS: OPEN", 6.6)
             + "</g>")
    s.append(f'<circle class="blink" cx="{rx}" cy="{ry + rrows * rch + 12}" r="3.5" fill="{th["red"]}"/>')

    s.append(corners(W, H, th))
    s.append(chrome_overlay(W, H, th, uid))
    s.append("</svg>")
    write(f"panel-{name}.svg", "".join(s))


def section_header(x, y, W, num, title, right, th):
    fs = 13; cw = fs * 0.6
    left = f"[{num}] {title}"
    o = f'<g font-size="{fs}">'
    o += seg_line(x, y, [(f"[{num}] ", th["red"]), (title, th["fg"])], cw)
    o += text_line(W - x - len(right) * cw, y, right, cw, fill=th["mid"])
    o += "</g>"
    lx0 = x + len(left) * cw + 14
    lx1 = W - x - len(right) * cw - 14
    o += f'<path d="M{lx0:.1f},{y - 4.5}H{lx1:.1f}" stroke="{th["dim"]}" stroke-width="1" stroke-dasharray="1 4"/>'
    return o


def write(fn, data):
    p = os.path.join(OUT, fn)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(data)
    print(f"{fn:28s} {len(data) / 1024:7.1f} KB")


if __name__ == "__main__":
    for name, th in THEMES.items():
        build_hero(th, name)
        build_panel(th, name)
