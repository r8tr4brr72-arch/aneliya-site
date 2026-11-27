"""Original ambient pluck track in the Japanese miyako-bushi scale (Karplus-Strong plucks + soft drone)."""
import sys, wave
import numpy as np
SR = 48000
dur = float(sys.argv[1]); out = sys.argv[2]; seed = int(sys.argv[3]) if len(sys.argv) > 3 else 1
rng = np.random.default_rng(seed)
N = int(dur * SR)
mix = np.zeros((N, 2))

def pluck(freq, length=2.6, bright=0.5):
    n = int(SR * length); p = int(SR / freq)
    buf = rng.uniform(-1, 1, p); out = np.zeros(n)
    for i in range(n):
        out[i] = buf[i % p]
        buf[i % p] = 0.5 * (buf[i % p] + buf[(i + 1) % p]) * (0.996 + 0.003 * bright)
    attack = np.exp(-np.arange(n) / (SR * 0.004))  # shamisen-like 'sawari' buzz on attack
    return out * (1 + 0.6 * attack * rng.uniform(-1, 1, n)) * np.exp(-np.arange(n) / (SR * 1.4))

# miyako-bushi on D: D Eb G A Bb (two octaves)
base = 293.66
steps = [0, 1, 5, 7, 8, 12, 13, 17, 19]
scale = [base * 2 ** (s / 12) for s in steps]
phrase = [4, 3, 2, None, 4, 5, 4, 2, None, 1, 2, 3, 2, None, 0, None]
t = 0.35; beat = 0.42
while t < dur - 2.5:
    for idx in phrase:
        if t >= dur - 2.5: break
        if idx is not None:
            note = pluck(scale[idx] * (2 if rng.random() < 0.15 else 1), bright=rng.random())
            pan = rng.uniform(-0.35, 0.35)
            i = int(t * SR); n = min(len(note), N - i)
            mix[i:i + n, 0] += note[:n] * (0.5 - pan) * 0.55
            mix[i:i + n, 1] += note[:n] * (0.5 + pan) * 0.55
        t += beat * (1.5 if idx is None else 1)

# soft drone: D + A, slow swell
tt = np.arange(N) / SR
drone = (np.sin(2 * np.pi * base / 2 * tt) + 0.6 * np.sin(2 * np.pi * base * 0.75 * tt) + 0.3 * np.sin(2 * np.pi * base * tt))
drone *= 0.05 * (0.6 + 0.4 * np.sin(2 * np.pi * tt / 7)) * np.minimum(1, tt / 2)
mix += drone[:, None]
fade = np.minimum(1, (dur - tt) / 1.5)[:, None]
mix *= fade
mix /= np.max(np.abs(mix)) + 1e-9
with wave.open(out, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 0.85 * 32767).astype("<i2").tobytes())
