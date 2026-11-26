"""Auto-vérif de audio.py: les vrais sons livrés (24 bits!) se lisent et se jouent, tous les formats PCM sont compris.

Rien n'est joué: sounddevice est remplacé. Lancer: .venv\\Scripts\\python test_audio.py
"""
import tempfile
import wave
from pathlib import Path

import numpy as np

import audio

played = []
audio.sd.play = lambda x, sr, device=None: played.append((x, sr, device))
audio.sd.wait = lambda: None

# les vrais sons du projet: ils ont déjà fait planter le moteur (« sons en 16 bits seulement ») alors qu'ils sont en 24 bits stéréo
for name in ("ready", "fail"):
    x, sr = audio.read_wav(audio.SOUNDS / f"{name}.wav")
    assert x.dtype == np.float32 and x.ndim == 1 and sr == 48000 and len(x) > 1000, (name, x.shape, sr)
    assert 0.05 < np.abs(x).max() <= 1.0, f"{name}: ni muet ni écrêté ({np.abs(x).max()})"
    played.clear()
    audio.play_sound(name, 3, 0.35)
    y, sr, dev = played[0]
    assert dev == 3 and sr == 48000 and y.dtype == np.float32, (dev, sr, y.dtype)
    assert abs(np.abs(y).max() - 0.35) < 1e-3, "le pic est normalisé au volume demandé"
    assert not y[-int(0.3 * sr):].any(), "0,3 s de silence à la fin (sinon le pilote MME coupe le son)"

# tous les formats PCM, 2 canaux: on garde le 1er, la valeur lue est celle qui a été écrite
tmp = Path(tempfile.mkdtemp(prefix="ruby_audio_"))
ref = np.array([0.0, 0.5, -0.5, 0.25, -1.0 + 2**-15], np.float64)
for width in (1, 2, 3, 4):
    levels = (1 << (8 * width - 1)) - 1
    ints = np.rint(ref * levels).astype(np.int64)
    if width == 1:
        data = (ints + 128).astype(np.uint8)
        frames = np.stack([data, data[::-1]], 1).tobytes()  # le 2e canal est l'inverse: il ne doit pas être lu
    elif width == 3:
        b = lambda v: [(v >> (8 * i)) & 0xFF for i in range(3)]
        frames = bytes(sum(([*b(int(l)), *b(int(r))] for l, r in zip(ints, ints[::-1])), []))
    else:
        d = np.int16 if width == 2 else np.int32
        frames = np.stack([ints.astype(d), ints[::-1].astype(d)], 1).tobytes()
    f = tmp / f"{width}.wav"
    with wave.open(str(f), "wb") as w:
        w.setnchannels(2), w.setsampwidth(width), w.setframerate(22050)
        w.writeframes(frames)
    x, sr = audio.read_wav(f)
    assert sr == 22050 and len(x) == len(ref), (width, sr, len(x))
    assert np.abs(x - ref).max() < 2.0 / (1 << (8 * width - 1)) + 1e-6, (width, x, ref)

import shutil
shutil.rmtree(tmp, ignore_errors=True)
print("OK")
