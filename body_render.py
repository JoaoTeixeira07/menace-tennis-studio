#!/usr/bin/env python3
"""Menace Tennis CAROUSEL BODY slide (1080x1350): photo, tennis overlay (dark green texture at the bottom),
a lime title (Agency FB Bold Condensed, caps) and a centred paragraph (Poppins Regular with **bold** parts),
thrill.com logo top-left. Built from Tennis_Carousel_Body.psd.

Usage:
    python3 body_render.py data.json out.png photo.jpg

data.json:
{
  "title": "Happy birthday to Pistol Pete",
  "text": "Pete **Sampras turns 55 today.** 14 Grand Slam titles, ...",   # **bold**, exactly as typed
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Optional: "title" can be empty (paragraph only). A "|" in the title forces a line break; "\n" in the text starts a new line.
"""
import json, os, re, sys
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
EDIT = None        # studio_editor.Scene while the editor page is being built (see studio_editor.py)
_FRAMING = {}      # exact photo framing of the last render (zoom, fx, fy), for the editor
W, H = 1080, 1350
PLAYER_HEAD_Y = 210

# --- design constants (Tennis_Carousel_Body.psd) ---
T_FONT = "AgencyFB-BoldCondensed.otf"
T_SIZE, T_MIN = 110, 84          # px (PSD 58.06 pt x 1.895)
T_TRACK = -0.02                  # em
T_PITCH = 1.12                   # title line pitch as a share of the cap height (2-line titles)
T_MAX_W = 1000
T_MAX_LINES = 2
T_LIME_TOP, T_LIME = (222, 250, 112), (200, 242, 30)    # same lime + bevel as the cover / quote
T_SHADOW = dict(offset=10, blur=8, opacity=0.26)
TITLE_TO_BODY = 56               # title baseline -> first paragraph baseline
T_CENTER_X = 547                 # title centre (PSD + published post sit 7 px right of the page centre)

B_FONT, B_FONT_BOLD = "Poppins-Regular.ttf", "Poppins-Bold.ttf"
B_SIZE, B_MIN = 41, 33           # px (PSD 76.62 pt x 0.535); shrinks to keep the paragraph to B_MAX_LINES
B_LEAD = 48                      # line pitch in px (PSD 89.83 pt leading); the published Sampras post keeps 48 at ~37 px
B_TRACK = -0.02
B_MAX_W = 1040                   # widest paragraph line (published Sampras post: ~1050)
B_MAX_LINES = 5
B_LAST_BASE = 1306               # baseline of the last paragraph line
B_WHITE = (255, 255, 255)
B_SHADOW = dict(offset=10, blur=10, opacity=0.33, spread=3)

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


# paragraph: words with **bold** runs, greedy wrap, each line centred
def para_words(text):
    """'Pete **Sampras** turns 55' -> words, each a list of (piece, bold); "\n" items are forced breaks."""
    chars, bold = [], False
    for p in re.split(r"(\*\*)", text.strip()):
        if p == "**":
            bold = not bold; continue
        chars.extend((c, bold) for c in p)
    words, cur = [], []
    def flush():
        if cur:
            word = []
            for c, b in cur:
                if word and word[-1][1] == b:
                    word[-1] = (word[-1][0] + c, b)
                else:
                    word.append((c, b))
            words.append(word); cur.clear()
    for c, b in chars:
        if c == " ":
            flush()
        elif c == "\n":
            flush(); words.append("\n")
        else:
            cur.append((c, b))
    flush()
    return words


def word_w(word, fr, fb, track):
    return sum(tracked_w(fb if b else fr, s, track) for s, b in word) + track * fr.size * (len(word) - 1)


def _greedy(seg, widths, space, max_w):
    n, cw = 1, None
    for ww in widths:
        if cw is not None and cw + space + ww > max_w:
            n += 1; cw = ww
        else:
            cw = ww if cw is None else cw + space + ww
    return n


def _end_cost(word):
    """Where a line may end: after punctuation is good, after a lone number / small word is bad."""
    t = "".join(s for s, _ in word)
    if t[-1:] in ".:;!?":
        return -0.35
    if t[-1:] in ",—–" or t in ("—", "–"):
        return -0.2
    if re.fullmatch(r"[\d.]+", t) or t.lower() in {"a", "an", "the", "of", "to", "in", "at", "on", "for", "and", "his", "her", "no."}:
        return 0.6
    return 0.0


def wrap_para(words, fr, fb, track, max_w):
    """Same number of lines as a greedy fill, but with even lines and breaks at natural points
    (after punctuation; never leaving a lone number or small word at the end of a line)."""
    space = fr.getlength(" ") + track * fr.size
    segs, cur = [], []
    for w in words:
        if w == "\n":
            segs.append(cur); cur = []
        else:
            cur.append(w)
    segs.append(cur)
    lines, total = [], 0.0
    for seg in segs:
        if not seg:
            lines.append([]); continue
        widths = [word_w(w, fr, fb, track) for w in seg]
        n = len(seg)
        k = _greedy(seg, widths, space, max_w)
        pre = [0.0]
        for ww in widths:
            pre.append(pre[-1] + ww)
        def lw(i, j):  # words i..j-1
            return pre[j] - pre[i] + space * (j - i - 1)
        INF = float("inf")
        best = {(0, 0): (0.0, None)}
        for lines_used in range(1, k + 1):
            for j in range(1, n + 1):
                cand = None
                for i in range(j - 1, -1, -1):
                    w_ = lw(i, j)
                    if w_ > max_w:
                        break
                    prev = best.get((i, lines_used - 1))
                    if prev is None:
                        continue
                    slack = (max_w - w_) / max_w
                    last = j == n
                    c = prev[0] + (0 if last else slack ** 2) + (0 if last else _end_cost(seg[j - 1]) * 0.15)
                    if last and lines_used > 1:
                        c += 0.5 * max(0, slack - 0.45) ** 2   # avoid a very short last line
                    if cand is None or c < cand[0]:
                        cand = (c, i)
                if cand:
                    best[(j, lines_used)] = cand
        if (n, k) not in best:   # fallback: greedy
            cur, cw = [], 0
            for w, ww in zip(seg, widths):
                if cur and cw + space + ww > max_w:
                    lines.append(cur); cur, cw = [w], ww
                else:
                    cw = cw + space + ww if cur else ww; cur.append(w)
            lines.append(cur); total += 9; continue
        total += best[(n, k)][0]
        out, j, l = [], n, k
        while l > 0:
            i = best[(j, l)][1]
            out.insert(0, seg[i:j]); j, l = i, l - 1
        lines.extend(out)
    return lines, total


def para_layer(text):
    words = para_words(text)
    tr = B_TRACK
    fits = None
    for size in range(B_SIZE, B_MIN - 1, -1):
        lines, cost = wrap_para(words, font(B_FONT, size), font(B_FONT_BOLD, size), tr, B_MAX_W)
        if len(lines) <= B_MAX_LINES:
            fits = size; break
    fits = fits or B_MIN
    # the largest size that fits, or 1-2 px smaller when that gives clearly better line breaks
    best = None
    for size in range(fits, max(B_MIN, fits - 2) - 1, -1):
        lines, cost = wrap_para(words, font(B_FONT, size), font(B_FONT_BOLD, size), tr, B_MAX_W)
        if len(lines) > B_MAX_LINES and size != fits:
            continue
        score = cost + 0.04 * (fits - size)
        if best is None or score < best[0] - 1e-9:
            best = (score, size, lines)
    _, size, lines = best
    fr, fb = font(B_FONT, size), font(B_FONT_BOLD, size)
    lead = B_LEAD if size >= 37 else round(size * 1.3)
    space = fr.getlength(" ") + tr * size
    mask = Image.new("L", (W, H), 0); d = ImageDraw.Draw(mask)
    n = len(lines)
    first = B_LAST_BASE - lead * (n - 1)
    plain = []
    for i, line in enumerate(lines):
        lw = sum(word_w(w, fr, fb, tr) for w in line) + space * (len(line) - 1)
        x = W / 2 - lw / 2
        y = first + i * lead
        for w in line:
            for s, b in w:
                f = fb if b else fr
                draw_tracked(d, x, y, s, f, tr)
                x += tracked_w(f, s, tr) + tr * size
            x += space - tr * size
        plain.append(" ".join("".join(s for s, _ in w) for w in line))
    out = shadow_of(mask, B_SHADOW)
    txt = Image.new("RGBA", (W, H), B_WHITE + (0,)); txt.putalpha(mask)
    out.alpha_composite(txt)
    return out, plain, size, first


def line_w(f, l):
    ws = l.split(" ")
    return sum(tracked_w(f, w, T_TRACK) for w in ws) + (f.getlength(" ") + 2 * T_TRACK * f.size) * (len(ws) - 1)


def title_lines(raw, f):
    raw = raw.strip().upper().replace("'", "’")
    if "|" in raw:
        return [p.strip() for p in raw.split("|") if p.strip()]
    lines, cur = [], ""
    for w in raw.split():
        t = (cur + " " + w) if cur else w
        if cur and line_w(f, t) > T_MAX_W:
            lines.append(cur); cur = w
        else:
            cur = t
    if cur: lines.append(cur)
    if len(lines) == 2:   # two lines: balance them (no orphan word on the second line)
        ws = raw.split(); best = None
        for k in range(1, len(ws)):
            a, b = " ".join(ws[:k]), " ".join(ws[k:])
            wa, wb = line_w(f, a), line_w(f, b)
            if max(wa, wb) <= T_MAX_W and (best is None or abs(wa - wb) < best[0]):
                best = (abs(wa - wb), [a, b])
        if best: lines = best[1]
    return lines


def title_layer(raw, last_base):
    size = T_SIZE
    while True:
        f = font(T_FONT, size)
        lines = title_lines(raw, f)
        widest = max(line_w(f, l) for l in lines)
        if (widest <= T_MAX_W and len(lines) <= T_MAX_LINES) or size <= T_MIN:
            break
        size -= 2
    cap = -f.getbbox("H", anchor="ls")[1]
    pitch = cap * T_PITCH
    n = len(lines)
    first = last_base - pitch * (n - 1)
    mask = Image.new("L", (W, H), 0); d = ImageDraw.Draw(mask)
    sp = f.getlength(" ") + T_TRACK * f.size
    for i, l in enumerate(lines):
        x = T_CENTER_X - line_w(f, l) / 2
        for w in l.split(" "):     # word by word: no kerning across the space (keeps "Y T" apart)
            draw_tracked(d, x, first + i * pitch, w, f, T_TRACK)
            x += tracked_w(f, w, T_TRACK) + T_TRACK * f.size + sp
    top = first - cap
    t = np.clip((np.arange(H) - top) / max(1, last_base - top), 0, 1)[:, None] ** 0.7
    grad = np.array(T_LIME_TOP) * (1 - t) + np.array(T_LIME) * t
    fill = Image.fromarray(np.repeat(grad[:, None, :], W, 1).astype(np.uint8), "RGB").convert("RGBA")
    fill.putalpha(mask)
    out = shadow_of(mask, T_SHADOW)
    out.alpha_composite(fill)
    return out, lines, size


def logo_img():
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if lg.width != LOGO_W:
        lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    return lg


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A photo is required: body_render.py data.json out.png photo.jpg")
    if not data.get("text"):
        raise SystemExit('The paragraph is required: "text": "..."')
    canvas, _, framing = place_photo(photo, data, need_cutout=False, autoframe=False)
    if EDIT is not None:
        canvas = EDIT.photo(photo, _FRAMING["zoom"], _FRAMING["fx"], _FRAMING["fy"], bool(data.get("bw")))
    canvas.alpha_composite(Image.open(asset("body_overlay.png")).convert("RGBA"))   # dark green texture + top glow
    pl, plines, psize, first = para_layer(data["text"])
    tlines, tsize = [], None
    if data.get("title", "").strip():
        tl, tlines, tsize = title_layer(data["title"], first - TITLE_TO_BODY * psize / B_SIZE)
        canvas.alpha_composite(tl)
    canvas.alpha_composite(pl)
    canvas.alpha_composite(logo_img(), LOGO_XY)
    if EDIT is not None:
        EDIT.static(canvas)
    canvas.convert("RGB").save(out_path, quality=95)
    return {"title": tlines, "title_size": tsize, "text_lines": plines, "text_size": psize, "framing": framing}


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
