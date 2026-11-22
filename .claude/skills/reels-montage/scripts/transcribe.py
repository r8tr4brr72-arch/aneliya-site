"""Step 1: transcribe a raw video word-by-word (faster-whisper, runs locally).

Usage:  python transcribe.py VIDEO [--model small|medium|large-v3] [--lang ru] [--device cpu|cuda]

Creates next to the video a folder <name>_montage/ with:
  words.json      — every word with start/end time (source timeline)
  transcript.txt  — readable phrases with ids and timecodes, for the edit plan
"""
import argparse
from pathlib import Path

from common import die, fmt_ts, need, run, save_json, workdir_for

DEFAULT_PROMPT = ("Привет! Сегодня про нейросети: ChatGPT, Claude, Gemini, Midjourney, "
                  "промпт, лайфхаки, искусственный интеллект, сайт.")


def build_phrases(words, max_gap=0.45):
    phrases, cur = [], []
    for w in words:
        if cur and (w["s"] - cur[-1]["e"] > max_gap):
            phrases.append(cur)
            cur = []
        cur.append(w)
        if w["w"].rstrip().endswith((".", "?", "!")) and len(cur) >= 3:
            phrases.append(cur)
            cur = []
    if cur:
        phrases.append(cur)
    return [{"id": i + 1, "start": p[0]["s"], "end": p[-1]["e"],
             "text": " ".join(x["w"] for x in p)} for i, p in enumerate(phrases)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("video")
    ap.add_argument("--model", default="small",
                    help="small (быстро), medium (точнее), large-v3 (лучше всего, медленно)")
    ap.add_argument("--lang", default="ru")
    ap.add_argument("--device", default="cpu", help="cpu (по умолчанию) или cuda, если есть видеокарта NVIDIA с CUDA")
    ap.add_argument("--prompt", default=DEFAULT_PROMPT, help="подсказка со словами/терминами из видео")
    args = ap.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        die(f"файл не найден: {video}")
    need("ffmpeg")
    try:
        from faster_whisper import WhisperModel
    except ImportError:
        die("не установлен faster-whisper: python -m pip install -r requirements.txt")

    wd = workdir_for(video)
    wav = wd / "audio16k.wav"
    run(["ffmpeg", "-y", "-i", video, "-vn", "-ac", "1", "-ar", "16000", wav])

    print(f"Распознаю речь моделью {args.model} (первый запуск скачает модель)…")
    model = WhisperModel(args.model, device=args.device, compute_type="int8" if args.device == "cpu" else "float16")
    segments, info = model.transcribe(
        str(wav), language=args.lang, word_timestamps=True, beam_size=5,
        condition_on_previous_text=False, initial_prompt=args.prompt,
    )
    words = []
    for seg in segments:
        for w in seg.words or []:
            txt = w.word.strip()
            if txt:
                words.append({"w": txt, "s": round(w.start, 3), "e": round(w.end, 3),
                              "p": round(w.probability, 2)})
        print(f"  {fmt_ts(seg.start)}  {seg.text.strip()}")
    if not words:
        die("речь не распознана — проверьте, что в видео есть звук")

    phrases = build_phrases(words)
    save_json(wd / "words.json", {"video": str(video), "duration": info.duration,
                                  "words": words, "phrases": phrases})
    with open(wd / "transcript.txt", "w", encoding="utf-8") as f:
        for p in phrases:
            f.write(f"#{p['id']:<3} [{fmt_ts(p['start'])} → {fmt_ts(p['end'])}]  {p['text']}\n")
    wav.unlink(missing_ok=True)
    print(f"\nГотово: {len(words)} слов, {len(phrases)} фраз → {wd}")


if __name__ == "__main__":
    main()
