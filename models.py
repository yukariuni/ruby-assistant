"""Où Ruby range ses modèles téléchargés, et comment les mesurer, déplacer ou supprimer (sans interface: testable seul).

Trois familles, chacune avec son dossier réglable (config.json -> paths): « whisper » (reconnaissance vocale), « voice » (voix
Supertonic), « wake » (openWakeWord). Vide = emplacement par défaut de la bibliothèque. Quand l'utilisateur choisit un dossier,
Ruby crée un sous-dossier dédié dedans (SUBDIR): déplacer ou supprimer ne touche donc jamais à autre chose que ses propres modèles.
« mine » n'est pas un téléchargement mais ta voix apprise (voice/wake.pkl): elle se mesure et se supprime comme le reste.
"""
import os
import shutil
import stat
from pathlib import Path

import config

SUBDIR = dict(whisper="whisper", voice="supertonic", wake="openwakeword")
WHISPER_PREFIX = "models--Systran--faster-whisper-"  # nom des dossiers du cache Hugging Face
WHISPER_APPROX = {"base": "≈150 Mo", "small": "≈480 Mo", "medium": "≈1,5 Go"}
VOICE_FILES = tuple(f"onnx/{n}.onnx" for n in ("duration_predictor", "text_encoder", "vector_estimator", "vocoder"))
WAKE_FILES = ("melspectrogram.onnx", "embedding_model.onnx")
WAKE_URL = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/"
CHUNK = 8 << 20


class Cancelled(Exception):
    """Déplacement annulé: la destination est nettoyée, la source n'a pas bougé."""


def fmt_size(n):
    return f"{n / 2**30:.1f} Go".replace(".", ",") if n >= 2**30 else f"{n / 2**20:.0f} Mo" if n >= 2**20 else f"{n / 1024:.0f} Ko"


def default_folder(kind):
    if kind == "whisper":
        return Path(os.environ.get("HF_HUB_CACHE") or Path(os.environ.get("HF_HOME") or Path.home() / ".cache" / "huggingface") / "hub")
    if kind == "voice":
        return Path.home() / ".cache" / "supertonic3"
    return config.WAKE_DEFAULT


def folder(cfg, kind):
    custom = (cfg.get("paths") or {}).get(kind)
    return Path(custom) if custom else default_folder(kind)


def is_custom(cfg, kind):
    return bool((cfg.get("paths") or {}).get(kind))


def custom_or_none(cfg, kind):
    """Dossier choisi par l'utilisateur, ou None (= défaut de la bibliothèque): à passer tel quel à WhisperModel / TTS / wake."""
    return str(folder(cfg, kind)) if is_custom(cfg, kind) else None


def whisper_dirs(cfg):
    """{taille: dossier} des modèles Whisper complets présents (un téléchargement interrompu n'a pas de model.bin: ignoré)."""
    base = folder(cfg, kind="whisper")
    return {d.name.removeprefix(WHISPER_PREFIX): d for d in sorted(base.glob(WHISPER_PREFIX + "*")) if any(d.glob("snapshots/*/model.bin"))}


def items(cfg, kind, key=None):
    """Fichiers et dossiers qui forment ce modèle sur le disque (liste vide = pas installé). key: taille Whisper (None = toutes)."""
    base = folder(cfg, kind)
    if kind == "whisper":
        found = whisper_dirs(cfg)
        if key is None:
            return list(found.values())
        return [found[key]] if key in found else []
    if kind == "voice":  # dossier dédié à Supertonic: on le prend en entier (il contient aussi les métadonnées du téléchargement)
        return [base] if all((base / f).exists() for f in VOICE_FILES) else []
    if kind == "wake":
        return [base / f for f in WAKE_FILES if (base / f).exists()]
    if kind == "mine":
        return [p for p in (config.MODEL_FILE, config.LEGACY_MODEL, config.SAMPLES_FILE) if p.exists()]
    raise ValueError(kind)


def installed(cfg, kind, key=None):
    n = len(items(cfg, kind, key))
    return n == len(WAKE_FILES) if kind == "wake" else n > 0


def size(paths):
    total = 0
    for p in map(Path, paths):
        if p.is_symlink():
            continue
        if p.is_file():
            total += p.stat().st_size
        elif p.is_dir():
            total += sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())
    return total


def _writable(func, path, _exc):
    """Fichier en lecture seule (cache Hugging Face sous Windows): on enlève l'attribut puis on réessaie."""
    os.chmod(path, stat.S_IWRITE)
    func(path)


def remove(paths):
    for p in map(Path, paths):
        if p.is_dir() and not p.is_symlink():
            shutil.rmtree(p, onexc=_writable)
        elif p.exists() or p.is_symlink():
            p.unlink()


def relocation(cfg, kind, new):
    """[(source, destination)] à déplacer pour passer de l'ancien dossier à `new`."""
    if kind == "voice":
        return [(folder(cfg, kind), Path(new))] if items(cfg, kind) else []
    return [(p, Path(new) / p.name) for p in items(cfg, kind)]


def move(pairs, progress=None, cancel=None):
    """Copie tout avec vérification, PUIS supprime les sources: rien n'est perdu si ça échoue ou si on annule.

    progress(octets_faits, octets_total, nom_du_fichier). cancel(): True pour annuler (lève Cancelled, destination nettoyée).
    Retourne les anciens chemins qu'on n'a pas pu supprimer (fichiers encore ouverts): la copie, elle, est complète.
    """
    pairs = [(Path(s), Path(d)) for s, d in pairs]
    for s, d in pairs:
        rs, rd = s.resolve(), d.resolve()
        if rs == rd or rd.is_relative_to(rs) or rs.is_relative_to(rd):
            raise ValueError("Le dossier de destination ne peut pas être l'ancien dossier ni en faire partie (ni l'inverse).")
    files = []
    for s, d in pairs:
        if s.is_dir():
            files += [(Path(root) / n, d / (Path(root) / n).relative_to(s)) for root, _, names in os.walk(s) for n in names]
        else:
            files.append((s, d))
    total = sum(f.stat().st_size for f, _ in files if not f.is_symlink())
    if pairs:
        anchor = next(p for p in (pairs[0][1], *pairs[0][1].parents) if p.exists())
        if shutil.disk_usage(anchor).free < total * 1.02 + (64 << 20):
            raise OSError(f"Espace insuffisant sur le disque de destination ({fmt_size(total)} requis).")
    done, made_dirs, made_files = 0, [], []
    try:
        for f, d in files:
            if cancel and cancel():
                raise Cancelled
            for parent in reversed([p for p in d.parents if not p.exists()]):  # dossiers manquants, du plus haut au plus bas
                parent.mkdir()
                made_dirs.append(parent)
            made_files.append(d)
            if f.is_symlink():  # lien (cache Hugging Face sous Linux/macOS): recopié tel quel
                os.symlink(os.readlink(f), d)
                continue
            with open(f, "rb") as r, open(d, "wb") as w:
                while chunk := r.read(CHUNK):
                    if cancel and cancel():
                        raise Cancelled
                    w.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, total, f.name)
            if d.stat().st_size != f.stat().st_size:
                raise OSError(f"Copie incomplète : {f.name}")
            shutil.copystat(f, d)
    except BaseException:  # annulation, disque plein, erreur: on efface ce qui a été copié, la source est intacte
        for d in made_files:
            d.unlink(missing_ok=True)
        for p in reversed(made_dirs):
            try:
                p.rmdir()
            except OSError:
                pass
        raise
    left = []
    for s, _ in pairs:
        try:
            remove([s])
        except OSError:
            left.append(s)
    return left


def ensure_wake(dest):
    """Télécharge les 2 petits modèles openWakeWord (≈2,4 Mo) dans `dest` s'ils manquent."""
    import requests  # ici seulement: le moteur n'en a besoin qu'au premier téléchargement
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    for name in WAKE_FILES:
        if (dest / name).exists():
            continue
        tmp = dest / (name + ".part")
        with requests.get(WAKE_URL + name, stream=True, timeout=30) as r:
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1 << 16):
                    f.write(chunk)
        os.replace(tmp, dest / name)  # le fichier final n'existe que complet


# ---------------------------------------------------------------- Whisper en int8, sans pic de mémoire au chargement
def quantize_ct2(src, dst, rows=4096):
    """model.bin CTranslate2 (float16) -> int8, variable par variable.

    Pourquoi: au chargement d'un fichier float16 avec compute_type=int8, CTranslate2 lit TOUT le fichier (461 Mo pour Whisper small) puis le
    convertit: pic mesuré à 681 Mo pour un modèle qui n'en occupe que 306 une fois chargé. Un fichier déjà en int8 se charge sans pic (265 Mo).
    Mêmes règles que le chargement de CTranslate2 (et que son convertisseur, ctranslate2.specs.model_spec._quantize, mode int8_float32):
    les poids de rang 2 (« …/weight ») deviennent int8 + « …/weight_scale » (un facteur par ligne), le reste passe en float32.
    Exception voulue: les 2 convolutions (poids de rang 3) restent en float32, comme au chargement de CTranslate2. Le convertisseur officiel,
    lui, les quantifie, et mesuré cela change la sortie de l'encodeur de ≈11 % alors que ce choix la laisse identique au bit près
    (test_models.py compare tout octet pour octet avec le convertisseur officiel). Mémoire: `rows` lignes à la fois (≈50 Mo au plus)."""
    import struct

    import numpy as np
    F32, I8, F16 = 0, 1, 4  # identifiants de types du format (voir _dtype_to_type_id de CTranslate2)
    ITEM = {0: 4, 1: 1, 2: 2, 3: 4, 4: 2}
    with open(src, "rb") as f, open(dst, "wb") as g:
        rd = lambda fmt: struct.unpack(fmt, f.read(struct.calcsize(fmt)))
        wr = lambda fmt, *v: g.write(struct.pack(fmt, *v))

        def rs():
            return f.read(rd("H")[0])[:-1]

        def ws(b):
            wr("H", len(b) + 1)
            g.write(b)
            wr("B", 0)

        def header():
            name = rs()
            rank, = rd("B")
            dims = rd("I" * rank) if rank else ()
            dt, = rd("B")
            nbytes, = rd("I")
            return name, dims, dt, nbytes

        quantizable = lambda n, dims, dt: n.endswith(b"/weight") and len(dims) == 2 and dt in (F32, F16)
        version, = rd("I")
        if version != 6:
            raise ValueError(f"format CTranslate2 {version} non géré (seule la version 6 l'est)")
        spec_name, revision, n = rs(), rd("I")[0], rd("I")[0]
        start, n_quant = f.tell(), 0
        for _ in range(n):  # 1re passe: en-têtes seulement, pour annoncer le bon nombre de variables
            name, dims, dt, nbytes = header()
            f.seek(nbytes, 1)
            n_quant += quantizable(name, dims, dt)
        f.seek(start)
        wr("I", 6)
        ws(spec_name)
        wr("I", revision)
        wr("I", n + n_quant)
        for _ in range(n):
            name, dims, dt, nbytes = header()
            if quantizable(name, dims, dt):
                r, c = dims[0], nbytes // ITEM[dt] // dims[0]
                ws(name)
                wr("B", len(dims))
                wr("I" * len(dims), *dims)
                wr("B", I8)
                wr("I", r * c)
                scales = []
                for i in range(0, r, rows):
                    k = min(rows, r - i)
                    v = np.frombuffer(f.read(k * c * ITEM[dt]), np.float16 if dt == F16 else np.float32).reshape(k, c).astype(np.float32)
                    amax = np.amax(np.absolute(v), axis=1)
                    amax[amax == 0] = 127.0
                    amax = np.maximum(amax, np.float32(127) / np.finfo(np.float32).max)
                    scale = 127.0 / amax
                    g.write(np.rint(v * np.expand_dims(scale, 1)).astype(np.int8).tobytes())
                    scales.append(scale.astype(np.float32))
                ws(name + b"_scale")
                wr("B", 1)
                wr("I", r)
                wr("B", F32)
                wr("I", r * 4)
                g.write(np.concatenate(scales).tobytes())
            else:
                ws(name)
                wr("B", len(dims))
                wr("I" * len(dims), *dims)
                if dt == F16:  # float16 -> float32, comme le convertisseur
                    wr("B", F32)
                    wr("I", nbytes * 2)
                    g.write(np.frombuffer(f.read(nbytes), np.float16).astype(np.float32).tobytes())
                else:
                    wr("B", dt)
                    wr("I", nbytes)
                    g.write(f.read(nbytes))
        g.write(f.read())  # alias: recopiés tels quels


def int8_dir(cfg, size):
    """Dossier de la copie int8 de Whisper `size` (dans le dossier du modèle: déplacée et supprimée avec lui), ou None si pas installé."""
    d = whisper_dirs(cfg).get(size)
    return d / "ruby-int8" if d else None


def whisper_source(cfg, size):
    """Ce qu'il faut donner à WhisperModel: la copie int8 si elle existe (aucun pic au chargement), sinon le nom du modèle."""
    d = int8_dir(cfg, size)
    return str(d) if d and (d / "model.bin").exists() else size


def ensure_int8(cfg, size):
    """Crée la copie int8 de Whisper `size` si elle manque (une fois, ≈5 s). Retourne True si elle a été créée."""
    d = int8_dir(cfg, size)
    if d is None or (d / "model.bin").exists():
        return False
    snap = next(whisper_dirs(cfg)[size].glob("snapshots/*/model.bin")).parent
    tmp = d.with_name("ruby-int8.tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir()
    for f in snap.iterdir():
        if f.name != "model.bin" and f.is_file():
            shutil.copy2(f, tmp / f.name)  # config, tokenizer, vocabulaire… (copie les fichiers pointés par les liens éventuels)
    quantize_ct2(snap / "model.bin", tmp / "model.bin")
    remove([d])  # reste d'une tentative interrompue (sans model.bin): c'est notre dossier
    os.replace(tmp, d)  # le dossier final n'existe que complet
    return True
