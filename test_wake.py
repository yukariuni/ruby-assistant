"""Auto-vérif de la détection du mot d'activation allégée, et garde-fou mémoire.

1. Mon extracteur donne les mêmes nombres que openwakeword.utils.AudioFeatures (s'il est installé, comme référence).
2. Le classifieur numpy donne les mêmes probabilités que scikit-learn, se sauvegarde et se recharge.
3. Le moteur et la fenêtre de réglages n'importent JAMAIS les bibliothèques lourdes (scikit-learn, scipy, Whisper…): c'est ce qui
   garde le moteur à ≈55 Mo au repos. Si ce test échoue, quelqu'un a réintroduit un import qui coûte des dizaines de Mo.

Lancer: .venv\\Scripts\\python test_wake.py
"""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

import config
import wake

rng = np.random.default_rng(0)

# --- 1. extracteur identique à la bibliothèque d'origine (référence facultative: elle n'est plus nécessaire à Ruby)
try:
    from openwakeword.utils import AudioFeatures
except ImportError:
    AudioFeatures = None
    print("(openwakeword non installé: comparaison à l'original ignorée)")
if AudioFeatures:
    ref_dir = Path(sys.modules["openwakeword"].__file__).parent / "resources" / "models"
    ref, mine = AudioFeatures(inference_framework="onnx", melspec_model_path=str(ref_dir / "melspectrogram.onnx"),
                              embedding_model_path=str(ref_dir / "embedding_model.onnx")), wake.Features(config.WAKE_DEFAULT)
    x = (rng.normal(0, 800, wake.CHUNK * 60)).astype(np.int16)
    worst = 0.0
    for i in range(60):
        c = x[i * wake.CHUNK:(i + 1) * wake.CHUNK]
        ref(c), mine(c)
        if i + 1 > wake.FRAMES:  # avant, les valeurs d'amorçage diffèrent volontairement (jamais utilisées, voir Detector.score)
            worst = max(worst, float(np.abs(ref.get_features(16) - mine.get_features(16)).max()))
    assert worst == 0.0, f"features différentes de l'original: {worst}"
    ref.reset(), mine.reset()
    i = k = 0
    sizes = [700, 1280, 2000, 333, 4096]  # morceaux de tailles quelconques
    while i < len(x):
        s = sizes[k % 5]
        k += 1
        ref(x[i:i + s]), mine(x[i:i + s])
        i += s
    assert np.abs(ref.get_features(16) - mine.get_features(16)).max() == 0.0

# --- 2. classifieur numpy == scikit-learn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

X = rng.normal(size=(300, 1536))
X[:, 5] = 0  # colonne constante: scikit-learn met scale_=1
y = (X[:, 0] + 0.5 * X[:, 1] > 0).astype(int)
pipe = make_pipeline(StandardScaler(), LogisticRegression(C=0.1, class_weight="balanced", max_iter=2000)).fit(X, y)
clf = wake.Classifier.from_sklearn(pipe)
assert np.abs(pipe.predict_proba(X)[:, 1] - np.array([clf.proba(r) for r in X])).max() < 1e-12
with tempfile.TemporaryDirectory() as d:
    clf.save(Path(d) / "c.npz")
    assert abs(wake.Classifier.load(Path(d) / "c.npz").proba(X[3]) - clf.proba(X[3])) < 1e-15
big = wake.Classifier(np.zeros(2), np.ones(2), np.array([1e4, 0]), 0)
assert big.proba(np.array([1, 0])) == 1.0 and wake.Classifier(np.zeros(2), np.ones(2), np.array([-1e4, 0]), 0).proba(np.array([1, 0])) == 0.0

# --- 3. garde-fou mémoire: ce que le moteur et les réglages ont le droit de charger
HEAVY = ("sklearn", "scipy", "joblib", "openwakeword", "faster_whisper", "supertonic", "edge_tts", "aiohttp", "requests", "pandas", "torch")
for module, forbidden in (("engine", HEAVY), ("settings", HEAVY + ("wake", "onnxruntime"))):
    code = ("import os, sys; os.environ['QT_QPA_PLATFORM'] = 'offscreen'; import " + module + "; "
            f"print(','.join(m for m in {forbidden!r} if m in sys.modules))")
    out = subprocess.run([sys.executable, "-X", "utf8", "-c", code], capture_output=True, text=True, cwd=config.ROOT)
    assert out.returncode == 0, out.stderr[-500:]
    loaded = out.stdout.strip().splitlines()[-1] if out.stdout.strip() else ""
    assert loaded == "", f"« {module} » importe des bibliothèques lourdes au démarrage: {loaded}"

from memory import private_mb
assert private_mb() > 10, "la mesure de mémoire fonctionne"
print("OK")
