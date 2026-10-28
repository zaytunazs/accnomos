"""Original music bed for the teaser, synthesised from scratch with numpy (no samples, no downloads).

120 BPM, C major, I–V–vi–IV. Bar = 2 s, so every scene cut in build.py lands on a beat.
Layout (bars): 0–1 intro (pad, pluck, hats) · 2 kick and bass drop in (the product demo starts) ·
4+ clap and lead · from `drums_until` (default: the last two bars) drums out, final chord rings and fades.
"""

from __future__ import annotations

import wave

import numpy as np

SR = 48_000
BPM = 120
BEAT = 60 / BPM
BAR = 4 * BEAT

# I–V–vi–IV in C: C, G, Am, F (MIDI notes for the pad, root for the bass)
CHORDS = [
    (48, [60, 64, 67, 72]),  # C
    (43, [59, 62, 67, 71]),  # G
    (45, [60, 64, 69, 72]),  # Am
    (41, [60, 65, 69, 72]),  # F
]
# A small lead motif per chord (beat offset, midi, length in beats)
MOTIF = [
    [(0, 76, 0.5), (0.5, 79, 0.5), (1.5, 76, 0.5), (2, 74, 1), (3, 72, 0.5), (3.5, 74, 0.5)],
    [(0, 74, 0.5), (0.5, 79, 0.5), (1.5, 74, 0.5), (2, 71, 1.5), (3.5, 74, 0.5)],
    [(0, 72, 0.5), (0.5, 76, 0.5), (1.5, 81, 0.5), (2, 79, 1), (3, 76, 1)],
    [(0, 77, 0.5), (0.5, 76, 0.5), (1, 74, 0.5), (1.5, 72, 0.5), (2, 74, 2)],
]


def hz(m: float) -> float:
    return 440.0 * 2 ** ((m - 69) / 12)


def env_adsr(n: int, a: float, d: float, s: float, r: float) -> np.ndarray:
    a_n, d_n, r_n = int(a * SR), int(d * SR), int(r * SR)
    e = np.full(n, s, dtype=np.float64)
    a_n = min(a_n, n)
    e[:a_n] = np.linspace(0, 1, a_n, endpoint=False)
    d_end = min(n, a_n + d_n)
    e[a_n:d_end] = np.linspace(1, s, d_end - a_n, endpoint=False)
    if r_n and n > r_n:
        e[-r_n:] *= np.linspace(1, 0, r_n)
    return e


def lp_fast(x: np.ndarray, cutoff: float) -> np.ndarray:
    """FFT brick-ish low-pass with a soft knee, for long buffers."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec *= 1 / (1 + (f / cutoff) ** 4)
    return np.fft.irfft(spec, len(x))


def saw(freq: float, t: np.ndarray, detune: float = 0.0) -> np.ndarray:
    ph = (freq * (1 + detune) * t) % 1.0
    return 2 * ph - 1


def kick(n: int) -> np.ndarray:
    t = np.arange(n) / SR
    f = 50 + 110 * np.exp(-t * 28)
    ph = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(ph) * np.exp(-t * 7.5) * 0.95 + 0.15 * np.random.default_rng(1).standard_normal(n) * np.exp(-t * 300)


def hat(n: int, rng: np.random.Generator, decay: float = 60) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = noise - lp_fast(noise, 7000)  # keep the top end
    return noise * np.exp(-t * decay)


def clap(n: int, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(n) / SR
    noise = rng.standard_normal(n)
    noise = lp_fast(noise, 5000) - lp_fast(noise, 900)
    env = np.exp(-t * 22)
    for off in (0.0, 0.011, 0.022):  # three quick bursts
        env += 0.6 * np.exp(-np.clip(t - off, 0, None) * 140) * (t >= off)
    return noise * env * 0.5


def add(buf: np.ndarray, sig: np.ndarray, start_s: float, gain: float = 1.0, pan: float = 0.0) -> None:
    i = int(start_s * SR)
    if i >= buf.shape[0]:
        return
    j = min(buf.shape[0], i + len(sig))
    l = np.cos((pan + 1) * np.pi / 4) * gain
    r = np.sin((pan + 1) * np.pi / 4) * gain
    buf[i:j, 0] += sig[: j - i] * l
    buf[i:j, 1] += sig[: j - i] * r


def render(duration: float, path: str, drums_until: float | None = None) -> None:
    n = int(duration * SR)
    out = np.zeros((n, 2))
    rng = np.random.default_rng(7)
    bars = int(np.ceil(duration / BAR))
    end_bar = int(drums_until // BAR) if drums_until else bars - 2  # drums stop here; final chord rings

    k = kick(int(0.45 * SR))
    h_closed = hat(int(0.06 * SR), rng, 90)
    h_open = hat(int(0.25 * SR), rng, 14)
    c = clap(int(0.3 * SR), rng)

    for b in range(bars):
        t0 = b * BAR
        root, chord = CHORDS[b % 4]
        last = b >= end_bar
        # pad: detuned saws, low-passed, long attack
        pad_len = BAR * (2.5 if b == end_bar else 1.0) + 0.3
        tt = np.arange(int(pad_len * SR)) / SR
        pad = np.zeros_like(tt)
        for m in chord:
            for d in (-0.004, 0.0, 0.004):
                pad += saw(hz(m), tt, d)
        pad = lp_fast(pad, 1400 if b < 2 else 2200) * env_adsr(len(tt), 0.25, 0.4, 0.8, 0.5)
        if b == end_bar:
            pad *= np.linspace(1, 0, len(pad)) ** 1.5
        if b <= end_bar:
            add(out, pad / 12, t0, 0.55, 0)

        if last:
            continue
        # hats: 16ths soft, offbeat 8ths accented, open hat on the last offbeat
        for s in range(16):
            ts = t0 + s * BEAT / 4
            if s % 4 == 2:
                add(out, h_open if s == 14 else h_closed, ts, 0.16 if s != 14 else 0.10, 0.25)
            elif b >= 2:
                add(out, h_closed, ts, 0.05, -0.2)
        # pluck arpeggio (whole track): 8ths over the chord
        for s in range(8):
            m = chord[[0, 1, 2, 3, 2, 1, 2, 3][s]] + 12
            nlen = int(0.22 * SR)
            tt = np.arange(nlen) / SR
            sig = (np.sin(2 * np.pi * hz(m) * tt) + 0.3 * np.sin(4 * np.pi * hz(m) * tt)) * np.exp(-tt * 18)
            add(out, sig, t0 + s * BEAT / 2, 0.07, 0.35 if s % 2 else -0.35)
        if b < 2:
            # riser into the drop
            if b == 1:
                tt = np.arange(int(BAR * SR)) / SR
                noise = rng.standard_normal(len(tt))
                noise = noise - lp_fast(noise, 2500)
                add(out, noise * (tt / BAR) ** 3, t0, 0.06, 0)
            continue
        # kick four on the floor
        for q in range(4):
            add(out, k, t0 + q * BEAT, 0.9, 0)
        # bass: offbeat 8ths on the root, plucky saw
        for s in range(8):
            if s % 2 == 0:
                continue
            nlen = int(0.24 * SR)
            tt = np.arange(nlen) / SR
            f = hz(root - 12 + 12 * (s == 7))
            sig = lp_fast(saw(f, tt) + 0.6 * np.sin(2 * np.pi * f * tt), 900) * np.exp(-tt * 9)
            add(out, sig, t0 + s * BEAT / 2, 0.38, 0)
        # sub on the downbeats
        tt = np.arange(int(BAR * SR)) / SR
        add(out, np.sin(2 * np.pi * hz(root - 12) * tt) * env_adsr(len(tt), 0.01, 0.2, 0.5, 0.3), t0, 0.12, 0)
        if b >= 4:
            add(out, c, t0 + BEAT, 0.4, 0.05)
            add(out, c, t0 + 3 * BEAT, 0.4, 0.05)
            # lead: square-ish with vibrato, every bar from 4
            for off, m, ln in MOTIF[b % 4]:
                nlen = int(ln * BEAT * SR)
                tt = np.arange(nlen) / SR
                vib = 1 + 0.004 * np.sin(2 * np.pi * 5.5 * tt) * np.clip(tt * 4, 0, 1)
                ph = np.cumsum(hz(m) * vib) / SR
                sq = np.tanh(3 * np.sin(2 * np.pi * ph)) * 0.6 + 0.4 * np.sin(4 * np.pi * ph)
                sig = lp_fast(sq, 3200) * env_adsr(nlen, 0.01, 0.12, 0.6, 0.06)
                add(out, sig, t0 + off * BEAT, 0.085, 0.1)
                # simple echo (dotted 8th)
                add(out, sig, t0 + off * BEAT + 0.75 * BEAT, 0.03, -0.4)

    # sidechain-style duck on the pad/hats from the kick: gentle pump
    t = np.arange(n) / SR
    beat_pos = (t % BEAT) / BEAT
    duck = 1 - 0.25 * np.exp(-beat_pos * 9) * (t >= 2 * BAR) * (t < end_bar * BAR)
    out *= duck[:, None]

    # fades
    fi = int(0.4 * SR)
    out[:fi] *= np.linspace(0, 1, fi)[:, None]
    fo = int(2.5 * SR)
    out[-fo:] *= (np.linspace(1, 0, fo) ** 1.6)[:, None]
    out = np.tanh(out * 1.2) / np.tanh(1.2)  # soft clip
    out /= max(1e-9, np.abs(out).max()) / 0.89
    pcm = (out * 32767).astype("<i2")
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


if __name__ == "__main__":
    import sys

    render(float(sys.argv[1]) if len(sys.argv) > 1 else 38.0, sys.argv[2] if len(sys.argv) > 2 else "music.wav")
