"""Auto-vérif de l'assistant « Apprendre ma voix » de bout en bout, avec des voix de synthèse (pas de micro, pas de fenêtre).

Les fichiers de l'utilisateur (config.json, voice/wake.pkl) ne sont pas touchés: tout est redirigé vers un dossier temporaire.
Lancer: .venv\\Scripts\\python test_sync.py
"""
import os
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
import numpy as np
from PySide6.QtWidgets import QApplication
from scipy.signal import resample_poly

import audio
import config
import settings
import wake

np.random.seed(0)  # voix de synthèse et bruit reproductibles: le test donne le même résultat à chaque lancement
tmp = Path(tempfile.mkdtemp())
config.CFG_FILE, config.MODEL_FILE, config.SAMPLES_FILE = tmp / "config.json", tmp / "wake.npz", tmp / "samples.npz"
config.LEGACY_MODEL = tmp / "wake.pkl"  # jamais le vrai fichier de l'utilisateur
settings.time.sleep = lambda s: None
audio.play_sound = lambda *a: None

from supertonic import TTS  # voix de synthèse: les « utilisateurs » de ce test

tts = TTS(auto_download=False)
rng = np.random.default_rng(1)
N = int(config.REC_SEC * wake.SR)


def say(text, voice="F1"):
    wav, _ = tts.synthesize(text, voice_style=tts.get_voice_style(voice), lang="en", total_steps=4)
    a = resample_poly(np.asarray(wav).squeeze(), 16000, tts.sample_rate)
    clip = np.concatenate([np.zeros(8000), a, np.zeros(N)])[:N]
    return (clip / np.abs(clip).max() * 12000 + rng.normal(0, 30, N)).astype(np.int16)


app = QApplication([])
cfg = dict(config.load_cfg(), lang="English", words="hi;hey", synced="")
d = settings.SyncDialog(None, cfg)
d.steps = ([(True, p, "") for p in ("Hi Ruby", "Hey Ruby") for _ in range(3)] + [(False, t, "") for t in config.LANGS["English"]["neg"]] + [(False, None, "")])
clips = iter([say("Hi Ruby", v) for v in ("F1", "M1", "F2")] + [say("Hey Ruby", v) for v in ("F1", "M1", "F2")]
             + [say(t) for t in config.LANGS["English"]["neg"]] + [rng.normal(0, 30, N).astype(np.int16)])
d.record = lambda: next(clips)
events = []
d.finished_ok.connect(lambda: events.append("ok"))
d.failed.connect(events.append)
d.run_steps()
assert events == ["ok"], events
assert config.MODEL_FILE.exists() and config.SAMPLES_FILE.exists()
saved = np.load(config.SAMPLES_FILE)
assert saved["pos"].shape == (6, N) and saved["neg"].shape == (5, N), (saved["pos"].shape, saved["neg"].shape)
assert config.load_cfg()["synced"] == "hi;hey"  # les mots appris sont mémorisés: le moteur accepte de démarrer

det = wake.Detector(wake.Classifier.load(config.MODEL_FILE))
def peak(clip):
    det.reset()
    x = np.concatenate([rng.normal(0, 30, wake.PAD * wake.CHUNK), clip]).astype(np.int16)
    return max(det.score(x[i:i + wake.CHUNK]) for i in range(0, len(x) - wake.CHUNK + 1, wake.CHUNK))
hit, miss = peak(say("Hey Ruby", "F2")), peak(say("What is the weather today"))
print("Hey Ruby:", round(hit, 2), "| autre phrase:", round(miss, 2))
assert hit > 0.85 > miss, f"détection: « Hey Ruby » {hit:.2f} (doit dépasser 0,85), autre phrase {miss:.2f} (doit rester sous 0,85)"
print("OK")
