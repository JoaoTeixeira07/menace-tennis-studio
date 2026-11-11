#!/usr/bin/env python3
"""Menace Tennis CAROUSEL COVER (1080x1350): photo, tennis overlay (green texture + "Swipe to read" pill),
headline in Agency FB Bold Condensed (each line centred, same size), lime parts in [brackets], thrill.com logo.

Usage:
    python3 cover_render.py data.json out.png photo.jpg

data.json:
{
  "text": "The U.S. Open is [guaranteed] | to have an American in | the [semi finals]",   # "|" = line break
  "circle": {"photo": "...", "pos": "top-right"},          # optional, same as the padel circle
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Built from Tennis_Carousel_Cover.psd.
"""
import json, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1350

# --- design constants ---
W_FONT = "NeuePlak-CompBlack.ttf"
W_STRETCH = 0.7 / 0.6          # PSD: horizontal 70%, vertical 60%
W_MAX_W = 976                  # widest word (side margins ~52)
W_MAX_CAP = 355                # tallest word (short words stop here)
W_TOP_Y = 40                   # cap top, "top" layout
SUB_GAP = 30                   # "bottom" layout: last baseline -> subtitle cap top
W_BOTTOM_BASE = 1320           # last baseline, "bottom" layout without subtitle (multiline.psd)
W_TOP_GREY = (255, 255, 255)
W_BOT_GREY = (184, 184, 184)   # gradient overlay white -> #B8B8B8 (scale 88%)
OUTER_GLOW = dict(opacity=0.14, size=24)
INNER_GLOW = dict(opacity=0.19, size=16, noise=0.79)

S_FONT = "Poppins-Bold.ttf"
S_SIZE = 32                    # measured on the published examples (caps)
S_MAX_W = 910
S_LEAD = 31
S_BASE_1 = 1310                # single-line baseline
S_BASE_2 = 1321                # last baseline when 2 lines
S_TOP = (248, 248, 248)
S_BOT = (232, 232, 232)

LOGO_W = 285
LOGO_TOP_LEFT = (50, 50)       # bottom layout
LOGO_BOTTOM_RIGHT = (747, 1153)  # top layout

PLAYER_HEAD_Y = 210            # top layout: where the top of the player's head lands
# black gradient behind the word (user's gradient PNG, alpha every 10 px from the word's edge, 0 after 710 px).
# "top": from the top edge down. "bottom": the same, flipped (from the bottom edge up).
FADE = [252, 251, 250, 249, 248, 247, 246, 244, 243, 241, 239, 237, 235, 232, 229, 226, 223, 219, 216, 211,
        207, 203, 198, 193, 188, 184, 177, 173, 166, 161, 154, 149, 141, 136, 129, 124, 116, 111, 104, 99,
        92, 87, 81, 76, 70, 65, 61, 55, 51, 46, 43, 38, 35, 31, 28, 25, 22, 19, 17, 15, 13, 11, 10, 8, 7,
        6, 5, 5, 4, 3, 3, 0]


def fade_layer(layout):
    col = np.interp(np.arange(H), np.arange(len(FADE)) * 10, FADE, right=0).astype(np.uint8)
    if layout == "bottom":
        col = col[::-1]
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


# ---------- assets ----------
SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
}


def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _files():
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                yield d, f


def asset(name):
    """Find an asset (case/space/dot-insensitive). Licensed fonts may be stored as <Font>_font_b64.txt."""
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
                txt = open(os.path.join(d, f), encoding="utf-8").read()
                body = "".join(l.strip() for l in txt.splitlines() if l.strip() and not l.startswith("#"))
                dst = os.path.join(HERE, name)
                open(dst, "wb").write(zlib.decompress(base64.b64decode(body)))
                return dst
    if name in DOWNLOADS:
        import urllib.request
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    raise FileNotFoundError(f"Missing asset: {name}. Copy it next to the script (or ask the user to attach it).")


def font(name, size):
    return ImageFont.truetype(asset(name), size)


# ---------- photo ----------
def cover_scale(im, zoom=1.0):
    s = max(W / im.width, H / im.height) * zoom
    return im.resize((round(im.width * s), round(im.height * s)), Image.LANCZOS)


_SESSION = None
MODEL_MIRROR = "https://github.com/JoaoTeixeira07/menace-padel-studio/releases/download/models/u2net_human_seg.onnx"


def person_mask(im):
    """Alpha mask of the person (rembg, u2net_human_seg). Installs rembg on first use."""
    global _SESSION
    try:
        from rembg import new_session, remove
    except ImportError:
        import subprocess
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--break-system-packages",
                        "rembg", "onnxruntime"], check=True)
        from rembg import new_session, remove
    if _SESSION is None:
        try:
            _SESSION = new_session("u2net_human_seg")
        except Exception:
            # fallback: copy of the model kept in the studio's GitHub release
            import urllib.request
            path = "/tmp/u2net_human_seg.onnx"
            if not os.path.exists(path):
                urllib.request.urlretrieve(MODEL_MIRROR, path)
            _SESSION = new_session("u2net_custom", model_path=path)
    m = remove(im.convert("RGB"), session=_SESSION, only_mask=True, post_process_mask=True)
    # tighten the edge a touch so no background halo shows over the word
    m = m.filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(0.7))
    return m


def main_people(mask):
    """Bounding box (left, top, right, bottom) of the main person/people, ignoring small passers-by."""
    from scipy import ndimage
    a = np.array(mask) > 128
    lab, n = ndimage.label(a)
    if n == 0:
        return None
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    keep = [i + 1 for i, v in enumerate(sizes) if v >= 0.35 * sizes.max()]
    ys, xs = np.where(np.isin(lab, keep))
    return xs.min(), ys.min(), xs.max(), ys.max()


def place_photo(photo, data, need_cutout, autoframe=None):
    im = Image.open(photo)
    im = ImageOps.exif_transpose(im).convert("RGB")
    if data.get("bw"):
        im = ImageOps.grayscale(im).convert("RGB")
    fx, fy, zoom = data.get("bg_focus_x"), data.get("bg_focus_y"), data.get("bg_zoom")
    own_cut = data.get("cutout")
    autoframe = need_cutout if autoframe is None else autoframe
    auto = autoframe and need_cutout and not own_cut and (fx is None or fy is None or zoom is None)
    head = cx = None
    if auto:
        base = cover_scale(im, 1.0)
        bb = main_people(person_mask(base))
        if bb:
            l, t, r, b = bb
            if zoom is None:
                # zoom in until the top of the head can sit inside the word (PLAYER_HEAD_Y)
                need = (H - PLAYER_HEAD_Y) / max(1, base.height - t)
                zoom = float(np.clip(need, 1.0, 2.5))
            head, cx = t * zoom, (l + r) / 2 * zoom
    zoom = zoom or 1.0
    big = cover_scale(im, zoom)
    if fy is None:
        if head is not None and big.height > H:
            fy = float(np.clip(head - PLAYER_HEAD_Y, 0, big.height - H)) / (big.height - H)
        else:
            fy = 0.35
    if fx is None:
        if cx is not None and big.width > W:
            fx = float(np.clip(cx - W / 2, 0, big.width - W)) / (big.width - W)
        else:
            fx = 0.5
    x0, y0 = round((big.width - W) * fx), round((big.height - H) * fy)
    box = (x0, y0, x0 + W, y0 + H)
    bg = big.crop(box)
    cut = None
    if need_cutout:
        if own_cut:
            c = Image.open(own_cut).convert("RGBA")
            if c.size != bg.size:
                c = cover_scale(c, zoom).crop(box)
            if data.get("bw"):
                c = Image.merge("RGBA", (*ImageOps.grayscale(c.convert("RGB")).convert("RGB").split(), c.getchannel("A")))
            cut = c
        else:
            cut = bg.convert("RGBA")
            cut.putalpha(person_mask(bg))  # recomputed on the final crop for crisp edges
    return bg.convert("RGBA"), cut, {"zoom": round(zoom, 2), "focus_x": round(fx, 2), "focus_y": round(fy, 2)}


# ---------- headline ----------
C_FONT = "AgencyFB-BoldCondensed.otf"
C_SIZE, C_MIN = 134, 80          # px (Tennis_Carousel_Cover.psd: 133.6)
C_TRACK = -0.02                  # em
C_PITCH = 1.15                   # line pitch as a share of the cap height
C_MAX_W = 1000                   # widest line
C_LAST_BASE = 1225               # baseline of the last line (above the "Swipe to read" pill)
C_WHITE = (250, 250, 250)
C_LIME_TOP, C_LIME = (222, 250, 112), (200, 242, 30)   # tennis lime (same as the tennis Quote)
C_SHADOW = dict(offset=10, blur=8, opacity=0.26)


def parse_headline(raw):
    raw = raw.strip().strip('"“”')
    chars, flags, inside = [], [], False
    for ch in raw:
        if ch == "[":
            inside = True; continue
        if ch == "]":
            inside = False; continue
        chars.append(ch); flags.append(inside)
    text = "".join(chars).upper().replace("'", "’")
    words, cur, curf = [], "", []
    for ch, f in zip(text, flags):
        if ch in " |\n":
            if cur:
                words.append((cur, curf)); cur, curf = "", []
            if ch in "|\n":
                words.append(("|", []))
        else:
            cur += ch; curf.append(f)
    if cur:
        words.append((cur, curf))
    return words, any(flags)


def tw(f, s):
    return f.getlength(s) + C_TRACK * f.size * max(0, len(s) - 1)


def wrap_headline(words, size):
    f = font(C_FONT, size)
    if any(w == "|" for w, _ in words):
        lines, cur = [], []
        for w in words:
            if w[0] == "|":
                if cur: lines.append(cur)
                cur = []
            else:
                cur.append(w)
        if cur: lines.append(cur)
        return lines
    # greedy fill (top lines fullest, like the published covers), but never end a line on a small word
    SMALL = {"THE", "A", "AN", "OF", "TO", "IN", "AT", "ON", "FOR", "AND", "WITH", "BY", "HIS", "HER", "MY", "IS"}
    lines, cur = [], []
    for w in words:
        t = cur + [w]
        if cur and tw(f, " ".join(x for x, _ in t)) > C_MAX_W:
            carry = []
            while len(cur) > 1 and cur[-1][0].strip(".,") in SMALL:
                carry.insert(0, cur.pop())
            lines.append(cur); cur = carry + [w]
        else:
            cur = t
    if cur: lines.append(cur)
    return lines


def headline_layer(raw):
    words, has_marks = parse_headline(raw)
    size = C_SIZE
    while True:
        lines = wrap_headline(words, size)
        f = font(C_FONT, size)
        widest = max(tw(f, " ".join(x for x, _ in l)) for l in lines)
        if (widest <= C_MAX_W and len(lines) <= 4) or size <= C_MIN:
            break
        size -= 2
    cap = -f.getbbox("H", anchor="ls")[1]
    pitch = cap * C_PITCH
    n = len(lines)
    first_base = C_LAST_BASE - pitch * (n - 1)
    m_w = Image.new("L", (W, H), 0); m_l = Image.new("L", (W, H), 0)
    dw, dl = ImageDraw.Draw(m_w), ImageDraw.Draw(m_l)
    tr = C_TRACK * size
    for i, line in enumerate(lines):
        text = " ".join(w for w, _ in line)
        flags = []
        default = (not has_marks) and i == n - 1 and n > 1
        for j, (w, fl) in enumerate(line):
            if j: flags.append(flags[-1])
            flags.extend(fl if has_marks else [default] * len(w))
        x = W / 2 - tw(f, text) / 2
        y = first_base + i * pitch
        for k, ch in enumerate(text):
            (dl if flags[k] else dw).text((x + f.getlength(text[:k]) + tr * k, y), ch, font=f, fill=255, anchor="ls")
    top = first_base - cap
    grad = np.zeros((H, 3), np.float32)
    t = np.clip((np.arange(H) - top) / max(1, C_LAST_BASE - top), 0, 1)[:, None] ** 0.7
    grad[:] = np.array(C_LIME_TOP) * (1 - t) + np.array(C_LIME) * t
    lime_fill = Image.fromarray(np.repeat(grad[:, None, :], W, 1).astype(np.uint8), "RGB")
    out = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    mask = ImageChops.lighter(m_w, m_l)
    sh = mask.filter(ImageFilter.GaussianBlur(C_SHADOW["blur"])).point(lambda v: int(v * C_SHADOW["opacity"]))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); a = Image.new("L", (W, H), 0); a.paste(sh, (0, C_SHADOW["offset"]))
    shadow.putalpha(a); out.alpha_composite(shadow)
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    txt.paste(Image.new("RGB", (W, H), C_WHITE), (0, 0), m_w)
    txt.paste(lime_fill, (0, 0), m_l)
    txt.putalpha(mask)
    out.alpha_composite(txt)
    return out, [" ".join(w for w, _ in l) for l in lines], size


# ---------- circle inset ----------
CIRCLE_D = 430                 # default diameter (circle.psd: 429 px)
CIRCLE_STROKE = 6              # white stroke, inside (circle.psd)
CIRCLE_POS = {                 # centre points for the usual spots; the user can also give "x,y"
    "top-left": (234, 424), "top-right": (846, 424), "top-center": (540, 430),
    "left": (234, 620), "right": (846, 620), "center": (540, 620),
}
X_RED = (237, 28, 36)


def _put(layer, img, xy):
    """alpha_composite that accepts positions partly outside the canvas."""
    x, y = xy
    l, t = max(0, -x), max(0, -y)
    if l >= img.width or t >= img.height:
        return
    img = img.crop((l, t, img.width, img.height))
    layer.alpha_composite(img, (x + l, y + t))


def circle_center(pos, d):
    if isinstance(pos, (list, tuple)) and len(pos) == 2:
        return int(pos[0]), int(pos[1])
    pos = (pos or "top-left").lower().replace(" ", "-").replace("_", "-")
    if "," in pos:
        x, y = pos.split(",")[:2]
        return int(float(x)), int(float(y))
    return CIRCLE_POS.get(pos, CIRCLE_POS["top-left"])


def head_point(mask):
    """(x, y_top) of the head of the largest person in a mask."""
    from scipy import ndimage
    a = np.array(mask) > 128
    lab, n = ndimage.label(a)
    if n == 0:
        return None
    sizes = ndimage.sum(a, lab, range(1, n + 1))
    big = lab == (int(np.argmax(sizes)) + 1)
    ys, xs = np.where(big)
    top, hgt = ys.min(), ys.max() - ys.min()
    sel = ys <= top + max(10, 0.18 * hgt)
    return float(np.median(xs[sel])), int(top)


def auto_position(d, person_alpha, avoid=None):
    """Pick the usual spot where the main player covers the least of the circle."""
    a = np.array(person_alpha, np.float32) / 255 if person_alpha is not None else None
    best = None
    for name in ("top-left", "top-right", "left", "right"):
        cx, cy = CIRCLE_POS[name]
        yy, xx = np.ogrid[:H, :W]
        disc = (xx - cx) ** 2 + (yy - cy) ** 2 <= (d / 2) ** 2
        cover = float(a[disc].mean()) if a is not None else 0.0
        if avoid is not None:
            cover += 0.5 * float(np.array(avoid, np.float32)[disc].mean() / 255)
        if best is None or cover < best[0] - 0.02:
            best = (cover, name)
    return best[1]


def circle_layers(spec, bw, person_alpha=None, avoid=None):
    """Returns (circle RGBA layer, red-X RGBA layer or None, position used) for the inset photo."""
    d = int(spec.get("size", CIRCLE_D))
    pos = spec.get("pos")
    if not pos or str(pos).lower() == "auto":
        pos = auto_position(d, person_alpha, avoid)
    cx, cy = circle_center(pos, d)
    im = ImageOps.exif_transpose(Image.open(spec["photo"])).convert("RGB")
    if bw:
        im = ImageOps.grayscale(im).convert("RGB")
    zoom = spec.get("zoom", 1.0)
    s = max(d / im.width, d / im.height) * zoom
    big = im.resize((max(d, round(im.width * s)), max(d, round(im.height * s))), Image.LANCZOS)
    fx, fy = spec.get("focus_x"), spec.get("focus_y")
    if fx is None or fy is None:
        try:  # centre on the head of the main person in the inset photo
            hc = head_point(person_mask(big))
        except Exception:
            hc = None
        if hc:
            hx, t = hc
            if fx is None and big.width > d:
                fx = float(np.clip(hx - d / 2, 0, big.width - d)) / (big.width - d)
            if fy is None and big.height > d:
                fy = float(np.clip(t - 0.08 * d, 0, big.height - d)) / (big.height - d)
    fx = 0.5 if fx is None else fx
    fy = 0.3 if fy is None else fy
    x0, y0 = round((big.width - d) * fx), round((big.height - d) * fy)
    disc = big.crop((x0, y0, x0 + d, y0 + d)).convert("RGBA")
    ss = 4  # supersampled circle edge
    m = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    m = m.resize((d, d), Image.LANCZOS)
    disc.putalpha(m)
    ring = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(ring).ellipse((0, 0, d * ss - 1, d * ss - 1), outline=255, width=CIRCLE_STROKE * ss)
    ring = ring.resize((d, d), Image.LANCZOS)
    white = Image.new("RGBA", (d, d), (255, 255, 255, 0)); white.putalpha(ring)
    disc.alpha_composite(white)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    _put(layer, disc, (cx - d // 2, cy - d // 2))
    if spec.get("pop"):
        # the inset person's head breaks out over the top of the frame (circle.psd "Layer 2 copy")
        try:
            top = max(0, y0 - int(0.12 * d))
            pm = person_mask(big)
            band = Image.new("L", big.size, 0)
            ImageDraw.Draw(band).rectangle((x0, top, x0 + d, y0 + d // 2), fill=255)
            pop = big.convert("RGBA"); pop.putalpha(ImageChops.multiply(pm, band))
            pop = pop.crop((x0, top, x0 + d, y0 + d // 2))
            _put(layer, pop, (cx - d // 2, cy - d // 2 - (y0 - top)))
        except Exception:
            pass
    xl = None
    if spec.get("x"):
        xs = int(d * 0.27); wdt = max(8, int(d * 0.05))
        xm = Image.new("L", (xs * 4, xs * 4), 0)
        dr = ImageDraw.Draw(xm); pad = wdt * 2
        dr.line((pad, pad, xs * 4 - pad, xs * 4 - pad), fill=255, width=wdt * 4)
        dr.line((pad, xs * 4 - pad, xs * 4 - pad, pad), fill=255, width=wdt * 4)
        xm = xm.resize((xs, xs), Image.LANCZOS)
        xi = Image.new("RGBA", (xs, xs), X_RED + (0,)); xi.putalpha(xm)
        sh = Image.new("RGBA", (xs + 40, xs + 40), (0, 0, 0, 0))
        sa = Image.new("L", (xs + 40, xs + 40), 0); sa.paste(xm, (20, 24))
        sh.putalpha(sa.filter(ImageFilter.GaussianBlur(6)).point(lambda v: int(v * 0.45)))
        xl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        _put(xl, sh, (cx - xs // 2 - 20, cy - d // 2 - int(xs * 0.55) - 20))
        _put(xl, xi, (cx - xs // 2, cy - d // 2 - int(xs * 0.55)))
    return layer, xl, pos


def logo_img():
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if lg.width != LOGO_W:
        lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    return lg


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A photo is required: cover_render.py data.json out.png photo.jpg")
    circ = data.get("circle")
    cpos = None
    bg, cut, framing = place_photo(photo, data, need_cutout=bool(circ), autoframe=False)
    canvas = bg
    if circ:
        # photo -> circle -> player (in front of the circle) -> overlay -> text
        cl, xl, cpos = circle_layers(circ, data.get("bw"), cut.getchannel("A"))
        canvas.alpha_composite(cl)
        canvas.alpha_composite(cut)
        if xl is not None:
            canvas.alpha_composite(xl)
    ov = Image.open(asset("cover_overlay.png")).convert("RGBA")
    canvas.alpha_composite(ov)        # green texture, top glow and the "Swipe to read" pill (Tennis_Carousel_Cover.psd)
    tl, lines, size = headline_layer(data["text"])
    canvas.alpha_composite(tl)
    canvas.alpha_composite(logo_img(), LOGO_TOP_LEFT)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"lines": lines, "size": size, "bw": bool(data.get("bw")), "framing": framing, "circle": cpos}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
