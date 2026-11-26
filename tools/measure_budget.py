"""Real memory budget of the engine: the actual Worker (with Qt), your real models and recordings, and no side effects
(no action executed, no sound played, no network, voice cache in a temporary folder).

A sampler reads the private working set (the "Memory" column of the Windows Task Manager) every 5 ms: the transient peaks are what
exceed the budget (config.MEM_LIMIT), not the average.

Prerequisites: Ruby launched at least once (models downloaded) and one recording logs/cmd-*.wav ("python ruby.py --debug" saves one per command).
Run from the project root:   .venv\\Scripts\\python tools\\measure_budget.py        (TIMELINE=1 prints a detailed timeline)
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
from PySide6.QtWidgets import QApplication
from scipy.io import wavfile

import actions
import audio
import brain
import config
import engine
from memory import private_mb

clips = sorted(glob.glob("logs/cmd-*.wav"))
if not clips:
    sys.exit("A recording logs/cmd-*.wav is required: run 'python ruby.py --debug' and give Ruby a command.")
clips = [wavfile.read(clips[0])[1], wavfile.read(clips[-1])[1]]

app = QApplication([])
config.CACHE = Path(tempfile.mkdtemp(prefix="ruby_cache_"))  # never the real phrase cache
plays, replies = [], iter(())
audio.play = lambda *a, **k: plays.append(time.time())
audio.play_sound = lambda *a: None
audio.device_index = lambda *a: None
actions.act = lambda text, L: (True, "J'ouvre le bloc-notes.")  # no real action


def groq(text, L, cfg):
    time.sleep(0.7)  # typical Groq network latency
    return True, next(replies)


brain.ask = lambda text, L, cfg: groq(text, L, cfg) if cfg["groq_key"] else None  # no key: local rules, like the real engine

peak, seg, events, t_ref, stop = [0], [0], [], [time.time()], threading.Event()


def sampler():
    while not stop.is_set():
        v = private_mb()
        peak[0], seg[0] = max(peak[0], v), max(seg[0], v)
        time.sleep(0.005)


def mark(label):
    events.append((time.time() - t_ref[0], label, private_mb(), seg[0]))
    seg[0] = 0


def wrap(obj, name, label):
    f = getattr(obj, name)

    def g(*a, **k):
        mark(label + " >")
        try:
            return f(*a, **k)
        finally:
            mark(label + " <")
    setattr(obj, name, g)


cfg = config.load_cfg()
print(f"configuration: Whisper {cfg['whisper']} | voice {cfg['engine']} {cfg['voice']} | language {cfg['lang']}")
w = engine.Worker(cfg, lambda s: None)
t = time.time()
w.ensure_whisper()  # what the engine does at startup: creates the int8 copy when missing (first time only)
print(f"ensure_whisper: {time.time() - t:.1f} s")
for o, n, label in ((w, "model", "Whisper.load"), (w, "release_whisper", "Whisper.release"), (w, "release_voice", "voice.release"),
                    (w.speaker, "load", "voice.load"), (w.speaker, "render", "voice.render"), (w, "handle", "handle")):
    wrap(o, n, label)
engine.trim()
time.sleep(0.5)
threading.Thread(target=sampler, daemon=True).start()
print(f"engine baseline (Python + Qt + onnxruntime, no model loaded): {private_mb()} MB\n")
rows = []


def scenario(name, pcm, groq_key, sentences=()):
    global replies
    replies = iter(sentences)
    w.cfg["groq_key"] = groq_key
    plays.clear()
    peak[0] = 0
    w.preload()  # the wake word has just been detected
    time.sleep(1.6)  # the user speaks for about 1.6 s: Whisper loads meanwhile
    t0 = time.time()  # end of the utterance
    events.clear(), t_ref.__setitem__(0, t0), mark("end of utterance")
    w.handle(pcm)
    lat = (plays[0] - t0) if plays else float("nan")
    time.sleep(0.4)
    rows.append((name, peak[0], private_mb(), lat))
    print(f"{name:<54} peak {peak[0]:>4} MB | after {private_mb():>3} MB | first sound {lat:4.1f} s after the end of the utterance | loaded: {w.loaded()}", flush=True)
    if os.environ.get("TIMELINE"):
        for ts, label, m, pk in events:
            print(f"      +{ts:5.2f}s {label:<22} memory {m:>4} MB | peak since previous event {pk:>4} MB")


scenario("1. local rules, new sentence (voice loaded)", clips[0], "")
scenario("2. local rules, same sentence (served from disk)", clips[0], "")
scenario("3. Groq, new sentence (voice loaded while Groq thinks)", clips[-1], "gsk_fake", ["Il est dix-sept heures quarante, tu as encore le temps."])
scenario("4. Groq, another new sentence", clips[0], "gsk_fake", ["Je ne sais pas, mais je peux le chercher sur Google si tu veux."])
scenario("5. local rules, same sentence as 1 (served from disk)", clips[-1], "")
w.cfg["groq_key"] = ""
engine.trim()
time.sleep(0.6)
print(f"\nidle after everything (models released, pages trimmed): {private_mb()} MB")
stop.set()
worst = max(r[1] for r in rows)
verdict = "OK" if worst <= config.MEM_LIMIT else "EXCEEDED"
print(f"==> ENGINE PEAK over the whole cycle: {worst} MB (budget {config.MEM_LIMIT} MB, {config.MEM_LIMIT - worst} MB left for the settings window) {verdict}")
sys.exit(0 if worst <= config.MEM_LIMIT else 1)
