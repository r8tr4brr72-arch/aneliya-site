"""Shared helpers for the reels-montage skill (Windows / macOS / Linux)."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
ASSETS = SKILL_DIR / "assets"
FONTS_DIR = ASSETS / "fonts"
SFX_DIR = ASSETS / "sfx"
STYLES_DIR = SKILL_DIR / "styles"

# Windows consoles default to cp1251/cp866 — force UTF-8 so Russian text prints.
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8")
    except Exception:
        pass


def die(msg: str) -> None:
    print(f"ОШИБКА: {msg}", file=sys.stderr)
    sys.exit(1)


def need(tool: str) -> str:
    path = shutil.which(tool)
    if not path:
        die(f"не найден {tool}. Установите FFmpeg: winget install Gyan.FFmpeg (затем перезапустите терминал).")
    return path


def run(cmd: list[str], cwd: Path | None = None, quiet: bool = True) -> subprocess.CompletedProcess:
    proc = subprocess.run(
        [str(c) for c in cmd], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        tail = "\n".join(proc.stderr.strip().splitlines()[-25:])
        die(f"команда завершилась с ошибкой:\n{' '.join(map(str, cmd))[:600]}\n---\n{tail}")
    if not quiet:
        print(proc.stdout)
    return proc


def workdir_for(video: Path) -> Path:
    wd = video.parent / f"{video.stem}_montage"
    wd.mkdir(parents=True, exist_ok=True)
    return wd


def load_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_style(name_or_path: str | None) -> dict:
    base = load_json(STYLES_DIR / "orange.json")
    if not name_or_path or name_or_path == "orange":
        return base
    p = Path(name_or_path)
    if not p.exists():
        p = STYLES_DIR / f"{name_or_path}.json"
    if not p.exists():
        die(f"стиль не найден: {name_or_path}")
    base.update(load_json(p))
    return base


def probe(video: Path) -> dict:
    need("ffprobe")
    out = run(["ffprobe", "-v", "error", "-show_entries",
               "format=duration:stream=codec_type,width,height,r_frame_rate",
               "-of", "json", video]).stdout
    data = json.loads(out)
    info = {"duration": float(data["format"]["duration"]), "has_audio": False}
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and "width" not in info:
            info["width"], info["height"] = s["width"], s["height"]
        if s.get("codec_type") == "audio":
            info["has_audio"] = True
    return info


def fmt_ts(t: float) -> str:
    m, s = divmod(max(t, 0.0), 60)
    return f"{int(m):02d}:{s:05.2f}"


def hex_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def ass_color(h: str, alpha: int = 0) -> str:
    r, g, b = hex_rgb(h)
    return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"


class Timeline:
    """Maps source-video time to output time after cutting."""

    def __init__(self, keep: list[dict]):
        self.segs = []
        out = 0.0
        for k in keep:
            s, e = float(k["start"]), float(k["end"])
            if e - s < 0.05:
                continue
            self.segs.append((s, e, out))
            out += e - s
        self.duration = out

    def contains(self, t: float) -> bool:
        return any(s <= t <= e for s, e, _ in self.segs)

    def map(self, t: float) -> float:
        """Source time -> output time. Times inside a cut snap to the next kept segment."""
        for s, e, o in self.segs:
            if t < s:
                return o
            if t <= e:
                return o + (t - s)
        return self.duration
