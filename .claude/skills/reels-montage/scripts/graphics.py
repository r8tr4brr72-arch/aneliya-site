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
