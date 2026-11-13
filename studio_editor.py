#!/usr/bin/env python3
"""Studio editor: turns a rendered post into an interactive page where the photos can be dragged and zoomed.

Every generator calls this when it gets `--editor` (or `"editor": true` in the JSON):

    python3 <format>_render.py data.json out.png photo.jpg --editor

That writes, next to out.png, `out_editor.html`: a self-contained page with
  - the background photo        -> drag to move, scroll / slider to zoom
  - the circle (if any)         -> drag to move it on the slide, scroll / slider to resize it
  - the photo inside the circle -> tick "Inside circle", then drag / zoom it
  - everything else (texture, text, cards, logos) as one fixed layer: the design can't be changed here
and a Download PNG button (1080x1350). Nothing is uploaded anywhere; the page needs no network.

How the layers are made: the generator runs a second time with the photo left transparent, so the
design layer is exactly the one in the PNG. The photos are embedded at up to 2400 px (circle 1400 px).
"""
import base64, io, json, os, sys
from PIL import Image, ImageOps

W, H = 1080, 1350
PHOTO_MAX = 2400
CIRCLE_MAX = 1400


def _uri(img, fmt="PNG", quality=90):
    buf = io.BytesIO()
    if fmt == "JPEG":
        img.convert("RGB").save(buf, "JPEG", quality=quality, optimize=True)
        mime = "image/jpeg"
    else:
        img.save(buf, "PNG", optimize=True)
        mime = "image/png"
    return f"data:{mime};base64," + base64.b64encode(buf.getvalue()).decode()


def _load(path, max_side, bw=False):
    im = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    if bw:
        im = ImageOps.grayscale(im).convert("RGB")
    k = min(1.0, max_side / max(im.size))
    if k < 1:
        im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
    return im


def _mask_png(mask):
    """L mask -> white PNG whose alpha is the mask (used with destination-in)."""
    m = Image.new("RGBA", mask.size, (255, 255, 255, 0))
    m.putalpha(mask.convert("L"))
    return _uri(m)


class Scene:
    """Ordered layers, bottom to top. Static layers are collected on a transparent canvas between the
    movable ones; call split(canvas) before adding a movable layer."""

    def __init__(self):
        self.layers = []
        self.bg = None          # embedded background photo (PIL) for the cutout mask

    # --- movable layers ---
    def photo(self, path, zoom=1.0, fx=0.5, fy=0.35, bw=False):
        im = _load(path, PHOTO_MAX, bw)
        self.bg = im
        self.layers.append({"type": "photo", "src": _uri(im, "JPEG", 92), "w": im.width, "h": im.height,
                            "zoom": float(zoom), "fx": float(fx), "fy": float(fy)})
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    def cutout(self, mask_fn, crop_mask=None):
        """The person from the background photo, drawn in front of what sits below (circle, word...).
        mask_fn(PIL RGB) -> L mask for the whole embedded photo, so the cutout follows every move.
        crop_mask: the mask the generator used on its 1080x1350 crop; pasted back in place so the
        starting state is exactly the PNG (the model can see a racket in the crop but not in the full photo)."""
        if self.bg is None:
            return
        m = mask_fn(self.bg)
        if m.size != self.bg.size:
            m = m.resize(self.bg.size, Image.LANCZOS)
        if crop_mask is not None:
            ph = next(l for l in self.layers if l["type"] == "photo")
            w, h = self.bg.size
            s = max(W / w, H / h) * ph["zoom"]
            nw, nh = w * s, h * s
            x0, y0 = round((nw - W) * ph["fx"]), round((nh - H) * ph["fy"])
            box = (round(x0 / s), round(y0 / s), round((x0 + W) / s), round((y0 + H) / s))
            cm = crop_mask.convert("L").resize((max(1, box[2] - box[0]), max(1, box[3] - box[1])), Image.LANCZOS)
            m = m.copy(); m.paste(cm, box[:2])
        self.layers.append({"type": "cutout", "mask": _mask_png(m)})

    def circle(self, path, d, cx, cy, zoom=1.0, fx=0.5, fy=0.3, stroke=6, bw=False, x_mark=False,
               pop=False, mask_fn=None):
        im = _load(path, CIRCLE_MAX, bw)
        lay = {"type": "circle", "src": _uri(im, "JPEG", 92), "w": im.width, "h": im.height,
               "d": float(d), "cx": float(cx), "cy": float(cy), "zoom": float(zoom), "fx": float(fx),
               "fy": float(fy), "stroke": float(stroke), "x": bool(x_mark), "pop": None}
        if pop and mask_fn:
            try:
                lay["pop"] = _mask_png(mask_fn(im))
            except Exception:
                pass
        if getattr(self, "defer_circle", False):   # generator computes the circle early, places it later
            self._pending = lay
        else:
            self.layers.append(lay)

    def flush_circle(self):
        if getattr(self, "_pending", None):
            self.layers.append(self._pending)
            self._pending = None

    def xmark(self):
        """The red X of the last circle (drawn above the cutout, like the generators)."""
        self.layers.append({"type": "xmark"})

    # --- fixed layers ---
    def static(self, canvas):
        if canvas is not None and canvas.getchannel("A").getbbox():
            self.layers.append({"type": "static", "src": _uri(canvas.convert("RGBA"))})

    def split(self, canvas):
        """Close the current static layer and start a new transparent one."""
        self.static(canvas)
        return Image.new("RGBA", (W, H), (0, 0, 0, 0))

    # --- output ---
    def write(self, html_path, title, filename, accent="#CCFA14"):
        scene = {"w": W, "h": H, "title": title, "filename": filename, "layers": self.layers}
        html = TEMPLATE.replace("__TITLE__", title).replace("__ACCENT__", accent)
        html = html.replace("/*__SCENE__*/null", json.dumps(scene, separators=(",", ":")))
        open(html_path, "w", encoding="utf-8").write(FULL_OPEN + html + FULL_CLOSE)
        return html_path


def run(module, data, out_png, photo=None, accent="#CCFA14"):
    """Render `module` a second time in editor mode and write <out>_editor.html next to out_png."""
    sc = Scene()
    module.EDIT = sc
    tmp = os.path.splitext(out_png)[0] + "_editor_design.png"
    try:
        if photo is None:
            module.render(data, tmp)
        else:
            module.render(data, tmp, photo)
    finally:
        module.EDIT = None
        if os.path.exists(tmp):
            os.remove(tmp)
    html = os.path.splitext(out_png)[0] + "_editor.html"
    sc.write(html, os.path.splitext(os.path.basename(out_png))[0], os.path.basename(out_png), accent)
    return html


def artifact_version(html_path):
    """The same page without the document skeleton, for publishing with the Artifact tool
    (it adds its own skeleton). Writes <name>_artifact.html and returns its path."""
    s = open(html_path, encoding="utf-8").read()
    if s.startswith(FULL_OPEN):
        s = s[len(FULL_OPEN):]
    if s.endswith(FULL_CLOSE):
        s = s[:-len(FULL_CLOSE)]
    out = os.path.splitext(html_path)[0] + "_artifact.html"
    open(out, "w", encoding="utf-8").write(s)
    return out



def wants_editor(argv, data):
    return "--editor" in argv or bool(data.get("editor"))


FULL_OPEN = ('<!doctype html><html lang="en"><head><meta charset="utf-8">'
             '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover"></head><body>')
FULL_CLOSE = '</body></html>'

TEMPLATE = r"""<title>__TITLE__</title>
<meta name="claude:viewport-fit-sides" content="cover">
<style>
:root{--acc:__ACCENT__;--ink:#0a0a0a;--bg:#0f1012;--panel:#17191c;--panel2:#202328;--line:rgba(255,255,255,.1);--txt:#f2f3f4;--mut:rgba(242,243,244,.62);--white:#ffffff;--black:#000000;color-scheme:dark}
/* deliberate single dark look: a photo-editing tool, so the post itself carries all the colour */
*{box-sizing:border-box}html,body{margin:0;background:var(--bg);color:var(--txt);font:14px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
.app{display:grid;grid-template-columns:300px minmax(0,1fr);gap:16px;min-height:100vh;padding-left:max(16px,env(safe-area-inset-left,0px));padding-right:max(16px,env(safe-area-inset-right,0px));padding-block:16px}
aside{background:var(--panel);border:1px solid var(--line);border-radius:12px;padding:18px;display:flex;flex-direction:column;gap:14px;align-self:start}
h1{font-size:16px;margin:0}.mut{color:var(--mut);font-size:12px}
.sec{border-top:1px solid var(--line);padding-top:12px;display:flex;flex-direction:column;gap:8px}
.lbl{font-size:11px;font-weight:700;letter-spacing:1.2px;text-transform:uppercase;color:var(--mut)}
.row{display:flex;align-items:center;gap:8px;font-size:12px}.row span{width:84px;color:var(--mut);flex:none}
input[type=range]{flex:1;accent-color:var(--acc);min-width:0}
.seg{display:flex;background:var(--panel2);border:1px solid var(--line);border-radius:9px;overflow:hidden}
.seg button{flex:1;background:none;border:0;color:var(--mut);font:600 12px system-ui;padding:8px 6px;cursor:pointer}
.seg button.on{background:var(--acc);color:var(--ink)}.seg button:disabled{opacity:.35;cursor:default}
.btn{border:0;border-radius:9px;padding:10px 14px;font:700 13px system-ui;cursor:pointer}
.btn.pri{background:var(--acc);color:var(--ink)}.btn.gh{background:var(--panel2);color:var(--txt);border:1px solid var(--line)}
.btn:focus-visible,.seg button:focus-visible{outline:2px solid var(--acc);outline-offset:2px}
main{display:flex;flex-direction:column;align-items:center;gap:12px;max-height:calc(100vh - 32px);min-width:0}
.stage{flex:1;min-height:0;width:100%;display:flex;align-items:center;justify-content:center}
canvas{height:100%;max-height:calc(100vh - 110px);width:auto;max-width:100%;aspect-ratio:1080/1350;border-radius:8px;box-shadow:0 18px 50px rgba(0,0,0,.55);touch-action:none;cursor:grab;background:var(--panel2)}
canvas.drag{cursor:grabbing}
.btns{display:flex;gap:10px;flex-wrap:wrap;justify-content:center}
textarea{width:100%;height:84px;background:var(--panel2);color:var(--txt);border:1px solid var(--line);border-radius:8px;font:11px ui-monospace,monospace;padding:8px;resize:vertical}
.toast{position:fixed;left:50%;bottom:calc(22px + env(safe-area-inset-bottom,0px));transform:translateX(-50%);background:var(--white);color:var(--black);font:600 13px system-ui;padding:9px 14px;border-radius:9px;opacity:0;transition:.2s;pointer-events:none}
.toast.show{opacity:1}
@media (prefers-reduced-motion: reduce){.toast{transition:none}}
.modal{position:fixed;inset:0;background:rgba(0,0,0,.85);display:none;align-items:center;justify-content:center;padding:16px}
.modal.show{display:flex}.modal .box{background:var(--panel);border-radius:12px;padding:14px;max-width:480px;width:100%;text-align:center}
.modal img{width:100%;max-height:70vh;object-fit:contain;margin:10px 0;border-radius:6px}
@media (max-width:860px){.app{grid-template-columns:minmax(0,1fr)}aside{order:2}main{order:1;max-height:none}canvas{width:100%;height:auto;max-height:none}}
</style>
<div class="app">
<aside>
  <div><h1 id="ttl">Adjust photos</h1><div class="mut">Drag on the preview to move. Scroll (or use the sliders) to zoom. Text and design stay locked.</div></div>
  <div class="sec">
    <div class="lbl">Drag moves</div>
    <div class="seg" id="seg">
      <button data-t="photo" class="on">Photo</button><button data-t="circle">Circle</button><button data-t="inner">Inside circle</button>
    </div>
    <div class="mut" id="segHint">Tip: with “Photo” selected, grabbing the circle moves the circle.</div>
  </div>
  <div class="sec">
    <div class="lbl">Zoom</div>
    <div class="row"><span>Photo</span><input type="range" id="zPhoto" min="1" max="4" step="0.01" value="1"></div>
    <div class="row cOnly"><span>Circle size</span><input type="range" id="zCircle" min="140" max="1000" step="1" value="430"></div>
    <div class="row cOnly"><span>Inside circle</span><input type="range" id="zInner" min="1" max="4" step="0.01" value="1"></div>
  </div>
  <div class="sec">
    <button class="btn gh" id="reset" type="button">Reset to Claude’s version</button>
  </div>
  <div class="sec">
    <div class="lbl">Settings for Claude</div>
    <div class="mut">Paste these into the chat to make the change permanent (Claude will render the same framing).</div>
    <textarea id="settings" readonly></textarea>
    <button class="btn gh" id="copySet" type="button">Copy settings</button>
  </div>
</aside>
<main>
  <div class="stage"><canvas id="c" width="1080" height="1350" aria-label="Post preview"></canvas></div>
  <div class="btns"><button class="btn pri" id="dl" type="button">Download PNG</button><button class="btn gh" id="copyImg" type="button">Copy image</button></div>
</main>
</div>
<div class="modal" id="modal"><div class="box"><b>Your post</b><div class="mut">Right-click → Save image as… (long-press on phone)</div><img id="mImg" alt="Finished post"><button class="btn gh" id="mClose" type="button">Close</button></div></div>
<div class="toast" id="toast" role="status"></div>
<script id="sceneData" type="application/json">/*__SCENE__*/null</script>
<script>
const S = JSON.parse(document.getElementById('sceneData').textContent);
const W = S.w, H = S.h, $ = id => document.getElementById(id);
const cv = $('c'), ctx = cv.getContext('2d');
document.title = S.title; $('ttl').textContent = S.title;
const L = S.layers;
const photo = L.find(l => l.type === 'photo'), circle = L.find(l => l.type === 'circle');
const ORIG = JSON.parse(JSON.stringify(L.map(l => ({zoom:l.zoom, fx:l.fx, fy:l.fy, d:l.d, cx:l.cx, cy:l.cy}))));
let target = 'photo';

/* ---- load images ---- */
const load = src => new Promise(r => { const i = new Image(); i.onload = () => r(i); i.onerror = () => r(null); i.src = src; });
async function boot(){
  for(const l of L){
    if(l.src) l.img = await load(l.src);
    if(l.mask) l.maskImg = await load(l.mask);
    if(l.pop) l.popImg = await load(l.pop);
  }
  if(!circle){ document.querySelectorAll('.cOnly').forEach(e => e.hidden = true);
    document.querySelectorAll('#seg button[data-t="circle"],#seg button[data-t="inner"]').forEach(b => b.disabled = true);
    $('segHint').hidden = true; }
  syncSliders(); render();
}

/* ---- geometry (same maths as the Python generators) ---- */
function photoRect(l){ // cover the canvas, zoom, focus = share of the overflow
  const s = Math.max(W / l.w, H / l.h) * l.zoom, nw = l.w * s, nh = l.h * s;
  return {x: -Math.round((nw - W) * l.fx), y: -Math.round((nh - H) * l.fy), w: nw, h: nh, s};
}
function innerRect(c){ // image inside the circle: covers the d x d disc
  const s = Math.max(c.d / c.w, c.d / c.h) * c.zoom, nw = Math.max(c.d, c.w * s), nh = Math.max(c.d, c.h * s);
  const x0 = Math.round((nw - c.d) * c.fx), y0 = Math.round((nh - c.d) * c.fy);
  return {x: c.cx - c.d / 2 - x0, y: c.cy - c.d / 2 - y0, w: nw, h: nh, x0, y0};
}

/* ---- drawing ---- */
const off = document.createElement('canvas'); off.width = W; off.height = H; const ox = off.getContext('2d');
function masked(img, rect, mask, clip){ // img drawn at rect, kept only where mask is, optional clip rect
  ox.save(); ox.clearRect(0, 0, W, H);
  if(clip){ ox.beginPath(); ox.rect(clip.x, clip.y, clip.w, clip.h); ox.clip(); }
  ox.imageSmoothingQuality = 'high';
  ox.drawImage(img, rect.x, rect.y, rect.w, rect.h);
  ox.globalCompositeOperation = 'destination-in';
  ox.drawImage(mask, rect.x, rect.y, rect.w, rect.h);
  ox.restore();
  ctx.drawImage(off, 0, 0);
}
function drawCircle(c){
  const r = innerRect(c), R = c.d / 2;
  ctx.save(); ctx.beginPath(); ctx.arc(c.cx, c.cy, R, 0, Math.PI * 2); ctx.clip();
  ctx.imageSmoothingQuality = 'high'; ctx.drawImage(c.img, r.x, r.y, r.w, r.h);
  ctx.restore();
  ctx.save(); ctx.beginPath(); ctx.arc(c.cx, c.cy, R - c.stroke / 2, 0, Math.PI * 2);
  ctx.lineWidth = c.stroke; ctx.strokeStyle = '#fff'; ctx.stroke(); ctx.restore();
  if(c.popImg){ // head breaking out over the top of the frame
    masked(c.img, r, c.popImg, {x: c.cx - R, y: c.cy - R - 0.12 * c.d, w: c.d, h: 0.12 * c.d + R});
  }
}
function drawX(c){
  const xs = Math.round(c.d * 0.27), wdt = Math.max(8, Math.round(c.d * 0.05)), pad = wdt / 2;
  const x = c.cx - xs / 2, y = c.cy - c.d / 2 - xs * 0.55;
  ctx.save(); ctx.lineCap = 'butt'; ctx.lineWidth = wdt;
  ctx.shadowColor = 'rgba(0,0,0,.45)'; ctx.shadowBlur = 12; ctx.shadowOffsetY = 4;
  ctx.strokeStyle = 'rgb(237,28,36)'; ctx.beginPath();
  ctx.moveTo(x + pad, y + pad); ctx.lineTo(x + xs - pad, y + xs - pad);
  ctx.moveTo(x + pad, y + xs - pad); ctx.lineTo(x + xs - pad, y + pad); ctx.stroke(); ctx.restore();
}
function render(){
  ctx.clearRect(0, 0, W, H);
  for(const l of L){
    if(l.type === 'photo' && l.img){ const r = photoRect(l); ctx.imageSmoothingQuality = 'high'; ctx.drawImage(l.img, r.x, r.y, r.w, r.h); }
    else if(l.type === 'static' && l.img) ctx.drawImage(l.img, 0, 0);
    else if(l.type === 'circle' && l.img) drawCircle(l);
    else if(l.type === 'cutout' && l.maskImg && photo && photo.img) masked(photo.img, photoRect(photo), l.maskImg);
    else if(l.type === 'xmark' && circle && circle.x) drawX(circle);
  }
  writeSettings();
}
let raf = 0; const req = () => { if(!raf) raf = requestAnimationFrame(() => { raf = 0; render(); }); };

/* ---- settings text: the same framing, as JSON the generators read ---- */
const r3 = v => Math.round(v * 1000) / 1000;
function writeSettings(){
  const o = {};
  if(photo){ o.bg_zoom = r3(photo.zoom); o.bg_focus_x = r3(photo.fx); o.bg_focus_y = r3(photo.fy); }
  if(circle){ o.circle = {pos: [Math.round(circle.cx), Math.round(circle.cy)], size: Math.round(circle.d),
                          zoom: r3(circle.zoom), focus_x: r3(circle.fx), focus_y: r3(circle.fy)}; }
  $('settings').value = JSON.stringify(o);
}

/* ---- interaction ---- */
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
function setTarget(t){ if(!circle && t !== 'photo') return; target = t;
  document.querySelectorAll('#seg button').forEach(b => b.classList.toggle('on', b.dataset.t === t)); }
document.querySelectorAll('#seg button').forEach(b => b.addEventListener('click', () => setTarget(b.dataset.t)));
function pt(e){ const r = cv.getBoundingClientRect(); return {x: (e.clientX - r.left) * W / r.width, y: (e.clientY - r.top) * H / r.height, k: W / r.width}; }
function inCircle(p){ return circle && Math.hypot(p.x - circle.cx, p.y - circle.cy) <= circle.d / 2; }
function whatAt(p){ if(target === 'inner') return circle ? 'inner' : 'photo'; if(target === 'circle') return 'circle';
  return inCircle(p) ? 'circle' : 'photo'; }
function movePhoto(l, dx, dy){ const r = photoRect(l);
  if(r.w > W) l.fx = clamp(l.fx - dx / (r.w - W), 0, 1); if(r.h > H) l.fy = clamp(l.fy - dy / (r.h - H), 0, 1); }
function moveInner(c, dx, dy){ const r = innerRect(c);
  if(r.w > c.d) c.fx = clamp(c.fx - dx / (r.w - c.d), 0, 1); if(r.h > c.d) c.fy = clamp(c.fy - dy / (r.h - c.d), 0, 1); }
function zoomPhoto(l, z, p){ // keep the point under the cursor in place
  const r0 = photoRect(l), ix = (p.x - r0.x) / r0.w, iy = (p.y - r0.y) / r0.h;
  l.zoom = clamp(z, 1, 4); const r1 = photoRect({...l, fx: 0, fy: 0});
  const x0 = ix * r1.w - p.x, y0 = iy * r1.h - p.y;
  l.fx = r1.w > W ? clamp(x0 / (r1.w - W), 0, 1) : 0.5; l.fy = r1.h > H ? clamp(y0 / (r1.h - H), 0, 1) : 0.5;
}
function zoomInner(c, z, p){
  const r0 = innerRect(c), ix = (p.x - r0.x) / r0.w, iy = (p.y - r0.y) / r0.h;
  c.zoom = clamp(z, 1, 4); const r1 = innerRect({...c, fx: 0, fy: 0});
  const x0 = ix * r1.w - (p.x - (c.cx - c.d / 2)), y0 = iy * r1.h - (p.y - (c.cy - c.d / 2));
  c.fx = r1.w > c.d ? clamp(x0 / (r1.w - c.d), 0, 1) : 0.5; c.fy = r1.h > c.d ? clamp(y0 / (r1.h - c.d), 0, 1) : 0.5;
}
function resizeCircle(c, d){ c.d = clamp(d, 140, 1000); }
let drag = null;
cv.addEventListener('pointerdown', e => { const p = pt(e), what = whatAt(p);
  if(what === 'photo' && !photo) return;
  drag = {what, x: e.clientX, y: e.clientY, k: p.k}; cv.setPointerCapture(e.pointerId); cv.classList.add('drag'); });
cv.addEventListener('pointermove', e => { if(!drag) return;
  const dx = (e.clientX - drag.x) * drag.k, dy = (e.clientY - drag.y) * drag.k; drag.x = e.clientX; drag.y = e.clientY;
  if(drag.what === 'photo') movePhoto(photo, dx, dy);
  else if(drag.what === 'circle'){ circle.cx = clamp(circle.cx + dx, -circle.d / 2, W + circle.d / 2); circle.cy = clamp(circle.cy + dy, -circle.d / 2, H + circle.d / 2); }
  else if(drag.what === 'inner') moveInner(circle, dx, dy);
  req(); });
const end = () => { drag = null; cv.classList.remove('drag'); syncSliders(); };
cv.addEventListener('pointerup', end); cv.addEventListener('pointercancel', end);
cv.addEventListener('wheel', e => { e.preventDefault(); const p = pt(e), what = whatAt(p), f = Math.exp(-e.deltaY * 0.0015);
  if(what === 'photo' && photo) zoomPhoto(photo, photo.zoom * f, p);
  else if(what === 'circle') resizeCircle(circle, circle.d * f);
  else if(what === 'inner') zoomInner(circle, circle.zoom * f, p);
  syncSliders(); req(); }, {passive: false});
window.addEventListener('keydown', e => { // arrow keys nudge the selected item by 1 px (10 with Shift)
  const m = {ArrowLeft: [-1, 0], ArrowRight: [1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1]}[e.key]; if(!m || e.target.tagName === 'TEXTAREA') return;
  e.preventDefault(); const n = e.shiftKey ? 10 : 1, dx = m[0] * n, dy = m[1] * n;
  if(target === 'photo' && photo) movePhoto(photo, dx, dy); else if(target === 'circle' && circle){ circle.cx += dx; circle.cy += dy; }
  else if(target === 'inner' && circle) moveInner(circle, dx, dy); req(); });
function syncSliders(){ if(photo) $('zPhoto').value = photo.zoom; else $('zPhoto').disabled = true;
  if(circle){ $('zCircle').value = circle.d; $('zInner').value = circle.zoom; } }
$('zPhoto').addEventListener('input', e => { if(photo){ zoomPhoto(photo, +e.target.value, {x: W / 2, y: H / 2}); req(); } });
$('zCircle').addEventListener('input', e => { if(circle){ resizeCircle(circle, +e.target.value); req(); } });
$('zInner').addEventListener('input', e => { if(circle){ zoomInner(circle, +e.target.value, {x: circle.cx, y: circle.cy}); req(); } });
$('reset').addEventListener('click', () => { L.forEach((l, i) => Object.assign(l, Object.fromEntries(Object.entries(ORIG[i]).filter(([k, v]) => v !== undefined)))); syncSliders(); req(); });

/* ---- export ---- */
function toast(m){ const t = $('toast'); t.textContent = m; t.classList.add('show'); clearTimeout(toast.t); toast.t = setTimeout(() => t.classList.remove('show'), 2400); }
let downloads = null;
try{ if(window.claude && typeof window.claude.use === 'function') window.claude.use('downloads').then(d => { downloads = d; }).catch(() => {}); }catch(e){}
const blob = () => { render(); return new Promise(r => cv.toBlob(r, 'image/png')); };
function modal(b){ $('mImg').src = URL.createObjectURL(b); $('modal').classList.add('show'); }
$('mClose').addEventListener('click', () => $('modal').classList.remove('show'));
$('dl').addEventListener('click', async () => {
  const b = await blob(); if(!b) return toast('Export failed');
  if(downloads){ try{ await downloads.save({filename: S.filename, data: b}); toast('Saved'); return; }
    catch(err){ if(err && err.code === 'declined'){ toast('Download cancelled'); return; } } }
  let top = false; try{ top = window.self === window.top; }catch(e){}
  if(top){ const a = document.createElement('a'); a.href = URL.createObjectURL(b); a.download = S.filename; document.body.appendChild(a); a.click(); a.remove(); toast('Saved to Downloads'); return; }
  modal(b);
});
$('copyImg').addEventListener('click', async () => { const b = await blob();
  try{ await navigator.clipboard.write([new ClipboardItem({'image/png': b})]); toast('Image copied'); }catch(e){ modal(b); } });
$('copySet').addEventListener('click', async () => { try{ await navigator.clipboard.writeText($('settings').value); toast('Settings copied'); }
  catch(e){ $('settings').select(); toast('Select and copy the text'); } });
boot();
</script>
"""
if __name__ == "__main__":
    # python3 studio_editor.py --artifact X_editor.html  ->  X_editor_artifact.html (for the Artifact tool)
    if len(sys.argv) == 3 and sys.argv[1] == "--artifact":
        print(artifact_version(sys.argv[2]))
    else:
        print(__doc__)
