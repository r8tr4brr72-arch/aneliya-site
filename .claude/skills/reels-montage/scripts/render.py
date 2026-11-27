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
import wave
from pathlib import Path

import numpy as np

from common import (FONTS_DIR, SFX_DIR, Timeline, ass_color, die, fmt_ts, load_json, load_style,
                    need, probe, run, workdir_for)
from compositor import Compositor, build_overlays, build_scenes


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


def build_ass(words: list[dict], tl: Timeline, plan: dict, style: dict, path: Path, sub_end: float,
              splits: list[tuple[float, float]]) -> int:
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

    def in_split(t):
        return any(a <= t < b for a, b in splits)

    acc = ass_color(style["accent"])
    caps = style.get("sub_caps")
    karaoke = style.get("sub_active_highlight", True)
    x = style["width"] // 2
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
        split = in_split(start + 0.01)
        sty, y = ("SubSplit", style["sub_y_split"]) if split else ("Sub", style["sub_y"])
        base = ass_color(style["sub_split_color"] if split else style["text"])
        pieces = range(len(ch)) if karaoke else [None]
        for wi in pieces:
            ws_ = start if not wi else ch[wi]["s"]
            we = end if (wi is None or wi == len(ch) - 1) else ch[wi + 1]["s"]
            if we - ws_ < 0.01:
                continue
            parts = []
            for j, o in enumerate(ch):
                t = _esc(o["w"].upper() if (caps or (o["key"] and karaoke)) else o["w"])
                col = acc if (j == wi or o["key"]) else base
                parts.append(f"{{\\c{col}}}{t}")
            if not wi:
                anim = ("\\fscx86\\fscy86\\t(0,90,\\fscx100\\fscy100)" if karaoke
                        else "\\fad(120,0)\\fscx96\\fscy96\\t(0,160,\\fscx100\\fscy100)")
            else:
                anim = ""
            events.append(f"Dialogue: 0,{_ass_time(ws_)},{_ass_time(we)},{sty},,0,0,0,,"
                          f"{{\\pos({x},{y}){anim}}}" + " ".join(parts))

    it = 1 if style.get("sub_italic") else 0
    white = ass_color(style["text"])
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {style['width']}
PlayResY: {style['height']}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{style['ass_font']},{style['sub_size']},{white},{white},{ass_color(style['outline'])},{ass_color('#000000', 0x80)},0,{it},0,0,100,100,0,0,1,{style['sub_outline']},{style['sub_shadow']},5,70,70,0,1
Style: SubSplit,{style['ass_font']},{style.get('sub_size_split', style['sub_size'])},{ass_color(style['sub_split_color'])},{white},{ass_color(style['panel_bg'])},{ass_color('#000000', 0xFF)},0,{it},0,0,100,100,0,0,1,0,0,5,70,70,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    path.write_text(header + "\n".join(events) + "\n", encoding="utf-8")
    return len(chunks)


# ---------------------------------------------------------------- 3. sound effects track
def build_sfx_track(events: list[tuple[float, str]], dur: float, volume: float, path: Path) -> bool:
    sr = 48000
    track = np.zeros((int(dur * sr) + sr, 2), dtype=np.float32)
    cache, used = {}, 0
    for t, name in events:
        f = SFX_DIR / name
        if not f.exists():
            continue
        if name not in cache:
            with wave.open(str(f), "rb") as w:
                data = np.frombuffer(w.readframes(w.getnframes()), dtype="<i2").reshape(-1, w.getnchannels())
                if data.shape[1] == 1:
                    data = np.repeat(data, 2, axis=1)
                cache[name] = data.astype(np.float32) / 32768
        clip = cache[name]
        i = int(max(t, 0) * sr)
        n = min(len(clip), len(track) - i)
        if n > 0:
            track[i:i + n] += clip[:n] * volume
            used += 1
    if not used:
        return False
    pcm = (np.clip(track[: int(dur * sr)], -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())
    return True


# ---------------------------------------------------------------- 4. final pass
def final_pass(body: Path, comp: Compositor, splits, plan: dict, style: dict, dur: float, wd: Path,
               out: Path, draft: bool):
    W, H, fps = style["width"], style["height"], style["fps"]
    inputs = ["-i", body.name, "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}", "-framerate", str(fps),
              "-i", "pipe:0"]
    n_in = 2
    fg = []
    if splits:
        en = "+".join(f"between(t,{a:.3f},{b - 0.001:.3f})" for a, b in splits)
        fg.append("[0:v]split=2[va][vb]")
        fg.append(f"[vb]crop={W}:{style['split_y']}:0:{style['split_crop_y']}[vtop]")
        fg.append(f"[va][vtop]overlay=0:0:enable='{en}'[base]")
    else:
        fg.append("[0:v]null[base]")
    fg.append("[base][1:v]overlay=0:0:format=auto[gfx]")
    fg.append("[gfx]ass=subs.ass:fontsdir=fonts,format=yuv420p[vout]")

    fg.append("[0:a]asplit=2[voice][sc]")
    mix = ["[voice]"]
    if plan.get("sfx", True) and build_sfx_track(comp.sfx_events(), dur, style["sfx_volume"], wd / "sfx.wav"):
        inputs += ["-i", "sfx.wav"]
        fg.append(f"[{n_in}:a]aresample=48000[sfx]")
        mix.append("[sfx]")
        n_in += 1
    music = plan.get("music")
    if music:
        mp = Path(music)
        if not mp.is_absolute():
            mp = Path(plan["video"]).parent / mp
        if not mp.exists():
            die(f"музыка не найдена: {mp}")
        inputs += ["-stream_loop", "-1", "-i", str(mp)]
        fg.append(f"[{n_in}:a]aresample=48000,volume={style['music_volume']},atrim=duration={dur:.3f}[mus]")
        fg.append("[mus][sc]sidechaincompress=threshold=0.03:ratio=6:attack=15:release=350[duck]")
        mix.append("[duck]")
        n_in += 1
    else:
        fg.append("[sc]anullsink")
    fg.append(f"{''.join(mix)}amix=inputs={len(mix)}:duration=first:normalize=0,"
              f"loudnorm=I={style['loudness_lufs']}:TP=-1.5:LRA=11,aresample=48000,"
              f"afade=t=out:st={max(dur - 0.3, 0):.3f}:d=0.3[aout]")

    script = wd / "filter.txt"
    script.write_text(";\n".join(fg), encoding="utf-8")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", *inputs, ffmpeg_filter_flag(), script.name,
           "-map", "[vout]", "-map", "[aout]",
           "-c:v", "libx264", "-preset", "ultrafast" if draft else "medium", "-crf", "28" if draft else "19",
           "-profile:v", "high", "-r", str(fps), "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
           "-movflags", "+faststart", "-t", f"{dur:.3f}", str(out)]
    log = wd / "ffmpeg_final.log"
    with open(log, "w", encoding="utf-8", errors="replace") as lf:
        proc = subprocess.Popen(cmd, cwd=wd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=lf)
        total = int(round(dur * fps))
        try:
            for i, fr in enumerate(comp.frames(dur)):
                proc.stdin.write(fr)
                if i % (fps * 5) == 0:
                    print(f"  графика: {i / fps:5.1f} / {dur:.1f} c", flush=True)
            proc.stdin.close()
        except (BrokenPipeError, OSError):
            pass
        rc = proc.wait()
    if rc != 0:
        tail = "\n".join(log.read_text(encoding="utf-8", errors="replace").splitlines()[-25:])
        die(f"финальная сборка ffmpeg упала (кадров {total}):\n{tail}")


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
    for f in list(FONTS_DIR.glob("*.otf")) + list(FONTS_DIR.glob("*.ttf")):
        if "Emoji" not in f.name and not (fonts / f.name).exists():
            shutil.copy2(f, fonts / f.name)

    body = render_segments(video, keep, style, wd, args.draft, info["has_audio"])
    cta = plan.get("cta") or {}
    sub_end = tl.duration - (float(cta.get("final_seconds", 0) or 0) if cta.get("keyword") and cta.get("hide_subs_on_final") else 0)
    comp = Compositor(style["width"], style["height"], style["fps"])
    splits = build_scenes(comp, plan, style, tl, tl.duration)
    build_overlays(comp, plan, style, tl, tl.duration)
    n = build_ass(load_json(wd / "words.json")["words"], tl, plan, style, wd / "subs.ass", sub_end, splits)
    print(f"Субтитры: {n} фраз, графика: {len(comp.els)} элементов, сцен-панелей: {len(splits)}. Финальная сборка…")

    out = Path(args.out) if args.out else video.parent / f"{video.stem}_{'DRAFT' if args.draft else 'REELS'}.mp4"
    final_pass(body, comp, splits, plan, style, tl.duration, wd, out.resolve(), args.draft)
    print(f"\nГОТОВО: {out}  ({tl.duration:.1f} c)")


if __name__ == "__main__":
    main()
