"""Step 2: build a draft edit plan (plan.json) from words.json.

Usage:  python draft_plan.py VIDEO [--style orange] [--keyword САЙТ]

Automatically: removes pauses longer than style.max_pause, removes filler sounds
("эээ", "ммм"), alternates punch-in zoom on every jump cut. Retakes, headers,
cards and highlights are then edited by Claude directly in plan.json.
"""
import argparse
import re
from pathlib import Path

from common import die, load_json, load_style, save_json, workdir_for

FILLER = re.compile(r"^(э+м*|м{2,}|хм+|а{2,}|эм+)$")


def norm(w: str) -> str:
    return re.sub(r"[^\w-]", "", w.lower())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--style", default="orange")
    ap.add_argument("--keyword", default="САЙТ", help="кодовое слово для воронки в комментариях")
    ap.add_argument("--force", action="store_true", help="перезаписать существующий plan.json")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    wd = workdir_for(video)
    if not (wd / "words.json").exists():
        die("нет words.json — сначала запустите transcribe.py")
    if (wd / "plan.json").exists() and not args.force:
        die(f"{wd / 'plan.json'} уже существует (добавьте --force, чтобы перезаписать)")
    style = load_style(args.style)
    words = load_json(wd / "words.json")["words"]

    runs, cur = [], []
    for w in words:
        if FILLER.match(norm(w["w"])):
            if cur:
                runs.append(cur)
                cur = []
            continue
        if cur and w["s"] - cur[-1]["e"] > style["max_pause"]:
            runs.append(cur)
            cur = []
        cur.append(w)
    if cur:
        runs.append(cur)

    keep, prev_end, zoom = [], -1.0, False
    for i, r in enumerate(runs):
        s = max(0.0, r[0]["s"] - style["cut_pad_before"])
        e = r[-1]["e"] + style["cut_pad_after"]
        if keep and s <= keep[-1]["end"]:          # paddings overlap → no real cut
            s = keep[-1]["end"]
        if keep and s - prev_end > 0.25:            # visible jump cut → toggle zoom
            zoom = not zoom
        keep.append({"id": i + 1, "start": round(s, 3), "end": round(e, 3),
                     "text": " ".join(x["w"] for x in r), "zoom": zoom, "bw": False})
        prev_end = e

    kw = args.keyword.upper()
    plan = {
        "video": str(video),
        "style": args.style,
        "keep": keep,
        "highlight": [],
        "headers": [],
        "cards": [],
        "cta": {
            "keyword": kw,
            "title": "Пиши в комментариях",
            "subtitle": "и я пришлю инструкцию, как сделать сайт",
            "bar_text": f"Напиши «{kw}» в комментариях — пришлю инструкцию",
            "bar_from": 3.0,
            "final_seconds": 4.0,
        },
        "music": None,
        "sfx": True,
    }
    save_json(wd / "plan.json", plan)
    src = sum(w["e"] - w["s"] for w in words)
    out = sum(k["end"] - k["start"] for k in keep)
    print(f"Черновик плана: {len(keep)} кусков, ~{out:.1f} c (речь в исходнике {src:.1f} c) → {wd / 'plan.json'}")


if __name__ == "__main__":
    main()
