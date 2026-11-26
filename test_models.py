"""Auto-vérif de models.py: emplacements, mesure, déplacement sûr, suppression. Rien n'est téléchargé, rien de l'utilisateur n'est touché.

Lancer: .venv\\Scripts\\python test_models.py
"""
import os
import shutil
import stat
import tempfile
from pathlib import Path

import config
import models

tmp = Path(tempfile.mkdtemp(prefix="ruby_models_"))


def write(p, data=b"x" * 1000):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def raises(exc, fn, *a, **k):
    try:
        fn(*a, **k)
    except exc:
        return True
    return False


# --- emplacements: défaut vs choisi
cfg = dict(config.DEFAULT, paths=dict(whisper="", voice="", wake=""))
assert not models.is_custom(cfg, "whisper") and models.custom_or_none(cfg, "whisper") is None
assert models.folder(cfg, "voice") == Path.home() / ".cache" / "supertonic3"
assert models.folder(cfg, "wake") == config.WAKE_DEFAULT
cfg["paths"]["whisper"] = str(tmp / "ia" / "whisper")
assert models.is_custom(cfg, "whisper") and models.custom_or_none(cfg, "whisper") == str(tmp / "ia" / "whisper")
assert config.DEFAULT["paths"]["whisper"] == "", "DEFAULT ne doit jamais être modifié par une config chargée"
assert config.load_cfg()["paths"] is not config.DEFAULT["paths"]

# --- Whisper: seuls les téléchargements complets comptent
w = Path(cfg["paths"]["whisper"])
write(w / "models--Systran--faster-whisper-small/snapshots/abc/model.bin", b"s" * 5000)
write(w / "models--Systran--faster-whisper-small/refs/main", b"abc")
write(w / "models--Systran--faster-whisper-base/blobs/partiel", b"b" * 100)  # téléchargement interrompu: pas de model.bin
write(w / "autre-chose-de-l-utilisateur/notes.txt")
assert set(models.whisper_dirs(cfg)) == {"small"}
assert models.installed(cfg, "whisper", "small") and not models.installed(cfg, "whisper", "base")
assert [p.name for p in models.items(cfg, "whisper")] == ["models--Systran--faster-whisper-small"]
assert models.size(models.items(cfg, "whisper", "small")) == 5003

# --- voix et mot d'activation: complets ou pas installés
v = tmp / "voix"
cfg["paths"]["voice"] = str(v)
assert not models.installed(cfg, "voice")
for f in models.VOICE_FILES[:3]:
    write(v / f)
assert not models.installed(cfg, "voice"), "il manque un fichier"
write(v / models.VOICE_FILES[3])
assert models.installed(cfg, "voice") and models.items(cfg, "voice") == [v]
cfg["paths"]["wake"] = str(tmp / "wake")
write(tmp / "wake" / models.WAKE_FILES[0])
assert not models.installed(cfg, "wake")
write(tmp / "wake" / models.WAKE_FILES[1])
assert models.installed(cfg, "wake")
config.MODEL_FILE, config.SAMPLES_FILE = tmp / "voice" / "wake.npz", tmp / "voice" / "samples.npz"
config.LEGACY_MODEL = tmp / "voice" / "wake.pkl"  # jamais le vrai fichier de l'utilisateur
assert models.items(cfg, "mine") == []
write(config.MODEL_FILE)
assert models.items(cfg, "mine") == [config.MODEL_FILE]
write(config.LEGACY_MODEL)
assert models.items(cfg, "mine") == [config.MODEL_FILE, config.LEGACY_MODEL], "l'ancien format compte aussi (et se supprime avec)"
config.LEGACY_MODEL.unlink()

# --- déplacement: copie, vérifie, puis supprime la source
src, dst = tmp / "src", tmp / "dst"
big = write(src / "a" / "gros.bin", os.urandom(9 << 20))  # > 8 Mo: plusieurs blocs
write(src / "petit.txt", b"bonjour")
progress = []
left = models.move([(src, dst)], progress=lambda d, t, n: progress.append((d, t, n)))
assert left == [] and not src.exists(), "la source doit disparaître après une copie réussie"
assert (dst / "petit.txt").read_bytes() == b"bonjour" and (dst / "a" / "gros.bin").stat().st_size == 9 << 20
assert progress and progress[-1][0] == progress[-1][1] == (9 << 20) + 7, progress[-1]
assert [p[0] for p in progress] == sorted(p[0] for p in progress), "la progression ne recule jamais"
shutil.rmtree(dst)

# --- annulation en cours de fichier: destination propre, source intacte
write(src / "a" / "gros.bin", os.urandom(9 << 20))
write(src / "petit.txt", b"bonjour")
calls = []
def cancel_second_block():
    calls.append(1)
    return len(calls) > 3  # laisse démarrer la copie, puis annule
assert raises(models.Cancelled, models.move, [(src, dst)], cancel=cancel_second_block)
assert not dst.exists(), "rien ne doit rester à la destination"
assert (src / "a" / "gros.bin").stat().st_size == 9 << 20 and (src / "petit.txt").exists(), "la source doit être intacte"

# --- erreur en cours de route (disque, antivirus…): même garantie
real_copystat = shutil.copystat
count = []
def flaky(*a, **k):
    count.append(1)
    if len(count) == 2:
        raise OSError("disque en panne")
    return real_copystat(*a, **k)
shutil.copystat = flaky
try:
    assert raises(OSError, models.move, [(src, dst)])
finally:
    shutil.copystat = real_copystat
assert not dst.exists() and (src / "petit.txt").exists() and (src / "a" / "gros.bin").exists()

# --- pas assez de place: refusé avant de commencer
real_usage = shutil.disk_usage
shutil.disk_usage = lambda p: shutil._ntuple_diskusage(100, 90, 10)
try:
    assert raises(OSError, models.move, [(src, dst)])
finally:
    shutil.disk_usage = real_usage
assert not dst.exists() and src.exists()

# --- chemins absurdes
assert raises(ValueError, models.move, [(src, src)])
assert raises(ValueError, models.move, [(src, src / "dedans")])
assert raises(ValueError, models.move, [(src / "a", src)])

# --- source impossible à supprimer (fichier ouvert): la copie est complète, on le signale
real_remove = models.remove
def locked(paths):
    raise PermissionError("fichier utilisé")
models.remove = locked
try:
    left = models.move([(src, dst)])
finally:
    models.remove = real_remove
assert left == [src] and (dst / "petit.txt").exists() and src.exists()
shutil.rmtree(dst)

# --- suppression, y compris fichiers en lecture seule (cache Hugging Face)
ro = write(src / "lecture_seule.bin")
os.chmod(ro, stat.S_IREAD)
models.remove([src, tmp / "n-existe-pas"])
assert not src.exists()

# --- déplacement d'un modèle Whisper: les dossiers du cache, et rien d'autre
new = tmp / "ailleurs" / "whisper"
pairs = models.relocation(cfg, "whisper", new)
assert [(a.name, b) for a, b in pairs] == [("models--Systran--faster-whisper-small", new / "models--Systran--faster-whisper-small")]
models.move(pairs)
assert (new / "models--Systran--faster-whisper-small/snapshots/abc/model.bin").exists()
assert (w / "autre-chose-de-l-utilisateur/notes.txt").exists(), "les fichiers qui ne sont pas à Ruby ne bougent pas"
assert not (w / "models--Systran--faster-whisper-small").exists()
cfg["paths"]["whisper"] = str(new)
assert models.installed(cfg, "whisper", "small"), "après le changement de dossier, le modèle est retrouvé"
assert models.relocation(cfg, "voice", tmp / "v2") == [(v, tmp / "v2")]
assert models.relocation(dict(cfg, paths=dict(cfg["paths"], voice=str(tmp / "vide"))), "voice", tmp / "v3") == []

# --- téléchargement des 2 petits modèles openWakeWord: complet ou absent, jamais à moitié
class Resp:
    def __init__(self, data): self.data = data
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def raise_for_status(self): pass
    def iter_content(self, n): yield self.data
import requests
fetched = []
real_get = requests.get
requests.get = lambda url, **k: fetched.append(url) or Resp(b"onnx")
try:
    models.ensure_wake(tmp / "dl" / "wake")
    models.ensure_wake(tmp / "dl" / "wake")  # 2e appel: déjà là, aucun accès réseau
finally:
    requests.get = real_get
assert [u.rsplit("/", 1)[1] for u in fetched] == list(models.WAKE_FILES), fetched
assert sorted(p.name for p in (tmp / "dl" / "wake").iterdir()) == sorted(models.WAKE_FILES), "pas de .part qui traîne"

# --- Whisper en int8: même résultat que le convertisseur officiel de CTranslate2 (sauf les 2 convolutions, voir quantize_ct2)
import numpy as np
from ctranslate2.specs import WhisperSpec
from ctranslate2.specs.model_spec import index_spec, _parent_scope

ROWS = 7  # lignes du vocabulaire du modèle minuscule


def tiny_spec(seed=0):
    """Un WhisperSpec minuscule aux poids aléatoires (déjà arrondis en float16), avec une ligne de zéros et l'alias projection -> embeddings."""
    rng, spec = np.random.default_rng(seed), WhisperSpec(1, 2, 1, 2)
    emb = rng.normal(size=(ROWS, 5)).astype(np.float16).astype(np.float32)
    for name, value in spec.variables().items():
        if value is not None:
            continue  # déjà fixé par le constructeur (nombre de têtes, activation…)
        shape = (8, 4, 3) if name.endswith(("conv1/weight", "conv2/weight")) else (6, 5) if name.endswith("/weight") else (4, 5) if name.endswith("encodings") else (5,)
        arr = rng.normal(size=shape).astype(np.float16).astype(np.float32)
        if name.endswith("layer_0/ffn/linear_0/weight"):
            arr[0] = 0  # ligne nulle: le facteur d'échelle ne doit pas diviser par zéro
        scope, attr = _parent_scope(name)
        setattr(index_spec(spec, scope), attr, emb if name.endswith(("embeddings/weight", "projection/weight")) else arr)
    spec.register_vocabulary([str(i) for i in range(ROWS)])
    spec.validate()
    return spec


src = tmp / "t8" / "float16.bin"
src.parent.mkdir()
fp16 = tiny_spec()
fp16.optimize("float16")  # comme le fichier téléchargé: float16, avec l'alias projection -> embeddings
fp16._serialize(str(src))
ref = tiny_spec()
ref._alias_variables()
ref._quantize("int8_float32", variable_filter=lambda n: not n.endswith(("conv1/weight", "conv2/weight")))
ref._serialize(str(tmp / "t8" / "officiel.bin"))
models.quantize_ct2(src, tmp / "t8" / "int8.bin")
models.quantize_ct2(src, tmp / "t8" / "int8_par_3.bin", rows=3)  # par morceaux de 3 lignes (7 lignes: reste de 1)
want = (tmp / "t8" / "officiel.bin").read_bytes()
assert (tmp / "t8" / "int8.bin").read_bytes() == want, "identique octet pour octet au convertisseur officiel"
assert (tmp / "t8" / "int8_par_3.bin").read_bytes() == want, "le découpage en morceaux ne change rien"
bad = tmp / "t8" / "v7.bin"
bad.write_bytes((7).to_bytes(4, "little") + b"x" * 20)
assert raises(ValueError, models.quantize_ct2, bad, tmp / "t8" / "x.bin"), "format inconnu: erreur claire, pas un fichier corrompu"

# --- copie int8 rangée dans le dossier du modèle: créée une fois, suit le modèle quand on le déplace, jamais à moitié
cfg8 = dict(cfg, paths=dict(cfg["paths"], whisper=str(tmp / "w8")))
snap = tmp / "w8" / "models--Systran--faster-whisper-small" / "snapshots" / "h1"
for name in ("config.json", "tokenizer.json", "vocabulary.txt"):
    write(snap / name, name.encode())
shutil.copy(src, snap / "model.bin")
assert models.whisper_source(cfg8, "small") == "small", "pas encore convertie: on garde le nom du modèle"
assert models.ensure_int8(cfg8, "base") is False, "modèle pas installé: rien à faire, pas d'erreur"
(snap.parent.parent / "ruby-int8").mkdir()  # reste d'une tentative interrompue
assert models.whisper_source(cfg8, "small") == "small"
assert models.ensure_int8(cfg8, "small") is True and models.ensure_int8(cfg8, "small") is False, "créée une seule fois"
d8 = snap.parent.parent / "ruby-int8"
assert models.whisper_source(cfg8, "small") == str(d8)
assert sorted(p.name for p in d8.iterdir()) == ["config.json", "model.bin", "tokenizer.json", "vocabulary.txt"]
assert (d8 / "model.bin").read_bytes() == want and (d8 / "tokenizer.json").read_bytes() == b"tokenizer.json"
assert not (d8.parent / "ruby-int8.tmp").exists()
assert set(models.whisper_dirs(cfg8)) == {"small"}, "la copie int8 n'est pas un 2e modèle"
models.move(models.relocation(cfg8, "whisper", tmp / "w9"))
cfg9 = dict(cfg, paths=dict(cfg["paths"], whisper=str(tmp / "w9")))
assert models.whisper_source(cfg9, "small") == str(tmp / "w9" / "models--Systran--faster-whisper-small" / "ruby-int8"), "elle suit le modèle"
models.remove(models.items(cfg9, "whisper", "small"))
assert not (tmp / "w9" / "models--Systran--faster-whisper-small").exists(), "supprimée avec le modèle"

assert models.fmt_size(1536) == "2 Ko" and models.fmt_size(5 << 20) == "5 Mo" and models.fmt_size(3 << 29) == "1,5 Go"
shutil.rmtree(tmp, ignore_errors=True)
print("OK")
