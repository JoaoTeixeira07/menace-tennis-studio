#!/usr/bin/env python3
"""Menace Tennis MATCH RESULT scoreboard (1080x1350), "Lime Glass" design.

Photo + tennis green texture, two frosted dark-green cards (one per player, or per doubles team),
the winner's card in green with a lime outline, a lime side bar and lime set scores. Inter Display throughout.
Handles long names (shrink, then two lines), 1-5 sets, tie-breaks, retirements and walkovers.

Usage:
    python3 score_render.py data.json out.png photo.jpg

data.json:
{
  "players": [                                       # top row first, in the screenshot's order
    {"name": "N. Osaka", "flag": "jp"},
    {"name": "M. Keys",  "flag": "us", "seed": 19}   # seed: number or "Q" / "WC" / "LL" / "PR"; optional
  ],
  "sets": [[6, 4], [3, 6], [7, 6, [7, 5]]],          # per set: [top, bottom]; tie-break points as a 3rd item
  "winner": 0,                                       # 0 = top row, 1 = bottom row
  "status": "",                                      # optional: "ret" (loser retired) or "wo" (walkover, no sets)
  "tournament": "Wimbledon", "round": "R32", "category": "Women",
  "logo": "logo_wimbledon.png",                      # optional tournament logo (white / transparent), top-right
  "bg_focus_y": 0.35, "bg_focus_x": 0.5, "bg_zoom": 1.0, "bw": false
}
Doubles: give "players" two teams as lists, e.g. [[{"name":..,"flag":..},{..}], [{..},{..}]] (seed on the first player).
"""
import io, json, os, re, sys, urllib.request
from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont, ImageOps
import numpy as np

W, H = 1080, 1350
HERE = os.path.dirname(os.path.abspath(__file__))

# ---------- design constants ----------
LIME, LIME_TOP = (200, 249, 8), (218, 254, 70)
WHITE = (255, 255, 255)
LOSER_TXT = (200, 214, 205)
SET_LOST = (118, 146, 128)
WIN_CARD = ((40, 140, 70, 200), (10, 46, 24, 190))       # left -> right gradient
LOSE_CARD = ((255, 255, 255, 22), (255, 255, 255, 8))
CARD_X0, CARD_X1, CARD_R = 60, 1020, 18
ROW_H = {1: 118, 2: 150}                                 # singles / doubles card height
ROWS_GAP = 20
CARDS_BOTTOM = 1168                                      # bottom of the lower card
DIVIDER_Y, FOOTER_BASE = 1200, 1288
LOGO_XY, LOGO_W = (50, 50), 285

NAME = dict(opsz=32, wght=700, size=50, min=40, min2=30, track=-0.02)     # Inter Display Bold, caps
NUM = dict(opsz=32, wght=800, track=-0.03)                               # Inter Display ExtraBold, tabular figures
SETS_LAYOUT = {1: (88, 40), 2: (88, 40), 3: (88, 40), 4: (76, 28), 5: (66, 22)}   # n sets -> (number size, gap between columns)
SETS_RIGHT = CARD_X1 - 28                                # right edge of the last set column
FOOT = dict(opsz=32, wght=700, size=40, track=0.04)

SEARCH_DIRS = [HERE, os.getcwd(), "/mnt/project", "/mnt/user-data/uploads"]
DOWNLOADS = {"Inter-var.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/inter/Inter%5Bopsz,wght%5D.ttf"}
FLAG_SVG = "https://raw.githubusercontent.com/lipis/flag-icons/main/flags/4x3/{}.svg"


# ---------- assets ----------
def _norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def asset(name, required=True):
    stem, ext = os.path.splitext(name)
    key = _norm(stem)
    for d in SEARCH_DIRS:
        if os.path.isdir(d):
            for f in sorted(os.listdir(d)):
                fs, fe = os.path.splitext(f)
                if fe.lower() == ext.lower() and _norm(fs).startswith(key):
                    return os.path.join(d, f)
    if name in DOWNLOADS:
        dst = os.path.join(HERE, name)
        urllib.request.urlretrieve(DOWNLOADS[name], dst)
        return dst
    if required:
        raise FileNotFoundError(f"Missing asset: {name}")
    return None


_F = {}


def inter(size, wght, opsz=32):
    k = (size, wght, opsz)
    if k not in _F:
        try:
            f = ImageFont.truetype(asset("Inter-var.ttf"), size, layout_engine=ImageFont.Layout.RAQM)
        except Exception:
            f = ImageFont.truetype(asset("Inter-var.ttf"), size)
        f.set_variation_by_axes([opsz, wght])
        _F[k] = f
    return _F[k]


# ---------- drawing helpers ----------
def vgrad(stops):
    ys = np.linspace(0, 1, H)
    cols = np.zeros((H, 4))
    for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
        m = (ys >= p0) & (ys <= p1)
        k = ((ys[m] - p0) / max(p1 - p0, 1e-6))[:, None]
        cols[m] = np.array(c0) * (1 - k) + np.array(c1) * k
    return Image.fromarray(np.repeat(cols[:, None, :], W, 1).astype(np.uint8), "RGBA")


def hgrad(w, h, c0, c1):
    k = np.linspace(0, 1, w)[None, :, None]
    arr = np.array(c0) * (1 - k) + np.array(c1) * k
    return Image.fromarray(np.repeat(arr, h, 0).astype(np.uint8), "RGBA")


def rounded(im, r):
    m = Image.new("L", im.size, 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, im.size[0] - 1, im.size[1] - 1), r, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), m))
    return im


def text_w(s, f, track, feats=None):
    return f.getlength(s, features=feats) + track * f.size * max(0, len(s) - 1)


def draw_text(img, xy, s, f, track=0.0, fill=WHITE, lime=False, feats=None):
    """Left/baseline text with tracking and kerning; lime = the tennis lime gradient (top -> baseline)."""
    x, y = xy
    tr = track * f.size
    m = Image.new("L", img.size, 0)
    md = ImageDraw.Draw(m)
    for k, ch in enumerate(s):
        px = f.getlength(s[:k + 1], features=feats) - f.getlength(ch, features=feats)
        md.text((x + px + tr * k, y), ch, font=f, fill=255, anchor="ls", features=feats)
    bb = m.getbbox()
    if not bb:
        return 0
    if lime:
        t = np.clip((np.arange(H) - bb[1]) / max(1, bb[3] - bb[1]), 0, 1)[:, None]
        g = np.array(LIME_TOP) * (1 - t) + np.array(LIME) * t
        layer = Image.fromarray(np.repeat(g[:, None, :], W, 1).astype(np.uint8)).convert("RGBA")
    else:
        layer = Image.new("RGBA", img.size, tuple(fill[:3]) + (0,))
    a = m if len(fill) == 3 or lime else m.point(lambda v: v * fill[3] // 255)
    layer.putalpha(a)
    img.alpha_composite(layer)
    return text_w(s, f, track, feats)


def white_logo(path, box):
    im = Image.open(path)
    if im.mode == "RGBA" and im.getchannel("A").getextrema()[0] < 250:
        out = im.convert("RGBA")
    else:
        out = Image.new("RGBA", im.size, (255, 255, 255, 255))
        out.putalpha(im.convert("L"))
    out.thumbnail(box, Image.LANCZOS)
    return out


_FLAGS = {}


def flag(code, w, h, r=5):
    code = code.lower()
    if code not in _FLAGS:
        p = asset(f"flag_{code}.png", required=False)
        if p:
            im = Image.open(p).convert("RGBA")
        else:
            svg = urllib.request.urlopen(FLAG_SVG.format(code), timeout=15).read()
            try:
                import cairosvg
                im = Image.open(io.BytesIO(cairosvg.svg2png(bytestring=svg, output_width=w * 3, output_height=h * 3))).convert("RGBA")
            except ImportError:
                import subprocess, tempfile
                with tempfile.NamedTemporaryFile(suffix=".svg", delete=False) as t:
                    t.write(svg)
                subprocess.run(["rsvg-convert", "-w", str(w * 3), "-h", str(h * 3), t.name, "-o", t.name + ".png"], check=True)
                im = Image.open(t.name + ".png").convert("RGBA")
        _FLAGS[code] = im
    im = _FLAGS[code].resize((w, h), Image.LANCZOS)
    m = Image.new("L", (w, h), 0)
    ImageDraw.Draw(m).rounded_rectangle((0, 0, w - 1, h - 1), r, fill=255)
    im.putalpha(ImageChops.multiply(im.getchannel("A"), m))
    return im


def seed_badge(img, x, cy, seed, won):
    s = str(seed).upper()
    f = inter(25 if len(s) < 2 else 21, 700)
    w, h = max(50, int(f.getlength(s)) + 22), 44
    b = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    bd = ImageDraw.Draw(b)
    if won:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), 12, fill=LIME + (48,), outline=LIME + (210,), width=2)
    else:
        bd.rounded_rectangle((0, 0, w - 1, h - 1), 12, fill=(255, 255, 255, 22), outline=(255, 255, 255, 70), width=2)
    bd.text((w / 2, h / 2 + 1), s, font=f, fill=WHITE if won else (228, 236, 230), anchor="mm")
    img.alpha_composite(b, (int(x), int(cy - h / 2)))
    return w


# ---------- photo ----------
def place_photo(photo, data):
    im = ImageOps.exif_transpose(Image.open(photo)).convert("RGB")
    if data.get("bw"):
        im = ImageOps.grayscale(im).convert("RGB")
    k = max(W / im.width, H / im.height) * data.get("bg_zoom", 1.0)
    im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    fx, fy = data.get("bg_focus_x", 0.5), data.get("bg_focus_y", 0.35)
    x0, y0 = round((im.width - W) * fx), round((im.height - H) * fy)
    return im.crop((x0, y0, x0 + W, y0 + H)).convert("RGBA")


# ---------- names ----------
def caps(n):
    return n.strip().upper().replace("'", "’")


def fit_name(name, max_w, extra=0):
    """One line at 50 px, shrinking to 40; if still too wide, two lines (surname split) down to 30.
    extra = width reserved after the name (e.g. RET. tag). Returns (lines, font)."""
    s = caps(name)
    for size in range(NAME["size"], NAME["min"] - 1, -1):
        f = inter(size, NAME["wght"])
        if text_w(s, f, NAME["track"]) + extra <= max_w:
            return [s], f
    # break points: spaces after the initial ("A. DAVIDOVICH | FOKINA") and after hyphens ("F. AUGER- | ALIASSIME")
    splits = []
    for mt in re.finditer(r" |-", s):
        a, b = s[:mt.end()].rstrip(), s[mt.end():].strip()
        if mt.group() == " " and re.fullmatch(r"[\w’]{1,2}\.", a):
            continue          # don't leave just the initial on line 1
        if a and b:
            splits.append((a, b))
    if splits:
        for size in range(44, NAME["min2"] - 1, -1):
            f = inter(size, NAME["wght"])
            best = min(splits, key=lambda ab: max(text_w(ab[0], f, NAME["track"]), text_w(ab[1], f, NAME["track"]) + extra))
            if max(text_w(best[0], f, NAME["track"]), text_w(best[1], f, NAME["track"]) + extra) <= max_w:
                return list(best), f
    f = inter(NAME["min2"], NAME["wght"])
    return [s], f


# ---------- render ----------
def render(data, out_path, photo=None):
    photo = photo or data.get("photo")
    if not photo:
        raise SystemExit("A background photo is required: score_render.py data.json out.png photo.jpg")
    rows = [p if isinstance(p, list) else [p] for p in data["players"]]
    doubles = max(len(r) for r in rows) > 1
    sets = data.get("sets") or []
    winner = data.get("winner", 0)
    status = (data.get("status") or "").lower().replace(".", "").replace("/", "")
    if status not in ("", "ret", "wo"):
        raise SystemExit('status must be "", "ret" or "wo"')
    for s in sets:
        if len(s) > 2 and s[2] is not None and (len(s[2]) != 2):
            raise SystemExit(f"Tie-break must be [top, bottom] points: {s}")
    if not sets and status != "wo":
        raise SystemExit('No sets given. Use "status": "wo" for a walkover.')
    if sets and status == "":
        won_sets = [sum(1 for s in sets if s[i] > s[1 - i]) for i in (0, 1)]
        if won_sets[winner] <= won_sets[1 - winner]:
            raise SystemExit(f"Winner {winner} didn't win more sets {won_sets}: check the score or add \"status\": \"ret\".")

    img = place_photo(photo, data)
    # dark fade towards the cards + tennis texture (Tennis_Carousel_Body.psd overlay)
    img.alpha_composite(vgrad([(0, (0, 0, 0, 0)), (0.5, (0, 0, 0, 0)), (0.66, (4, 14, 8, 225)), (1, (4, 14, 8, 250))]))
    img.alpha_composite(Image.open(asset("score_overlay.png")).convert("RGBA"))
    if data.get("logo"):
        patch = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        ImageDraw.Draw(patch).rounded_rectangle((650, 0, 1100, 150), 50, fill=(3, 10, 6, 210))
        img.alpha_composite(patch.filter(ImageFilter.GaussianBlur(18)))

    # logos
    lg = Image.open(asset("thrill_logo.png")).convert("RGBA")
    lg = lg.resize((LOGO_W, round(lg.height * LOGO_W / lg.width)), Image.LANCZOS)
    img.alpha_composite(lg, LOGO_XY)
    missing_logo = None
    if data.get("logo"):
        lp = asset(data["logo"], required=False)
        if lp:
            tl = white_logo(lp, (260, 101))
            img.alpha_composite(tl, (W - 52 - tl.width, 46 + (101 - tl.height) // 2))
        else:
            missing_logo = data["logo"]

    # geometry
    rh = ROW_H[2 if doubles else 1]
    ys = [CARDS_BOTTOM - 2 * rh - ROWS_GAP, CARDS_BOTTOM - rh]
    n = len(sets)
    num_size, gap = SETS_LAYOUT.get(n, SETS_LAYOUT[5]) if n else (88, 40)
    fnum = inter(num_size, NUM["wght"])
    ftb = inter(round(num_size * 0.34), 700)
    nfe = ["tnum"]
    # even columns: every number on the same pitch, tie-break superscripts trail into the gap
    base = max([text_w(str(v), fnum, NUM["track"], nfe) for s_ in sets for v in s_[:2]] or [0])
    tbs = [text_w(str(s_[2][0 if s_[0] < s_[1] else 1]), ftb, 0, nfe) + 3 if len(s_) > 2 and s_[2] is not None else 0 for s_ in sets]
    pitch = base + gap + max(tbs or [0]) * (0.5 if n <= 3 else 1.0)
    start = SETS_RIGHT - (n - 1) * pitch - base - (tbs[-1] if tbs else 0)
    col_x = [start + k * pitch for k in range(n)]       # left edge of each number
    col_w = [base] * n
    any_seed = any(p.get("seed") for r in rows for p in r[:1])
    seed_x = CARD_X0 + 22
    flag_w, flag_h = 50, 36
    flag_x = CARD_X0 + (92 if any_seed else 30)
    name_x = flag_x + flag_w + 20
    sets_left = (col_x[0] - gap / 2) if n else SETS_RIGHT - 160
    name_max = sets_left - 12 - name_x

    report = []
    for i, (row, y) in enumerate(zip(rows, ys)):
        won = i == winner
        card = img.crop((CARD_X0, y, CARD_X1, y + rh)).filter(ImageFilter.GaussianBlur(18))
        card.alpha_composite(Image.new("RGBA", card.size, (0, 0, 0, 70)))
        card.alpha_composite(hgrad(CARD_X1 - CARD_X0, rh, *(WIN_CARD if won else LOSE_CARD)))
        card = rounded(card, CARD_R)
        cd = ImageDraw.Draw(card)
        cd.rounded_rectangle((0, 0, CARD_X1 - CARD_X0 - 1, rh - 1), CARD_R, outline=(LIME + (230,)) if won else (255, 255, 255, 40), width=2)
        if won:
            cd.rectangle((0, 22, 6, rh - 22), fill=LIME + (255,))
        img.alpha_composite(card, (CARD_X0, y))
        cy = y + rh / 2
        if row[0].get("seed"):
            seed_badge(img, seed_x, cy, row[0]["seed"], won)
        ret_tag = status == "ret" and not won
        f_tag = inter(19, 700)
        tag_w = text_w("RET.", f_tag, 0.12) + 28 if ret_tag else 0
        col = WHITE if won else LOSER_TXT
        players = row[:2]
        slot_h = rh / len(players)
        names_out = []
        for j, p in enumerate(players):
            pcy = y + slot_h * (j + 0.5)
            if p.get("flag"):
                img.alpha_composite(flag(p["flag"], flag_w, flag_h), (flag_x, int(pcy - flag_h / 2)))
            lines, f = fit_name(p["name"], name_max, tag_w if j == len(players) - 1 else 0)
            if doubles:  # two players per card: keep each on one line, smaller
                lines, f = [caps(p["name"])], inter(max(30, min(44, int(44 * name_max / max(1, text_w(caps(p['name']), inter(44, 700), NAME['track']))))), NAME["wght"])
            cap = -f.getbbox("H", anchor="ls")[1]
            lead = cap * 1.32
            first = pcy + cap / 2 - lead * (len(lines) - 1) / 2
            end_x = name_x
            for k, ln in enumerate(lines):
                end_x = name_x + draw_text(img, (name_x, first + k * lead), ln, f, NAME["track"], fill=col)
            if ret_tag and j == len(players) - 1:
                tx, tby = end_x + 16, first + (len(lines) - 1) * lead
                th = 30
                d = ImageDraw.Draw(img)
                d.rounded_rectangle((tx, tby - cap / 2 - th / 2, tx + tag_w - 16, tby - cap / 2 + th / 2), 8,
                                    outline=(255, 255, 255, 120), width=2)
                draw_text(img, (tx + 10, tby - cap / 2 + 7), "RET.", f_tag, 0.12, fill=(220, 228, 222))
            names_out.append(" ".join(lines).replace("- ", "-"))
        # set scores
        if status == "wo" and not sets:
            if won:
                fw_ = inter(46, 800)
                draw_text(img, (SETS_RIGHT - text_w("W/O", fw_, 0.02), cy + 17), "W/O", fw_, 0.02, lime=True)
        ncap = -fnum.getbbox("0", anchor="ls")[1]
        for k, s_ in enumerate(sets):
            m, t = s_[i], s_[1 - i]
            st = str(m)
            w_ = text_w(st, fnum, NUM["track"], nfe)
            x = col_x[k] + (col_w[k] - w_) / 2
            draw_text(img, (x, cy + ncap / 2), st, fnum, NUM["track"], fill=SET_LOST, lime=m > t, feats=nfe)
            if len(s_) > 2 and s_[2] is not None and m < t:   # tie-break points next to the set loser's games
                draw_text(img, (x + w_ + 3, cy - ncap / 2 + ftb.size * 0.72), str(s_[2][i]), ftb, 0, fill=SET_LOST, feats=nfe)
        report.append(" / ".join(names_out))

    # divider + footer
    ov = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(ov).line((CARD_X0, DIVIDER_Y, CARD_X1, DIVIDER_Y), fill=LIME + (110,), width=2)
    img.alpha_composite(ov)
    ff = inter(FOOT["size"], FOOT["wght"])
    tour = (data.get("tournament") or "").upper()
    rnd = (data.get("round") or "").upper()
    rw = text_w(rnd, ff, FOOT["track"]) if rnd else 0
    # long tournament names shrink so they never touch the round
    fsz = FOOT["size"]
    while tour and text_w(tour, inter(fsz, FOOT["wght"]), FOOT["track"]) > CARD_X1 - CARD_X0 - rw - 200 and fsz > 28:
        fsz -= 1
    adv = draw_text(img, (CARD_X0, FOOTER_BASE), tour, inter(fsz, FOOT["wght"]), FOOT["track"]) if tour else 0
    if data.get("category"):
        draw_text(img, (CARD_X0 + adv + 16, FOOTER_BASE), data["category"].upper(), inter(17, 700), 0.25, lime=True)
    if rnd:
        draw_text(img, (CARD_X1 - rw, FOOTER_BASE), rnd, ff, FOOT["track"], lime=True)

    img.convert("RGB").save(out_path, quality=95)

    def fmt(s, i):
        a, b = s[i], s[1 - i]
        tb = f"({s[2][i] if a < b else s[2][1 - i]})" if len(s) > 2 and s[2] is not None else ""
        return f"{a}-{b}{tb}"
    score = " ".join(fmt(s, winner) for s in sets) + (" ret." if status == "ret" else "") if sets else "w/o"
    out = {"result": f"{report[winner]} d. {report[1 - winner]} {score}", "tournament": tour, "round": rnd}
    if missing_logo:
        out["missing_logo"] = missing_logo
    return out


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    print(json.dumps(render(data, sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None), ensure_ascii=False))
