"""Mot d'activation appris sur la voix de l'utilisateur (Sync voice).

Deux petits modèles ONNX d'openWakeWord (mel-spectrogramme, puis « embeddings » Google speech_embedding) transforment l'audio en
vecteurs 16 x 96; une régression logistique, entraînée sur les enregistrements de l'utilisateur, décide si c'est « Hey Ruby ».
Écoute et entraînement passent par le même chemin « streaming » pour que les features soient identiques.

`Features` reprend la logique de openwakeword.utils.AudioFeatures (Apache-2.0, David Scripka) SANS importer le paquet openwakeword:
celui-ci charge scikit-learn et scipy dès l'import (≈70 Mo de mémoire en permanence) alors qu'écouter n'a besoin que de numpy et
onnxruntime. scikit-learn n'est importé que pour apprendre (train). test_wake.py vérifie que les nombres sont identiques à l'original.
"""
import math
from pathlib import Path

import numpy as np
import onnxruntime as ort

import config

SR, CHUNK, FRAMES, PAD = 16000, 1280, 16, 25  # PAD: chunks de bruit avant chaque clip (chauffe du buffer)
MEL_ROWS, MEL_KEEP, FEAT_KEEP = 76, 970, 120  # fenêtre du modèle d'embeddings, et combien d'historique on garde


class Features:
    """Audio int16 16 kHz -> embeddings (1 vecteur de 96 par morceau de 1280 échantillons = 80 ms)."""

    def __init__(self, folder=None):
        so = ort.SessionOptions()
        so.intra_op_num_threads = so.inter_op_num_threads = 1
        so.enable_cpu_mem_arena = False  # 2 minuscules modèles: pas besoin de réserver de gros blocs
        so.enable_mem_pattern = False
        f = Path(folder or config.WAKE_DEFAULT)
        self.mel = ort.InferenceSession(str(f / "melspectrogram.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
        self.emb = ort.InferenceSession(str(f / "embedding_model.onnx"), sess_options=so, providers=["CPUExecutionProvider"])
        self.reset()

    def reset(self):
        self.raw = np.empty(0, np.int16)
        self.pending = np.empty(0, np.int16)
        self.mels = np.ones((MEL_ROWS, 32))
        # Avant FRAMES morceaux la fin de ce tampon est sans effet: Detector.score et windows() ignorent ces premières valeurs
        self.feature_buffer = np.zeros((FRAMES, 96), np.float32)

    def _push(self, chunk):
        self.raw = np.concatenate([self.raw, chunk])[-(CHUNK + 480):]  # le modèle mel veut 3 x 160 échantillons de recul
        spec = np.squeeze(self.mel.run(None, {"input": self.raw[None].astype(np.float32)})[0]) / 10 + 2
        self.mels = np.vstack((self.mels, spec))[-MEL_KEEP:]
        window = self.mels[-MEL_ROWS:].astype(np.float32)[None, :, :, None]
        row = self.emb.run(None, {"input_1": window})[0].squeeze()
        self.feature_buffer = np.vstack((self.feature_buffer, row))[-FEAT_KEEP:]

    def __call__(self, x):
        self.pending = np.concatenate([self.pending, x])
        while len(self.pending) >= CHUNK:
            self._push(self.pending[:CHUNK])
            self.pending = self.pending[CHUNK:]

    def get_features(self, n=FRAMES):
        return self.feature_buffer[-n:][None].astype(np.float32)


def features(folder=None):
    """Extracteur. folder: dossier des 2 modèles (voir models.py); None = emplacement par défaut (config.WAKE_DEFAULT)."""
    return Features(folder)


class Classifier:
    """Régression logistique sur les 16 x 96 features, en numpy pur (c'est tout ce qu'il faut pour écouter)."""

    def __init__(self, mean, scale, coef, bias):
        self.mean, self.scale, self.coef, self.bias = (np.asarray(a, np.float64) for a in (mean, scale, coef, bias))

    def proba(self, x):
        z = float(((np.asarray(x, np.float64).reshape(-1) - self.mean) / self.scale) @ self.coef + self.bias)
        return 0.5 * (1 + math.tanh(z / 2))  # sigmoïde stable: pas de dépassement pour les grandes valeurs

    def save(self, path):
        np.savez(path, mean=self.mean, scale=self.scale, coef=self.coef, bias=self.bias)

    @classmethod
    def load(cls, path):
        with np.load(path) as d:
            return cls(d["mean"], d["scale"], d["coef"], d["bias"])

    @classmethod
    def from_sklearn(cls, pipe):
        scaler, lr = pipe[0], pipe[1]
        return cls(scaler.mean_, scaler.scale_, lr.coef_[0], lr.intercept_[0])


def migrate_legacy(pkl, npz):
    """Ancien format (pipeline scikit-learn sauvegardé avec joblib) -> numpy. Importe scikit-learn: à lancer dans un processus à part."""
    import joblib
    Classifier.from_sklearn(joblib.load(pkl)).save(npz)


def _rms(x):
    n = len(x) // 320 * 320
    return np.sqrt((x[:n].astype(np.float32).reshape(-1, 320) ** 2).mean(1))  # un point / 20 ms


def speech_end(clip):
    """Fin de la parole en échantillons, ou None si le clip est silencieux."""
    r = _rms(clip)
    loud = np.flatnonzero(r > max(3 * np.median(r), 80))
    return int((loud[-1] + 1) * 320) if len(loud) >= 5 else None


def windows(clip, feats):
    """Features après chaque chunk de 80 ms, comme pendant l'écoute en direct."""
    noise = np.random.randn(PAD * CHUNK) * np.median(_rms(clip))
    x = np.concatenate([noise, clip]).astype(np.int16)
    feats.reset()
    out = []
    for i in range(0, len(x) - CHUNK + 1, CHUNK):
        feats(x[i:i + CHUNK])
        out.append(feats.get_features(FRAMES).ravel())
    return np.array(out)


def train(pos_clips, neg_clips, folder=None):
    """pos_clips: « Hey Ruby » (int16 16 kHz). neg_clips: autres phrases + bruit ambiant. Retourne un Classifier."""
    from sklearn.linear_model import LogisticRegression  # seulement ici: écouter n'en a pas besoin
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    feats = features(folder)
    P, N = [], []
    for clip in pos_clips:
        w, c = windows(clip, feats), PAD + speech_end(clip) // CHUNK
        P.append(w[max(c - 1, PAD):c + 4])  # le mot vient de finir
        N += [w[PAD:c - 4], w[c + 8:]]  # mot coupé, ou déjà passé
    for clip in neg_clips:
        N.append(windows(clip, feats)[PAD:])
    n_pos = sum(map(len, P))
    X = np.vstack(P + N)
    y = np.r_[np.ones(n_pos), np.zeros(len(X) - n_pos)]
    pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, class_weight="balanced", max_iter=2000)).fit(X, y)
    return Classifier.from_sklearn(pipe)


class Detector:
    def __init__(self, clf, folder=None):
        self.clf, self.feats, self.n = clf, features(folder), 0

    def reset(self):
        self.feats.reset()
        self.n = 0

    def score(self, chunk):
        """chunk: 1280 échantillons int16. Retourne la probabilité de « Hey Ruby »."""
        self.feats(chunk)
        self.n += 1
        if self.n <= FRAMES:  # buffer de features pas encore chauffé
            return 0.0
        return self.clf.proba(self.feats.get_features(FRAMES))
