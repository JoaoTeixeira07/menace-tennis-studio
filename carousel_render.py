#!/usr/bin/env python3
"""Menace Tennis CAROUSEL: renders a whole carousel in one go, with the locked templates
   slide 1      = COVER  (cover_render.py)
   slides 2..N  = BODY   (body_render.py), one per content slide
   last slide   = CTA / close (cta_render.py)

Usage:
    python3 carousel_render.py carousel.json [--editor]
    --editor also writes one editor page per slide (<slide>_editor.html) to drag / zoom the photos.

carousel.json:
{
  "date": "2026-11-12", "name": "sampras",                      # file names: <date>_carousel_<name>_slideNN.png
  "cover": {"photo": "/mnt/user-data/uploads/1.jpg", "text": "Happy birthday to [Pistol Pete]"},
  "slides": [
    {"photo": "/mnt/user-data/uploads/2.jpg", "title": "14 Grand Slams", "text": "Pete **Sampras** ..."},
    {"photo": "/mnt/user-data/uploads/3.jpg", "title": "The last match", "text": "..."}
  ],
  "cta": {"photo": "/mnt/user-data/uploads/4.jpg"},              # "text" optional (default: FOLLOW US for more stories like this!)
  "out_dir": "/mnt/user-data/outputs"                            # optional
}
Every slide also takes its template's own options (bg_focus_y, bg_zoom, bw, circle on the cover...).
"""
import json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)


def need(cond, msg):
    if not cond:
        raise SystemExit("Carousel input problem: " + msg)


def main(path, editor=False):
    data = json.load(open(path, encoding="utf-8"))
    cover, slides, cta = data.get("cover"), data.get("slides") or [], data.get("cta")
    need(cover and cover.get("photo") and cover.get("text"), "the cover needs a photo and a headline")
    for i, s in enumerate(slides, 2):
        need(s.get("photo") and s.get("text"), f"slide {i} needs a photo and a paragraph")
    need(cta and cta.get("photo"), "the CTA (last slide) needs a photo")
    for p in [cover["photo"], *[s["photo"] for s in slides], cta["photo"]]:
        need(os.path.exists(p), f"photo not found: {p}")

    import cover_render, body_render, cta_render
    out_dir = data.get("out_dir") or os.getcwd()
    os.makedirs(out_dir, exist_ok=True)
    stem = f'{data.get("date", "carousel")}_carousel_{data.get("name", "post")}'
    files, report = [], []

    def name(n):
        return os.path.join(out_dir, f"{stem}_slide{n:02d}.png")

    f = name(1)
    r = cover_render.render(cover, f, cover["photo"])
    files.append(f); report.append({"slide": 1, "template": "cover", "lines": r.get("lines")})
    for i, s in enumerate(slides, 2):
        f = name(i)
        r = body_render.render(s, f, s["photo"])
        files.append(f); report.append({"slide": i, "template": "body", "title": r.get("title"), "text_size": r.get("text_size")})
    n = len(slides) + 2
    f = name(n)
    r = cta_render.render(cta, f, cta["photo"])
    files.append(f); report.append({"slide": n, "template": "cta", "lines": r.get("lines")})

    if editor:   # one editor page per slide: <file>_editor.html (drag / zoom the photos, see studio_editor.py)
        import studio_editor
        jobs = [(cover_render, cover)] + [(body_render, s) for s in slides] + [(cta_render, cta)]
        for (mod, d), f, rep in zip(jobs, files, report):
            rep["editor"] = studio_editor.run(mod, d, f, d["photo"], accent="#CCFA14")

    # contact sheet to check the whole carousel at a glance
    from PIL import Image
    th = [Image.open(x).convert("RGB").resize((270, 338), Image.LANCZOS) for x in files]
    sheet = Image.new("RGB", (len(th) * 280 + 10, 358), (24, 24, 24))
    for k, im in enumerate(th):
        sheet.paste(im, (10 + k * 280, 10))
    prev = os.path.join(out_dir, f"{stem}_preview.png")
    sheet.save(prev, quality=90)
    print(json.dumps({"slides": report, "files": files, "preview": prev}, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if a != "--editor"]
    if not args:
        print(__doc__); sys.exit(1)
    main(args[0], editor="--editor" in sys.argv)
