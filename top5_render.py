#!/usr/bin/env python3
"""Menace Tennis TOP 5 / RANKING table (1080x1350), single slide. Works for 3-10 rows.
Same as the padel (thrill.com) version, with the tennis green texture and tennis-green highlights.

Usage:
    python3 top5_render.py data.json out.png photo.jpg

data.json:
{
  "metric": "Titles",                        # label above the value column (TITLES, POINTS, WINS, FINALS...)
  "subtitle": "Players with the most titles when turning 27",
  "rows": [
    {"rank": 1, "name": "Agustin Tapia", "flags": ["ar"], "value": "60"},
    {"rank": 2, "name": "Tapia/Coello", "flags": ["ar", "es"], "value": "10.440"},   # pairs: 2 flags
    ...
  ],
  "highlight": [1],          # rows (1 = first row) highlighted; or {"1": "gold", "3": "green"} for one colour per row
  "green": [5],              # optional: rows with only the green value box
  "accent": "gold",          # gold (default), green or lime
  "bg_focus_y": 0.3, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Built from TOP5.psd: Inter ExtraBold names, Poppins Bold labels, Druk Wide for numbers
(falls back to Archivo Expanded Black when the Druk files aren't available).
"""
import json, os, re, sys, io, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))
X0, X1 = 46, 1033                 # row left / right (TOP5.psd)
NUM_W = 73                        # rank box width
ROW_H, PITCH = 95, 102
LAST_BOTTOM = 1268                # bottom of the last row
SUB_BASE = 1324                   # subtitle baseline (1 line)
# highlight styles (TOP5.psd): stroke colour, glow colour, rank box gradient, name gradient, rank digit colour
ACCENTS = {
    "gold":     dict(stroke=(255, 240, 0), glow=(255, 238, 0), box=((255, 236, 90), (226, 176, 18)),
                     name=((255, 238, 80), (236, 196, 30)), digit=(20, 14, 0)),
    "green":    dict(stroke=(150, 255, 40), glow=(140, 255, 30), box=((196, 255, 90), (112, 214, 12)),
                     name=((206, 255, 112), (150, 250, 30)), digit=(6, 22, 12)),
    "lime":     dict(stroke=(200, 249, 8), glow=(200, 249, 8), box=((218, 254, 70), (176, 226, 6)),
                     name=((218, 254, 70), (200, 249, 8)), digit=(6, 22, 12)),
}
ACCENTS["electric"] = ACCENTS["green"]      # padel name kept as an alias
VAL_MAX_W = 330                   # widest value box: grows with long values (e.g. "10.440"), min 142
GREEN_A, GREEN_B = (128, 228, 22), (46, 128, 6)    # electric lime-green value box (padel: electric blue)
GREEN_GLOW = (140, 255, 30)
GREY_A, GREY_B = (74, 74, 76), (22, 22, 24)

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Inter-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf",
    "Archivo-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/archivo/Archivo%5Bwdth,wght%5D.ttf",
}
FLAG_SVG = "https://raw.githubusercontent.com/lipis/flag-icons/main/flags/1x1/{}.svg"


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _files():
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                yield d, f


def asset(name, required=True):
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d, f in _files():
        fs, fe = os.path.splitext(f)
        if fe.lower() == ext.lower() and _norm(fs).startswith(key) and "trial" not in f.lower():
            return os.path.join(d, f)
    if ext.lower() in (".otf", ".ttf"):
        for d, f in _files():  # licensed fonts stored as text: <Font>_font_b64.txt
            if f.lower().endswith(".txt") and _norm(f).startswith(key) and "b64" in f.lower() and "trial" not in f.lower():
                import base64, zlib
                body = "".join(l.strip() for l in open(os.path.join(d, f), encoding="utf-8") if l.strip() and not l.startswith("#"))
                dst = os.path.join(HERE, name)
                open(dst, "wb").write(zlib.decompress(base64.b64decode(body)))
                return dst
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


_F = {}


def font(kind, size):
    """kind: name | label | rank | value"""
    key = (kind, size)
    if key in _F:
        return _F[key]
    if kind == "name":
        f = ImageFont.truetype(asset("Inter-var.ttf"), size); f.set_variation_by_name("ExtraBold")
    elif kind == "label":
        f = ImageFont.truetype(asset("Poppins-Bold.ttf"), size)
    else:
        druk = asset("DrukWideBold.ttf", False) if kind == "value" else (asset("DrukWideMedium.ttf", False) or asset("DrukWideBold.ttf", False))
        if druk:
            f = ImageFont.truetype(druk, size)
        else:  # free stand-in: Archivo, widest + black
            f = ImageFont.truetype(asset("Archivo-var.ttf"), size)
            f.set_variation_by_axes([900 if kind == "value" else 700, 125])
    _F[key] = f
    return f


def vgrad(w, h, c0, c1):
    t = np.linspace(0, 1, h)[:, None, None]
    arr = np.array(c0, np.float32) * (1 - t) + np.array(c1, np.float32) * t
    return Image.fromarray(np.repeat(arr, w, 1).astype(np.uint8), "RGB" if len(c0) == 3 else "RGBA")


def rmask(w, h, radii, ss=4):
    """radii: (tl, tr, br, bl); supports all-equal or left-only rounding."""
    tl, tr, br, bl = radii
    r = max(radii) * ss
    m = Image.new("L", (w * ss, h * ss), 0)
    d = ImageDraw.Draw(m)
    d.rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), r, fill=255)
    if tr == 0 and br == 0:
        d.rectangle((w * ss // 2, 0, w * ss, h * ss), fill=255)
    return m.resize((w, h), Image.LANCZOS)


def paste_rgb(base, img, xy, mask):
    layer = Image.new("RGBA", base.size, (0, 0, 0, 0))
    im = img.convert("RGBA"); im.putalpha(ImageChops.multiply(im.getchannel("A"), mask))
    layer.paste(im, xy, im)
    base.alpha_composite(layer)


def glow(base, mask, xy, color, opacity, blur):
    layer = Image.new("RGBA", base.size, color + (0,))
    a = Image.new("L", base.size, 0); a.paste(mask, xy)
    a = a.filter(ImageFilter.GaussianBlur(blur)).point(lambda v: int(min(255, v * opacity * 1.6)))
    layer.putalpha(a)
    base.alpha_composite(layer)


def inner_edge(base, mask, xy, opacity=0.28, width=2):
    """thin light edge inside a shape (PSD inner glow 2px)"""
    er = mask.filter(ImageFilter.MinFilter(2 * width + 1))
    edge = ImageChops.subtract(mask, er).point(lambda v: int(v * opacity))
    layer = Image.new("RGBA", base.size, (255, 255, 255, 0))
    a = Image.new("L", base.size, 0); a.paste(edge, xy); layer.putalpha(a)
    base.alpha_composite(layer)


_FLAGS = {}


def circle_flag(code, d):
    code = code.lower()
    if code not in _FLAGS:
        p = asset(f"flagc_{code}.png", False)
        if p:
            im = Image.open(p).convert("RGBA")
        else:
            svg = urllib.request.urlopen(FLAG_SVG.format(code), timeout=15).read()
            try:
                import cairosvg
                im = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=240, output_height=240))).convert("RGBA")
            except ImportError:
                import subprocess, tempfile
                t = tempfile.NamedTemporaryFile(suffix=".svg", delete=False); t.write(svg); t.close()
                subprocess.run(["rsvg-convert", "-w", "240", "-h", "240", t.name, "-o", t.name + ".png"], check=True)
                im = Image.open(t.name + ".png").convert("RGBA")
        _FLAGS[code] = im
    im = _FLAGS[code].resize((d, d), Image.LANCZOS)
    # soft "globe" shading like the PSD flags
    yy, xx = np.mgrid[0:d, 0:d].astype(np.float32) / d
    shade = np.clip(0.18 * (yy - 0.35) * 2, -0.12, 0.25)
    arr = np.array(im, np.float32)
    arr[..., :3] = np.clip(arr[..., :3] * (1 - shade[..., None]) + 255 * np.clip(-shade, 0, 1)[..., None] * 0.6, 0, 255)
    im = Image.fromarray(arr.astype(np.uint8), "RGBA")
    m = Image.new("L", (d * 4, d * 4), 0); ImageDraw.Draw(m).ellipse((0, 0, d * 4 - 1, d * 4 - 1), fill=255)
    circ = m.resize((d, d), Image.LANCZOS)
    im.putalpha(circ)
    # 2 px white stroke (outside) + soft drop shadow (TOP5.psd)
    s = 2
    out = Image.new("RGBA", (d + 2 * s + 8, d + 2 * s + 8), (0, 0, 0, 0))
    ring = Image.new("L", (4 * (d + 2 * s), 4 * (d + 2 * s)), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, ring.width - 1, ring.height - 1), fill=255)
    ring = ring.resize((d + 2 * s, d + 2 * s), Image.LANCZOS)
    sh = Image.new("RGBA", out.size, (0, 0, 0, 0)); sa = Image.new("L", out.size, 0); sa.paste(ring, (4, 6))
    sh.putalpha(sa.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * 0.35))); out.alpha_composite(sh)
    w = Image.new("RGBA", ring.size, (255, 255, 255, 0)); w.putalpha(ring); out.alpha_composite(w, (4, 4))
    out.alpha_composite(im, (4 + s, 4 + s))
    return out


def text_fill(base, xy, text, f, fill_top, fill_bot, anchor="ls", shadow=None, inner=False, glow_col=None):
    """Text with a vertical gradient fill (+ optional drop shadow / outer glow)."""
    m = Image.new("L", base.size, 0)
    ImageDraw.Draw(m).text(xy, text, font=f, fill=255, anchor=anchor)
    bb = m.getbbox()
    if not bb:
        return
    if glow_col:
        layer = Image.new("RGBA", base.size, glow_col + (0,))
        layer.putalpha(m.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.35)))
        base.alpha_composite(layer)
    if shadow:
        sh = Image.new("RGBA", base.size, (0, 0, 0, 0))
        a = Image.new("L", base.size, 0); a.paste(m, (0, 2))
        sh.putalpha(a.filter(ImageFilter.GaussianBlur(3)).point(lambda v: int(v * shadow)))
        base.alpha_composite(sh)
    g = vgrad(bb[2] - bb[0], bb[3] - bb[1], fill_top, fill_bot)
    full = Image.new("RGB", base.size, fill_top); full.paste(g, (bb[0], bb[1]))
    layer = full.convert("RGBA"); layer.putalpha(m)
    base.alpha_composite(layer)


def fit_size(kind, texts, max_w, cap_target, smin=12):
    """Largest size (<= the one giving cap_target) where every text fits max_w."""
    probe = font(kind, 100)
    cap = -probe.getbbox("H", anchor="ls")[1]
    size = int(100 * cap_target / cap)
    while size > smin and max(font(kind, size).getlength(t) for t in texts) > max_w:
        size -= 1
    return size


def wrap(text, f, max_w):
    if f.getlength(text) <= max_w:
        return [text]
    ws = text.split(); best = None
    for i in range(1, len(ws)):
        a, b = " ".join(ws[:i]), " ".join(ws[i:])
        if max(f.getlength(a), f.getlength(b)) <= max_w:
            sc = abs(f.getlength(a) - f.getlength(b))
            if best is None or sc < best[0]:
                best = (sc, [a, b])
    return best[1] if best else [text]


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: top5_render.py data.json out.png photo.jpg")
    rows = data["rows"]
    n = len(rows)
    default_acc = data.get("accent", "gold")
    # "highlight": [1, 3] (all in the post accent) or {"1": "gold", "3": "green"} (one colour per row);
    # a row can also carry its own "accent"
    raw = data.get("highlight", [])
    hl_acc = {int(k): v for k, v in raw.items()} if isinstance(raw, dict) else {int(k): default_acc for k in raw}
    for i_, r_ in enumerate(rows):
        if r_.get("accent"):
            hl_acc[i_ + 1] = r_["accent"]
    hl = set(hl_acc)
    green = set(data.get("green", [])) | set(data.get("blue", [])) | hl

    # photo
    bg = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    if data.get("bw"):
        bg = ImageOps.grayscale(bg).convert("RGB")
    k = max(W / bg.width, H / bg.height) * data.get("bg_zoom", 1.0)
    bg = bg.resize((round(bg.width * k), round(bg.height * k)), Image.LANCZOS)
    fx, fy = data.get("bg_focus_x", 0.5), data.get("bg_focus_y", 0.3)
    x0, y0 = round((bg.width - W) * fx), round((bg.height - H) * fy)
    base = bg.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")
    ov = Image.open(asset("top5_overlay.png")).convert("RGBA")
    if n > 5:  # taller table: raise the dark fade with it, keep the green texture at the bottom
        shift = (n - 5) * PITCH
        ov2 = Image.new("RGBA", (W, H), (0, 0, 0, 255))
        ov2.paste(ov.crop((0, shift, W, H)), (0, 0))
        ov2.alpha_composite(ov.crop((0, H - 260, W, H)), (0, H - 260))
        ov = ov2
    base.alpha_composite(ov)

    # subtitle (1-2 lines) decides where the table ends
    f_sub = font("label", 34)
    sub_lines = wrap(data.get("subtitle", "").upper(), f_sub, 900) if data.get("subtitle") else []
    extra = 34 * (len(sub_lines) - 1) if sub_lines else 0
    pitch = min(PITCH, max(64, int((LAST_BOTTOM - 420) / n)))
    row_h = min(ROW_H, pitch - 7)
    last_bottom = LAST_BOTTOM - extra
    tops = [last_bottom - row_h - (n - 1 - i) * pitch for i in range(n)]

    # values: one box width for all rows (longest value)
    vals = [str(r["value"]) for r in rows]
    cap_v = 43 * row_h / ROW_H
    fs_v = fit_size("value", vals, VAL_MAX_W - 48, cap_v)
    f_v = font("value", fs_v)
    box_w = int(max(f_v.getlength(v) for v in vals) + 2 * 24)
    box_w = min(max(box_w, 142), VAL_MAX_W)
    vx0 = X1 + 2 - box_w

    # names: one size for all rows
    flag_d = int(80 * row_h / ROW_H)
    name_x_pair = X0 + NUM_W + 14 + flag_d + int(flag_d * 0.7) + 20
    name_x_one = X0 + NUM_W + 14 + flag_d + 20
    names = [r["name"].upper() for r in rows]
    fs_n = fit_size("name", names, vx0 - name_x_pair - 22, 38 * row_h / ROW_H)
    f_n = font("name", fs_n)
    any_pair = any(len(r.get("flags", [])) > 1 for r in rows)

    # metric label above the value column
    if data.get("metric"):
        lab = data["metric"].upper()
        lx0, lx1 = vx0, vx0 + box_w            # same width as the value boxes (TOP5.psd)
        ly1 = tops[0] - 10; ly0 = ly1 - 50
        fs_m = 30
        while fs_m > 16 and font("label", fs_m).getlength(lab) > box_w - 24:
            fs_m -= 1
        f_m = font("label", fs_m)
        m = rmask(lx1 - lx0, ly1 - ly0, (5, 5, 5, 5))
        # thin light stroke around the label so it pops out
        sm = rmask(lx1 - lx0 + 4, ly1 - ly0 + 4, (7, 7, 7, 7))
        layer = Image.new("RGBA", base.size, (255, 255, 255, 0)); a = Image.new("L", base.size, 0)
        a.paste(sm.point(lambda v: int(v * 0.55)), (lx0 - 2, ly0 - 2)); layer.putalpha(a); base.alpha_composite(layer)
        paste_rgb(base, vgrad(lx1 - lx0, ly1 - ly0, (44, 44, 46), (12, 12, 14)), (lx0, ly0), m)
        inner_edge(base, m, (lx0, ly0), 0.35)
        ImageDraw.Draw(base).text(((lx0 + lx1) / 2, (ly0 + ly1) / 2 + 1), lab, font=f_m, fill=(255, 255, 255), anchor="mm")

    tex = Image.open(asset("top5_texture.png")).convert("L")
    for i, r in enumerate(rows):
        idx = i + 1
        y = tops[i]
        is_hl = idx in hl
        acc = ACCENTS.get(hl_acc.get(idx, default_acc), ACCENTS["gold"])
        # body (texture on every other row: 1st, 3rd, 5th...)
        bw_, bh_ = X1 - X0, row_h
        m = rmask(bw_, bh_, (5, 5, 5, 5))
        sm = rmask(bw_ + 2 * (3 if is_hl else 1), bh_ + 2 * (3 if is_hl else 1), (7, 7, 7, 7))
        so = 3 if is_hl else 1
        if is_hl:
            glow(base, m, (X0, y), acc["glow"], 0.17, 18)
            col, op = acc["stroke"], 1.0
        else:
            col, op = (255, 255, 255), 0.35
        layer = Image.new("RGBA", base.size, col + (0,)); a = Image.new("L", base.size, 0)
        a.paste(sm.point(lambda v: int(v * op)), (X0 - so, y - so)); layer.putalpha(a); base.alpha_composite(layer)
        body = vgrad(bw_, bh_, (65, 65, 67), (2, 2, 3)).convert("RGBA")
        if i % 2 == 0:
            tl = Image.new("RGBA", (bw_, bh_), (255, 255, 255, 0))
            tl.putalpha(tex.resize((bw_, bh_)).point(lambda v: int(v * 0.22)))
            body.alpha_composite(tl)
        paste_rgb(base, body, (X0, y), m)
        # rank box
        nm = rmask(NUM_W, bh_, (5, 0, 0, 5))
        if is_hl:
            paste_rgb(base, vgrad(NUM_W, bh_, *acc["box"]), (X0, y), nm)
        else:
            paste_rgb(base, vgrad(NUM_W, bh_, (255, 255, 255), (196, 196, 198)), (X0, y), nm)
        inner_edge(base, nm, (X0, y), 0.5)
        f_r = font("rank", int(40 * row_h / ROW_H) if len(str(r["rank"])) < 2 else int(30 * row_h / ROW_H))
        ImageDraw.Draw(base).text((X0 + NUM_W / 2, y + bh_ / 2 + 1), str(r["rank"]), font=f_r,
                                  fill=acc["digit"] if is_hl else (8, 8, 8), anchor="mm")
        # flags
        flags = r.get("flags", [])[:2]
        fx_ = X0 + NUM_W + 14
        cy = y + bh_ / 2
        if len(flags) == 2:
            for j, fl in enumerate(reversed(flags)):
                xx = fx_ + int(flag_d * 0.7) * (1 - j)
                base.alpha_composite(circle_flag(fl, flag_d), (int(xx) - 6, int(cy - flag_d / 2) - 6))
            nx = name_x_pair
        else:
            if flags:
                off = int(flag_d * 0.35) if any_pair else 0
                base.alpha_composite(circle_flag(flags[0], flag_d), (int(fx_ + off) - 6, int(cy - flag_d / 2) - 6))
            nx = name_x_pair if any_pair else name_x_one
        # name
        cap_n = -f_n.getbbox("H", anchor="ls")[1]
        if is_hl:
            text_fill(base, (nx, cy + cap_n / 2), names[i], f_n, *acc["name"], glow_col=acc["glow"])
        else:
            ImageDraw.Draw(base).text((nx, cy + cap_n / 2), names[i], font=f_n, fill=(255, 255, 255), anchor="ls")
        # value box
        vm = rmask(box_w, bh_ + 2, (10, 10, 10, 10))
        if idx in green:
            glow(base, vm, (vx0, y - 1), GREEN_GLOW, 0.43, 22)
            paste_rgb(base, vgrad(box_w, bh_ + 2, GREEN_A, GREEN_B), (vx0, y - 1), vm)
        else:
            paste_rgb(base, vgrad(box_w, bh_ + 2, GREY_A, GREY_B), (vx0, y - 1), vm)
        inner_edge(base, vm, (vx0, y - 1), 0.28)
        cap_vv = -f_v.getbbox("8", anchor="ls")[1]
        text_fill(base, (vx0 + box_w / 2, cy + cap_vv / 2), vals[i], f_v, (255, 255, 255), (185, 185, 185),
                  anchor="ms", shadow=0.44)

    # subtitle
    d = ImageDraw.Draw(base)
    for j, ln in enumerate(sub_lines):
        d.text((W / 2, SUB_BASE - extra + j * 34 + (extra and 0)), ln, font=f_sub, fill=(255, 255, 255), anchor="ms")
    # logo
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    lg = lg.resize((285, round(lg.height * 285 / lg.width)), Image.LANCZOS)
    base.alpha_composite(lg, (50, 50))
    base.convert("RGB").save(out_path, quality=95)
    return {"rows": n, "name_size": fs_n, "value_size": fs_v, "value_box": box_w,
            "druk": bool(asset("DrukWideBold.ttf", False))}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
