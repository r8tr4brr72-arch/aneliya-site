"""Frame-by-frame graphics layer: every overlay (headers, cards, CTA, scene pills, bars, counters…)
is an Element with its own animation. The layer is streamed as raw RGBA frames into ffmpeg."""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from PIL import Image

import graphics as g
from common import Timeline

POP = 0.38      # spring pop-in duration, s
MAX_W = 960     # widest a scene block may be (px)
FADE_OUT = 0.15


@dataclass
class Element:
    img: Image.Image | None
    x: int
    y: int
    start: float
    end: float
    anim: str = "pop"            # pop | fade | slide | wipe | grow | none
    anim_dur: float = POP
    sfx: str | None = None
    z: int = 0
    hold_to_end: bool = False    # no fade-out (last element of the video)
    dynamic: Callable[[float], Image.Image] | None = None   # re-rendered per frame (counters)
    dyn_dur: float = 0.0
    meta: dict = field(default_factory=dict)

    def size(self):
        im = self.img if self.img is not None else self.dynamic(1e9)
        return im.size


def spring(p: float) -> float:
    return 1 - math.exp(-5.5 * p) * math.cos(9.5 * p)


def ease_out(p: float) -> float:
    return 1 - (1 - p) ** 3


class Compositor:
    def __init__(self, W: int, H: int, fps: int):
        self.W, self.H, self.fps = W, H, fps
        self.els: list[Element] = []

    def add(self, el: Element):
        if el.end - el.start >= 0.12:
            self.els.append(el)

    # ------------------------------------------------------------------ per-frame
    def _state(self, el: Element, t: float):
        """Return (image, x, y, alpha) for element at time t, or None."""
        lt = t - el.start
        img = el.dynamic(lt) if el.dynamic else el.img
        x, y, alpha = el.x, el.y, 1.0
        if el.dynamic and "cx" in el.meta:
            x = round(el.meta["cx"] - img.width / 2)
        if el.anim in ("pop", "fade", "slide") and lt < el.anim_dur:
            p = max(lt / el.anim_dur, 0.0)
            alpha = min(1.0, p / 0.45)
            if el.anim == "pop":
                s = 0.55 + 0.45 * spring(p)
                w, h = max(1, round(img.width * s)), max(1, round(img.height * s))
                cx, cy = x + img.width / 2, y + img.height / 2
                img = img.resize((w, h), Image.BILINEAR)
                x, y = round(cx - w / 2), round(cy - h / 2)
            elif el.anim == "slide":
                y = round(y + 40 * (1 - ease_out(p)))
        elif el.anim == "wipe" and lt < el.anim_dur:
            w = max(1, round(img.width * ease_out(max(lt / el.anim_dur, 0))))
            img = img.crop((0, 0, w, img.height))
        elif el.anim == "grow" and lt < el.anim_dur:
            h = max(1, round(img.height * ease_out(max(lt / el.anim_dur, 0))))
            img = img.crop((0, img.height - h, img.width, img.height))
            y = y + (el.img.height - h)
        if not el.hold_to_end and el.end - t < FADE_OUT:
            alpha *= max(0.0, (el.end - t) / FADE_OUT)
        return img, x, y, alpha

    def _key(self, t: float, active: list[Element]):
        parts = []
        for el in active:
            lt = t - el.start
            animating = lt < max(el.anim_dur, el.dyn_dur) or (not el.hold_to_end and el.end - t < FADE_OUT)
            parts.append((id(el), round(t, 3) if animating else None))
        return tuple(parts)

    def frames(self, duration: float):
        """Yield raw RGBA bytes for every frame; static frames are reused."""
        n = int(round(duration * self.fps))
        els = sorted(self.els, key=lambda e: e.z)
        last_key, last_bytes = None, None
        blank = bytes(self.W * self.H * 4)
        for i in range(n):
            t = i / self.fps
            active = [e for e in els if e.start <= t < e.end]
            if not active:
                last_key = None
                yield blank
                continue
            key = self._key(t, active)
            if key == last_key:
                yield last_bytes
                continue
            canvas = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
            for el in active:
                img, x, y, alpha = self._state(el, t)
                if alpha <= 0.01:
                    continue
                if alpha < 0.999:
                    img = img.copy()
                    img.putalpha(img.split()[3].point(lambda v, a=alpha: int(v * a)))
                # clip to canvas
                sx, sy = max(0, -x), max(0, -y)
                if sx or sy:
                    img = img.crop((sx, sy, img.width, img.height))
                    x, y = x + sx, y + sy
                if x >= self.W or y >= self.H:
                    continue
                canvas.alpha_composite(img, (x, y))
            last_key, last_bytes = key, canvas.tobytes()
            yield last_bytes

    def sfx_events(self):
        return [(e.start, e.sfx) for e in self.els if e.sfx]


# ====================================================================== scenes
def _fmt_num(v: float, decimals: int = 0) -> str:
    s = f"{v:,.{decimals}f}".replace(",", " ").replace(" ", " ")
    return s


def build_scenes(comp: Compositor, plan: dict, style: dict, tl: Timeline, video_end: float) -> list[tuple[float, float]]:
    """Adds scene elements; returns split-layout intervals (output time)."""
    scenes = sorted(plan.get("scenes", []), key=lambda s: s["at"])
    splits = []
    sfx = style["sfx"]
    W = style["width"]
    for si, sc in enumerate(scenes):
        s0 = tl.map(sc["at"])
        if sc.get("until") is not None:
            s1 = tl.map(sc["until"])
        elif si + 1 < len(scenes):
            s1 = tl.map(scenes[si + 1]["at"])
        else:
            s1 = s0 + float(sc.get("dur", 4))
        s1 = min(s1, video_end)
        if s1 - s0 < 0.3:
            continue
        layout = sc.get("layout", "split")
        if layout == "split":
            splits.append((s0, s1))
            top, bottom = style["panel_area"]
        else:
            top, bottom = style["overlay_area"]

        # ---- build blocks: each block = list of (img, dx, dy, start, anim, sfx, extra)
        blocks = []
        for it in sc.get("items", []):
            typ = it.get("type", "pill")
            at = tl.map(it.get("at", sc["at"]))
            if at >= s1 - 0.15:
                continue
            at = max(at, s0)
            if typ == "strike":
                blocks.append({"strike": True, "at": at, "targets": it.get("targets")})
                continue
            parts = []   # (img, dx, dy, start, anim, sfx, dynamic)
            if typ == "title":
                parts.append((g.title(style, it["text"], it.get("size")), 0, 0, at, "pop", sfx.get("title"), None))
            elif typ == "text":
                parts.append((g.body_text(style, it["text"], it.get("size")), 0, 0, at, "slide", None, None))
            elif typ == "pill":
                parts.append((g.pill(style, it["text"], it.get("emoji"), it.get("variant", style.get("pill_variant", "dark"))),
                              0, 0, at, "pop", sfx.get("pill"), None))
            elif typ == "emoji":
                parts.append((g.emoji(it["emoji"], int(it.get("size", 150))), 0, 0, at, "pop", sfx.get("pill"), None))
            elif typ == "card":
                parts.append((g.doc_card(style, it.get("title", ""), it.get("text", ""), it.get("emoji"), int(it.get("lines", 3))),
                              0, 0, at, "pop", sfx.get("card"), None))
            elif typ == "row":
                # pills side by side, wrapped into centred lines that fit the screen width
                ims = []
                for sub in it.get("items", []):
                    sat = max(tl.map(sub["at"]), s0) if "at" in sub else at
                    im = g.pill(style, sub["text"], sub.get("emoji"), sub.get("variant", style.get("pill_variant", "dark")),
                                size=sub.get("size", style.get("pill_size", 46) - 4))
                    ims.append((im, sat))
                lines, cur, cw = [], [], 0
                for im, sat in ims:
                    if cur and cw + 18 + im.width > MAX_W:
                        lines.append((cur, cw))
                        cur, cw = [], 0
                    cw += (18 if cur else 0) + im.width
                    cur.append((im, sat))
                if cur:
                    lines.append((cur, cw))
                full_w = max(w for _, w in lines)
                yy = 0
                for ln, lw in lines:
                    x = (full_w - lw) // 2
                    lh = max(im.height for im, _ in ln)
                    for im, sat in ln:
                        parts.append((im, x, yy + (lh - im.height) // 2, sat, "pop", sfx.get("pill"), None))
                        x += im.width + 18
                    yy += lh + 16
            elif typ == "flow":
                x = 0
                for k, step in enumerate(it.get("steps", [])):
                    sat = max(tl.map(step["at"]), s0) if "at" in step else at + 0.5 * k
                    if k:
                        ar = g.arrow(style)
                        parts.append((ar, x, None, sat, "wipe", None, None))
                        x += ar.width + 16
                    im = g.body_text(style, step["text"], step.get("size", style.get("flow_size", 54)))
                    parts.append((im, x, None, sat, "pop", sfx.get("pill"), None))
                    x += im.width + 16
            elif typ == "bars":
                bars = it.get("bars", [])
                bw, gap, maxh = 210, 110, int(it.get("height", 380))
                x = 0
                for k, b in enumerate(bars):
                    sat = max(tl.map(b["at"]), s0) if "at" in b else at + 0.35 * k
                    col = b.get("color") or style["bar_colors"][k % len(style["bar_colors"])]
                    h = max(12, int(maxh * float(b.get("value", 0.5))))
                    lab = g.pill(style, b.get("label", ""), b.get("emoji"), "light", size=44)
                    cx = x + max(bw, lab.width) // 2
                    parts.append((g.bar_rect(style, bw, h, col), cx - bw // 2, maxh - h, sat, "grow", sfx.get("bar"), None))
                    parts.append((lab, cx - lab.width // 2, maxh + 16, sat, "pop", None, None))
                    x += max(bw, lab.width) + gap
            elif typ == "counter":
                v0, v1 = float(it.get("from", 0)), float(it["to"])
                pre, suf, dec = it.get("prefix", ""), it.get("suffix", ""), int(it.get("decimals", 0))
                size = it.get("size")
                dur = float(it.get("count_dur", 1.2))

                def dyn(lt, v0=v0, v1=v1, pre=pre, suf=suf, dec=dec, size=size, dur=dur):
                    p = ease_out(min(max(lt / dur, 0), 1))
                    return g.title(style, f"{pre}{_fmt_num(v0 + (v1 - v0) * p, dec)}{suf}", size)
                parts.append((None, 0, 0, at, "fade", sfx.get("counter"), (dyn, dur)))
            else:
                continue
            if parts:
                blocks.append({"parts": parts, "at": at})

        # ---- measure & stack
        def part_size(p):
            img, _, _, _, _, _, dynp = p
            return (dynp[0](1e9) if dynp else img).size

        laid = []
        for b in blocks:
            if b.get("strike"):
                continue
            ws = [p[1] + part_size(p)[0] for p in b["parts"]]
            hs = [(p[2] or 0) + part_size(p)[1] for p in b["parts"]]
            b["w"], b["h"] = max(ws), max(hs)
            b["fit"] = min(1.0, MAX_W / b["w"]) if b["w"] else 1.0   # shrink wide blocks to screen width
            laid.append(b)
        gap = style.get("scene_gap", 30)
        total = sum(b["h"] * b["fit"] for b in laid) + gap * max(0, len(laid) - 1)
        avail = bottom - top
        scale = min(1.0, avail / total) if total else 1.0
        y = top + (avail - total * scale) / 2 if style.get("scene_valign", "center") == "center" else top
        for b in laid:
            k = scale * b["fit"]
            bw, bh = b["w"] * k, b["h"] * k
            bx = (W - bw) / 2
            b["box"] = (bx, y, bw, bh)
            for img, dx, dy, st, anim, sf, dynp in b["parts"]:
                if dynp:
                    fn, dd = dynp
                    if k < 1:
                        def fn(lt, f=fn, k=k):
                            im = f(lt)
                            return im.resize((max(1, int(im.width * k)), max(1, int(im.height * k))), Image.LANCZOS)
                    w0, h0 = fn(1e9).size
                    comp.add(Element(None, int(W / 2 - w0 / 2), int(y + (bh - h0) / 2), st, s1, "fade", sfx=sf,
                                     z=10, dynamic=fn, dyn_dur=dd, hold_to_end=s1 >= video_end - 0.01,
                                     meta={"cx": W / 2}))
                    continue
                if k < 1:
                    img = img.resize((max(1, int(img.width * k)), max(1, int(img.height * k))), Image.LANCZOS)
                py = y + (dy * k if dy is not None else (bh - img.height) / 2)
                comp.add(Element(img, int(bx + dx * k), int(py), st, s1, anim,
                                 anim_dur=0.3 if anim == "wipe" else (0.8 if anim == "grow" else POP),
                                 sfx=sf, z=10, hold_to_end=s1 >= video_end - 0.01))
            y += bh + gap * scale

        # ---- strikes: line through earlier blocks
        for bi, b in enumerate(blocks):
            if not b.get("strike"):
                continue
            prev = [x for x in blocks[:bi] if "box" in x]
            if b.get("targets"):
                prev = [prev[i] for i in b["targets"] if i < len(prev)]
            for k, tb in enumerate(prev):
                bx, by, bw, bh = tb["box"]
                ln = g.line(style, int(bw + 40))
                comp.add(Element(ln, int(bx - 20), int(by + bh / 2 - 4), b["at"] + 0.07 * k, s1, "wipe",
                                 anim_dur=0.28, sfx=sfx.get("strike") if k == 0 else None, z=11,
                                 hold_to_end=s1 >= video_end - 0.01))

        if layout == "split":
            panel = Image.new("RGBA", (W, style["height"] - style["split_y"]), g._rgba(style["panel_bg"]))
            comp.add(Element(panel, 0, style["split_y"], s0, s1, "none", z=1,
                             sfx=sfx.get("scene") if sc.get("sfx", True) else None, hold_to_end=True))
    return splits


# ====================================================================== classic overlays
def build_overlays(comp: Compositor, plan: dict, style: dict, tl: Timeline, video_end: float):
    cta = plan.get("cta") or {}
    final_s = video_end - float(cta.get("final_seconds", 0) or 0) if cta.get("keyword") else video_end
    final_s = max(final_s, 0.0)
    sfx = style["sfx"] if plan.get("sfx", True) else {}

    def add(img_xy, start, end, kind, anim="pop", z=20):
        img, x, y = img_xy
        comp.add(Element(img, x, y, max(0.0, start), min(end, video_end), anim, sfx=sfx.get(kind), z=z,
                         hold_to_end=end >= video_end - 0.01))

    heads = sorted(plan.get("headers", []), key=lambda h: h["at"])
    hdr = g.serif_header if style.get("header_kind") == "serif" else g.header
    for i, h in enumerate(heads):
        s = tl.map(h["at"])
        e = s + float(h["dur"]) if h.get("dur") else (tl.map(heads[i + 1]["at"]) if i + 1 < len(heads) else final_s)
        add(hdr(style, h["text"]), s, min(e, final_s), "header", "slide")
    for c in plan.get("cards", []):
        s = tl.map(c["at"])
        add(g.card(style, c.get("title", ""), c.get("text", "")), s, min(s + float(c.get("dur", 2.5)), final_s), "card")
    for st in plan.get("stickers", []):
        s = tl.map(st["at"])
        im = g.emoji(st["emoji"], int(st.get("size", 140)))
        x = int(st.get("x", 0.78) * style["width"] - im.width / 2)
        y = int(st.get("y", 0.30) * style["height"] - im.height / 2)
        add((im, x, y), s, min(s + float(st.get("dur", 1.6)), video_end), "sticker", z=25)
    if cta.get("keyword"):
        if cta.get("bar_text"):
            add(g.cta_bar(style, cta["bar_text"]), float(cta.get("bar_from", 3.0)), final_s, "bar", "slide")
        if final_s < video_end:
            add(g.cta_final(style, cta.get("title", ""), cta["keyword"], cta.get("subtitle", "")),
                final_s, video_end, "cta", z=30)
