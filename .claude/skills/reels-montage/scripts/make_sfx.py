"""Synthesize the built-in sound effects (pop, whoosh, click) into assets/sfx.

The WAVs are already shipped with the skill; run this only to regenerate them.
"""
import wave

import numpy as np

from common import SFX_DIR

SR = 48000


def write(name: str, x: np.ndarray) -> None:
    x = x / (np.max(np.abs(x)) + 1e-9) * 0.9
    pcm = (x * 32767).astype("<i2")
    stereo = np.repeat(pcm[:, None], 2, axis=1)
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    with wave.open(str(SFX_DIR / name), "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(stereo.tobytes())


def pop() -> np.ndarray:
    t = np.arange(int(SR * 0.12)) / SR
    freq = 320 + 900 * np.exp(-t * 45)
    phase = 2 * np.pi * np.cumsum(freq) / SR
    env = np.exp(-t * 38) * np.minimum(1, t * 800)
    return np.sin(phase) * env


def whoosh() -> np.ndarray:
    n = int(SR * 0.45)
    t = np.arange(n) / SR
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(n)
    out = np.zeros(n)
    # time-varying one-pole lowpass: cutoff sweeps up then down
    cutoff = 300 + 4200 * np.sin(np.pi * t / t[-1]) ** 2
    a = np.exp(-2 * np.pi * cutoff / SR)
    y = 0.0
    for i in range(n):
        y = a[i] * y + (1 - a[i]) * noise[i]
        out[i] = y
    env = np.sin(np.pi * t / t[-1]) ** 1.5
    return out * env


def click() -> np.ndarray:
    t = np.arange(int(SR * 0.03)) / SR
    rng = np.random.default_rng(3)
    return (rng.standard_normal(t.size) * 0.5 + np.sin(2 * np.pi * 2400 * t)) * np.exp(-t * 260)


if __name__ == "__main__":
    write("pop.wav", pop())
    write("whoosh.wav", whoosh())
    write("click.wav", click())
    print("ok:", ", ".join(p.name for p in SFX_DIR.glob("*.wav")))
