"""Sortie audio: périphériques, volume, et lecture sans coupure de fin."""
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

SOUNDS = Path(__file__).parent / "sounds"
MME = next(i for i, h in enumerate(sd.query_hostapis()) if h["name"] == "MME")


def device_names(kind):
    return [d["name"] for d in sd.query_devices() if d["hostapi"] == MME and d[f"max_{kind}_channels"] > 0]


def device_index(name, kind):
    """Index sounddevice du périphérique `name` (None = défaut système)."""
    return next((i for i, d in enumerate(sd.query_devices())
                 if name and d["name"] == name and d["hostapi"] == MME and d[f"max_{kind}_channels"] > 0), None)


def play(x, sr, dev, volume, tail=0.3):
    """Joue x (int16 ou float) à `volume` (0-1). Le pic est normalisé: tous les sons ont le même niveau.

    Fondu de 25 ms + `tail` secondes de silence: sans ça, le pilote MME coupe la fin du son.
    """
    x = np.asarray(x)
    x = (x / np.iinfo(x.dtype).max if x.dtype.kind == "i" else x).astype(np.float32).squeeze()
    x = x / (np.abs(x).max() or 1) * volume
    n = min(len(x), int(0.025 * sr))
    x[-n:] *= np.linspace(1, 0, n, dtype=np.float32)
    sd.play(np.concatenate([x, np.zeros(int(tail * sr), np.float32)]), sr, device=dev)
    sd.wait()


def read_wav(path):
    """(float32 mono entre -1 et 1, fréquence) d'un .wav PCM de 8, 16, 24 ou 32 bits, premier canal.

    Bibliothèque standard seulement: scipy coûterait ≈30 Mo de mémoire pour lire 2 petits sons."""
    with wave.open(str(path)) as w:
        ch, width, sr = w.getnchannels(), w.getsampwidth(), w.getframerate()
        raw = w.readframes(w.getnframes())
    if width == 3:  # 24 bits (c'est le cas de sounds/): numpy n'a pas ce type, on assemble les 3 octets puis on étend le signe
        b = np.frombuffer(raw, np.uint8).reshape(-1, ch, 3).astype(np.int32)
        x = ((b[..., 0] | b[..., 1] << 8 | b[..., 2] << 16) ^ 0x800000) - 0x800000
    else:
        x = np.frombuffer(raw, {1: np.uint8, 2: np.int16, 4: np.int32}[width]).reshape(-1, ch)
    x = x[:, 0].astype(np.float32)
    return (x - 128 if width == 1 else x) / (1 << (8 * width - 1)), sr


def play_sound(name, dev, volume):
    """sounds/<name>.wav (Kenney, CC0): « ready » = je t'écoute (monte), « fail » = pas compris (descend)."""
    play(*read_wav(SOUNDS / f"{name}.wav"), dev, volume)
