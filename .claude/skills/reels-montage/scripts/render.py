"""Step 3: render the finished Reel from plan.json.

Usage:  python render.py VIDEO [--draft] [--out PATH]

--draft  fast low-quality encode for checking the edit (same layout & timing).
Output: <video name>_REELS.mp4 (or _DRAFT.mp4) next to the source video.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
from pathlib import Path

import graphics
from common import (FONTS_DIR, SFX_DIR, Timeline, ass_color, die, fmt_ts, load_json, load_style,
                    need, probe, run, workdir_for)


# ---------------------------------------------------------------- plan checks
def validate(plan: dict, info: dict, fps: int) -> list[dict]:
    keep = sorted(plan.get("keep", []), key=lambda k: k["start"])
    if not keep:
        die("в plan.json пустой список keep")
    out, last_end = [], 0.0
    for k in keep:
        s = round(max(float(k["start"]), 0.0) * fps) / fps
        e = round(min(float(k["end"]), info["duration"]) * fps) / fps
        s = max(s, last_end)
        if e - s < 2 / fps:
            continue
        out.append({**k, "start": s, "end": e})
        last_end = e
    return out


# ---------------------------------------------------------------- 1. segments
def ffmpeg_filter_flag() -> str:
    """ffmpeg ≥7.1 replaced -filter_complex_script with -/filter_complex."""
    h = subprocess.run(["ffmpeg", "-hide_banner", "-h", "full"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace").stdout
    return "-filter_complex_script" if "filter_complex_script" in h else "-/filter_complex"


def render_segments(video: Path, keep: list[dict], style: dict, wd: Path, draft: bool, has_audio: bool) -> Path:
    W, H, fps = style["width"], style["height"], style["fps"]
    segdir = wd / "segments"
    segdir.mkdir(exist_ok=True)
    files = []
    mtime = int(video.stat().st_mtime)
    for i, k in enumerate(keep):
        d = k["end"] - k["start"]
        z = style["zoom_punch"] if k.get("zoom") else 1.0
        key = f"{video.name}|{mtime}|{k['start']:.3f}|{k['end']:.3f}|{z}|{k.get('bw')}|{draft}|{W}x{H}@{fps}"
        name = f"seg_{hashlib.md5(key.encode()).hexdigest()[:12]}.mkv"
        files.append(name)
        if (segdir / name).exists():
            continue
        zw, zh = int(W * z) // 2 * 2, int(H * z) // 2 * 2
        anchor = style["zoom_anchor_y"] if z > 1 else 0.5
        vf = (f"scale={zw}:{zh}:force_original_aspect_ratio=increase,"
              f"crop={W}:{H}:(iw-{W})/2:(ih-{H})*{anchor},fps={fps},setsar=1")
        if k.get("bw"):
            vf += ",hue=s=0"
        vf += f",tpad=stop_mode=clone:stop_duration=0.5,trim=duration={d:.4f},setpts=PTS-STARTPTS"
        af = (f"aresample=48000,apad,atrim=duration={d:.4f},asetpts=PTS-STARTPTS,"
              f"afade=t=in:d=0.012,afade=t=out:st={max(d - 0.02, 0):.4f}:d=0.02")
        cmd = ["ffmpeg", "-y", "-ss", f"{k['start']:.4f}", "-t", f"{d + 0.3:.4f}", "-i", video]
        if not has_audio:
            cmd += ["-f", "lavfi", "-t", f"{d + 0.3:.4f}", "-i", "anullsrc=r=48000:cl=stereo"]
        cmd += ["-map", "0:v:0", "-map", "0:a:0" if has_audio else "1:a:0", "-vf", vf, "-af", af,
                "-c:v", "libx264", "-preset", "ultrafast" if draft else "veryfast",
                "-crf", "26" if draft else "15", "-pix_fmt", "yuv420p", "-g", str(fps),
                "-c:a", "pcm_s16le", "-ac", "2", segdir / name]
        run(cmd)
        print(f"  кусок {i + 1}/{len(keep)}  {fmt_ts(k['start'])}–{fmt_ts(k['end'])}")
    lst = wd / "concat.txt"
    lst.write_text("".join(f"file 'segments/{n}'\n" for n in files), encoding="utf-8")
    body = wd / "body.mkv"
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst.name, "-c", "copy", body.name], cwd=wd)
    used = set(files)
    for old in segdir.glob("seg_*.mkv"):   # drop stale cache from earlier plans
        if old.name not in used:
            old.unlink()
    return body


# ---------------------------------------------------------------- 2. subtitles
def _norm(w: str) -> str:
    return re.sub(r"[^\w-]", "", w.lower())


def _ass_time(t: float) -> str:
    cs = int(round(max(t, 0) * 100))
    h, cs = divmod(cs, 360000)
    m, cs = divmod(cs, 6000)
    s, cs = divmod(cs, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _esc(t: str) -> str:
    return t.replace("\\", "/").replace("{", "(").replace("}", ")")


def build_ass(words: list[dict], tl: Timeline, plan: dict, style: dict, path: Path, sub_end: float) -> int:
    replace = {_norm(a): b for a, b in (plan.get("replace") or {}).items()}
    highlights = [_norm(h) for h in plan.get("highlight", []) if _norm(h)]
    ws = []
    for w in words:
        mid = (w["s"] + w["e"]) / 2
        if not tl.contains(mid):
            continue
        text = replace.get(_norm(w["w"]), w["w"])
        if not text:
            continue
        s, e = tl.map(w["s"]), tl.map(w["e"])
        if s >= sub_end:
            continue
        ws.append({"w": text, "s": s, "e": max(e, s + 0.08), "key": any(_norm(text).startswith(h) for h in highlights)})

    chunks, cur = [], []
    for w in ws:
        chars = sum(len(x["w"]) + 1 for x in cur) + len(w["w"])
        if cur and (len(cur) >= style["sub_max_words"] or chars > style["sub_max_chars"]
                    or w["s"] - cur[-1]["e"] > 0.35 or cur[-1]["w"].endswith((".", "?", "!", ","))):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)

    acc, white = ass_color(style["accent"]), ass_color(style["text"])
    caps = style.get("sub_caps")
    x, y = style["width"] // 2, style["sub_y"]
    events = []
    for ci, ch in enumerate(chunks):
        start = ch[0]["s"]
        nxt = chunks[ci + 1][0]["s"] if ci + 1 < len(chunks) else None
        end = ch[-1]["e"]
        if nxt is not None and nxt - end < 0.4:
            end = nxt
        end = min(max(end, start + 0.35), sub_end)
        if nxt is not None:
            end = min(end, nxt)
        for wi, w in enumerate(ch):
            ws_ = start if wi == 0 else w["s"]
            we = end if wi == len(ch) - 1 else ch[wi + 1]["s"]
            if we - ws_ < 0.01:
                continue
            parts = []
            for j, o in enumerate(ch):
                t = _esc(o["w"].upper() if (caps or o["key"]) else o["w"])
                col = acc if (j == wi or o["key"]) else white
                parts.append(f"{{\\c{col}}}{t}")
            anim = "\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)" if wi == 0 else ""
            events.append(f"Dialogue: 0,{_ass_time(ws_)},{_ass_time(we)},Sub,,0,0,0,,"
                          f"{{\\pos({x},{y}){anim}}}" + " ".join(parts))

    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style['width']}
PlayResY: {style['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{style['ass_font']},{style['sub_size']},{white},{white},{ass_color(style['outline'])},{ass_color('#000000', 0x80)},0,0,0,0,100,100,0,0,1,{style['sub_outline']},{style['sub_shadow']},5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return len(chunks)


# ---------------------------------------------------------------- 3. overlays
def build_overlays(plan: dict, style: dict, tl: Timeline, wd: Path) -> list[dict]:
    odir = wd / "overlays"
    if odir.exists():
        shutil.rmtree(odir)
    odir.mkdir()
    dur = tl.duration
    cta = plan.get("cta") or {}
    final_s = dur - float(cta.get("final_seconds", 0) or 0) if cta.get("keyword") else dur
    final_s = max(final_s, 0.0)
    ovs = []

    def add(kind, img_xy, start, end, sfx_kind=None):
        start, end = max(0.0, start), min(end, dur)
        if end - start < 0.2:
            return
        img, x, y = img_xy
        p = odir / f"{len(ovs):02d}_{kind}.png"
        img.save(p)
        ovs.append({"png": p, "x": x, "y": y, "start": start, "end": end,
                    "sfx": style["sfx"].get(sfx_kind or kind) if plan.get("sfx", True) else None})

    heads = sorted(plan.get("headers", []), key=lambda h: h["at"])
    for i, h in enumerate(heads):
        s = tl.map(h["at"])
        e = s + float(h["dur"]) if h.get("dur") else (tl.map(heads[i + 1]["at"]) if i + 1 < len(heads) else final_s)
        add("header", graphics.header(style, h["text"]), s, min(e, final_s))

    for c in plan.get("cards", []):
        s = tl.map(c["at"])
        add("card", graphics.card(style, c.get("title", ""), c.get("text", "")), s,
            min(s + float(c.get("dur", 2.5)), final_s))

    if cta.get("keyword"):
        if cta.get("bar_text"):
            add("bar", graphics.cta_bar(style, cta["bar_text"]), float(cta.get("bar_from", 3.0)), final_s)
        if final_s < dur:
            add("cta", graphics.cta_final(style, cta.get("title", ""), cta["keyword"], cta.get("subtitle", "")),
                final_s, dur)
    return ovs


# ---------------------------------------------------------------- 4. final mix
def final_pass(body: Path, ovs: list[dict], plan: dict, style: dict, dur: float, wd: Path, out: Path, draft: bool):
    fps = style["fps"]
    inputs = ["-i", body.name]
    n_in = 1
    fg = []
    v = "[0:v]"
    for i, o in enumerate(ovs):
        idx, n_in = n_in, n_in + 1
        L = o["end"] - o["start"]
        inputs += ["-loop", "1", "-framerate", str(fps), "-t", f"{L + 0.1:.3f}",
                   "-i", str(o["png"].relative_to(wd)).replace("\\", "/")]
        fade_out = f",fade=t=out:st={max(L - 0.15, 0):.3f}:d=0.15:alpha=1" if o["end"] < dur - 0.05 else ""
        fg.append(f"[{idx}:v]format=rgba,fade=t=in:st=0:d=0.18:alpha=1{fade_out},"
                  f"setpts=PTS-STARTPTS+{o['start']:.3f}/TB[o{i}]")
        s = o["start"]
        fg.append(f"{v}[o{i}]overlay=x={o['x']}:y='{o['y']}+36*max(0,1-(t-{s:.3f})/0.18)':"
                  f"eval=frame:enable='between(t,{s:.3f},{o['end']:.3f})'[v{i}]")
        v = f"[v{i}]"
    fg.append(f"{v}ass=subs.ass:fontsdir=fonts,format=yuv420p[vout]")

    # audio: voice + sfx + optional ducked music
    fg.append("[0:a]asplit=2[voice][sc]")
    mix = ["[voice]"]
    for i, o in enumerate(ovs):
        if not o["sfx"] or not (SFX_DIR / o["sfx"]).exists():
            continue
        idx, n_in = n_in, n_in + 1
        inputs += ["-i", str(SFX_DIR / o["sfx"])]
        ms = int(o["start"] * 1000)
        fg.append(f"[{idx}:a]aresample=48000,volume={style['sfx_volume']},adelay={ms}:all=1[s{i}]")
        mix.append(f"[s{i}]")
    music = plan.get("music")
    if music:
        mp = Path(music)
        if not mp.is_absolute():
            mp = Path(plan["video"]).parent / mp
        if not mp.exists():
            die(f"музыка не найдена: {mp}")
        idx, n_in = n_in, n_in + 1
        inputs += ["-stream_loop", "-1", "-i", str(mp)]
        fg.append(f"[{idx}:a]aresample=48000,volume={style['music_volume']},atrim=duration={dur:.3f}[mus]")
        fg.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[duck]")
        mix.append("[duck]")
    else:
        fg.append("[sc]anullsink")
    fg.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
              f"loudnorm=I={style['loudness_lufs']}:TP=-1.5:LRA=11,aresample=48000,"
              f"afade=t=out:st={max(dur - 0.3, 0):.3f}:d=0.3[aout]")

    script = wd / "filter.txt"
    script.write_text(";\n".join(fg), encoding="utf-8")
    cmd = ["ffmpeg", "-y", *inputs, ffmpeg_filter_flag(), script.name, "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "ultrafast" if draft else "medium", "-crf", "28" if draft else "19",
           "-profile:v", "high", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", "-t", f"{dur:.3f}", str(out)]
    run(cmd, cwd=wd)


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--draft", action="store_true", help="быстрый черновой рендер")
    ap.add_argument("--out")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    need("ffmpeg")
    wd = workdir_for(video)
    for f in ("plan.json", "words.json"):
        if not (wd / f).exists():
            die(f"нет {f} в {wd}")
    plan = load_json(wd / "plan.json")
    plan.setdefault("video", str(video))
    style = load_style(plan.get("style"))
    info = probe(video)
    keep = validate(plan, info, style["fps"])
    tl = Timeline(keep)
    print(f"Монтаж: {len(keep)} кусков → {tl.duration:.1f} c")

    fonts = wd / "fonts"
    fonts.mkdir(exist_ok=True)
    for f in FONTS_DIR.glob("*.otf"):
        shutil.copy2(f, fonts / f.name)

    body = render_segments(video, keep, style, wd, args.draft, info["has_audio"])
    cta = plan.get("cta") or {}
    sub_end = tl.duration - (float(cta.get("final_seconds", 0) or 0) if cta.get("keyword") and cta.get("hide_subs_on_final") else 0)
    n = build_ass(load_json(wd / "words.json")["words"], tl, plan, style, wd / "subs.ass", sub_end)
    ovs = build_overlays(plan, style, tl, wd)
    print(f"Субтитры: {n} фраз, графика: {len(ovs)} элементов. Финальная сборка…")

    out = Path(args.out) if args.out else video.parent / f"{video.stem}_{'DRAFT' if args.draft else 'REELS'}.mp4"
    final_pass(body, ovs, plan, style, tl.duration, wd, out.resolve(), args.draft)
    print(f"\nГОТОВО: {out}  ({tl.duration:.1f} c)")


if __name__ == "__main__":
    main()
