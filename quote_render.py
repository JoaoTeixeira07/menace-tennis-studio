#!/usr/bin/env python3
"""thrill.com QUOTE post generator, TENNIS version (green texture, red quote icon, mixed-weight subtitle) (1080x1350).

Usage:
    python3 quote_render.py data.json out.png [photo.jpg]

data.json:
{
  "quote": "In 2027, [I'll keep playing with Fede Chingotto]",
  "subtitle": "Alejandro Galán confirms that the partnership will continue in 2027",
  "bg_focus_y": 0.35,      # optional, 0 = show top of photo, 1 = bottom
  "bg_focus_x": 0.5,       # optional, 0 = left, 1 = right
  "bg_zoom": 1.0           # optional, >1 zooms into the photo
}

Quote rules:
  - [square brackets] mark the lime part. No brackets -> last line is lime.
  - "|" forces a line break. Otherwise lines are balanced automatically.
  - Quotation marks are stripped (the quote icon does that job).

All measurements come from the original QUOTE.psd.
"""
import json, os, re, sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageChops

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 1080, 1350

# --- design constants (from QUOTE.psd) ---
LOGO_XY = (50, 50)                     # thrill_logo.png, scaled to 285 px wide
LOGO_W = 285
ICON_SIZE = (162, 56)                  # quote_icon.png
ICON_GAP = 24                          # icon bottom -> quote cap top
Q_FONT = "AgencyFB-BoldCondensed.otf"
Q_SIZE = 150                           # px
Q_MIN_SIZE = 104
Q_LEAD = 130 / 150                     # line pitch as share of size
Q_TRACK = -0.02                        # em
Q_SKEW = 0.21                          # faux italic slant (tan)
Q_MAX_W = 975                          # widest allowed line (visual)
Q_WHITE = (250, 250, 250)
Q_LIME = (204, 246, 30)                # tennis lime (Tennis_Quote_.psd / published posts), bottom of the block
Q_LIME_TOP = (222, 250, 112)           # paler lime at the top of the block (bevel)
Q_LIME_CURVE = 1.6
SHADOW = dict(offset=10, blur=8, opacity=0.26)
S_FONT = "Poppins-Regular.ttf"           # tennis subtitle: sentence case, Regular with **Bold** words
S_FONT_BOLD = "Poppins-Bold.ttf"
S_SIZE = 27                            # px (published tennis posts)
S_LEAD = 34
S_TRACK = -0.02
S_MAX_W = 940
S_TOP = (247, 247, 247)
S_BOT = (232, 232, 232)
S_LAST_BASELINE = 1320
GAP_Q_TO_S = 29                        # quote last baseline -> subtitle cap top
DEFAULT_ICON_TOP = 915                 # where the stack starts in the original


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
    """Find an asset next to the script, in the cwd or in the project/uploads folders.
    Matching ignores case, spaces, dots and underscores, because uploads get renamed
    (e.g. 'quote_icon 1.png', 'thrill-logo.png')."""
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d, f in _files():
        fs, fe = os.path.splitext(f)
        if fe.lower() == ext.lower() and _norm(fs).startswith(key):
            return os.path.join(d, f)
    if ext.lower() in (".otf", ".ttf"):
        # Licensed fonts are stored in the project as text (zlib + base64), because
        # projects don't keep binary font files. File: <FontName>_font_b64.txt
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
    raise FileNotFoundError(f"Missing asset: {name}. Copy it next to quote_render.py (or ask the user to attach it).")


_FONTS = {}


def load_font(name, size):
    key = (name, size)
    if key not in _FONTS:
        try:   # raqm = GPOS kerning, like Photoshop's metric kerning
            _FONTS[key] = ImageFont.truetype(asset(name), size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            _FONTS[key] = ImageFont.truetype(asset(name), size)
    return _FONTS[key]


def cap_height(font):
    return font.getbbox("H", anchor="ls")[1] * -1


def line_width(font, text, track):
    if not text:
        return 0
    return font.getlength(text) + track * font.size * (len(text) - 1)


# ---------- quote parsing / wrapping ----------
def parse_quote(raw):
    raw = raw.strip().strip('"“”«»\'‘’').strip()
    forced = "|" in raw
    chars, lime = [], []
    inside = False
    for ch in raw:
        if ch == "[":
            inside = True; continue
        if ch == "]":
            inside = False; continue
        chars.append(ch); lime.append(inside)
    text = "".join(chars).upper().replace("'", "’")
    has_marks = any(lime)
    # words with per-char lime flags, keep "|" as break token
    words, cur, curf = [], "", []
    for ch, f in zip(text, lime):
        if ch == " " or ch == "|":
            if cur:
                words.append((cur, curf)); cur, curf = "", []
            if ch == "|":
                words.append(("|", []))
        else:
            cur += ch; curf.append(f)
    if cur:
        words.append((cur, curf))
    return words, has_marks, forced


def split_forced(words):
    lines, cur = [], []
    for w in words:
        if w[0] == "|":
            lines.append(cur); cur = []
        else:
            cur.append(w)
    lines.append(cur)
    return [l for l in lines if l]


def best_wrap(words, n, font, max_w=None):
    """Split words into n lines minimizing the widest line.
    If a split can land exactly where white turns lime and still fits, that wins.
    (Dynamic programming: fast even for 5-6 line quotes.)"""
    k = len(words)
    if n > k:
        return None
    lime_at = [bool(f) and all(f) for _, f in words]
    seg = {}
    for i in range(k):
        for j in range(i + 1, k + 1):
            seg[i, j] = visual_w(font, words[i:j])
    INF = float("inf")
    # dp[(j, m, b)] = (max width, prev i) for words[:j] in m lines; b = a cut already sits on a colour change
    dp = {(0, 0, False): (0.0, None)}
    for m in range(1, n + 1):
        for j in range(m, k + 1):
            for i in range(m - 1, j):
                for b in (False, True):
                    prev = dp.get((i, m - 1, b))
                    if prev is None:
                        continue
                    nb = b or (0 < i and lime_at[i] != lime_at[i - 1])
                    w = max(prev[0], seg[i, j])
                    key = (j, m, nb)
                    if key not in dp or w < dp[key][0]:
                        dp[key] = (w, (i, b))
    def build(b):
        if (k, n, b) not in dp:
            return None
        out, j, m, bb = [], k, n, b
        w = dp[(k, n, b)][0]
        while m > 0:
            i, pb = dp[(j, m, bb)][1]
            out.insert(0, words[i:j]); j, m, bb = i, m - 1, pb
        return (w, out)
    best_b, best_n = build(True), build(False)
    best = min([r for r in (best_b, best_n) if r], key=lambda r: r[0])
    if best_b and (max_w is None or best_b[0] <= max_w):
        return best_b
    return best


def visual_w(font, line):
    text = " ".join(w for w, _ in line)
    return line_width(font, text, Q_TRACK) + Q_SKEW * cap_height(font)


def layout_quote(words, forced):
    if forced:
        lines = split_forced(words)
        size = Q_SIZE
        while size > Q_MIN_SIZE:
            f = load_font(Q_FONT, size)
            if max(visual_w(f, l) for l in lines) <= Q_MAX_W:
                break
            size -= 2
        return size, lines
    words = [w for w in words if w[0] != "|"]
    # preference: <=2 lines at big size, then 3, then 4; longer quotes get more lines (5, 6) rather than smaller text
    for max_lines, min_size in ((2, 132), (3, 112), (4, Q_MIN_SIZE), (5, Q_MIN_SIZE), (6, Q_MIN_SIZE - 8)):
        size = Q_SIZE
        while size >= min_size:
            f = load_font(Q_FONT, size)
            for n in range(1, max_lines + 1):
                r = best_wrap(words, n, f, Q_MAX_W)
                if r and r[0] <= Q_MAX_W:
                    return size, r[1]
            size -= 2
    f = load_font(Q_FONT, Q_MIN_SIZE - 8)
    return Q_MIN_SIZE - 8, best_wrap(words, 6, f)[1]


# ---------- drawing ----------
def render_quote_line(line, font, lime_default):
    """Return (white_mask, lime_mask, pad, baseline_y, width) for one line, already slanted."""
    text = " ".join(w for w, _ in line)
    flags = []
    for i, (w, f) in enumerate(line):
        if i:
            flags.append(flags[-1] if flags else False)  # space takes prev colour
        flags.extend(f if f else [lime_default] * len(w))
    asc = cap_height(font)
    pad = 40
    lw = int(line_width(font, text, Q_TRACK))
    cw, chh = lw + 2 * pad + int(Q_SKEW * asc) + 20, int(font.size * 1.3) + 2 * pad
    base_y = pad + int(font.size)  # baseline inside canvas
    m_white = Image.new("L", (cw, chh), 0)
    m_lime = Image.new("L", (cw, chh), 0)
    dw, dl = ImageDraw.Draw(m_white), ImageDraw.Draw(m_lime)
    track = Q_TRACK * font.size
    for i, ch in enumerate(text):
        x = pad + font.getlength(text[:i + 1]) - font.getlength(ch) + track * i   # keeps the kerning pair before ch
        (dl if flags[i] else dw).text((x, base_y), ch, font=font, fill=255, anchor="ls")
    # faux italic: shear around baseline
    def shear(im):
        return im.transform(im.size, Image.AFFINE,
                            (1, Q_SKEW, -Q_SKEW * base_y, 0, 1, 0),
                            resample=Image.BICUBIC)
    m_white, m_lime = shear(m_white), shear(m_lime)
    return m_white, m_lime, pad, base_y, lw


def wrap_plain(text, font, track, max_w):
    words, lines, cur = text.split(), [], ""
    for w in words:
        t = (cur + " " + w).strip()
        if line_width(font, t, track) <= max_w or not cur:
            cur = t
        else:
            lines.append(cur); cur = w
    if cur:
        lines.append(cur)
    # rebalance 2 lines like the original (first line shorter or equal)
    if len(lines) == 2:
        ws = text.split()
        best = None
        for i in range(1, len(ws)):
            a, b = " ".join(ws[:i]), " ".join(ws[i:])
            wa, wb = line_width(font, a, track), line_width(font, b, track)
            if max(wa, wb) <= max_w:
                score = max(wa, wb) + (1000 if wa > wb else 0)  # first line shorter, like the original
                if best is None or score < best[0]:
                    best = (score, [a, b])
        if best:
            lines = best[1]
    return lines


def sub_runs(text):
    """'Sabalenka claps back at **disrespectful** reporter' -> list of (word, bold) incl. spaces."""
    parts = re.split(r"(\*\*)", text.strip())
    bold, words = False, []
    for p in parts:
        if p == "**":
            bold = not bold; continue
        for w in re.split(r"( )", p):
            if w:
                words.append((w, bold))
    return words


def runs_width(runs, fr, fb, track):
    return sum(line_width(fb if b else fr, w, track) + track * (fb if b else fr).size for w, b in runs)


def wrap_runs(runs, fr, fb, track, max_w):
    if runs_width(runs, fr, fb, track) <= max_w:
        return [runs]
    idx = [i for i, (w, _) in enumerate(runs) if w == " "]
    best = None
    for i in idx:
        a, b = runs[:i], runs[i + 1:]
        wa, wb = runs_width(a, fr, fb, track), runs_width(b, fr, fb, track)
        if max(wa, wb) <= max_w:
            sc = abs(wa - wb)
            if best is None or sc < best[0]:
                best = (sc, [a, b])
    return best[1] if best else [runs]


def draw_runs_tracked(draw, x, y, runs, fr, fb, track, fill):
    for w, b in runs:
        f = fb if b else fr
        draw_tracked(draw, (x, y), w, f, track, fill)
        x += line_width(f, w, track) + track * f.size


def draw_tracked(draw, xy, text, font, track, fill):
    x, y = xy
    t = track * font.size
    for i, ch in enumerate(text):
        draw.text((x + font.getlength(text[:i + 1]) - font.getlength(ch) + t * i, y), ch, font=font, fill=fill, anchor="ls")


def fit_photo(path, fx, fy, zoom):
    im = Image.open(path).convert("RGB")
    s = max(W / im.width, H / im.height) * zoom
    nw, nh = round(im.width * s), round(im.height * s)
    im = im.resize((nw, nh), Image.LANCZOS)
    x = round((nw - W) * fx); y = round((nh - H) * fy)
    return im.crop((x, y, x + W, y + H))


def extra_shade(overlay, shift):
    """Raise the dark fade by `shift` px for taller text stacks."""
    if shift <= 0:
        return None
    a = overlay.getchannel("A")
    col = [a.getpixel((540, y)) for y in range(H)]
    shade = Image.new("L", (1, H))
    for y in range(H):
        src = min(H - 1, y + shift)
        shade.putpixel((0, y), max(0, col[src] - col[y]))
    shade = shade.resize((W, H))
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 255))
    layer.putalpha(shade)
    return layer


def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: quote_render.py data.json out.png photo.jpg")
    canvas = fit_photo(photo, data.get("bg_focus_x", 0.5), data.get("bg_focus_y", 0.35),
                       data.get("bg_zoom", 1.0)).convert("RGBA")

    # --- text layout (bottom-up) ---
    sfont = load_font(S_FONT, S_SIZE)
    sbold = load_font(S_FONT_BOLD, S_SIZE)
    slines = wrap_runs(sub_runs(data["subtitle"]), sfont, sbold, S_TRACK, S_MAX_W)   # exactly as typed
    s_first_base = S_LAST_BASELINE - S_LEAD * (len(slines) - 1)
    s_cap_top = s_first_base - cap_height(sfont)

    words, has_marks, forced = parse_quote(data["quote"])
    qsize, qlines = layout_quote(words, forced)
    qfont = load_font(Q_FONT, qsize)
    lead = round(Q_LEAD * qsize)
    q_last_base = s_cap_top - GAP_Q_TO_S
    q_first_base = q_last_base - lead * (len(qlines) - 1)
    q_cap_top = q_first_base - cap_height(qfont)
    icon_top = q_cap_top - ICON_GAP - ICON_SIZE[1]

    # --- overlay (+ extra shade if the stack is taller than the original) ---
    overlay = Image.open(asset("quote_overlay.png")).convert("RGBA")
    shade = extra_shade(overlay, DEFAULT_ICON_TOP - icon_top)
    if shade:
        canvas.alpha_composite(shade)
    canvas.alpha_composite(overlay)

    # --- quote lines ---
    m_white = Image.new("L", (W, H), 0)
    m_lime = Image.new("L", (W, H), 0)
    for i, line in enumerate(qlines):
        lime_default = (not has_marks) and (i == len(qlines) - 1) and len(qlines) > 1
        mw, ml, pad, base_y, lw = render_quote_line(line, qfont, lime_default)
        vis_w = lw + Q_SKEW * cap_height(qfont)
        x = round(W / 2 - vis_w / 2) - pad
        y = q_first_base + i * lead - base_y
        m_white.paste(mw, (x, y), mw)
        m_lime.paste(ml, (x, y), ml)
    mask_layer = ImageChops.lighter(m_white, m_lime)
    # lime: pale at the top of the block, full lime at the bottom
    grad = Image.new("RGB", (1, H))
    for y in range(H):
        t = min(max((y - q_cap_top) / max(1, q_last_base - q_cap_top), 0), 1)
        k = (1 - t) ** Q_LIME_CURVE
        grad.putpixel((0, y), tuple(round(Q_LIME[c] + (Q_LIME_TOP[c] - Q_LIME[c]) * k) for c in range(3)))
    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text_layer.paste(Image.new("RGB", (W, H), Q_WHITE), (0, 0), m_white)
    text_layer.paste(grad.resize((W, H)), (0, 0), m_lime)
    text_layer.putalpha(mask_layer)
    # drop shadow
    sh = mask_layer.filter(ImageFilter.GaussianBlur(SHADOW["blur"]))
    sh = sh.point(lambda v: int(v * SHADOW["opacity"]))
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 255)); shadow.putalpha(sh)
    canvas.alpha_composite(shadow, (0, SHADOW["offset"]))
    canvas.alpha_composite(text_layer)

    # --- subtitle (soft white -> light grey) ---
    smask = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(smask)
    for i, t in enumerate(slines):
        w = runs_width(t, sfont, sbold, S_TRACK)
        draw_runs_tracked(d, W / 2 - w / 2, s_first_base + i * S_LEAD, t, sfont, sbold, S_TRACK, 255)
    grad = Image.new("RGB", (1, H))
    y0, y1 = s_cap_top, S_LAST_BASELINE
    for y in range(H):
        t = min(max((y - y0) / max(1, y1 - y0), 0), 1)
        grad.putpixel((0, y), tuple(int(S_TOP[c] + (S_BOT[c] - S_TOP[c]) * t) for c in range(3)))
    canvas.paste(grad.resize((W, H)), (0, 0), smask)

    # --- icon + logo ---
    icon = Image.open(asset("quote_icon.png")).convert("RGBA")
    canvas.alpha_composite(icon, (round(W / 2 - ICON_SIZE[0] / 2), icon_top))
    logo = Image.open(asset("thrill_logo.png")).convert("RGBA")
    if logo.width != LOGO_W:  # any resolution works: scaled to the template width
        logo = logo.resize((LOGO_W, round(logo.height * LOGO_W / logo.width)), Image.LANCZOS)
    canvas.alpha_composite(logo, LOGO_XY)

    canvas.convert("RGB").save(out_path, quality=95)
    return {"quote_size": qsize, "quote_lines": [" ".join(w for w, _ in l) for l in qlines],
            "subtitle_lines": ["".join(w for w, _ in l) for l in slines], "icon_top": icon_top}


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    info = render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
    print(json.dumps(info, ensure_ascii=False))
