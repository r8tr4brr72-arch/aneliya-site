"""PNG overlays (headers, cards, CTA funnel) drawn with Pillow."""
from __future__ import annotations

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from common import FONTS_DIR, hex_rgb

_cache: dict = {}


def font(style: dict, kind: str, size: int) -> ImageFont.FreeTypeFont:
    key = (style[f"font_{kind}"], size)
    if key not in _cache:
        _cache[key] = ImageFont.truetype(str(FONTS_DIR / style[f"font_{kind}"]), size)
    return _cache[key]


def wrap(text: str, f: ImageFont.FreeTypeFont, max_w: int) -> list[str]:
    lines: list[str] = []
    for para in str(text).split("\n"):
        cur = ""
        for word in para.split():
            test = f"{cur} {word}".strip()
            if f.getlength(test) <= max_w or not cur:
                cur = test
            else:
                lines.append(cur)
                cur = word
        lines.append(cur)
    return [line for line in lines if line] or [""]


def _text_block(lines, f, spacing):
    asc, desc = f.getmetrics()
    lh = asc + desc
    w = max(int(f.getlength(line)) for line in lines)
    h = lh * len(lines) + spacing * (len(lines) - 1)
    return w, h, lh


def _shadowed(card: Image.Image, radius: int = 22, offset: int = 10, alpha: int = 90) -> Image.Image:
    pad = radius * 2
    out = Image.new("RGBA", (card.width + pad * 2, card.height + pad * 2), (0, 0, 0, 0))
    mask = card.split()[3].point(lambda a: alpha if a > 0 else 0)
    shadow = Image.new("RGBA", card.size, (0, 0, 0, 255))
    shadow.putalpha(mask)
    out.alpha_composite(shadow, (pad, pad + offset))
    out = out.filter(ImageFilter.GaussianBlur(radius))
    out.alpha_composite(card, (pad, pad))
    return out


def header(style: dict, text: str):
    """Accent pill with white bold text. Returns (image, x, y)."""
    f = font(style, "bold", style["header_size"])
    lines = wrap(text, f, 900)
    tw, th, lh = _text_block(lines, f, 6)
    px, py = 38, 22
    img = Image.new("RGBA", (tw + px * 2, th + py * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=28, fill=hex_rgb(style["accent"]))
    y = py
    for line in lines:
        d.text(((img.width - f.getlength(line)) / 2, y), line, font=f, fill=hex_rgb(style["text"]))
        y += lh + 6
    img = _shadowed(img)
    return img, (style["width"] - img.width) // 2, style["header_y"] - 44


def card(style: dict, title: str, text: str = ""):
    """White rounded card: accent title + dark body text."""
    W = 900
    ft = font(style, "heavy", 64)
    fb = font(style, "regular", 46)
    tl = wrap(title, ft, W - 100)
    bl = wrap(text, fb, W - 100) if text else []
    _, th, tlh = _text_block(tl, ft, 4)
    bh = _text_block(bl, fb, 8)[1] if bl else 0
    H = 60 + th + (28 + bh if bl else 0) + 60
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=40, fill=hex_rgb(style["card_bg"]))
    d.rounded_rectangle([0, 0, 14, H - 1], radius=7, fill=hex_rgb(style["accent"]))
    y = 60
    for line in tl:
        d.text((60, y), line, font=ft, fill=hex_rgb(style["accent"]))
        y += tlh + 4
    if bl:
        y += 24
        a, de = fb.getmetrics()
        for line in bl:
            d.text((60, y), line, font=fb, fill=hex_rgb(style["card_text"]))
            y += a + de + 8
    img = _shadowed(img)
    return img, (style["width"] - img.width) // 2, style["card_y"] - 44


def cta_bar(style: dict, text: str):
    """Persistent bottom funnel bar (dark translucent pill, keyword in accent)."""
    f = font(style, "bold", 40)
    lines = wrap(text, f, 860)
    tw, th, lh = _text_block(lines, f, 4)
    px, py = 36, 20
    img = Image.new("RGBA", (tw + px * 2, th + py * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, img.width - 1, img.height - 1], radius=img.height // 2 if len(lines) == 1 else 30,
                        fill=(15, 15, 15, 205), outline=hex_rgb(style["accent"]), width=4)
    y = py
    for line in lines:
        d.text(((img.width - f.getlength(line)) / 2, y), line, font=f, fill=hex_rgb(style["text"]))
        y += lh + 4
    return img, (style["width"] - img.width) // 2, style["cta_bar_y"]


def cta_final(style: dict, title: str, keyword: str, subtitle: str):
    """Big final call-to-action card with the keyword badge."""
    W = 920
    ft = font(style, "bold", 60)
    fk = font(style, "heavy", 150)
    fs = font(style, "regular", 44)
    tl = wrap(title, ft, W - 100)
    sl = wrap(subtitle, fs, W - 100) if subtitle else []
    _, th, tlh = _text_block(tl, ft, 4)
    kw_w = int(fk.getlength(keyword))
    ka, kd = fk.getmetrics()
    badge_w, badge_h = min(kw_w + 110, W - 60), ka + kd + 40
    sh = _text_block(sl, fs, 8)[1] if sl else 0
    H = 60 + th + 36 + badge_h + (36 + sh if sl else 0) + 64
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=44, fill=hex_rgb(style["card_bg"]))
    y = 60
    for line in tl:
        d.text(((W - ft.getlength(line)) / 2, y), line, font=ft, fill=hex_rgb(style["card_text"]))
        y += tlh + 4
    y += 32
    bx = (W - badge_w) // 2
    d.rounded_rectangle([bx, y, bx + badge_w, y + badge_h], radius=34, fill=hex_rgb(style["accent"]))
    d.text(((W - kw_w) / 2, y + 14), keyword, font=fk, fill=hex_rgb(style["text"]))
    y += badge_h + 36
    a, de = fs.getmetrics()
    for line in sl:
        d.text(((W - fs.getlength(line)) / 2, y), line, font=fs, fill=hex_rgb(style["card_text"]))
        y += a + de + 8
    img = _shadowed(img)
    return img, (style["width"] - img.width) // 2, style["card_y"] - 44


# ================================================================ scene primitives
# Used by compositor.py for plan["scenes"]. All return bare RGBA images; layout is done there.

EMOJI_FONT = FONTS_DIR / "NotoColorEmoji.ttf"


def _rgba(h: str, a: int = 255):
    return (*hex_rgb(h), a)


def emoji(ch: str, size: int) -> Image.Image:
    """Colour emoji rendered from Noto Color Emoji (bitmap font, native size 109)."""
    ch = ch.replace("️", "")
    key = ("emoji", ch, size)
    if key in _cache:
        return _cache[key].copy()
    f = ImageFont.truetype(str(EMOJI_FONT), 109)
    im = Image.new("RGBA", (360, 160), (0, 0, 0, 0))
    ImageDraw.Draw(im).text((10, 10), ch, font=f, embedded_color=True)
    bb = im.getbbox()
    if not bb:
        return Image.new("RGBA", (size, size), (0, 0, 0, 0))
    im = im.crop(bb)
    im = im.resize((max(1, round(im.width * size / im.height)), size), Image.LANCZOS)
    _cache[key] = im
    return im.copy()


def _text_img(text: str, f: ImageFont.FreeTypeFont, color, max_w: int | None = None, spacing: int = 6,
              align: str = "center") -> Image.Image:
    lines = wrap(text, f, max_w) if max_w else str(text).split("\n")
    asc, desc = f.getmetrics()
    lh = asc + desc
    w = max(1, max(int(f.getlength(line)) for line in lines))
    h = lh * len(lines) + spacing * (len(lines) - 1)
    pad = 8  # italic overhang
    im = Image.new("RGBA", (w + pad * 2, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for i, line in enumerate(lines):
        lw = f.getlength(line)
        x = pad + ((w - lw) / 2 if align == "center" else 0)
        d.text((x, i * (lh + spacing)), line, font=f, fill=color)
    return im


def title(style: dict, text: str, size: int | None = None, color: str | None = None) -> Image.Image:
    f = font(style, "title", size or style.get("title_size", 104))
    return _text_img(text, f, _rgba(color or style["ink"]), max_w=940)


def body_text(style: dict, text: str, size: int | None = None, color: str | None = None) -> Image.Image:
    f = font(style, "body", size or style.get("body_size", 54))
    return _text_img(text, f, _rgba(color or style["ink"]), max_w=940)


def pill(style: dict, text: str, emo: str | None = None, variant: str = "dark", size: int | None = None) -> Image.Image:
    """dark: emoji outside on the left + filled pill.  light: white rounded badge, emoji inside."""
    fs = size or style.get("pill_size", 46)
    f = font(style, "pill", fs)
    a, de = f.getmetrics()
    th = a + de
    tw = int(f.getlength(text)) + 8
    ph = th + 30
    em = emoji(emo, int(fs * 1.15)) if emo else None
    if variant == "light":
        inner = (em.width + 18 if em else 0) + tw
        badge = Image.new("RGBA", (inner + 64, ph + 12), (0, 0, 0, 0))
        d = ImageDraw.Draw(badge)
        d.rounded_rectangle([0, 0, badge.width - 1, badge.height - 1], radius=int(ph * 0.42),
                            fill=_rgba(style.get("card_bg", "#FFFFFF")))
        x = 32
        if em:
            badge.alpha_composite(em, (x, (badge.height - em.height) // 2))
            x += em.width + 18
        d.text((x, (badge.height - th) // 2), text, font=f, fill=_rgba(style["ink"]))
        return _shadowed(badge, radius=14, offset=6, alpha=45)
    body = Image.new("RGBA", (tw + 56, ph), (0, 0, 0, 0))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle([0, 0, body.width - 1, ph - 1], radius=ph // 2, fill=_rgba(style["pill_bg"]))
    d.text((28, (ph - th) // 2 - 2), text, font=f, fill=_rgba(style["pill_text"]))
    if not em:
        return body
    out = Image.new("RGBA", (em.width + 16 + body.width, max(em.height, ph)), (0, 0, 0, 0))
    out.alpha_composite(em, (0, (out.height - em.height) // 2))
    out.alpha_composite(body, (em.width + 16, (out.height - ph) // 2))
    return out


def doc_card(style: dict, heading: str, sub: str = "", emo: str | None = None, lines: int = 3) -> Image.Image:
    """White 'document / app' mockup card: emoji + heading, subheading, grey placeholder lines."""
    W = 820
    fh = font(style, "title", 52)
    fs = font(style, "body", 40)
    em = emoji(emo, 64) if emo else None
    hx = 48 + (em.width + 20 if em else 0)
    hl = wrap(heading, fh, W - hx - 48)
    a, de = fh.getmetrics()
    sa, sd = fs.getmetrics()
    H = 44 + len(hl) * (a + de) + (14 + sa + sd if sub else 0) + 30 + lines * 40 + 30
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=36, fill=_rgba(style.get("card_bg", "#FFFFFF")))
    y = 44
    if em:
        img.alpha_composite(em, (48, y))
    for line in hl:
        d.text((hx, y), line, font=fh, fill=_rgba(style["ink"]))
        y += a + de
    if sub:
        y += 14
        d.text((hx, y), sub, font=fs, fill=_rgba(style.get("muted", "#8A817A")))
        y += sa + sd
    y += 30
    grey = _rgba(style.get("placeholder", "#E7E1DA"))
    for i in range(lines):
        w = int((W - 96) * (1.0, 0.82, 0.6, 0.9)[i % 4])
        d.rounded_rectangle([48, y, 48 + w, y + 18], radius=9, fill=grey)
        y += 40
    return _shadowed(img, radius=18, offset=8, alpha=50)


def arrow(style: dict, length: int = 70, color: str | None = None) -> Image.Image:
    c = _rgba(color or style["ink"])
    im = Image.new("RGBA", (length + 8, 40), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.line([(4, 20), (length - 6, 20)], fill=c, width=5)
    d.polygon([(length + 4, 20), (length - 14, 8), (length - 14, 32)], fill=c)
    return im


def bar_rect(style: dict, w: int, h: int, color: str) -> Image.Image:
    im = Image.new("RGBA", (w, max(h, 2)), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, max(h, 2) - 1], radius=min(22, w // 4), fill=_rgba(color))
    return im


def line(style: dict, w: int, thickness: int = 8, color: str | None = None) -> Image.Image:
    im = Image.new("RGBA", (w, thickness), (0, 0, 0, 0))
    ImageDraw.Draw(im).rounded_rectangle([0, 0, w - 1, thickness - 1], radius=thickness // 2,
                                         fill=_rgba(color or style["strike"]))
    return im


def serif_header(style: dict, text: str):
    """Hook/header variant: big serif text with soft shadow, straight on the video."""
    f = font(style, "title", style.get("header_size", 64))
    im = _text_img(text, f, _rgba(style.get("header_text", "#FFFFFF")), max_w=920)
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(im.split()[3].point(lambda v: int(v * 0.55)))
    out = Image.new("RGBA", (im.width + 40, im.height + 40), (0, 0, 0, 0))
    out.alpha_composite(sh, (20, 24))
    out = out.filter(ImageFilter.GaussianBlur(8))
    out.alpha_composite(im, (20, 20))
    return out, (style["width"] - out.width) // 2, style["header_y"] - 40


# ================================================================ minimal brand variants
# Quiet, editorial look: spaced caps labels, thin rules, serif italic, translucent brand panels.

def _spaced(d, cx, y, text, f, fill, track):
    widths = [f.getlength(c) for c in text]
    x = cx - (sum(widths) + track * (len(text) - 1)) / 2
    for c, w in zip(text, widths):
        d.text((x, y), c, font=f, fill=fill)
        x += w + track


def _soft_shadow(im: Image.Image, blur: int = 10, alpha: float = 0.55) -> Image.Image:
    sh = Image.new("RGBA", im.size, (0, 0, 0, 0))
    sh.putalpha(im.split()[3].point(lambda v: int(v * alpha)))
    pad = blur * 3
    out = Image.new("RGBA", (im.width + pad * 2, im.height + pad * 2), (0, 0, 0, 0))
    out.alpha_composite(sh, (pad, pad + 3))
    out = out.filter(ImageFilter.GaussianBlur(blur))
    out.alpha_composite(im, (pad, pad))
    return out


def header_caps(style: dict, text: str):
    """Small spaced capitals + thin rule, cream, on the video (no plate)."""
    f = font(style, "label", style.get("header_size", 30))
    cream = _rgba(style["text"], 235)
    t = text.upper()
    w = int(sum(f.getlength(c) for c in t) + 9 * (len(t) - 1)) + 40
    im = Image.new("RGBA", (min(w, 1000), 90), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    _spaced(d, im.width / 2, 8, t, f, cream, 9)
    d.line([(im.width / 2 - 50, 66), (im.width / 2 + 50, 66)], fill=cream, width=2)
    im = _soft_shadow(im)
    return im, (style["width"] - im.width) // 2, style["header_y"] - 30


def card_min(style: dict, title: str, text: str = ""):
    """Translucent brand-colour panel, cream serif text, no shadow."""
    W = 880
    ft = font(style, "title", 60)
    fb = font(style, "body", 42)
    tl = wrap(title, ft, W - 120)
    bl = wrap(text, fb, W - 120) if text else []
    a, de = ft.getmetrics()
    ba, bd = fb.getmetrics()
    H = 56 + len(tl) * (a + de) + (24 + len(bl) * (ba + bd + 6) if bl else 0) + 56
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=22, fill=_rgba(style["accent"], 215))
    y = 56
    for line in tl:
        d.text(((W - ft.getlength(line)) / 2, y), line, font=ft, fill=_rgba(style["text"]))
        y += a + de
    if bl:
        y += 24
        d.line([(W / 2 - 40, y - 12), (W / 2 + 40, y - 12)], fill=_rgba(style["text"], 160), width=2)
        for line in bl:
            d.text(((W - fb.getlength(line)) / 2, y), line, font=fb, fill=_rgba(style["text"], 235))
            y += ba + bd + 6
    return im, (style["width"] - W) // 2, style["card_y"]


def cta_bar_min(style: dict, text: str):
    """One line of spaced caps near the bottom, cream with a soft shadow — no pill."""
    f = font(style, "label", 26)
    t = text.upper()
    w = int(sum(f.getlength(c) for c in t) + 6 * (len(t) - 1)) + 40
    im = Image.new("RGBA", (min(w, 1040), 60), (0, 0, 0, 0))
    _spaced(ImageDraw.Draw(im), im.width / 2, 12, t, f, _rgba(style["text"], 230), 6)
    im = _soft_shadow(im, blur=8, alpha=0.7)
    return im, (style["width"] - im.width) // 2, style["cta_bar_y"]


def cta_final_min(style: dict, title: str, keyword: str, subtitle: str):
    """Quiet closing card: caps label, keyword in serif italic, thin rules, translucent brand panel."""
    W = 860
    fl = font(style, "label", 28)
    fk = font(style, "title", 132)
    fs = font(style, "body", 40)
    ka, kd = fk.getmetrics()
    sl = wrap(subtitle, fs, W - 120) if subtitle else []
    H = 70 + 40 + 30 + ka + kd + 30 + len(sl) * 56 + 70
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, W - 1, H - 1], radius=26, fill=_rgba(style["accent"], 225))
    cream = _rgba(style["text"])
    y = 70
    _spaced(d, W / 2, y, title.upper(), fl, _rgba(style["text"], 200), 9)
    y += 40 + 30
    d.text(((W - fk.getlength(keyword)) / 2, y), keyword, font=fk, fill=cream)
    y += ka + kd + 10
    d.line([(W / 2 - 60, y), (W / 2 + 60, y)], fill=_rgba(style["text"], 170), width=2)
    y += 26
    for line in sl:
        d.text(((W - fs.getlength(line)) / 2, y), line, font=fs, fill=_rgba(style["text"], 235))
        y += 56
    return im, (style["width"] - W) // 2, style.get("cta_y", style["card_y"])
