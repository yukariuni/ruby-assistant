"""End-to-end run of the REAL listening loop, with no microphone, no speakers and no side effects:

simulated microphone (your voice recorded during enrollment + a real command from logs/) -> real wake-word detector -> Whisper preloading
-> recording until silence -> real transcription -> (simulated action) -> real Supertonic voice -> simulated sounddevice.
The real 24-bit sounds go through audio.play_sound. Memory is sampled every 5 ms.

Prerequisites: enrolled voice (voice/samples.npz), downloaded models, one recording logs/cmd-*.wav ("python ruby.py --debug").
Run from the project root:   .venv\\Scripts\\python tools\\e2e_listen.py
"""
import glob
import os
import sys
import tempfile
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)
os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("GROQ_API_KEY", None)
import numpy as np
from PySide6.QtWidgets import QApplication
from scipy.io import wavfile

import actions
import audio
import config
import engine
import wake
from memory import private_mb

clips = sorted(glob.glob("logs/cmd-*.wav"))
if not config.SAMPLES_FILE.exists() or not clips:
    sys.exit("An enrolled voice (Settings > Listening) and a recording logs/cmd-*.wav ('python ruby.py --debug') are required.")
app = QApplication([])
config.CACHE = Path(tempfile.mkdtemp(prefix="ruby_cache_"))
actions.act = lambda text, L: (True, "J'ouvre le bloc-notes.")  # no real action

CHUNK = wake.CHUNK
rng = np.random.default_rng(1)
quiet = lambda n: (rng.normal(size=n) * 8).astype(np.int16)
wake_clip = np.load(config.SAMPLES_FILE)["pos"][0]
cmd_clip = wavfile.read(clips[0])[1].astype(np.int16)
feed = np.concatenate([quiet(16000), wake_clip[:40000], quiet(4000), cmd_clip, quiet(16000 * 3)])  # 2.5 s of the wake phrase, then the command
t_feed, played = [None], []  # played: (time, frequency, duration)


class FakeStream:
    """A microphone that plays `feed` in real time, in chunks of 80 ms like the real one."""

    def __init__(self, samplerate=None, channels=None, dtype=None, blocksize=None, device=None, callback=None):
        self.cb, self.stop = callback, threading.Event()

    def __enter__(self):
        def run():
            t_feed[0] = time.time()
            for i in range(0, len(feed) - CHUNK + 1, CHUNK):
                if self.stop.is_set():
                    return
                self.cb(feed[i:i + CHUNK, None].copy(), CHUNK, None, None)
                time.sleep(CHUNK / 16000)
            while not self.stop.is_set():  # then silence
                self.cb(quiet(CHUNK)[:, None], CHUNK, None, None)
                time.sleep(CHUNK / 16000)
        threading.Thread(target=run, daemon=True).start()
        return self

    def __exit__(self, *a):
        self.stop.set()


audio.sd.InputStream = FakeStream
audio.sd.play = lambda x, sr, device=None: played.append((time.time(), sr, len(x) / sr))
audio.sd.wait = lambda: time.sleep(played[-1][2])  # playback blocks for the whole sound, like sounddevice

peak, stop = [0], threading.Event()


def sampler():
    while not stop.is_set():
        peak[0] = max(peak[0], private_mb())
        time.sleep(0.005)


cfg = config.load_cfg()
cfg["groq_key"] = ""
states = []
w = engine.Worker(cfg, lambda s: states.append((round(time.time() - (t_feed[0] or time.time()), 2), s, w.loaded())))
engine.trim()
time.sleep(0.4)
threading.Thread(target=sampler, daemon=True).start()
print(f"engine idle: {private_mb()} MB | wake phrases: {config.phrases(cfg['synced'])} | threshold {cfg['threshold']}")
t = threading.Thread(target=w.listen, daemon=True)
t.start()
deadline = time.time() + 60
while time.time() < deadline and not (w.reply and states and states[-1][1] == "listening" and len(played) >= 2):
    time.sleep(0.1)
time.sleep(0.5)
w.stop.set()
t.join(5)
stop.set()
print("\nstates (seconds since the start of the stream, state, loaded models):")
last = None
for s in states:
    if s[1:] != last:
        print("  ", s)
        last = s[1:]
print(f"\ntranscription: {w.text!r}\nspoken reply: {w.reply!r}")
print("sounds played (t, Hz, duration):", [(round(p[0] - t_feed[0], 2), p[1], round(p[2], 2)) for p in played])
ok = bool(w.reply) and len(played) >= 2 and not w.loaded() and peak[0] <= config.MEM_LIMIT
print(f"==> memory peak over the whole loop: {peak[0]} MB (budget {config.MEM_LIMIT}) | models still loaded: {w.loaded()} | {'OK' if ok else 'FAILED'}")
sys.exit(0 if ok else 1)
