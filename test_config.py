"""Auto-vérif de config.py: langue qui suit Windows (et reste modifiable), lancement avec Windows.

Rien de réel n'est touché: les langues de Windows sont simulées, config.json est dans un dossier temporaire, et le lancement avec Windows
écrit dans une clé de test (HKCU\\Software\\RubyTest), jamais dans la vraie clé « Run ». Lancer: .venv\\Scripts\\python test_config.py
"""
import json
import shutil
import sys
import tempfile
import types
import winreg
from pathlib import Path

import config

tmp = Path(tempfile.mkdtemp(prefix="ruby_config_"))
config.CFG_FILE = tmp / "config.json"
real_ctypes = config.ctypes


class FakeCtypes:
    """ctypes, sauf que Windows répond avec les langues d'affichage voulues (GetUserPreferredUILanguages)."""

    def __init__(self, langs):
        def get(flags, num, buf, size):
            data = "".join(lang + "\0" for lang in langs) + "\0"
            size._obj.value = len(data)
            if buf is not None:
                buf[:len(data)] = data
                num._obj.value = len(langs)
            return 1
        self.windll = types.SimpleNamespace(kernel32=types.SimpleNamespace(GetUserPreferredUILanguages=get))

    def __getattr__(self, name):
        return getattr(real_ctypes, name)


def windows_in(*langs):
    config.ctypes = FakeCtypes(langs)
    return config.os_lang()


# --- la langue de Ruby suit la langue d'affichage de Windows
assert windows_in("fr-FR") == "Français" and windows_in("fr-CA") == "Français" and windows_in("en-US") == "English" and windows_in("en-GB") == "English"
assert windows_in("de-DE", "fr-FR") == "Français", "1re langue préférée que Ruby parle"
assert windows_in("en-US", "fr-FR") == "English", "l'ordre de préférence de Windows compte"
assert windows_in("de-DE", "ja-JP") == "English", "aucune langue connue: English"
assert windows_in() == config.DEFAULT["lang"], "Windows ne répond rien: langue par défaut"
config.ctypes = types.SimpleNamespace()  # pas de windll (autre système, API absente)
assert config.os_lang() == config.DEFAULT["lang"]
config.ctypes = real_ctypes
assert config.os_lang() in config.LANGS, "le vrai Windows de cette machine donne une langue que Ruby parle"

# --- config.json: automatique par défaut, choix explicite conservé, anciens réglages inchangés
config.ctypes = FakeCtypes(["en-US"])
assert not config.CFG_FILE.exists()
c = config.load_cfg()
assert c["lang_auto"] is True and c["lang"] == "English", "installation neuve: la langue de Windows"
config.ctypes = FakeCtypes(["fr-FR"])
assert config.load_cfg()["lang"] == "Français", "Windows change de langue: Ruby suit, sans qu'on ait touché à ses réglages"
config.CFG_FILE.write_text(json.dumps({"lang": "English"}), "utf-8")
c = config.load_cfg()
assert c["lang_auto"] is False and c["lang"] == "English", "réglages d'avant la langue automatique: leur langue est gardée"
config.CFG_FILE.write_text(json.dumps({"lang": "English", "lang_auto": False}), "utf-8")
assert config.load_cfg()["lang"] == "English", "choix explicite: Windows en français ne le change pas"
config.CFG_FILE.write_text(json.dumps({"lang": "English", "lang_auto": True}), "utf-8")
assert config.load_cfg()["lang"] == "Français", "automatique: la langue enregistrée est ignorée"
config.CFG_FILE.write_text(json.dumps({"lang": "Klingon", "lang_auto": False}), "utf-8")
assert config.load_cfg()["lang"] == config.DEFAULT["lang"], "langue inconnue: retour à un choix valide"
# la voix en ligne dépend de la langue: quand la langue suit Windows, elle suit aussi
config.CFG_FILE.write_text(json.dumps({"engine": config.EDGE, "voice": "fr-FR-DeniseNeural"}), "utf-8")
assert config.load_cfg()["voice"] == "fr-FR-DeniseNeural"  # lang_auto est faux: ces réglages contiennent « engine » mais pas « lang »
config.CFG_FILE.write_text(json.dumps({"engine": config.EDGE, "voice": "fr-FR-DeniseNeural", "lang_auto": True}), "utf-8")
config.ctypes = FakeCtypes(["en-US"])
assert config.load_cfg()["lang"] == "English" and config.load_cfg()["voice"] == "en-US-AriaNeural"
config.ctypes = real_ctypes

# --- lancement avec Windows: clé de test, jamais la vraie
HKCU = winreg.HKEY_CURRENT_USER
config.RUN_KEY, config.APPROVED_KEY = r"Software\RubyTest\Run", r"Software\RubyTest\Approved"
try:
    assert not config.autostart()
    config.set_autostart(True)
    assert config.autostart()
    with winreg.OpenKey(HKCU, config.RUN_KEY) as k:
        assert winreg.QueryValueEx(k, "Ruby")[0] == config.startup_command()
    with winreg.CreateKey(HKCU, config.APPROVED_KEY) as k:  # le Gestionnaire des tâches > Démarrage > Désactiver écrit ceci
        winreg.SetValueEx(k, "Ruby", 0, winreg.REG_BINARY, bytes([3] + [0] * 11))
    assert not config.autostart(), "désactivé dans le Gestionnaire des tâches: Windows ne le lancera pas"
    config.set_autostart(True)
    assert config.autostart(), "réactivé depuis Ruby: l'ancien « désactivé » est effacé"
    with winreg.OpenKey(HKCU, config.APPROVED_KEY) as k:
        try:
            winreg.QueryValueEx(k, "Ruby")
            raise AssertionError("l'entrée « désactivé » devait disparaître")
        except FileNotFoundError:
            pass
    with winreg.CreateKey(HKCU, config.APPROVED_KEY) as k:
        winreg.SetValueEx(k, "Ruby", 0, winreg.REG_BINARY, bytes([2] + [0] * 11))
    assert config.autostart(), "activé explicitement par le Gestionnaire des tâches"
    config.set_autostart(False)
    assert not config.autostart()
    config.set_autostart(False)  # déjà désactivé: aucune erreur
    assert not config.autostart()
finally:
    for key in (config.RUN_KEY, config.APPROVED_KEY, r"Software\RubyTest"):
        try:
            winreg.DeleteKey(HKCU, key)
        except OSError:
            pass
config.FROZEN = True
assert config.startup_command() == f'"{sys.executable}"', "dans l'exe: l'exe lui-même"
config.FROZEN = False
cmd = config.startup_command()
assert cmd.startswith('"') and cmd.endswith('ruby.py"') and "pythonw" in cmd.lower(), "depuis les sources: pythonw + ruby.py"

shutil.rmtree(tmp, ignore_errors=True)
print("OK")
