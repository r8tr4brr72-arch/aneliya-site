"""Build one 1080x1920 Instagram story from a JSON spec: background (video or photo),
brand veil, fading text lines, optional music. Used for the quiz series (анонс → вопрос → ответ → опрос).

Usage:  python story.py spec.json
See ../examples/*.json for every field.
"""
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H, FPS = 1080, 1920, 30
HERE = Path(__file__).resolve().parent
FONTS = HERE.parent.parent / "reels-montage" / "assets" / "fonts"
FONT_FILES = {
    "label": "Montserrat_500Medium.ttf",      # small caps line with letter spacing
    "title": "PlayfairDisplay_400Regular_Italic.ttf",
    "body": "NotoSerif_400Regular_Italic.ttf",
}

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def font(kind, size):
    return ImageFont.truetype(str(FONTS / FONT_FILES[kind]), size)


def wrap(text, f, maxw):
    out, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if f.getlength(t) <= maxw or not cur:
            cur = t
        else:
            out.append(cur)
            cur = w
    out.append(cur)
    return out


def draw_text(item, spec, path):
    """One transparent full-frame PNG per text item."""
    cream = rgb(spec.get("text_color", "#F0E4CD"))
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    kind = item.get("kind", "body")
    y = item["y"]
    if kind == "label":
        f = font("label", item.get("size", 30))
        col = (*cream, 175)
        track = item.get("track", 9)
        text = item["text"].upper()
        widths = [f.getlength(c) for c in text]
        x = (W - (sum(widths) + track * (len(text) - 1))) / 2
        for c, w in zip(text, widths):
            d.text((x, y), c, font=f, fill=col)
            x += w + track
        if item.get("line", True):
            d.line([(W / 2 - 60, y + 66), (W / 2 + 60, y + 66)], fill=col, width=2)
    else:
        f = font("title" if kind == "title" else "body", item.get("size", 112 if kind == "title" else 46))
        lines = item.get("lines") or wrap(item["text"], f, item.get("maxw", 860))
        lh = int(f.size * item.get("lh", 1.32))
        for line in lines:
            d.text(((W - f.getlength(line)) / 2, y), line, font=f, fill=cream)
            y += lh
    im.save(path)


def veil_layers(v, tmp):
    """mask.png (where to blur) and tint.png (wine overlay) for a top veil."""
    wine = rgb(v.get("color", "#2A0C10"))
    top, end, alpha = v.get("top_solid", 640), v.get("fade_end", 1060), v.get("alpha", 0.66)
    mask = Image.new("L", (W, H), 0)
    tint = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for y in range(H):
        a = 1.0 if y < top else max(0.0, 1 - (y - top) / (end - top))
        a = a * a * (3 - 2 * a)
        mask.paste(int(255 * a), (0, y, W, y + 1))
        tint.paste((*wine, int(255 * alpha * a)), (0, y, W, y + 1))
    mask.save(tmp / "mask.png")
    tint.save(tmp / "tint.png")


def photo_frame(bg, tmp):
    """Photo placed lower on the frame; the top band continues it, blurred (for text)."""
    src = Image.open(bg["image"]).convert("RGB")
    off = bg.get("photo_offset", 0)
    ph = src.resize((W, round(src.height * W / src.width)), Image.LANCZOS)
    cover = src.resize((max(W, round(src.width * H / src.height)), H), Image.LANCZOS)
    cover = cover.crop(((cover.width - W) // 2, 0, (cover.width - W) // 2 + W, H)).filter(ImageFilter.GaussianBlur(40))
    if off:
        m = Image.new("L", ph.size, 255)
        for y in range(260):
            m.paste(int(255 * (y / 260) ** 1.4), (0, y, W, y + 1))
        cover.paste(ph, (0, off), m)
    else:
        top = max(0, (ph.height - H) // 2)
        cover = ph.crop((0, top, W, top + H)) if ph.height >= H else cover
    out = tmp / "photo.png"
    cover.save(out)
    return out


def main():
    spec_path = Path(sys.argv[1]).resolve()
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    base = spec_path.parent
    rel = lambda p: str((base / p).resolve()) if p and not Path(p).is_absolute() else p
    dur = float(spec["duration"])
    out = rel(spec["out"])
    bg = spec["background"]
    veil = spec.get("veil", {"mode": "top"})
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        if "video" in bg:
            inputs = ["-i", rel(bg["video"])]
        else:
            img = photo_frame({**bg, "image": rel(bg["image"])}, tmp)
            if veil.get("mode") == "full":   # brand "Вариант А": whole frame blurred, colour and light halved
                im = Image.open(img).convert("RGB").filter(ImageFilter.GaussianBlur(22))
                im = ImageEnhance.Brightness(ImageEnhance.Color(im).enhance(0.5)).enhance(0.55).convert("RGBA")
                im.alpha_composite(Image.new("RGBA", (W, H), (*rgb(veil.get("color", "#2A0C10")), int(255 * veil.get("alpha", 0.45)))))
                im.convert("RGB").save(img)
            inputs = ["-loop", "1", "-framerate", str(FPS), "-t", str(dur), "-i", str(img)]
        n_in = 1
        fg = []
        z = float(bg.get("zoom", 0))
        if z:
            n = int(dur * FPS)
            fg.append(f"[0:v]scale=2160:3840,zoompan=z='1+{z}*on/{n}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}[src]")
        else:
            fg.append(f"[0:v]scale={W}:{H},fps={FPS}[src]")
        v = "[src]"
        if veil.get("mode", "top") == "top":
            veil_layers(veil, tmp)
            inputs += ["-loop", "1", "-i", str(tmp / "mask.png"), "-loop", "1", "-i", str(tmp / "tint.png")]
            fg += [f"{v}split[a][b]", "[b]gblur=sigma=26,eq=saturation=0.55[bl]", "[1:v]format=gray[m]",
                   "[bl][m]alphamerge[blm]", "[a][blm]overlay=0:0:shortest=1[v0]", "[2:v]format=rgba[t]",
                   "[v0][t]overlay=0:0:shortest=1[v1]"]
            v, n_in = "[v1]", 3
        for i, item in enumerate(spec["texts"]):
            p = tmp / f"t{i}.png"
            draw_text(item, spec, p)
            inputs += ["-loop", "1", "-i", str(p)]
            fg.append(f"[{n_in}:v]format=rgba,fade=t=in:st={item.get('at', 0.5)}:d=0.7:alpha=1[x{i}]")
            fg.append(f"{v}[x{i}]overlay=0:0:shortest=1[w{i}]")
            v, n_in = f"[w{i}]", n_in + 1
        fg.append(f"{v}format=yuv420p[vout]")
        audio = []
        music = spec.get("music")
        if music == "generate":
            raw = tmp / "music.wav"
            subprocess.run([sys.executable, str(HERE / "music.py"), str(dur + 1), str(raw), str(spec.get("music_seed", 1))], check=True)
            music = str(raw)
        elif music:
            music = rel(music)
        if music:
            inputs += ["-i", music]
            fg.append(f"[{n_in}:a]aecho=0.8:0.7:120|260:0.35|0.2,loudnorm=I=-16,atrim=duration={dur},"
                      f"afade=t=in:d=0.6,afade=t=out:st={dur - 1.2}:d=1.2[aout]")
            audio = ["-map", "[aout]", "-c:a", "aac", "-b:a", "192k"]
        else:
            audio = ["-an"]
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", *inputs, "-filter_complex", ";".join(fg), "-map", "[vout]",
                        *audio, "-t", str(dur), "-r", str(FPS), "-c:v", "libx264", "-crf", "18", "-preset", "slow",
                        "-movflags", "+faststart", out], check=True)
    print("ГОТОВО:", out)


if __name__ == "__main__":
    main()
