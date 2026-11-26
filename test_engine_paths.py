"""Auto-vérif du moteur: dossiers choisis, téléchargements annoncés, plafond de mémoire (Whisper et la voix jamais ensemble), cache vocal, migration.

Les bibliothèques (Whisper, Supertonic) sont remplacées par des doubles qui enregistrent leurs arguments: rien n'est téléchargé,
et aucun fichier de l'utilisateur n'est touché. Lancer: .venv\\Scripts\\python test_engine_paths.py
(La mesure réelle du pic de mémoire avec les vrais modèles se fait à part: voir le résumé de la session / test_memory.py.)
"""
import gc
import logging
import os
import shutil
import sys
import tempfile
import threading
import time
import types
import weakref
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
os.environ.pop("GROQ_API_KEY", None)  # le test décide lui-même s'il y a une clé
import numpy as np

import actions
import audio
import config
import engine
import models
import tts
import wake

tmp = Path(tempfile.mkdtemp(prefix="ruby_engine_"))
models.default_folder = lambda kind: tmp / "defaut" / kind
config.MODEL_FILE, config.LEGACY_MODEL = tmp / "voice" / "wake.npz", tmp / "voice" / "wake.pkl"  # jamais les vrais fichiers
config.CACHE = tmp / "cache"  # jamais le vrai cache des phrases


def write(p, data=b"x" * 100):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(data)


def join_threads():
    for t in threading.enumerate():
        if t is not threading.current_thread() and t.daemon and t.name.startswith("Thread-"):
            t.join(5)


# ---------- Whisper: dossier choisi, copie int8 préférée, aucun réseau si installé, pas de préchauffage
calls, states = [], []
installed = {"yes": True}


class FakeWhisper:
    def __init__(self, name, device=None, compute_type=None, download_root=None, local_files_only=False):
        calls.append(dict(name=name, root=download_root, local=local_files_only))
        if local_files_only and not installed["yes"]:
            raise FileNotFoundError("pas dans le cache")  # ce que fait huggingface_hub quand le modèle manque

    def transcribe(self, *a, **k):
        raise AssertionError("pas de préchauffage: mesuré, il ne rend pas la 1re commande plus rapide")


downloads = []
fw = types.ModuleType("faster_whisper")
fw.WhisperModel = FakeWhisper
fw_utils = types.ModuleType("faster_whisper.utils")
fw_utils.download_model = lambda name, cache_dir=None: downloads.append(("whisper", name, cache_dir))
fw.utils = fw_utils
sys.modules.update({"faster_whisper": fw, "faster_whisper.utils": fw_utils})

cfg = dict(config.load_cfg(), whisper="small", paths=dict(whisper="", voice="", wake=""))
wk = engine.Worker(cfg, states.append)

wk.model()
assert calls == [dict(name="small", root=None, local=True)], "déjà installé: chargé en local, sans réseau, au dossier par défaut"
assert states == [], "charger un modèle ne change pas l'état affiché (seuls les téléchargements le font)"
wk.model()
assert len(calls) == 1, "même modèle, même dossier: pas de rechargement"

root = str(tmp / "ia" / "whisper")
cfg["paths"]["whisper"] = root
wk.model()
assert calls[-1] == dict(name="small", root=root, local=True), "dossier choisi: transmis à Whisper, et rechargé"

# la copie int8 (voir models.quantize_ct2) est ce que Whisper charge: sans elle son chargement monte à 680 Mo
small = tmp / "ia" / "whisper" / "models--Systran--faster-whisper-small"
write(small / "snapshots" / "h" / "model.bin")
wk.model()
assert calls[-1]["name"] == "small", "pas encore de copie int8: on garde le nom du modèle"
write(small / "ruby-int8" / "model.bin")
wk.release_whisper()
wk.model()
assert calls[-1] == dict(name=str(small / "ruby-int8"), root=root, local=True), "la copie int8 existe: c'est elle qui est chargée"

# supprimé pendant que Ruby tournait: retéléchargé et reconverti, sans jamais charger le gros fichier d'origine sans passer par là
cfg["whisper"] = "base"
installed["yes"] = False
calls.clear(), downloads.clear()
int8_calls = []
real_int8 = models.ensure_int8
models.ensure_int8 = lambda c, n: int8_calls.append(n) or False
wk.model()
assert calls == [dict(name="base", root=root, local=True), dict(name="base", root=root, local=False)], calls
assert downloads == [("whisper", "base", root)] and int8_calls == ["base"], (downloads, int8_calls)
assert wk.whisper_key == ("base", root)
assert wk.loaded() == ["Whisper base"]
models.ensure_int8 = real_int8

# ---------- téléchargements annoncés: avant de démarrer, sans rien charger en mémoire
voice_dl = []
sup_loader = types.ModuleType("supertonic.loader")
sup_loader.download_model = lambda d: voice_dl.append(str(d))
sup = types.ModuleType("supertonic")
sup.loader = sup_loader
sys.modules.update({"supertonic": sup, "supertonic.loader": sup_loader})
wake_dl = []
real_ensure = models.ensure_wake
models.ensure_wake = lambda d: wake_dl.append(str(d))
cfg2 = dict(config.load_cfg(), whisper="base", engine=config.SUPERTONIC,
            paths=dict(whisper=str(tmp / "w2"), voice=str(tmp / "v2"), wake=str(tmp / "k2")))
states2 = []
w2 = engine.Worker(cfg2, lambda s: states2.append((s, w2.detail)))
w2.ensure_downloaded()
assert downloads[-1] == ("whisper", "base", str(tmp / "w2")), downloads
assert wake_dl == [str(tmp / "k2")] and voice_dl == [str(tmp / "v2")]
assert [s for s, _ in states2] == ["downloading"] * 4 + ["starting"], states2
assert "Whisper base" in states2[0][1] and "Optimisation" in states2[1][1] and states2[-1][1] == "", "le détail disparaît une fois fini"
assert w2.loaded() == [], "télécharger ne charge rien en mémoire"
# tout est déjà installé, mais pas encore optimisé: l'optimisation (une seule fois) est annoncée, sans aucun téléchargement
b2 = tmp / "w2" / "models--Systran--faster-whisper-base"
write(b2 / "snapshots" / "h" / "model.bin")
for f in models.VOICE_FILES:
    write(tmp / "v2" / f)
for f in models.WAKE_FILES:
    write(tmp / "k2" / f)
made_int8 = []
models.ensure_int8 = lambda c, n: made_int8.append(n) or write(b2 / "ruby-int8" / "model.bin") or True
downloads.clear(), wake_dl.clear(), voice_dl.clear(), states2.clear()
w2.ensure_downloaded()
assert not downloads and not wake_dl and not voice_dl and made_int8 == ["base"], (downloads, made_int8)
assert [s for s, _ in states2] == ["downloading", "starting"] and states2[0][1].startswith("Optimisation"), states2
# tout est prêt: aucun état « Téléchargement », aucun accès réseau, rien à convertir
states2.clear()
w2.ensure_downloaded()
assert made_int8 == ["base"] and [s for s, _ in states2] == ["starting"], (made_int8, states2)
# la conversion échoue (disque plein…): Ruby démarre quand même, avec le fichier d'origine
shutil.rmtree(b2 / "ruby-int8")


def broken(c, n):
    raise OSError("disque plein")


models.ensure_int8 = broken
logging.disable(logging.CRITICAL)
w2.ensure_downloaded()
logging.disable(logging.NOTSET)
assert w2.cfg["whisper"] == "base" and [s for s, _ in states2][-1] == "starting"
models.ensure_int8 = real_int8
models.ensure_wake = real_ensure

# ---------- voix Supertonic: dossier choisi, téléchargement seulement si elle manque
made = []


class FakeTTS:
    sample_rate = 44100

    def __init__(self, model_dir=None, auto_download=True, **k):
        made.append(dict(dir=model_dir, dl=auto_download))


sup.TTS = FakeTTS
vc = dict(config.load_cfg(), paths=dict(whisper="", voice=str(tmp / "voix"), wake=""))
sp = tts.Speaker()
sp.load(vc)
assert made == [dict(dir=str(tmp / "voix"), dl=True)], "pas installée: on la télécharge dans le dossier choisi"
for f in models.VOICE_FILES:
    write(tmp / "voix" / f)
made.clear()
sp.load(vc)
assert made == [], "même dossier: déjà chargée"
vc["paths"]["voice"] = str(tmp / "voix2")
shutil.copytree(tmp / "voix", tmp / "voix2")
sp.load(vc)
assert made == [dict(dir=str(tmp / "voix2"), dl=False)], "installée dans le nouveau dossier: rechargée de là, SANS téléchargement"
vc["paths"]["voice"] = ""
made.clear()
sp.load(vc)
assert made == [dict(dir=None, dl=True)], "dossier par défaut vide: la bibliothèque choisit, et télécharge car il n'y a rien"
wk.release(), sp.unload()
gc.collect()

# ---------- plafond de mémoire: Whisper et la voix ne sont JAMAIS chargés en même temps (à eux deux ≈700 Mo, le plafond est 500)
live, peak, log = dict(whisper=0, voice=0), [0], []


def born(kind, obj):
    live[kind] += 1
    peak[0] = max(peak[0], sum(live.values()))
    log.append(kind + "+")

    def died():
        live[kind] -= 1
        log.append(kind + "-")
    weakref.finalize(obj, died)


heard = [" ouvre Discord "]  # ce que le faux Whisper « entend »; "" = rien d'intelligible


class Whisper3:
    def __init__(self, name, **k):
        born("whisper", self)
        time.sleep(0.05)

    def transcribe(self, pcm, language=None, vad_filter=None, initial_prompt=None, temperature=None):
        assert pcm.dtype == np.float32 and language == "fr"
        assert temperature == 0.0, "un seul essai: le repli en température (best_of=5) fait monter le pic à 850 Mo, plafond 500"
        return [types.SimpleNamespace(text=heard[0])] if heard[0] else [], types.SimpleNamespace(language="fr", language_probability=0.99)


class Tts3:
    sample_rate = 22050

    def __init__(self, model_dir=None, auto_download=True, **k):
        born("voice", self)
        time.sleep(0.05)

    def get_voice_style(self, name):
        return name

    def synthesize(self, text, voice_style=None, lang=None, total_steps=None, speed=None):
        return np.full((1, 2205), 0.25, np.float32), np.array([0.1])


fw.WhisperModel, sup.TTS = Whisper3, Tts3
sounds = []  # petits sons joués (« ready », « fail »)
audio.play, audio.play_sound, audio.device_index = lambda *a, **k: None, lambda name, *a: sounds.append(name), lambda *a: None
trims = []
engine.trim = lambda: trims.append(1)  # le vidage du jeu de travail n'a lieu qu'après une libération
shut = dict(config.load_cfg(), whisper="small", engine=config.SUPERTONIC, groq_key="", paths=dict(whisper="", voice="", wake=""))
w5 = engine.Worker(shut, lambda s: None)
pcm = np.zeros(16000, np.int16)
actions.act = lambda text, L: (True, "J'ouvre Discord.")
assert w5.loaded() == [], "au repos: aucun modèle en mémoire"

# 1. sans Groq (règles locales): Whisper pendant la phrase, libéré, PUIS la voix, libérée dès que Ruby a fini de parler
w5.preload()
join_threads()
assert w5.loaded() == ["Whisper small"], "au mot d'activation seul Whisper se charge: la voix attend"
w5.handle(pcm)
assert log == ["whisper+", "whisper-", "voice+", "voice-"], log
assert w5.loaded() == [] and w5.text == "ouvre Discord" and w5.reply == "J'ouvre Discord."
assert any(config.CACHE.glob("*.wav")), "la phrase est gardée sur disque"
# 2. la même phrase: lue depuis le disque, la voix n'est même pas chargée
log.clear()
w5.preload()
join_threads()
w5.handle(pcm)
assert log == ["whisper+", "whisper-"], "phrase déjà dite: la voix (1-2 s, 415 Mo) n'est pas chargée"
# 3. avec Groq: la voix se charge pendant que Groq réfléchit, Whisper est déjà parti
log.clear()
w5.cfg["groq_key"] = "gsk_test"
seen = []


def slow_groq(text, L, cfg):
    seen.append(("Whisper déjà libéré", w5.whisper is None))
    time.sleep(0.4)  # Groq réfléchit: la voix a le temps de se charger en parallèle
    seen.append(("voix chargée d'avance", live["voice"] == 1))
    return True, "Une phrase que je n'ai jamais dite."


engine.brain.ask = slow_groq
w5.preload()
join_threads()
w5.handle(pcm)
assert seen == [("Whisper déjà libéré", True), ("voix chargée d'avance", True)], seen
assert log == ["whisper+", "whisper-", "voice+", "voice-"], log
assert w5.loaded() == []
# 4. Groq plante en route: la voix chargée d'avance est quand même libérée
log.clear()


def boom(text, L, cfg):
    time.sleep(0.2)
    raise RuntimeError("boom")


engine.brain.ask = boom
logging.disable(logging.CRITICAL)
w5.preload()
join_threads()
w5.handle(pcm)
logging.disable(logging.NOTSET)
assert w5.loaded() == [] and log == ["whisper+", "whisper-", "voice+", "voice-"], (w5.loaded(), log)
# 5. personne n'a parlé: Whisper préchargé au mot d'activation est libéré quand même
log.clear()
w5.record = lambda q, noise: None
w5.preload()
join_threads()
assert w5.loaded() == ["Whisper small"]
w5.command(None, 0.0)
assert w5.loaded() == [] and log == ["whisper+", "whisper-"], log
# 6. la voix est encore chargée au mot d'activation (cas anormal): elle part AVANT que Whisper naisse
w5.speaker.load(w5.cfg)
log.clear()
w5.preload()
join_threads()
assert log == ["voice-", "whisper+"], log
w5.release()
# 7. voix en ligne (Edge): aucune voix locale n'est jamais chargée
log.clear()
w5.cfg["engine"] = config.EDGE
w5.cfg["voice"] = config.VOICES[config.EDGE]["Français"][0]
tts.Speaker._edge = staticmethod(lambda text, cfg: np.zeros(2400, np.int16))
engine.brain.ask = lambda text, L, cfg: (True, "Réponse en ligne.")
w5.preload()
join_threads()
w5.handle(pcm)
assert log == ["whisper+", "whisper-"] and w5.reply == "Réponse en ligne.", log
w5.cfg["engine"], w5.cfg["voice"] = config.SUPERTONIC, "F1"
assert peak[0] == 1, f"jamais plus d'un gros modèle à la fois (vu: {peak[0]})"
w5.release()
# 8. pas compris: UNIQUEMENT le son d'échec, jamais une phrase (« Je ne comprends pas la demande. » était dit à voix haute)
actions.act = lambda text, L: (True, "J'ouvre Discord.")
w5.cfg["groq_key"] = ""
engine.brain.ask = lambda text, L, cfg: (_ for _ in ()).throw(AssertionError("sans texte, on n'interroge même pas Groq"))
heard[0] = ""  # Whisper n'a rien compris (bruit): ni Groq, ni règles locales, ni voix
sounds.clear(), log.clear()
w5.reply = "ancienne réponse"
w5.preload()
join_threads()
w5.handle(pcm)
assert sounds == ["fail"] and w5.reply == "" and log == ["whisper+", "whisper-"], (sounds, w5.reply, log)
heard[0] = " c'est né "  # du texte, mais Groq (ou les règles) répond « pas compris »: (False, None)
for brain_ask, key in ((lambda text, L, cfg: (False, None), "gsk_test"), (lambda text, L, cfg: None, "")):
    engine.brain.ask = brain_ask
    actions.act = lambda text, L: (False, None)
    w5.cfg["groq_key"] = key
    sounds.clear(), log.clear()
    w5.reply = "ancienne réponse"
    w5.preload()
    join_threads()
    w5.handle(pcm)
    assert sounds == ["fail"] and w5.reply == "" and w5.loaded() == [], (key, sounds, w5.reply)
heard[0] = " ouvre Discord "
w5.cfg["groq_key"] = ""
w5.release()

# ---------- mémoire rendue à Windows: seulement quand plus aucun modèle n'est chargé
trims.clear()
w5.model()
w5.settle()
assert trims == [], "des modèles sont chargés: on ne vide surtout pas la mémoire (ils partiraient sur le disque)"
whisper_ref = weakref.ref(w5.whisper)
w5.release_whisper()
gc.collect()
assert whisper_ref() is None, "l'objet modèle est vraiment détruit (la mémoire est rendue à Windows)"
assert trims == [1], "la mémoire inutilisée est rendue à Windows après la libération"
w5.release_whisper(), w5.release_voice()
assert trims == [1], "rien à libérer: rien à vider"
w5.settle()
assert trims == [1, 1], "rien de gros n'est chargé: on rend ce qui ne sert plus"
trims.clear()
w5.tidy()
assert trims == [1], "au repos, sans modèle: la mémoire non touchée est reprise"
w5.tidy()
assert trims == [1], "pas plus d'une fois toutes les 30 s"
w5.last_trim = time.time() - 31
w5.tidy()
assert trims == [1, 1], "30 s plus tard: de nouveau"
w5.model()
w5.last_trim = 0.0
w5.tidy()
assert trims == [1, 1], "un modèle est chargé: on ne vide JAMAIS la mémoire (il partirait sur le disque)"
w5.release()

# ---------- cache vocal sur disque: borné, les moins utilisées partent d'abord, jamais bloquant
tts.CACHE_MAX = 3
k = lambda i: ("test", i)
for i in range(5):
    tts.store(k(i), np.full(100, 0.5, np.float32), 24000)
    time.sleep(0.03)  # des dates de modification bien distinctes
assert len(list(config.CACHE.glob("*.wav"))) == 3 and tts.cached(k(0)) is None and tts.cached(k(1)) is None, "au-delà de 3: les plus anciennes partent"
x, sr = tts.cached(k(4))
assert sr == 24000 and x.dtype == np.int16 and abs(int(x[0]) - 16383) <= 1, "gardée en 16 bits"
time.sleep(0.03)
tts.cached(k(2))  # utilisée récemment
time.sleep(0.03)
tts.store(k(5), np.zeros(10, np.float32), 24000)
assert tts.cached(k(2)) is not None and tts.cached(k(3)) is None, "ce qui vient d'être rejoué est gardé, la moins récente part"
raw = np.arange(10, dtype=np.int16)
tts.store(("edge",), raw, 24000)
assert np.array_equal(tts.cached(("edge",))[0], raw), "audio déjà en 16 bits (Edge): gardé tel quel"
tts._file(k(9)).write_bytes(b"pas un wav")
assert tts.cached(k(9)) is None, "fichier abîmé: on recalcule"
assert not list(config.CACHE.glob("*.tmp")), "pas de fichier temporaire qui traîne"
write(tmp / "fichier", b"x")
real_cache, config.CACHE = config.CACHE, tmp / "fichier" / "cache"
logging.disable(logging.CRITICAL)
tts.store(k(7), np.zeros(10, np.float32), 24000)  # impossible d'écrire: ne doit jamais empêcher Ruby de parler
logging.disable(logging.NOTSET)
config.CACHE = real_cache

# ---------- openWakeWord: les 2 modèles lus depuis le dossier choisi (vrais fichiers ONNX, copiés d'ici)
(tmp / "wk").mkdir()
for f in models.WAKE_FILES:
    shutil.copy(config.WAKE_DEFAULT / f, tmp / "wk" / f)
feats = wake.features(str(tmp / "wk"))
feats(np.zeros(wake.CHUNK, np.int16))
assert feats.feature_buffer.shape[1] == 96, "l'extracteur construit depuis le dossier choisi fonctionne"
assert wake.features(None).feature_buffer.shape[1] == 96, "dossier par défaut inchangé"
d = wake.Detector(object(), str(tmp / "wk"))
assert d.feats.mel.get_inputs()[0].name == "input", "le détecteur transmet bien le dossier"

# ---------- ancien format de voix apprise: converti automatiquement, dans un autre processus
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
import joblib
rng = np.random.default_rng(0)
X = rng.normal(size=(120, 1536))
y = (X[:, 0] > 0).astype(int)
pipe = make_pipeline(StandardScaler(), LogisticRegression(max_iter=500)).fit(X, y)
config.LEGACY_MODEL.parent.mkdir(parents=True, exist_ok=True)
joblib.dump(pipe, config.LEGACY_MODEL)
assert not config.MODEL_FILE.exists()
w5.migrate()
assert config.MODEL_FILE.exists(), "l'ancienne voix apprise a été convertie"
assert abs(wake.Classifier.load(config.MODEL_FILE).proba(X[0]) - pipe.predict_proba(X[:1])[0, 1]) < 1e-9
t0 = config.MODEL_FILE.stat().st_mtime
w5.migrate()
assert config.MODEL_FILE.stat().st_mtime == t0, "déjà converti: rien à refaire"

# ---------- anciens réglages: le mode mémoire n'existe plus, « medium » (≈800 Mo) dépasserait le plafond
real_file = config.CFG_FILE
config.CFG_FILE = tmp / "config.json"
config.CFG_FILE.write_text('{"ram": "fast", "whisper": "medium"}', "utf-8")
old = config.load_cfg()
assert "ram" not in old and old["whisper"] == "small", old
config.CFG_FILE = real_file

shutil.rmtree(tmp, ignore_errors=True)
print("OK")
