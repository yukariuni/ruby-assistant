"""Budget mémoire RÉEL du moteur: le vrai Worker (avec Qt), tes vrais modèles, tes vrais enregistrements, aucun effet de bord
(aucune action exécutée, aucun son joué, aucun réseau, cache vocal dans un dossier temporaire).

Un échantillonneur relève la mémoire privée (la colonne « Mémoire » du Gestionnaire des tâches) toutes les 5 ms: ce sont les pics
transitoires qui dépassent le plafond (config.MEM_LIMIT), pas la valeur moyenne.

Prérequis: Ruby lancé au moins une fois (modèles téléchargés) et un enregistrement logs/cmd-*.wav (python ruby.py --debug en crée un par commande).
Lancer depuis la racine du projet:   .venv\\Scripts\\python tools\\measure_budget.py        (TIMELINE=1: chronologie détaillée)
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
    sys.exit("Il faut un enregistrement logs/cmd-*.wav: lance « python ruby.py --debug » et donne un ordre à Ruby.")
clips = [wavfile.read(clips[0])[1], wavfile.read(clips[-1])[1]]

app = QApplication([])
config.CACHE = Path(tempfile.mkdtemp(prefix="ruby_cache_"))  # jamais le vrai cache des phrases
plays, replies = [], iter(())
audio.play = lambda *a, **k: plays.append(time.time())
audio.play_sound = lambda *a: None
audio.device_index = lambda *a: None
actions.act = lambda text, L: (True, "J'ouvre le bloc-notes.")  # aucune vraie action


def groq(text, L, cfg):
    time.sleep(0.7)  # latence réseau typique de Groq
    return True, next(replies)


brain.ask = lambda text, L, cfg: groq(text, L, cfg) if cfg["groq_key"] else None  # sans clé: règles locales, comme le vrai moteur

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
print(f"config réelle: Whisper {cfg['whisper']} | voix {cfg['engine']} {cfg['voice']} | langue {cfg['lang']}")
w = engine.Worker(cfg, lambda s: None)
t = time.time()
w.ensure_whisper()  # ce que le moteur fait au démarrage: crée la copie int8 si elle manque (1re fois seulement)
print(f"ensure_whisper: {time.time() - t:.1f} s")
for o, n, label in ((w, "model", "Whisper.charger"), (w, "release_whisper", "Whisper.libérer"), (w, "release_voice", "voix.libérer"),
                    (w.speaker, "load", "voix.charger"), (w.speaker, "render", "voix.rendre"), (w, "handle", "handle")):
    wrap(o, n, label)
engine.trim()
time.sleep(0.5)
threading.Thread(target=sampler, daemon=True).start()
print(f"base du moteur (Python + Qt + onnxruntime, modèles non chargés): {private_mb()} Mo\n")
rows = []


def scenario(name, pcm, groq_key, sentences=()):
    global replies
    replies = iter(sentences)
    w.cfg["groq_key"] = groq_key
    plays.clear()
    peak[0] = 0
    w.preload()  # « Hey Ruby » vient d'être détecté
    time.sleep(1.6)  # l'utilisateur parle ≈1,6 s: Whisper se charge pendant ce temps
    t0 = time.time()  # fin de la phrase
    events.clear(), t_ref.__setitem__(0, t0), mark("fin de ta phrase")
    w.handle(pcm)
    lat = (plays[0] - t0) if plays else float("nan")
    time.sleep(0.4)
    rows.append((name, peak[0], private_mb(), lat))
    print(f"{name:<52} pic {peak[0]:>4} Mo | après {private_mb():>3} Mo | 1er son {lat:4.1f} s après la fin de ta phrase | chargé: {w.loaded()}", flush=True)
    if os.environ.get("TIMELINE"):
        for ts, label, m, pk in events:
            print(f"      +{ts:5.2f}s {label:<22} mémoire {m:>4} Mo | pic depuis l'évènement précédent {pk:>4} Mo")


scenario("1. règles locales, phrase nouvelle (voix chargée)", clips[0], "")
scenario("2. règles locales, même phrase (sur disque)", clips[0], "")
scenario("3. Groq, phrase inédite (voix chargée pendant Groq)", clips[-1], "gsk_fake", ["Il est dix-sept heures quarante, tu as encore le temps."])
scenario("4. Groq, autre phrase inédite", clips[0], "gsk_fake", ["Je ne sais pas, mais je peux le chercher sur Google si tu veux."])
scenario("5. règles locales, même phrase qu'en 1 (sur disque)", clips[-1], "")
w.cfg["groq_key"] = ""
engine.trim()
time.sleep(0.6)
print(f"\nrepos après tout (modèles libérés, pages reprises): {private_mb()} Mo")
stop.set()
worst = max(r[1] for r in rows)
verdict = "OK" if worst <= config.MEM_LIMIT else "DÉPASSÉ"
print(f"==> PIC DU MOTEUR sur tout le cycle: {worst} Mo (plafond {config.MEM_LIMIT} Mo, il reste {config.MEM_LIMIT - worst} Mo pour la fenêtre de réglages) {verdict}")
sys.exit(0 if worst <= config.MEM_LIMIT else 1)
