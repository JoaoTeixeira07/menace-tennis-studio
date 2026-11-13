#!/usr/bin/env python3
"""Menace Tennis TWEET template generator (based on the thrill.com padel version) (1080x1350).

Usage:
    python3 tweet_render.py data.json out.png photo.jpg

data.json:
{
  "name": "Jose", "handle": "@JoseP0933", "verified": true,
  "avatar": "/mnt/user-data/uploads/avatar.jpg",          # the account's real profile photo (full-size, sharpest)
  "screenshot": "/mnt/user-data/uploads/tweet.png",      # or: crop the avatar from the tweet screenshot
  "avatar_crop": [x0, y0, x1, y1],                        #   box of the avatar circle in the screenshot (pixels)
  "text": "Everyone is praising the Spanish coach but **his decision was terrible.** If they lose ...",
  "circle": {...},                                         # optional, same as 1word/multiline
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
**double asterisks** = bold. Emoji are supported in the name and the text (Twemoji).
The card grows upwards with the text; its bottom edge stays fixed (TWEET.psd + published examples).
Layers: photo -> (circle -> player cut-out) -> black gradient -> tweet card; logo top-left.
"""
import json, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)
_FRAMING = {}      # exact photo framing of the last render (zoom, fx, fy), for the editor
W, H = 1080, 1350

# --- design constants ---
W_FONT = "NeuePlak-CompBlack.ttf"
W_STRETCH = 0.7 / 0.6          # PSD: horizontal 70%, vertical 60%
W_MAX_W = 976                  # widest word (side margins ~52)
W_MAX_CAP = 355                # tallest word (short words stop here)
W_TOP_Y = 40                   # cap top, "top" layout
SUB_GAP = 33                   # "bottom" layout: word baseline -> subtitle cap top (PSD)
W_BOTTOM_BASE = 1300           # baseline, "bottom" layout without subtitle
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

SHADE_FROM, SHADE_MAX = 1000, 215   # "top" layout with subtitle: soft black shade at the bottom
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
    _FRAMING.update(zoom=zoom, fx=fx, fy=fy)
    return bg.convert("RGBA"), cut, {"zoom": round(zoom, 2), "focus_x": round(fx, 2), "focus_y": round(fy, 2)}


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
    if EDIT is not None:   # editor page: the circle is drawn there (movable), not here
        EDIT.circle(spec["photo"], d, cx, cy, zoom, fx, fy, CIRCLE_STROKE, bw, bool(spec.get("x")),
                    bool(spec.get("pop")), person_mask)
    return layer, xl, pos


def logo_img():
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if lg.width != LOGO_W:
        lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    return lg


# ---------- tweet card ----------
INTER = "Inter-var.ttf"
DOWNLOADS["Inter-var.ttf"] = "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"
TWEMOJI = "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{}.png"

CARD_X0, CARD_X1 = 86, 995     # card (TWEET.psd Rectangle 9), radius 20, 5 px white stroke outside
CARD_R = 20
CARD_STROKE = 5
CARD_BOTTOM = 1240             # fixed bottom edge; the card grows upwards
CARD_FILL = (250, 250, 250)
INNER_SHADOW = dict(opacity=0.25, size=35)
AVATAR = dict(x=129, dy=23, d=72, ring=3)          # dy = offset from the card top
NAME = dict(x=215, dy=53, size=30, weight="Bold", color=(15, 20, 25), opsz=24)
HANDLE = dict(x=215, dy=86, size=24, weight="Regular", color=(83, 100, 113), opsz=14, track=0.01)
HEADER_SS = 3   # header text is drawn at 3x and downscaled: clean letter spacing, no touching glyphs
BADGE = dict(gap=6, dy=29, d=27)
XCOM = dict(x=831, dy=37, w=115)
DIVIDER = dict(x0=101, x1=978, dy=111, h=2, color=(229, 229, 229))
BODY = dict(x=133, dy=164, size=36, lead=50, max_w=805, regular="Regular", bold="SemiBold", color=(15, 15, 15))
BOTTOM_PAD = 44                # last baseline -> card bottom (tightened: compact card for long tweets)
# black gradient behind the card (TWEET.psd "Gradient Fill 5"), alpha every 10 px from y=0
TW_FADE = [0] * 65 + [1, 4, 7, 10, 13, 17, 22, 27, 32, 38, 45, 51, 58, 66, 73, 80, 89, 97, 106, 116, 126, 137,
                      147, 158, 170, 181, 192, 204, 215, 225, 235, 245, 253] + [255] * 38

_IF = {}


WGHT = {"Regular": 400, "Medium": 500, "SemiBold": 600, "Bold": 700}


def inter(weight, size, opsz=None):
    key = (weight, size, opsz)
    if key not in _IF:
        f = ImageFont.truetype(asset(INTER), size)
        if opsz is None:
            f.set_variation_by_name(weight)
        else:
            f.set_variation_by_axes([opsz, WGHT[weight]])
        _IF[key] = f
    return _IF[key]


# --- emoji ---
def _is_emoji_cp(cp):
    return (0x1F000 <= cp <= 0x1FAFF or 0x2600 <= cp <= 0x27BF or 0x2300 <= cp <= 0x23FF or
            0x2B00 <= cp <= 0x2BFF or cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D,
                                               0x3297, 0x3299, 0x2934, 0x2935) or 0x2190 <= cp <= 0x21FF and cp in (0x2194, 0x2195, 0x2196, 0x2197, 0x2198, 0x2199, 0x21A9, 0x21AA))


def tokens(text):
    """Split into runs of plain text and single emoji clusters."""
    out, buf, i = [], "", 0
    cps = [ord(c) for c in text]
    while i < len(cps):
        cp = cps[i]
        keycap = i + 1 < len(cps) and cps[i + 1] in (0xFE0F, 0x20E3) and chr(cp) in "0123456789#*" and 0x20E3 in cps[i + 1:i + 3]
        if _is_emoji_cp(cp) or keycap:
            if buf:
                out.append(("t", buf)); buf = ""
            j = i + 1
            if 0x1F1E6 <= cp <= 0x1F1FF and j < len(cps) and 0x1F1E6 <= cps[j] <= 0x1F1FF:
                j += 1                                  # flag = 2 regional indicators
            while j < len(cps):
                c = cps[j]
                if c in (0xFE0F, 0x20E3) or 0x1F3FB <= c <= 0x1F3FF or 0xE0020 <= c <= 0xE007F:
                    j += 1
                elif c == 0x200D and j + 1 < len(cps):
                    j += 2
                else:
                    break
            out.append(("e", text[i:j])); i = j
        else:
            buf += text[i]; i += 1
    if buf:
        out.append(("t", buf))
    return out


_EMOJI = {}


def emoji_img(seq, size):
    """Twemoji PNG for an emoji sequence, scaled to `size`."""
    if seq not in _EMOJI:
        import urllib.request, io
        cps = [ord(c) for c in seq]
        names = ["-".join(f"{c:x}" for c in cps if c != 0xFE0F), "-".join(f"{c:x}" for c in cps)]
        img = None
        for n in names:
            try:
                data = urllib.request.urlopen(TWEMOJI.format(n), timeout=10).read()
                img = Image.open(io.BytesIO(data)).convert("RGBA"); break
            except Exception:
                continue
        _EMOJI[seq] = img
    img = _EMOJI[seq]
    return img.resize((size, size), Image.LANCZOS) if img is not None else None


def emoji_w(size):
    return round(size * 1.18)


def measure(runs, f_reg, f_bold, size):
    w = 0
    for kind, s, bold in runs:
        if kind == "e":
            w += emoji_w(size)
        else:
            w += (f_bold if bold else f_reg).getlength(s)
    return w


def draw_runs(canvas, xy, runs, f_reg, f_bold, size, color):
    x, base = xy
    d = ImageDraw.Draw(canvas)
    for kind, s, bold in runs:
        if kind == "e":
            ew = emoji_w(size)
            im = emoji_img(s, ew)
            if im is not None:
                canvas.alpha_composite(im, (round(x), round(base - ew * 0.83)))
            x += ew
        else:
            f = f_bold if bold else f_reg
            d.text((x, base), s, font=f, fill=color, anchor="ls")
            x += f.getlength(s)
    return x


def parse_body(text):
    """'**bold**' markup -> list of words, each a list of (kind, str, bold) runs, plus spaces."""
    parts = re.split(r"(\*\*)", text.strip())
    bold, styled = False, []
    for p in parts:
        if p == "**":
            bold = not bold; continue
        for kind, s in tokens(p):
            styled.append((kind, s, bold))
    # split into words on spaces, keep newlines as hard breaks
    words, cur = [], []
    for kind, s, b in styled:
        if kind == "e":
            cur.append((kind, s, b)); continue
        for piece in re.split(r"( |\n)", s):
            if piece == " ":
                if cur: words.append(cur); cur = []
            elif piece == "\n":
                if cur: words.append(cur); cur = []
                words.append("\n")
            elif piece:
                cur.append(("t", piece, b))
    if cur:
        words.append(cur)
    return words


def wrap_body(words, f_reg, f_bold, size, max_w):
    lines, cur = [], []
    space = f_reg.getlength(" ")
    for w in words:
        if w == "\n":
            lines.append(cur); cur = []; continue
        if not cur:
            cur = list(w); continue
        trial = cur + [("t", " ", w[0][2] and cur[-1][2])] + w
        if measure(trial, f_reg, f_bold, size) <= max_w:
            cur = trial
        else:
            lines.append(cur); cur = list(w)
    if cur:
        lines.append(cur)
    return lines


def rounded_mask(w, h, r, ss=4):
    m = Image.new("L", (w * ss, h * ss), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w * ss - 1, h * ss - 1), r * ss, fill=255)
    return m.resize((w, h), Image.LANCZOS)


def avatar_from_screenshot(data):
    """Crop the avatar circle from the tweet screenshot (tight box), upscale to 240x240 (LANCZOS)."""
    if not (data.get("screenshot") and data.get("avatar_crop")):
        return None
    x0, y0, x1, y1 = [int(v) for v in data["avatar_crop"]]
    im = ImageOps.exif_transpose(Image.open(data["screenshot"])).convert("RGB").crop((x0, y0, x1, y1))
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width - s) // 2 + s, (im.height - s) // 2 + s))
    out = os.path.join(HERE, "_avatar_from_screenshot.png")
    im.resize((240, 240), Image.LANCZOS).save(out)
    return out


def avatar_img(path, d, ring):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    s = min(im.width, im.height)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    ss = 4
    im = im.resize((d * ss, d * ss), Image.LANCZOS).convert("RGBA")
    m = Image.new("L", (d * ss, d * ss), 0)
    ImageDraw.Draw(m).ellipse((0, 0, d * ss - 1, d * ss - 1), fill=255)
    im.putalpha(m)
    ImageDraw.Draw(im).ellipse((0, 0, d * ss - 1, d * ss - 1), outline=(0, 0, 0, 255), width=ring * ss)
    return im.resize((d, d), Image.LANCZOS)


def card_layer(data):
    size = BODY["size"]
    f_reg, f_bold = inter(BODY["regular"], size), inter(BODY["bold"], size)
    lines = wrap_body(parse_body(data["text"]), f_reg, f_bold, size, BODY["max_w"])
    last_base_dy = BODY["dy"] + BODY["lead"] * (len(lines) - 1)
    height = last_base_dy + BOTTOM_PAD
    top = CARD_BOTTOM - height
    w = CARD_X1 - CARD_X0
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # stroke (outside) + card
    st = rounded_mask(w + 2 * CARD_STROKE, height + 2 * CARD_STROKE, CARD_R + CARD_STROKE)
    white = Image.new("RGBA", st.size, (255, 255, 255, 0)); white.putalpha(st)
    layer.alpha_composite(white, (CARD_X0 - CARD_STROKE, top - CARD_STROKE))
    m = rounded_mask(w, height, CARD_R)
    card = Image.new("RGBA", (w, height), CARD_FILL + (255,))
    # inner shadow: soft darkening along the inside edge
    sh = ImageChops.invert(m).filter(ImageFilter.GaussianBlur(INNER_SHADOW["size"] / 2.5))
    sh = ImageChops.multiply(sh, m).point(lambda v: int(v * INNER_SHADOW["opacity"]))
    dark = Image.new("RGBA", (w, height), (0, 0, 0, 0)); dark.putalpha(sh)
    card.alpha_composite(dark)
    card.putalpha(m)
    layer.alpha_composite(card, (CARD_X0, top))
    d = ImageDraw.Draw(layer)
    # header
    av = data.get("avatar") or avatar_from_screenshot(data)
    if av:
        layer.alpha_composite(avatar_img(av, AVATAR["d"], AVATAR["ring"]), (AVATAR["x"], top + AVATAR["dy"]))
    # name + handle drawn on a 3x supersampled tile, then downscaled (crisp, open spacing)
    ss = HEADER_SS
    tile = Image.new("RGBA", ((XCOM["x"] - NAME["x"]) * ss, 110 * ss), (0, 0, 0, 0))
    fn = inter(NAME["weight"], NAME["size"] * ss, NAME.get("opsz"))
    name_runs = [(k, s_, False) for k, s_ in tokens(data.get("name", ""))]
    x_end = draw_runs(tile, (0, NAME["dy"] * ss), name_runs, fn, fn, NAME["size"] * ss, NAME["color"]) / ss + NAME["x"]
    fh = inter(HANDLE["weight"], HANDLE["size"] * ss, HANDLE.get("opsz"))
    handle = data.get("handle", "")
    if handle and not handle.startswith("@"):
        handle = "@" + handle
    td = ImageDraw.Draw(tile)
    hx = 0.0
    for ch in handle:
        td.text((hx, HANDLE["dy"] * ss), ch, font=fh, fill=HANDLE["color"], anchor="ls")
        hx += fh.getlength(ch) + HANDLE.get("track", 0) * fh.size
    tile = tile.resize((tile.width // ss, tile.height // ss), Image.LANCZOS)
    layer.alpha_composite(tile, (NAME["x"], top))
    if data.get("verified"):
        b = Image.open(asset("tweet_verified.png")).convert("RGBA").resize((BADGE["d"], BADGE["d"]), Image.LANCZOS)
        layer.alpha_composite(b, (round(x_end + BADGE["gap"]), top + BADGE["dy"]))
    xl = Image.open(asset("tweet_xcom.png")).convert("RGBA")
    xl = xl.resize((XCOM["w"], round(xl.height * XCOM["w"] / xl.width)), Image.LANCZOS)
    layer.alpha_composite(xl, (XCOM["x"], top + XCOM["dy"]))
    d.rectangle((DIVIDER["x0"], top + DIVIDER["dy"], DIVIDER["x1"], top + DIVIDER["dy"] + DIVIDER["h"] - 1), fill=DIVIDER["color"])
    # body
    for i, ln in enumerate(lines):
        draw_runs(layer, (BODY["x"], top + BODY["dy"] + i * BODY["lead"]), ln, f_reg, f_bold, size, BODY["color"])
    plain = [" ".join("".join(s for k, s, b in w) for w in [ln]) for ln in lines]
    return layer, top, ["".join(s for k, s, b in ln) for ln in lines]


def tennis_bottom():
    """Tennis background layers from Tennis_Tweet_.psd: soft top-left shade + the 'Shadowing' group
    (dark fade, green brush texture and court-line details at the bottom), exported as one PNG."""
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    # 'Gradient Fill 2': black, 100% -> 0%, angle -29 deg, only the top-left corner gets darker
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    t = np.clip(1 - (yy * 0.87 + xx * 0.49) / 760, 0, 1) * 40
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 255)); sh.putalpha(Image.fromarray(t.astype(np.uint8), "L"))
    layer.alpha_composite(sh)
    ov = Image.open(asset("tweet_overlay_tennis.png")).convert("RGBA")
    if ov.size != (W, H):
        ov = ov.resize((W, H), Image.LANCZOS)
    layer.alpha_composite(ov)
    return layer


def tw_fade():
    col = np.interp(np.arange(H), np.arange(len(TW_FADE)) * 10, TW_FADE).astype(np.uint8)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(Image.fromarray(np.repeat(col[:, None], W, 1), "L"))
    return layer


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: tweet_render.py data.json out.png photo.jpg")
    circ = data.get("circle")
    bg, cut, framing = place_photo(photo, data, need_cutout=bool(circ), autoframe=False)
    canvas = bg
    if EDIT is not None:
        canvas = EDIT.photo(photo, _FRAMING["zoom"], _FRAMING["fx"], _FRAMING["fy"], bool(data.get("bw")))
    cpos = None
    card, top, lines = card_layer(data)
    if circ:
        avoid = card.getchannel("A")
        if EDIT is not None:
            canvas = EDIT.split(canvas)
        cl, xl, cpos = circle_layers(circ, data.get("bw"), cut.getchannel("A"), avoid)
        if EDIT is not None:
            EDIT.cutout(person_mask, cut.getchannel("A"))
            if xl is not None:
                EDIT.xmark()
        else:
            canvas.alpha_composite(cl)
            canvas.alpha_composite(cut)
            if xl is not None:
                canvas.alpha_composite(xl)
    canvas.alpha_composite(tennis_bottom())   # tennis: green texture + dark fade (Tennis_Tweet_.psd)
    canvas.alpha_composite(card)
    canvas.alpha_composite(logo_img(), LOGO_TOP_LEFT)
    if EDIT is not None:
        EDIT.static(canvas)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"lines": lines, "card_top": top, "verified": bool(data.get("verified")), "circle": cpos, "framing": framing}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    data = json.load(open(args[0], encoding="utf-8"))
    photo = args[2] if len(args) > 2 else None
    info = render(data, args[1], photo)
    if "--editor" in sys.argv or data.get("editor"):
        # interactive page to drag / zoom the photos: <out>_editor.html (see studio_editor.py)
        import studio_editor
        info["editor"] = studio_editor.run(sys.modules[__name__], data, args[1], photo, accent="#CCFA14")
    print(json.dumps(info, ensure_ascii=False))
