"""Auto-vérif de la fenêtre de réglages (sans écran: QT offscreen) : gestion des modèles, dossiers, animations.

Tout est redirigé vers un dossier temporaire (config, caches, « dossiers par défaut »): les vrais modèles de l'utilisateur ne sont
jamais touchés. Lancer: .venv\\Scripts\\python test_settings.py
"""
import json
import os
import shutil
import tempfile
from pathlib import Path

os.environ["QT_QPA_PLATFORM"] = "offscreen"
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog

import config
import models
import settings

tmp = Path(tempfile.mkdtemp(prefix="ruby_settings_"))
config.CFG_FILE, config.STATUS_FILE, config.QUIT_FILE = tmp / "config.json", tmp / "status.json", tmp / "engine.quit"
config.MODEL_FILE, config.SAMPLES_FILE = tmp / "voice" / "wake.npz", tmp / "voice" / "samples.npz"
config.LEGACY_MODEL = tmp / "voice" / "wake.pkl"  # jamais le vrai fichier de l'utilisateur (« supprimer ta voix » l'effacerait)
models.default_folder = lambda kind: tmp / "defaut" / kind  # jamais le vrai cache Hugging Face / Supertonic de l'utilisateur
launched = []
config.launch = lambda script: launched.append(script)
config.RUN_KEY, config.APPROVED_KEY = r"Software\RubyTest\Settings\Run", r"Software\RubyTest\Settings\Approved"  # jamais la vraie clé « Run »
real_os_lang = config.os_lang


def write(p, data=b"x" * 2000):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    Path(p).write_bytes(data)


def fake_install(root):
    """Modèles factices dans `root`: Whisper small + base, voix Supertonic, openWakeWord, ta voix apprise."""
    for size, n in (("small", 5000), ("base", 3000)):
        write(root / "whisper" / f"models--Systran--faster-whisper-{size}" / "snapshots" / "h" / "model.bin", b"w" * n)
    for f in models.VOICE_FILES:
        write(root / "voix" / f, b"v" * 1000)
    for f in models.WAKE_FILES:
        write(root / "wake" / f, b"k" * 500)
    write(config.MODEL_FILE, b"m" * 100)
    write(config.SAMPLES_FILE, b"s" * 100)


def new_config(root):
    cfg = dict(config.DEFAULT, synced="salut;hey", words="salut;hey", whisper="small", engine=config.SUPERTONIC, voice="F1",
               paths=dict(whisper=str(root / "whisper"), voice=str(root / "voix"), wake=str(root / "wake")))
    config.CFG_FILE.write_text(json.dumps(cfg), "utf-8")


def saved():
    return json.loads(config.CFG_FILE.read_text("utf-8"))


app = QApplication([])
app.setStyleSheet(settings.QSS)
settings.ANIMATE = True
root = tmp / "ia"
fake_install(root)
new_config(root)
asks, dialogs = [], []
settings.Confirm.ask = staticmethod(lambda parent, title, text, buttons, icon=None: (asks.append((title, text, [b[0] for b in buttons])), answers.pop(0))[1])
answers = []
w = settings.Settings()
w.show()
QTest.qWait(500)

# --- ce que Ruby utilise, et où
used, others, total = settings.model_rows(w.cfg)
assert [r["kind"] for r in used] == ["wake", "mine", "whisper", "cloud", "voice"], [r["kind"] for r in used]
assert [(r["kind"], r["key"]) for r in others] == [("whisper", "base")], "Whisper base est installé mais inutilisé: il apparaît dans « autres »"
by = {r["kind"]: r for r in used}
assert by["whisper"]["size"] == 5000 and by["whisper"]["path"] == root / "whisper" and by["whisper"]["status"][0] == "Installé"
assert by["cloud"]["where"] == "local" and by["cloud"]["items"] == [], "sans clé Groq: règles locales, rien à gérer"
assert total == 5000 + 3000 + 4000 + 1000 + 200, total
assert [p for p in used if p["pipeline"]] == [by["wake"], by["whisper"], by["cloud"], by["voice"]]
assert w.chips.count() == 4 and w.models_box.count() == 3, "utilisés + autres + espace disque"

# --- UN seul bouton par ligne, avec les bonnes actions
def labels(r):
    return [a[1] for a in w.manage_actions(r)]
assert labels(by["whisper"]) == ["Ouvrir le dossier", "Changer le dossier…", "Revenir au dossier par défaut", "Supprimer…"]
assert labels(by["mine"]) == ["Ouvrir le dossier", "Supprimer…"], "ta voix n'est pas un téléchargement: pas de changement de dossier"
assert labels(by["cloud"]) == [], "rien à gérer pour un modèle hébergé ailleurs"
assert "Changer le dossier…" not in labels(others[0]), "le dossier se change depuis la ligne utilisée (il est commun à toutes les tailles)"
assert "Supprimer…" in labels(others[0])
rows = [b for b in w.findChildren(settings.ManageButton)]
assert len(rows) == 5, "un bouton « Gérer » par modèle qui a quelque chose à gérer (hors Intelligence)"

# --- supprimer un modèle inutilisé: Ruby tourne, elle est relancée après
state = {"n": 0}
def status_running():
    state["n"] += 1
    return {"pid": None, "state": "listening", "ts": 0} if state["n"] < 3 else None
w.read_status = status_running
answers[:] = [1]
w.delete_model(others[0])
assert asks[-1][0] == "Supprimer Whisper base ?" and "3 Ko" in asks[-1][1] and asks[-1][2] == ["Annuler", "Supprimer"], asks[-1]
assert not (root / "whisper" / "models--Systran--faster-whisper-base").exists(), "supprimé"
assert (root / "whisper" / "models--Systran--faster-whisper-small").exists(), "le modèle utilisé n'est pas touché"
assert config.QUIT_FILE.exists(), "le moteur a été arrêté avant de supprimer (Windows refuse de supprimer des fichiers ouverts)"
config.QUIT_FILE.unlink()
assert launched == ["engine.py"], "modèle inutilisé: Ruby est relancée"
launched.clear()
assert w.models_box.count() == 2, "plus de carte « autres modèles »"

# --- annuler la confirmation: rien ne bouge
answers[:] = [0]
w.read_status = lambda: None
w.delete_model(by["voice"])
assert models.installed(w.cfg, "voice") and not launched

# --- supprimer un modèle UTILISÉ pendant que Ruby tourne: Ruby reste arrêtée (sinon elle le retélécharge aussitôt)
state["n"] = 0
w.read_status = status_running
answers[:] = [1]
w.delete_model(by["voice"])
config.QUIT_FILE.unlink(missing_ok=True)
assert not models.installed(w.cfg, "voice") and models.items(w.cfg, "voice") == []
assert launched == [], "Ruby ne repart pas toute seule: elle retélécharge un modèle de 385 Mo sans qu'on l'ait décidé"
assert "Ruby arrêté" in w.toast_widget.text(), w.toast_widget.text()
w.read_status = lambda: None

# --- supprimer ta voix apprise: « synced » est remis à zéro, Ruby demandera de refaire l'apprentissage
answers[:] = [1]
w.delete_model([r for r in settings.model_rows(w.cfg)[0] if r["kind"] == "mine"][0])
assert not config.MODEL_FILE.exists() and not config.SAMPLES_FILE.exists() and saved()["synced"] == ""
assert [r for r in settings.model_rows(w.cfg)[0] if r["kind"] == "mine"][0]["status"][0] == "À enregistrer"

# --- changer le dossier AVEC déplacement (le vrai MoveDialog, sur un vrai thread)
new_root = tmp / "disque_d"
new_root.mkdir()
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(new_root))
answers[:] = [2]  # « Déplacer »
w.change_folder("whisper")
assert asks[-1][0] == "Déplacer les fichiers existants ?" and str(new_root / "whisper") in asks[-1][1]
assert saved()["paths"]["whisper"] == str(new_root / "whisper"), "le nouveau dossier est enregistré (le moteur le relit à chaud)"
assert (new_root / "whisper" / "models--Systran--faster-whisper-small" / "snapshots" / "h" / "model.bin").read_bytes() == b"w" * 5000
assert not (root / "whisper" / "models--Systran--faster-whisper-small").exists(), "l'ancien emplacement est nettoyé"
assert models.installed(w.cfg, "whisper", "small"), "le modèle est retrouvé dans le nouveau dossier"
assert "Dossier changé" in w.toast_widget.text()
assert w.path_rows["whisper"][0][0].toolTip() == str(new_root / "whisper"), "la page Écoute affiche le nouveau chemin"

# --- changer le dossier SANS déplacer: seul le réglage change, les fichiers restent
answers[:] = [1]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(tmp / "ailleurs"))
w.change_folder("voice")
assert saved()["paths"]["voice"] == str(tmp / "ailleurs" / "supertonic") and not (tmp / "ailleurs").exists()

# --- annuler au moment de choisir le dossier / à la confirmation: rien ne change
before = saved()
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: "")
w.change_folder("whisper")
answers[:] = [0]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(tmp / "autre"))
w.change_folder("whisper")
assert saved() == before and (new_root / "whisper").exists()

# --- revenir au dossier par défaut (déplace les fichiers, remet le réglage à vide)
answers[:] = [2]
w.change_folder("whisper", default=True)
assert saved()["paths"]["whisper"] == "" and (tmp / "defaut" / "whisper" / "models--Systran--faster-whisper-small").exists()
assert not models.is_custom(w.cfg, "whisper")

# --- le déplacement échoue (disque plein…): réglage inchangé, message d'erreur, fichiers intacts
real_move = models.move
models.move = lambda *a, **k: (_ for _ in ()).throw(OSError("disque plein"))
answers[:] = [2]
QFileDialog.getExistingDirectory = staticmethod(lambda *a, **k: str(tmp / "plein"))
w.change_folder("whisper")
models.move = real_move
assert saved()["paths"]["whisper"] == "" and "disque plein" in w.toast_widget.text() and w.toast_widget.property("kind") == "error"
assert (tmp / "defaut" / "whisper" / "models--Systran--faster-whisper-small").exists()

# --- annuler PENDANT le déplacement: la destination est nettoyée, la source est intacte
write(tmp / "gros" / "m.bin", os.urandom(25 << 20))
d = settings.MoveDialog(w, "de test", [(tmp / "gros", tmp / "copie")])
QTest.qWait(1)
d.reject()  # demande d'annulation (peut arriver avant ou pendant la copie)
assert d.exec() == QDialog.Rejected and not (tmp / "copie").exists() and (tmp / "gros" / "m.bin").stat().st_size == 25 << 20

# --- état du moteur affiché: téléchargement en cours
config.STATUS_FILE.write_text(json.dumps(dict(state="downloading", detail="Whisper medium (≈1,5 Go)", score=0, text="", reply="", ts=__import__("time").time())), "utf-8")
del w.read_status
w.poll()
assert w.home_state.text() == "Préparation…" and "Whisper medium" in w.tip.text() and w.running

# --- plafond de mémoire: la fenêtre compte avec le moteur, et « Écouter » ne charge jamais la voix pendant que le moteur travaille
import sys
import time
import types
assert w.trimmer.isActive() and w.trimmer.interval() == 5000, "la fenêtre rend régulièrement la mémoire qu'elle n'utilise pas (≈10 Mo au lieu de ≈54)"
status = lambda **k: config.STATUS_FILE.write_text(json.dumps(dict(state="listening", score=0, text="", reply="", ts=time.time(), **k)), "utf-8")
status(mem=12, loaded=[])
w.poll()
assert f"sur {config.MEM_LIMIT}" in w.mem_lbl.text() and "moteur 12" in w.mem_lbl.text() and "Aucun modèle chargé" in w.mem_lbl.text(), w.mem_lbl.text()
spoken = []


class FakeSpeaker:
    def say(self, text, cfg):
        spoken.append(("say", text))

    def unload(self):
        spoken.append(("unload",))


sys.modules["tts"] = types.SimpleNamespace(Speaker=FakeSpeaker)
status(mem=430, loaded=["Whisper small"])
w.test_voice()
assert spoken == [] and w.test_btn.isEnabled() and "Commande en cours de traitement" in w.voice_err.text(), "moteur occupé: la voix n'est pas chargée ici en plus"
status(mem=12, loaded=[])
w.test_voice()
for _ in range(50):
    QTest.qWait(20)
    if len(spoken) == 2:
        break
assert spoken == [("say", config.LANGS[w.cfg["lang"]]["hello"]), ("unload",)], "la voix est libérée juste après « Écouter » (≈415 Mo)"
QTest.qWait(100)
assert w.test_btn.isEnabled()
del sys.modules["tts"]

# --- langue: « Automatique » suit Windows (et le dit), un choix explicite reste jusqu'à ce qu'on rechoisisse « Automatique »
cb = w.lang_combo
assert [cb.itemData(i) for i in range(cb.count())] == ["auto"] + list(config.LANGS)
assert cb.currentData() == "auto" and f"Windows ({real_os_lang()})" in cb.itemText(0) and w.cfg["lang_auto"], "par défaut: automatique, et le texte dit laquelle"
cb.setCurrentIndex(cb.findData("English"))
saved = json.loads(config.CFG_FILE.read_text("utf-8"))
assert w.cfg["lang"] == "English" and not w.cfg["lang_auto"] and saved["lang"] == "English" and saved["lang_auto"] is False, saved
config.os_lang = lambda: "Français"
cb.setCurrentIndex(0)
saved = json.loads(config.CFG_FILE.read_text("utf-8"))
assert w.cfg["lang"] == "Français" and w.cfg["lang_auto"] and saved["lang"] == "Français" and saved["lang_auto"] is True, saved
assert config.load_cfg()["lang_auto"] is True
config.os_lang = real_os_lang

# --- lancer Ruby avec Windows: l'interrupteur écrit dans la clé de test, une erreur d'écriture est annoncée sans planter
t = w.autostart_toggle
assert not t.isChecked() and not config.autostart()
t.setChecked(True)
assert config.autostart(), "activé: Windows lancera Ruby à l'ouverture de session"
t.setChecked(False)
assert not config.autostart()
toasts = []
w.toast = lambda text, error=False: toasts.append((text, error))
real_set = config.set_autostart


def refuse(on):
    raise PermissionError("accès refusé")


config.set_autostart = refuse
w.set_autostart(True)
assert toasts and toasts[0][1] is True and "accès refusé" in toasts[0][0], toasts
config.set_autostart = real_set
del w.toast

# --- animations: les effets temporaires sont retirés, tout arrive à son état final
for i in (1, 2, 3, 4, 5, 0):
    w.pages.setCurrentIndex(i)
    QTest.qWait(80)  # change de page en pleine animation: ne doit rien casser
QTest.qWait(900)
assert all(c.graphicsEffect() is None for c in w.pages.currentWidget().findChildren(settings.Card)), "effets de fondu retirés à la fin"
assert w.sidebar.indicator.geometry() == w.sidebar.buttons[0].geometry(), "le surligneur du menu a fini de glisser"
assert w.sidebar.buttons[0].isChecked() and not w.sidebar.buttons[5].isChecked()
t = settings.Toggle(False, lambda v: None)
t.setChecked(True)
QTest.qWait(400)
assert t.t == 1.0, "la pastille de l'interrupteur arrive au bout"
w.timer.stop()  # le sondage du moteur (toutes les 250 ms) remettrait la barre au score réel
w.meter.glide(80)
QTest.qWait(400)
assert w.meter.value() == 80
w.timer.start()
w.toast_widget.show_msg("Test", hold=150)
QTest.qWait(150)
assert w.toast_widget.isVisible() and w.toast_widget.fx.opacity() > 0.5
QTest.qWait(900)
assert not w.toast_widget.isVisible(), "le message disparaît tout seul"

# --- animations coupées dans Windows: tout est instantané et rien ne casse
settings.ANIMATE = False
w.pages.setCurrentIndex(5)
w.refresh_models(animate=True)
QTest.qWait(50)
assert w.pages.currentIndex() == 5 and w.models_box.count() >= 2
settings.ANIMATE = True

w.close()
import winreg
for key in (config.RUN_KEY, config.APPROVED_KEY, r"Software\RubyTest\Settings", r"Software\RubyTest"):
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key)
    except OSError:
        pass
shutil.rmtree(tmp, ignore_errors=True)
print("OK")
