"""
Soft music-box chimes for save/load feedback, generated as small WAV files
(sine tone with faint overtones, quick attack, gentle decay) and played
asynchronously. Replaces winsound.Beep, which is a harsh square wave.
"""
from __future__ import annotations

import math
import struct
import wave
import winsound
from pathlib import Path

from paths import APP_DIR

RATE = 44100
VOLUME = 0.22
SOUNDS_DIR = APP_DIR / "sounds"
VERSION = 1  # bump to regenerate after changing the tones


def _note(freq: float, length: float, decay: float) -> list[float]:
    out = []
    for i in range(int(RATE * length)):
        t = i / RATE
        env = min(1.0, t / 0.004) * math.exp(-t / decay)
        s = (math.sin(2 * math.pi * freq * t)
             + 0.25 * math.sin(2 * math.pi * freq * 2 * t) * math.exp(-t / (decay * 0.5))
             + 0.08 * math.sin(2 * math.pi * freq * 3 * t) * math.exp(-t / (decay * 0.3)))
        out.append(env * s / 1.33)
    return out


def _mix(parts: list[tuple[float, list[float]]]) -> list[float]:
    total = max(int(start * RATE) + len(p) for start, p in parts)
    buf = [0.0] * total
    for start, p in parts:
        o = int(start * RATE)
        for i, v in enumerate(p):
            buf[o + i] += v
    # short fade-out so nothing clicks at the end
    fade = int(0.02 * RATE)
    for i in range(fade):
        buf[-1 - i] *= i / fade
    return buf


def _write(path: Path, samples: list[float]) -> None:
    peak = max(1e-9, max(abs(s) for s in samples))
    scale = VOLUME * 32767 / max(1.0, peak)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(b"".join(struct.pack("<h", int(s * scale)) for s in samples))


# C6=1046.5, E6=1318.5, G6=1568.0, A4=440
SOUNDS = {
    "save": lambda: _mix([(0.0, _note(1046.5, 0.35, 0.12)), (0.07, _note(1568.0, 0.45, 0.16))]),
    "load": lambda: _mix([(0.0, _note(1568.0, 0.35, 0.12)), (0.07, _note(1046.5, 0.45, 0.16))]),
    "slot": lambda: _mix([(0.0, _note(1318.5, 0.18, 0.05))]),
    "error": lambda: _mix([(0.0, _note(440.0, 0.3, 0.09)), (0.12, _note(392.0, 0.35, 0.11))]),
}


def ensure_sounds() -> None:
    SOUNDS_DIR.mkdir(exist_ok=True)
    for name, make in SOUNDS.items():
        path = SOUNDS_DIR / f"{name}_v{VERSION}.wav"
        if not path.exists():
            _write(path, make())


def play(name: str) -> None:
    path = SOUNDS_DIR / f"{name}_v{VERSION}.wav"
    try:
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
    except RuntimeError:
        pass
