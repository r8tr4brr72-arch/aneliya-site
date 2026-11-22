"""Contact sheet of frames from a rendered video, so Claude can visually check the edit.

Usage:  python snapshot.py OUT.mp4 [--times 1 4.5 10] [--n 8]
Writes OUT_frames.png next to the video and prints its path.
"""
import argparse
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from common import fmt_ts, need, probe, run


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--times", nargs="*", type=float)
    ap.add_argument("--n", type=int, default=8)
    args = ap.parse_args()
    need("ffmpeg")
    video = Path(args.video).resolve()
    dur = probe(video)["duration"]
    times = args.times or [dur * (i + 0.5) / args.n for i in range(args.n)]
    thumbs = []
    with tempfile.TemporaryDirectory() as tmp:
        for i, t in enumerate(times):
            p = Path(tmp) / f"{i}.png"
            run(["ffmpeg", "-y", "-ss", f"{min(t, dur - 0.05):.3f}", "-i", video, "-frames:v", "1",
                 "-vf", "scale=360:640", p])
            im = Image.open(p).convert("RGB")
            ImageDraw.Draw(im).rectangle([0, 0, 110, 34], fill=(0, 0, 0))
            ImageDraw.Draw(im).text((8, 8), fmt_ts(t), fill=(255, 255, 0))
            thumbs.append(im)
    cols = min(4, len(thumbs))
    rows = (len(thumbs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * 364, rows * 644), (40, 40, 40))
    for i, im in enumerate(thumbs):
        sheet.paste(im, ((i % cols) * 364 + 2, (i // cols) * 644 + 2))
    out = video.with_name(video.stem + "_frames.png")
    sheet.save(out)
    print(out)


if __name__ == "__main__":
    main()
