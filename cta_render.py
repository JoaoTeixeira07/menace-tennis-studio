#!/usr/bin/env python3
"""Menace Tennis CAROUSEL CTA / closing slide (1080x1350): photo, tennis overlay (dark green texture at the bottom),
big call to action in Agency FB Bold Condensed (lime part in [brackets], rest white), thrill.com logo top-left.
Built from Tennis_Carousel_Close.psd.

Usage:
    python3 cta_render.py data.json out.png photo.jpg

data.json:
{
  "text": "[Follow us] for more | stories like this!",    # optional; this is the default. "|" = line break
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
"""
import json, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)
_FRAMING = {}      # exact photo framing of the last render (zoom, fx, fy), for the editor
W, H = 1080, 1350
PLAYER_HEAD_Y = 210

# --- design constants (Tennis_Carousel_Close.psd) ---
DEFAULT_TEXT = "[Follow us] for more | stories like this!"
C_FONT = "AgencyFB-BoldCondensed.otf"
C_SIZE, C_MIN = 187, 120         # px (PSD 67 pt x 2.789)
C_TRACK = -0.02                  # em
C_PITCH = 172.8 / 187            # line pitch as a share of the size (PSD leading 61.96 pt)
C_MAX_W = 1000                   # widest line (PSD box 62-1024)
C_MAX_LINES = 3
C_TWO_LINE_MIN = 150          # shrink to this before going to 3 lines
C_LAST_BASE = 1284               # baseline of the last line
C_CENTER_X = 542
C_WHITE = (255, 255, 255)
C_LIME_TOP, C_LIME = (218, 254, 70), (200, 249, 8)    # per line, top of the caps -> baseline (published post)
C_SHADOW = dict(offset=10, blur=8, opacity=0.26)

LOGO_W = 285
LOGO_XY = (50, 50)


# ---------- assets ----------
SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {
    "Poppins-Bold.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Bold.ttf",
    "Poppins-Regular.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/poppins/Poppins-Regular.ttf",
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


_FONTS = {}


def font(name, size):
    """Fonts with GPOS kerning (raqm) when available, like Photoshop's metric kerning."""
    k = (name, size)
    if k not in _FONTS:
        try:
            _FONTS[k] = ImageFont.truetype(asset(name), size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            _FONTS[k] = ImageFont.truetype(asset(name), size)
    return _FONTS[k]


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


# ---------- text ----------
def tracked_w(f, s, track):
    return f.getlength(s) + track * f.size * max(0, len(s) - 1)


def draw_tracked(draw, x, y, s, f, track, fill=255):
    tr = track * f.size
    for k, ch in enumerate(s):
        # pen position incl. the kerning pair before this glyph (getlength of a prefix alone would drop it)
        px = f.getlength(s[:k + 1]) - f.getlength(ch)
        draw.text((x + px + tr * k, y), ch, font=f, fill=fill, anchor="ls")


def shadow_of(mask, spec):
    m = mask
    if spec.get("spread"):
        m = m.filter(ImageFilter.MaxFilter(spec["spread"] * 2 + 1))
    m = m.filter(ImageFilter.GaussianBlur(spec["blur"])).point(lambda v: int(v * spec["opacity"]))
    a = Image.new("L", (W, H), 0); a.paste(m, (0, spec["offset"]))
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sh.putalpha(a)
    return sh



def parse(raw):
    """'[Follow us] for more | stories like this!' -> lines of (char, lime) ; '|' or newline = forced break."""
    raw = raw.strip().strip('"“”').replace("'", "’")
    chars, inside = [], False
    for ch in raw:
        if ch == "[":
            inside = True; continue
        if ch == "]":
            inside = False; continue
        chars.append((ch.upper(), inside))
    has_marks = any(f for _, f in chars)
    text = "".join(c for c, _ in chars)
    forced = "|" in text or "\n" in text
    return chars, has_marks, forced


def words_of(chars):
    out, cur = [], []
    for c, f in chars:
        if c in " |\n":
            if cur: out.append(cur); cur = []
            if c in "|\n": out.append("|")
        else:
            cur.append((c, f))
    if cur: out.append(cur)
    return out


def word_str(w):
    return "".join(c for c, _ in w)


def line_w(f, words):
    sp = f.getlength(" ") + 2 * C_TRACK * f.size
    return sum(tracked_w(f, word_str(w), C_TRACK) for w in words) + sp * (len(words) - 1)


def wrap(words, f, forced):
    if forced:
        lines, cur = [], []
        for w in words:
            if w == "|":
                if cur: lines.append(cur)
                cur = []
            else:
                cur.append(w)
        if cur: lines.append(cur)
        return lines
    lines, cur = [], []
    for w in words:
        if cur and line_w(f, cur + [w]) > C_MAX_W:
            lines.append(cur); cur = [w]
        else:
            cur.append(w)
    if cur: lines.append(cur)
    n = len(lines)
    if n > 1:   # same number of lines, balanced (no orphan word on the last line)
        from itertools import combinations
        best = None
        for cuts in combinations(range(1, len(words)), n - 1):
            b = [0, *cuts, len(words)]
            ls = [words[b[i]:b[i + 1]] for i in range(n)]
            m = max(line_w(f, l) for l in ls)
            if m <= C_MAX_W and (best is None or m < best[0]):
                best = (m, ls)
        if best:
            lines = best[1]
    return lines


def cta_layer(raw):
    chars, has_marks, forced = parse(raw)
    words = words_of(chars)
    size = C_SIZE
    while True:
        f = font(C_FONT, size)
        lines = wrap(words, f, forced)
        # prefer 2 lines (like the template): shrink down to C_TWO_LINE_MIN before allowing a 3rd line
        limit = 2 if size > C_TWO_LINE_MIN else C_MAX_LINES
        if (max(line_w(f, l) for l in lines) <= C_MAX_W and len(lines) <= limit) or size <= C_MIN:
            break
        size -= 2
    if not has_marks:      # nothing marked: the first line is lime (like "FOLLOW US")
        lines = [[[(c, i == 0) for c, _ in w] for w in l] for i, l in enumerate(lines)]
    cap = -f.getbbox("H", anchor="ls")[1]
    pitch = size * C_PITCH
    n = len(lines)
    first = C_LAST_BASE - pitch * (n - 1)
    m_w, m_l = Image.new("L", (W, H), 0), Image.new("L", (W, H), 0)
    dw, dl = ImageDraw.Draw(m_w), ImageDraw.Draw(m_l)
    grad = np.zeros((H, 3), np.float32); grad[:] = C_LIME
    sp = f.getlength(" ") + C_TRACK * f.size
    tr = C_TRACK * size
    for i, line in enumerate(lines):
        y = first + i * pitch
        x = C_CENTER_X - line_w(f, line) / 2
        for w in line:
            s = word_str(w)
            for k, (ch, lime) in enumerate(w):
                px = f.getlength(s[:k + 1]) - f.getlength(ch)
                (dl if lime else dw).text((x + px + tr * k, y), ch, font=f, fill=255, anchor="ls")
            x += tracked_w(f, s, C_TRACK) + tr + sp
        top = int(y - cap)
        t = np.clip((np.arange(H) - top) / max(1, cap), 0, 1)[:, None]
        rows = slice(max(0, top - 20), min(H, int(y) + 60))
        grad[rows] = (np.array(C_LIME_TOP) * (1 - t) + np.array(C_LIME) * t)[rows]
    lime_fill = Image.fromarray(np.repeat(grad[:, None, :], W, 1).astype(np.uint8), "RGB")
    mask = ImageChops.lighter(m_w, m_l)
    out = shadow_of(mask, C_SHADOW)
    txt = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    txt.paste(Image.new("RGB", (W, H), C_WHITE), (0, 0), m_w)
    txt.paste(lime_fill, (0, 0), m_l)
    txt.putalpha(mask)
    out.alpha_composite(txt)
    plain = []
    for l in lines:
        seq = [(c, lm) for j, w in enumerate(l) for c, lm in ([(" ", w[0][1] and l[j - 1][-1][1])] if j else []) + w]
        txt_, on = "", False
        for c, lm in seq:
            if lm != on:
                txt_ += "[" if lm else "]"; on = lm
            txt_ += c
        plain.append(txt_ + ("]" if on else ""))
    return out, plain, size


def logo_img():
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if lg.width != LOGO_W:
        lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    return lg


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A photo is required: cta_render.py data.json out.png photo.jpg")
    canvas, _, framing = place_photo(photo, data, need_cutout=False, autoframe=False)
    if EDIT is not None:
        canvas = EDIT.photo(photo, _FRAMING["zoom"], _FRAMING["fx"], _FRAMING["fy"], bool(data.get("bw")))
    canvas.alpha_composite(Image.open(asset("cta_overlay.png")).convert("RGBA"))   # dark green texture (Tennis_Carousel_Close.psd)
    tl, lines, size = cta_layer(data.get("text") or DEFAULT_TEXT)
    canvas.alpha_composite(tl)
    canvas.alpha_composite(logo_img(), LOGO_XY)
    if EDIT is not None:
        EDIT.static(canvas)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"lines": lines, "size": size, "framing": framing}


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if len(args) < 2:
        print(__doc__); sys.exit(1)
    data = json.load(open(args[0], encoding="utf-8")) if args[0] != "-" else {}
    photo = args[2] if len(args) > 2 else None
    info = render(data, args[1], photo)
    if "--editor" in sys.argv or data.get("editor"):
        # interactive page to drag / zoom the photos: <out>_editor.html (see studio_editor.py)
        import studio_editor
        info["editor"] = studio_editor.run(sys.modules[__name__], data, args[1], photo, accent="#CCFA14")
    print(json.dumps(info, ensure_ascii=False))
