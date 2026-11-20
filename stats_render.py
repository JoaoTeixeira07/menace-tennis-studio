#!/usr/bin/env python3
"""Menace Tennis STATS COMPARISON (1080x1350): two players or two pairs side by side.

Left half / right half photo, white divider, dark fade with the green tennis texture, then per side:
flag(s), name(s), 1-3 big numbers with a label pill, a "VS" disc in the middle and a subtitle.
Each side has a colour ("color"); stats are white unless highlighted. Built from "2 STATS vs 2 STATS TEMPLATYE.psd"
(1080x1440), with the info block moved up 90 px for 1350.

Usage:
    python3 stats_render.py data.json out.png [--editor]

data.json:
{
  "left":  {"photo": "/mnt/user-data/uploads/a.jpg",            # or "photos": [p1, p2] (two players side by side)
            "first": "Agustín", "name": "Tapia",                 # one player: first name (small) + surname (big)
            "flags": ["ar"],
            "stats": [{"value": "12", "label": "Titles"}, {"value": "84%", "label": "Win rate"}]},
  "right": {"photo": "...", "names": ["Galán", "Chingotto"],     # a pair: the two surnames
            "flags": ["es", "ar"],
            "stats": [{"value": "9", "label": "Titles"}, {"value": "79%", "label": "Win rate"}]},
  "subtitle": "ATP 2026 season",                       # or "subtitles": ["left text", "right text"]
  "middle_stat": {"value": "18-8", "label": "Head to head"},      # optional: shared head-to-head box in the middle (1-3 stats per side)
  "seamless": {"left": {"photo": "a.jpg", "scale": 1.1, "dx": -700, "dy": -50},   # optional: both players cut out
               "right": {"photo": "b.jpg", "scale": 2.0, "dx": 330, "dy": -20}},  # on one blended backdrop
  "middle_logo": "logo_atp_finals.png"                        # optional: a logo in the middle disc instead of VS
}
Framing per side: "bg_zoom", "bg_focus_x", "bg_focus_y" (one photo) or
"framing": [{"zoom": 1, "focus_x": 0.5, "focus_y": 0.2}, {...}] (two photos).
"""
import io, json, os, re, sys, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)

# ---------- design constants (PSD values, info block 90 px higher) ----------
# colours: each side picks one ("color"), each stat can be highlighted in it ("highlight") or in its own "color"
COLORS = {   # number gradient (t, b), pill gradient (pt, pb), pill text, glow
    "lime":   dict(t=(228, 251, 120), b=(196, 240, 24), pt=(226, 252, 100), pb=(190, 234, 18), txt=(8, 8, 8), glow=(196, 240, 24)),
    "red":    dict(t=(255, 84, 70), b=(214, 8, 14), pt=(238, 36, 36), pb=(176, 4, 16), txt=(255, 255, 255), glow=(230, 20, 20)),
    "yellow": dict(t=(255, 246, 110), b=(238, 204, 0), pt=(255, 236, 40), pb=(232, 192, 0), txt=(10, 8, 0), glow=(250, 220, 0)),
    "blue":   dict(t=(120, 178, 255), b=(34, 110, 255), pt=(70, 150, 255), pb=(24, 92, 232), txt=(255, 255, 255), glow=(40, 120, 255)),
    "gold":   dict(t=(255, 240, 196), b=(214, 170, 76), pt=(248, 226, 160), pb=(200, 154, 62), txt=(26, 18, 4), glow=(214, 170, 76)),
    "green":  dict(t=(120, 255, 170), b=(20, 200, 100), pt=(70, 230, 140), pb=(16, 170, 84), txt=(4, 20, 10), glow=(30, 210, 110)),
    "optic":  dict(t=(250, 255, 168), b=(214, 230, 46), pt=(244, 252, 150), pb=(206, 224, 40), txt=(16, 30, 6), glow=(214, 230, 46)),
    "soft":   dict(t=(240, 255, 184), b=(170, 212, 34), pt=(234, 250, 160), pb=(168, 206, 30), txt=(10, 38, 16), glow=(160, 205, 40)),
    "white":  dict(t=(255, 255, 255), b=(214, 216, 220), pt=(255, 255, 255), pb=(206, 209, 214), txt=(12, 12, 12), glow=(200, 200, 200)),
}
DEFAULT_COLOR = "gold"           # tennis default: champagne gold
PLAIN = COLORS["white"]          # stats that are not highlighted: white number, white pill, black label


def color_spec(c):
    """A preset name ("red", "gold"...) or a hex colour ("#E10600")."""
    if not c:
        return COLORS[DEFAULT_COLOR]
    if isinstance(c, str) and c.lower() in COLORS:
        return COLORS[c.lower()]
    h = str(c).lstrip("#")
    if not re.fullmatch(r"[0-9a-fA-F]{6}", h):
        raise SystemExit(f'Unknown colour "{c}": use one of {", ".join(COLORS)} or a hex like "#E10600".')
    rgb = tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    lift = lambda k: tuple(round(v + (255 - v) * k) for v in rgb)
    dark = lambda k: tuple(round(v * (1 - k)) for v in rgb)
    lum = 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]
    return dict(t=lift(0.35), b=dark(0.08), pt=lift(0.12), pb=dark(0.18), txt=(10, 10, 10) if lum > 150 else (255, 255, 255), glow=rgb)


WHITE_T, WHITE_B = (255, 255, 255), (214, 216, 220)
LIME_B = COLORS[DEFAULT_COLOR]["b"]

SIDE_CX = (270, 810)
FLAG_CY, FLAG_D, FLAG_GAP = 814, 50, 10
FIRST = dict(base=886, size=50, font="Poppins-Medium.ttf")            # "PAU": cap 35 px (PSD)
SUR = dict(base=954, size=86, min=52, max_w=400, font="Poppins-ExtraBold.ttf")    # "PIQUE": cap 61 px; long names shrink (CUBARSI 80)
DUO = dict(size=72, min=44, max_w=430, gap=14)                        # a pair: two surnames, same size, cap ~51 px
NUM = dict(base=1162, cap=172, font="DharmaGothicM-ExBold.ttf", fallback="LeagueGothic-var.ttf")   # fallback: closest free condensed face
PILL = dict(top=1183, h=48, r=24)                    # capsule
COLS = {1: ([270], 220), 2: ([156.5, 383.5], 183), 3: ([102, 270, 438], 150)}   # centres on the left side, pill width
H2H = dict(pill_side=200, pill_mid=280, colw_mid=250)   # head to head: side stat | shared middle stat | side stat
# bottom row, any mix: 1-3 stats per side (mirrored) + an optional shared middle stat (head to head)
ROW = dict(gap=16, outer=40, inner=500, max_w=200, mid_w={1: 280, 2: 250, 3: 240})
LABEL = dict(font="Poppins-Bold.ttf", size1=32, size2=24, lead2=22)
VS = dict(cx=540, cy=923, d=80, font="Poppins-ExtraBoldItalic.ttf", size=52)
SEP = dict(bottom=1250, w=2, op=0.32)          # thin lines between the numbers (fade at both ends)
DIVIDER_FADE = (760, 1350)                             # centre line: solid down to here, then fades out
DIVIDER_X = 539
SUB = dict(base=1297, size=30, font="Poppins-Bold.ttf", track=0.02)
LOGO_XY, LOGO_W = (49, 50), 286

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
G = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
DOWNLOADS = {
    "Poppins-Medium.ttf": G + "poppins/Poppins-Medium.ttf",
    "Poppins-Bold.ttf": G + "poppins/Poppins-Bold.ttf",
    "Poppins-ExtraBold.ttf": G + "poppins/Poppins-ExtraBold.ttf",
    "Poppins-ExtraBoldItalic.ttf": G + "poppins/Poppins-ExtraBoldItalic.ttf",
    "LeagueGothic-var.ttf": G + "leaguegothic/LeagueGothic%5Bwdth%5D.ttf",
}
FLAG_SVG = "https://raw.githubusercontent.com/lipis/flag-icons/main/flags/1x1/{}.svg"


# ---------- assets ----------
def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _files():
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                yield d, f


def asset(name, required=True):
    """Find an asset (case/space-insensitive). Licensed fonts may be stored as <Font>_font_b64.txt."""
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d, f in _files():
        fs, fe = os.path.splitext(f)
        if fe.lower() == ext.lower() and _norm(fs).startswith(key):
            return os.path.join(d, f)
    if ext.lower() in (".otf", ".ttf"):
        for d, f in _files():
            if f.lower().endswith(".txt") and _norm(f).startswith(key) and "b64" in f.lower():
                import base64, zlib
                body = "".join(l.strip() for l in open(os.path.join(d, f), encoding="utf-8") if l.strip() and not l.startswith("#"))
                raw = base64.b64decode(body)
                try:
                    raw = zlib.decompress(raw)
                except zlib.error:
                    pass
                dst = os.path.join(HERE, name)
                open(dst, "wb").write(raw)
                return dst
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


_F = {}


def font(name, size):
    k = (name, size)
    if k not in _F:
        path = asset(name)
        try:
            _F[k] = ImageFont.truetype(path, size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            _F[k] = ImageFont.truetype(path, size)
    return _F[k]


def num_font_name():
    """Dharma Gothic ExBold (licensed, from the project) when available, else League Gothic."""
    return NUM["font"] if asset(NUM["font"], required=False) else NUM["fallback"]


# ---------- drawing helpers ----------
def text_mask(s, f, xy, anchor="ms", track=0.0):
    m = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(m)
    if not track:
        d.text(xy, s, font=f, fill=255, anchor=anchor)
        return m
    tr = track * f.size
    width = f.getlength(s) + tr * (len(s) - 1)
    x = xy[0] - (width / 2 if anchor[0] == "m" else 0)
    for k, ch in enumerate(s):
        d.text((x + f.getlength(s[:k + 1]) - f.getlength(ch) + tr * k, xy[1]), ch, font=f, fill=255, anchor="l" + anchor[1])
    return m


def vgrad_fill(mask, top_col, bot_col):
    bb = mask.getbbox()
    if not bb:
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))
    t = np.clip((np.arange(H) - bb[1]) / max(1, bb[3] - bb[1]), 0, 1)[:, None]
    g = np.array(top_col) * (1 - t) + np.array(bot_col) * t
    layer = Image.fromarray(np.repeat(g[:, None, :], W, 1).astype(np.uint8)).convert("RGBA")
    layer.putalpha(mask)
    return layer


def glow(img, mask, color, opacity, blur):
    a = mask.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * opacity * 2)))
    layer = Image.new("RGBA", (W, H), tuple(color) + (0,))
    layer.putalpha(a)
    img.alpha_composite(layer)


def shadow(img, mask, opacity=0.45, blur=6, dy=3):
    a = Image.new("L", (W, H), 0)
    a.paste(mask, (0, dy))
    a = a.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(v * opacity))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.putalpha(a)
    img.alpha_composite(layer)


def styled(img, s, f, xy, top, bot, glow_col=None, glow_op=0.25, glow_blur=18, anchor="ms", track=0.0):
    m = text_mask(s, f, xy, anchor, track)
    if glow_col is not None:
        glow(img, m, glow_col, glow_op, glow_blur)
    shadow(img, m)
    img.alpha_composite(vgrad_fill(m, top, bot))


def width(s, f):
    return f.getlength(s)


def caps(s):
    return s.strip().upper().replace("'", "’")


_FLAGS = {}


def circle_flag(code, d):
    code = code.lower()
    if code not in _FLAGS:
        p = asset(f"flagc_{code}.png", required=False)
        if p:
            im = Image.open(p).convert("RGBA")
        else:
            svg = urllib.request.urlopen(FLAG_SVG.format(code), timeout=15).read()
            try:
                import cairosvg
                im = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=200, output_height=200))).convert("RGBA")
            except ImportError:
                import subprocess, tempfile
                t = tempfile.NamedTemporaryFile(suffix=".svg", delete=False); t.write(svg); t.close()
                subprocess.run(["rsvg-convert", "-w", "200", "-h", "200", t.name, "-o", t.name + ".png"], check=True)
                im = Image.open(t.name + ".png").convert("RGBA")
        _FLAGS[code] = im
    im = _FLAGS[code].resize((d, d), Image.LANCZOS)
    m = Image.new("L", (d * 4, d * 4), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    im.putalpha(m.resize((d, d), Image.LANCZOS))
    out = Image.new("RGBA", (d + 12, d + 12), (0, 0, 0, 0))
    ring = Image.new("L", ((d + 4) * 4, (d + 4) * 4), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=255)
    ring = ring.resize((d + 4, d + 4), Image.LANCZOS)
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0)); sa = Image.new("L", out.size, 0); sa.paste(ring, (4, 7))
    sh.putalpha(sa.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.45))); out.alpha_composite(sh)
    wr = Image.new("RGBA", ring.size, (255, 255, 255, 0)); wr.putalpha(ring); out.alpha_composite(wr, (4, 4))
    out.alpha_composite(im, (6, 6))
    return out


def white_logo(path, box):
    im = Image.open(path)
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 250:
        out = im.convert("RGBA")
    else:
        out = Image.new("RGBA", im.size, (255, 255, 255, 255))
        out.putalpha(im.convert("L"))
    out.thumbnail(box, Image.LANCZOS)
    return out


# ---------- photos ----------
def cover(path, rect, zoom=1.0, fx=0.5, fy=0.2):
    x, y, w, h = rect
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    s = max(w / im.width, h / im.height) * zoom
    nw, nh = round(im.width * s), round(im.height * s)
    im = im.resize((nw, nh), Image.LANCZOS)
    x0, y0 = round((nw - w) * fx), round((nh - h) * fy)
    return im.crop((x0, y0, x0 + w, y0 + h))


def side_photos(side, key, data):
    """[(path, rect, zoom, fx, fy, index or None)] for one side."""
    x = 0 if key == "left" else 540
    paths = side.get("photos") or ([side["photo"]] if side.get("photo") else [])
    if not paths:
        raise SystemExit(f'The {key} side needs a photo: "photo": "..." (or "photos": [a, b] for two players).')
    paths = paths[:2]
    out = []
    if len(paths) == 1:
        out.append((paths[0], (x, 0, 540, H), side.get("bg_zoom", 1.0), side.get("bg_focus_x", 0.5),
                    side.get("bg_focus_y", 0.2), None))
    else:
        fr = side.get("framing") or [{}, {}]
        for i, p in enumerate(paths):
            f = fr[i] if i < len(fr) else {}
            out.append((p, (x + 270 * i, 0, 270, H), f.get("zoom", 1.0), f.get("focus_x", 0.5), f.get("focus_y", 0.2), i))
    return out


# ---------- seamless background: both players cut out on one blended backdrop ----------
_SESSION = None


def person_mask(im):
    global _SESSION
    try:
        from rembg import new_session, remove
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages", "rembg", "onnxruntime"], check=True)
        from rembg import new_session, remove
    if _SESSION is None:
        _SESSION = new_session("u2net_human_seg")
    return remove(im.convert("RGB"), session=_SESSION, only_mask=True, post_process_mask=True)


def seamless_photo(spec, out_path):
    """spec = {"left": {"photo", "scale", "dx", "dy"}, "right": {...}, "seam": [420, 520], "front": "left"}
    Each photo is scaled by `scale` and its top-left put at (dx, dy). The two backgrounds cross-fade over
    the seam band (right background tone-matched to the left one), then both players are pasted on top,
    cut out and sharp, so neither is ever faded. Small photos are enlarged with LANCZOS + light sharpening."""
    layers = {}
    for key in ("left", "right"):
        p = spec[key]
        im = ImageOps.exif_transpose(Image.open(p["photo"])).convert("RGB")
        s = float(p["scale"])
        nw, nh = round(im.width * s), round(im.height * s)
        big = im.resize((nw, nh), Image.LANCZOS)
        if s > 1.3:
            big = big.filter(ImageFilter.UnsharpMask(radius=1.6, percent=60, threshold=2))
        m = person_mask(im).resize((nw, nh), Image.LANCZOS)
        canvas = Image.new("RGB", (W, H)); mc = Image.new("L", (W, H), 0); cov = Image.new("L", (W, H), 0)
        dx, dy = int(p.get("dx", 0)), int(p.get("dy", 0))
        canvas.paste(big, (dx, dy)); mc.paste(m, (dx, dy)); cov.paste(Image.new("L", (nw, nh), 255), (dx, dy))
        a = np.array(canvas); c = np.array(cov) > 0
        for x in range(W):      # fill rows the photo doesn't reach (hidden under the fade) with its last row
            col = np.where(c[:, x])[0]
            if len(col):
                a[col.max() + 1:, x] = a[col.max(), x]; a[:col.min(), x] = a[col.min(), x]
        layers[key] = (Image.fromarray(a), mc)
    (li, lm), (ri, rm) = layers["left"], layers["right"]
    la, ra = np.array(li).astype(np.float32), np.array(ri).astype(np.float32)
    s0, s1 = spec.get("seam", [420, 520])
    bgl, bgr = np.array(lm) < 40, np.array(rm) < 40
    regl = np.zeros((H, W), bool); regl[:900, max(0, s0 - 150):s0] = True
    regr = np.zeros((H, W), bool); regr[:900, s1:min(W, s1 + 150)] = True
    if (regl & bgl).any() and (regr & bgr).any():
        gain = np.clip(la[regl & bgl].mean(0) / np.maximum(ra[regr & bgr].mean(0), 1), 0.7, 1.4)
        ra = np.clip(ra * gain, 0, 255)
    t = np.clip((np.arange(W) - s0) / max(1, s1 - s0), 0, 1); t = t * t * (3 - 2 * t)
    bg = la * (1 - t)[None, :, None] + ra * t[None, :, None]
    img = Image.fromarray(bg.astype(np.uint8)).convert("RGBA")
    order = ["right", "left"] if spec.get("front", "left") == "left" else ["left", "right"]
    for key in order:
        im, m = layers[key]
        cut = im.convert("RGBA"); cut.putalpha(m); img.alpha_composite(cut)
    img.convert("RGB").save(out_path, quality=95)
    return out_path


# ---------- blocks ----------
def names_block(img, side, key):
    cx = SIDE_CX[0 if key == "left" else 1]
    cs = color_spec(side.get("color"))
    top, bot, gcol = cs["t"], cs["b"], cs["glow"]
    names = side.get("names")
    if names and len(names) >= 2:      # a pair: two surnames, white over colour, same size
        a, b = caps(names[0]), caps(names[1])
        size = DUO["size"]
        while size > DUO["min"] and max(width(a, font(SUR["font"], size)), width(b, font(SUR["font"], size))) > DUO["max_w"]:
            size -= 2
        f = font(SUR["font"], size)
        pitch = round(-f.getbbox("H", anchor="ls")[1] + DUO["gap"])
        styled(img, a, f, (cx, SUR["base"] - pitch), WHITE_T, WHITE_B, glow_col=gcol, glow_op=0.15)
        styled(img, b, f, (cx, SUR["base"]), top, bot, glow_col=gcol, glow_op=0.25)
        return f"{a} / {b}", SUR["base"] - pitch - size * 0.71
    first, last = caps(side.get("first", "")), caps(side.get("name", ""))
    if not last:
        raise SystemExit(f'The {key} side needs a name: "name" (+ optional "first"), or "names": [a, b] for a pair.')
    size = SUR["size"]
    while size > SUR["min"] and width(last, font(SUR["font"], size)) > SUR["max_w"]:
        size -= 2
    sf = font(SUR["font"], size)
    styled(img, last, sf, (cx, SUR["base"]), top, bot, glow_col=gcol, glow_op=0.25)
    if first:
        ff = font(FIRST["font"], FIRST["size"])
        # accented capitals (GALÁN, LEBRÓN) stand taller: keep an 8 px gap above the surname's real top
        ink_top = SUR["base"] + sf.getbbox(last, anchor="ls")[1]
        fbase = min(FIRST["base"], ink_top - 8)
        styled(img, first, ff, (cx, fbase), WHITE_T, WHITE_B, glow_col=gcol, glow_op=0.12)
        return f"{first} {last}", fbase - FIRST["size"] * 0.71
    return last, SUR["base"] - size * 0.71


def flags_block(img, side, key, names_top):
    flags = [f for f in (side.get("flags") or []) if f][:2]
    if not flags:
        return
    cx = SIDE_CX[0 if key == "left" else 1]
    n = len(flags)
    total = n * FLAG_D + (n - 1) * FLAG_GAP
    cy = min(FLAG_CY, names_top - 22 - FLAG_D / 2)
    for i, c in enumerate(flags):
        fl = circle_flag(c, FLAG_D)
        x = cx - total / 2 + i * (FLAG_D + FLAG_GAP)
        img.alpha_composite(fl, (int(x - 6), int(cy - FLAG_D / 2 - 6)))


def label_lines(text, f1, f2, maxw):
    t = caps(text)
    if width(t, f1) <= maxw:
        return [t], f1
    ws = t.split()
    best = None
    for i in range(1, len(ws)):
        a, b = " ".join(ws[:i]), " ".join(ws[i:])
        w = max(width(a, f2), width(b, f2))
        if best is None or w < best[0]:
            best = (w, [a, b])
    if best and best[0] <= maxw:
        return best[1], f2
    size = f2.size
    while size > 14 and width(t, font(LABEL["font"], size)) > maxw:
        size -= 1
    return [t], font(LABEL["font"], size)


def num_font(vals, colw):
    nf_name = num_font_name()
    probe = font(nf_name, 200)
    size = round(200 * NUM["cap"] / -probe.getbbox("8", anchor="ls")[1])
    while size > 60 and max(width(v, font(nf_name, size)) for v in vals) > colw:
        size -= 4
    return font(nf_name, size)


def stat_cell(img, cx, pw, value, label, nf, cs, lsize=None):
    """One big number + its capsule label, centred on cx. cs = colour spec (PLAIN = white)."""
    hl = cs is not PLAIN
    styled(img, str(value), nf, (cx, NUM["base"]), cs["t"], cs["b"], glow_col=cs["glow"] if hl else (190, 190, 190),
           glow_op=0.30 if hl else 0.10, glow_blur=16 if hl else 30)
    x0, y0 = round(cx - pw / 2), PILL["top"]
    pm = Image.new("L", (W, H), 0)
    ImageDraw.Draw(pm).rounded_rectangle((x0, y0, x0 + pw - 1, y0 + PILL["h"] - 1), PILL["r"], fill=255)
    if hl:
        glow(img, pm, cs["glow"], 0.22, 26)
    shadow(img, pm, 0.5, 8, 4)
    img.alpha_composite(vgrad_fill(pm, cs["pt"], cs["pb"]))
    room = pw - 24
    f1 = font(LABEL["font"], lsize or label_size(label, room))
    lines, lf = label_lines(label, f1, font(LABEL["font"], LABEL["size2"]), room)
    d = ImageDraw.Draw(img)
    cy = y0 + PILL["h"] / 2
    capl = -lf.getbbox("H", anchor="ls")[1]
    if len(lines) == 1:
        d.text((cx, cy + capl / 2), lines[0], font=lf, fill=cs["txt"], anchor="ms")
    else:
        b1 = cy - LABEL["lead2"] / 2 + capl / 2
        for j, ln in enumerate(lines):
            d.text((cx, b1 + j * LABEL["lead2"]), ln, font=lf, fill=cs["txt"], anchor="ms")


def label_size(label, room):
    """Largest one-line label size (LABEL size1 down to 26 px); below that the label wraps."""
    one = LABEL["size1"]
    while one > 26 and width(caps(label), font(LABEL["font"], one)) > room:
        one -= 1
    return one


def separator(img, x, top):
    """Thin vertical line between two numbers, fading in at the top and out at the bottom."""
    bot = SEP["bottom"]
    t = np.linspace(0, 1, bot - top)
    a = np.minimum(1, np.minimum(t / 0.25, (1 - t) / 0.25)) * 255 * SEP["op"]
    col = np.zeros((bot - top, SEP["w"], 4), np.uint8)
    col[..., :3] = 255
    col[..., 3] = a[:, None].astype(np.uint8)
    img.alpha_composite(Image.fromarray(col, "RGBA"), (round(x - SEP["w"] / 2), top))


def row_layout(n, has_mid):
    """Centres, pill widths and number column widths of the bottom row, symmetrical around x = 540.
    No middle stat: the PSD columns. 1 per side + middle: the head-to-head layout.
    2-3 per side + middle: boxes spread evenly beside a shared middle box."""
    if not has_mid:
        cols, pw = COLS[n]
        return list(cols), pw, 0, {1: 420, 2: 235, 3: 165}[n], 0
    if n == 1:
        return [SIDE_CX[0]], H2H["pill_side"], H2H["pill_mid"], H2H["colw_mid"], H2H["colw_mid"]
    gap, outer = ROW["gap"], ROW["outer"]
    wm = ROW["mid_w"][n]
    inner = 540 - wm / 2 - gap
    span = inner - outer
    pw = min(ROW["max_w"], (span - (n - 1) * gap) / n)
    left = [outer + span * (i + 0.5) / n for i in range(n)]
    return left, pw, wm, pw + 20, wm - 30


def side_colours(side, n):
    """Which stats are highlighted, and in which colour. Default: the last stat in the side colour."""
    stats = side["stats"]
    base = side.get("color")
    if any("highlight" in st or "color" in st for st in stats):
        return [color_spec(st.get("color") or base) if (st.get("highlight") or "color" in st) and st.get("highlight", True) else PLAIN
                for st in stats]
    return [color_spec(base) if i == n - 1 else PLAIN for i in range(n)]


def bottom_row(img, L, R, mid):
    n = len(L["stats"])
    left, pw, wm, colw, colw_mid = row_layout(n, bool(mid))
    right = sorted(W - x for x in left)              # mirrored positions, same stat order on both sides
    nf = num_font([str(s["value"]) for s in L["stats"] + R["stats"]], colw)   # one number size for the row
    if mid:
        nf2 = num_font([str(mid["value"])], colw_mid)
        if nf2.size < nf.size:
            nf = nf2
    lc = side_colours(L, n) if not mid or n > 1 or any("highlight" in s or "color" in s for s in L["stats"]) else [PLAIN]
    rc = side_colours(R, n) if not mid or n > 1 or any("highlight" in s or "color" in s for s in R["stats"]) else [PLAIN]
    if mid and n > 1 and not any("highlight" in s or "color" in s for s in L["stats"] + R["stats"]):
        lc, rc = [PLAIN] * n, [PLAIN] * n            # head to head: the middle box carries the colour
    # one label size for the whole row (the smallest that keeps every label on one line)
    cells = [(st.get("label", ""), pw) for st in L["stats"] + R["stats"]] + ([(mid.get("label", "Head to head"), wm)] if mid else [])
    lsize = min(label_size(lb, w - 24) for lb, w in cells)
    sep_top = round(NUM["base"] + nf.getbbox("8", anchor="ls")[1] - 22)
    # separators: between neighbouring boxes (the centre line splits the two sides when there is no middle box)
    xs = left + ([540] if mid else []) + right
    widths = [pw] * n + ([wm] if mid else []) + [pw] * n
    for (xa, wa), (xb, wb) in zip(zip(xs, widths), zip(xs[1:], widths[1:])):
        if not mid and xa < 540 < xb:
            continue
        separator(img, ((xa + wa / 2) + (xb - wb / 2)) / 2, sep_top)
    for st, cx, cs in zip(L["stats"], left, lc):
        stat_cell(img, cx, pw, st["value"], st.get("label", ""), nf, cs, lsize)
    if mid:
        stat_cell(img, 540, wm, mid["value"], mid.get("label", "Head to head"), nf, color_spec(mid.get("color")), lsize)
    for st, cx, cs in zip(R["stats"], right, rc):
        stat_cell(img, cx, pw, st["value"], st.get("label", ""), nf, cs, lsize)
    fmt = lambda ss: [f'{s["value"]} {s.get("label", "")}' for s in ss]
    return fmt(L["stats"]), (f'{mid["value"]} {mid.get("label", "Head to head")}' if mid else None), fmt(R["stats"])


def divider(img, end):
    """Centre line over the fade: solid at the top, fading out towards `end`."""
    y0 = DIVIDER_FADE[0]
    a = np.full(H, 254.0)
    a[y0:end] = np.linspace(254, 0, end - y0) ** 1 if end > y0 else 0
    a[max(y0, end):] = 0
    col = np.zeros((H, 2, 4), np.uint8); col[..., :3] = 255; col[..., 3] = a[:, None].astype(np.uint8)
    img.alpha_composite(Image.fromarray(col, "RGBA"), (DIVIDER_X, 0))


def middle(img, data):
    c = VS
    m = Image.new("L", (W, H), 0)
    ImageDraw.Draw(m).ellipse((c["cx"] - c["d"] / 2, c["cy"] - c["d"] / 2, c["cx"] + c["d"] / 2, c["cy"] + c["d"] / 2), fill=255)
    glow(img, m, (177, 177, 177), 0.24, 30)
    disc = Image.new("RGBA", (W, H), (38, 39, 39, 0)); disc.putalpha(m); img.alpha_composite(disc)
    edge = ImageChops.subtract(m, m.filter(ImageFilter.MinFilter(5))).point(lambda v: int(v * 0.35))
    e = Image.new("RGBA", (W, H), (255, 255, 255, 0)); e.putalpha(edge); img.alpha_composite(e)
    lp = asset(data["middle_logo"], required=False) if data.get("middle_logo") else None
    if lp:
        lg = white_logo(lp, (52, 52))
        img.alpha_composite(lg, (int(c["cx"] - lg.width / 2), int(c["cy"] - lg.height / 2)))
        return None
    f = font(c["font"], c["size"])
    capv = -f.getbbox("V", anchor="ls")[1]
    ImageDraw.Draw(img).text((c["cx"] - 1, c["cy"] + capv / 2), "VS", font=f, fill=(255, 255, 255), anchor="ms")
    return data.get("middle_logo") if data.get("middle_logo") else None


def subtitle(img, data):
    f = font(SUB["font"], SUB["size"])
    if data.get("subtitles"):
        for key, txt in zip(("left", "right"), data["subtitles"][:2]):
            if not txt:
                continue
            cx = SIDE_CX[0 if key == "left" else 1]
            lines, lf = label_lines(txt, f, font(SUB["font"], 26), 440)
            for j, ln in enumerate(lines):
                styled(img, ln, lf, (cx, SUB["base"] - (len(lines) - 1 - j) * 30), WHITE_T, WHITE_B, track=SUB["track"])
    elif data.get("subtitle"):
        t = caps(data["subtitle"])
        size = SUB["size"]
        while size > 18 and width(t, font(SUB["font"], size)) > 980:
            size -= 1
        styled(img, t, font(SUB["font"], size), (540, SUB["base"]), WHITE_T, WHITE_B, track=SUB["track"])


# ---------- render ----------
def render(data, out_path):
    L, R = data.get("left"), data.get("right")
    if not L or not R:
        raise SystemExit('Both sides are needed: "left" and "right".')
    n = len(L.get("stats") or [])
    mid = data.get("middle_stat")
    if n != len(R.get("stats") or []) or n not in COLS:
        raise SystemExit("Both sides need the same number of stats (1, 2 or 3).")
    if mid and str(mid.get("value", "")).strip() == "":
        raise SystemExit("The head-to-head stat needs a value: ask the user, never invent one.")
    for s in (L["stats"] + R["stats"]):
        if str(s.get("value", "")).strip() == "":
            raise SystemExit("Every stat needs a value: ask the user, never invent one.")

    img = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    if data.get("seamless") and not data.get("photo"):
        data = dict(data); data["photo"] = seamless_photo(data["seamless"], os.path.splitext(out_path)[0] + "_seamless.jpg")
    if data.get("photo"):   # one photo for the whole post (e.g. a seamless edit of both players)
        shots = [(None, (data["photo"], (0, 0, W, H), data.get("bg_zoom", 1.0), data.get("bg_focus_x", 0.5),
                         data.get("bg_focus_y", 0.0), None))]
    else:
        shots = [("left", p) for p in side_photos(L, "left", data)] + [("right", p) for p in side_photos(R, "right", data)]
    for _, (path, rect, z, fx, fy, idx) in shots:
        img.paste(cover(path, rect, z, fx, fy), rect[:2])
    if EDIT is not None:   # editor page: the photos are movable layers; everything below is the fixed design
        for k, (path, rect, z, fx, fy, idx) in shots:
            img = EDIT.photo(path, z, fx, fy, False, rect=rect, key=k, index=idx)
    d = ImageDraw.Draw(img)
    # thin white line between two photos on the same side, then the centre divider
    for side, x in ((L, 0), (R, 540)):
        if len(side.get("photos") or []) >= 2:
            d.rectangle((x + 269, 0, x + 270, H), fill=(255, 255, 255, 150))
    img.alpha_composite(Image.open(asset("stats_overlay.png")).convert("RGBA"))   # fade + green tennis texture

    ln, lt = names_block(img, L, "left")
    rn, rt = names_block(img, R, "right")
    flags_block(img, L, "left", lt)
    flags_block(img, R, "right", rt)
    if data.get("divider", not data.get("photo")):   # centre line (none on a seamless full-width photo)
        divider(img, NUM["base"] - NUM["cap"] - 40 if mid else DIVIDER_FADE[1])
    ls, mids, rs = bottom_row(img, L, R, mid)
    middle(img, data)
    subtitle(img, data)
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    img.alpha_composite(lg, LOGO_XY)
    if EDIT is not None:
        EDIT.static(img)
    img.convert("RGB").save(out_path, quality=95)
    out = {"left": ln, "left_stats": ls, "right": rn, "right_stats": rs, "number_font": num_font_name()}
    if mids:
        out["head_to_head"] = mids
    if data.get("middle_logo") and not asset(data["middle_logo"], required=False):
        out["missing_logo"] = data["middle_logo"]
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    data = json.load(open(args[0], encoding="utf-8"))
    info = render(data, args[1])
    if "--editor" in sys.argv or data.get("editor"):
        import studio_editor
        info["editor"] = studio_editor.run(sys.modules[__name__], data, args[1], None, accent="#CCFA14")
    print(json.dumps(info, ensure_ascii=False))
