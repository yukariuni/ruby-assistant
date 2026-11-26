"""Configuration partagée par le moteur (engine.py) et les réglages (settings.py): config.json + textes."""
import ctypes
import json
import os
import subprocess
import sys
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)  # True dans l'exe (PyInstaller)
# ROOT = tout ce que Ruby écrit (réglages, ta voix, journaux, cache). Code: le dossier du projet. Exe: %APPDATA%\Ruby (le dossier du programme
# peut être en lecture seule). RUBY_HOME impose un autre dossier: mode portable, ou tester l'exe sans toucher à tes vrais réglages.
if os.environ.get("RUBY_HOME"):
    ROOT = Path(os.environ["RUBY_HOME"])
elif FROZEN:
    ROOT = Path(os.environ.get("APPDATA") or Path.home()) / "Ruby"
else:
    ROOT = Path(__file__).parent
CFG_FILE, STATUS_FILE, QUIT_FILE = ROOT / "config.json", ROOT / "status.json", ROOT / "engine.quit"
MODEL_FILE, SAMPLES_FILE = ROOT / "voice" / "wake.npz", ROOT / "voice" / "samples.npz"  # ta voix apprise (numpy pur) et les enregistrements
LEGACY_MODEL = ROOT / "voice" / "wake.pkl"  # ancien format (scikit-learn): converti au démarrage, voir wake.migrate_legacy
WAKE_DEFAULT = ROOT / "models" / "openwakeword"  # emplacement par défaut des 2 petits modèles openWakeWord (≈2,4 Mo)
LOGS = ROOT / "logs"
(ROOT / "voice").mkdir(parents=True, exist_ok=True)

N_POS, REC_SEC = 6, 3.5  # « Hey Ruby » à répéter pendant Sync voice, durée de chaque enregistrement
SUPERTONIC, EDGE = "Supertonic (local)", "Edge (en ligne)"

LANGS = {
    "Français": dict(
        tts="fr", whisper="fr", hello="Bonjour, je suis Ruby.", browser="le navigateur",
        # ce que Ruby dit après avoir agi
        opening="J'ouvre {}.", searching="Je cherche {} sur Google.", noapp="Je ne trouve pas {}.",
        vol_up="J'ai monté le volume.", vol_down="J'ai baissé le volume.", mute="Son coupé.",
        playpause="Lecture ou pause.", next="Piste suivante.", prev="Piste précédente.", time="Il est {}.", clock="%Hh%M",
        calc="Ça fait {}.", calc_err="Je ne peux pas calculer ça.", dec=",",
        prompt="Ouvre Discord. Lance Spotify. Cherche sur internet. Mets pause. Monte le volume. Combien font 12 fois 7 ?",  # oriente Whisper
        neg=["Bonjour", "Quelle heure est-il", "Ouvre le navigateur", "Il fait beau aujourd'hui"]),
    "English": dict(
        tts="en", whisper="en", hello="Hello, I'm Ruby.", browser="the browser",
        opening="Opening {}.", searching="Searching Google for {}.", noapp="I can't find {}.",
        vol_up="Volume up.", vol_down="Volume down.", mute="Muted.",
        playpause="Play or pause.", next="Next track.", prev="Previous track.", time="It's {}.", clock="%I:%M %p",
        calc="That's {}.", calc_err="I can't calculate that.", dec=".",
        prompt="Open Discord. Launch Spotify. Search the internet. Pause. Volume up. What is 12 times 7?",
        neg=["Hello there", "What time is it", "Open the browser", "The weather is nice"]),
}
SUPERTONIC_VOICES = ["F1", "F2", "F3", "F4", "F5", "M1", "M2", "M3", "M4", "M5"]  # mêmes voix en français et en anglais
VOICES = {
    SUPERTONIC: {lang: SUPERTONIC_VOICES for lang in LANGS},
    EDGE: {"Français": ["fr-FR-DeniseNeural", "fr-FR-HenriNeural", "fr-FR-VivienneMultilingualNeural", "fr-FR-RemyMultilingualNeural"],
           "English": ["en-US-AriaNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]},
}
# Mémoire: plafond voulu par l'utilisateur pour TOUT Ruby (moteur + fenêtre de réglages), en Mo de « jeu de travail privé » (Gestionnaire des tâches).
# Pour le tenir, Whisper (pic 423 Mo) et la voix (pic 427 Mo) ne sont JAMAIS chargés en même temps: voir engine.Worker.handle.
MEM_LIMIT = 500
WHISPER_SIZES = ("base", "small")  # « medium » a besoin de ≈800 Mo: au-dessus du plafond, donc plus proposé
CACHE = ROOT / "cache" / "tts"  # phrases déjà dites (voir tts.py)
DEFAULT = dict(lang="Français", lang_auto=True, engine=SUPERTONIC, voice="F1", speed=1.0, volume=0.35, glow=True, tts_steps=5,
               mic="", speaker="", threshold=0.85, words="hi;hey", synced="",  # synced: mots utilisés au dernier Sync voice
               whisper="small",  # base: rapide (≈300 Mo au pic), small: plus précis (≈430 Mo au pic)
               groq_key="", groq_model="openai/gpt-oss-20b",  # la clé est stockée en clair dans config.json
               paths=dict(whisper="", voice="", wake=""))  # dossier d'installation de chaque modèle téléchargé; vide = emplacement par défaut (voir models.py)


def os_lang():
    """La langue de Ruby qui correspond à la langue d'affichage de Windows: la 1re de ses langues préférées que Ruby parle.

    Aucune ne correspond: English. Détection impossible (pas Windows…): la langue par défaut."""
    try:
        k, n, size = ctypes.windll.kernel32, ctypes.c_ulong(), ctypes.c_ulong()
        k.GetUserPreferredUILanguages(0x8, ctypes.byref(n), None, ctypes.byref(size))  # 0x8: noms de langues (« fr-FR »); 1er appel: taille
        buf = ctypes.create_unicode_buffer(size.value)
        k.GetUserPreferredUILanguages(0x8, ctypes.byref(n), buf, ctypes.byref(size))
        wanted = [s.split("-")[0].lower() for s in buf[:size.value].split("\0") if s]
    except Exception:
        return DEFAULT["lang"]
    if not wanted:
        return DEFAULT["lang"]
    return next((name for code in wanted for name, L in LANGS.items() if L["whisper"] == code), "English")


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"  # où Windows lit ce qu'il lance à l'ouverture de session
APPROVED_KEY = r"Software\Microsoft\Windows\CurrentVersion\Explorer\StartupApproved\Run"  # « Désactiver » du Gestionnaire des tâches


def startup_command():
    """Ce que Windows lance à l'ouverture de session: l'exe, ou depuis les sources pythonw + ruby.py."""
    if FROZEN:
        return f'"{sys.executable}"'
    exe = Path(sys.executable).with_name("pythonw.exe")
    return f'"{exe if exe.exists() else sys.executable}" "{Path(__file__).parent / "ruby.py"}"'


def autostart():
    """True si Ruby se lance à l'ouverture de session de Windows (et que le Gestionnaire des tâches ne l'a pas désactivé)."""
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, "Ruby")
    except OSError:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, APPROVED_KEY) as k:
            return winreg.QueryValueEx(k, "Ruby")[0][0] % 2 == 0  # 1er octet: 02 = activé, 03 = désactivé par l'utilisateur
    except OSError:
        return True


def set_autostart(on):
    import winreg

    def delete(key):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key, 0, winreg.KEY_SET_VALUE) as k:
                winreg.DeleteValue(k, "Ruby")
        except FileNotFoundError:
            pass
    if on:
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.SetValueEx(k, "Ruby", 0, winreg.REG_SZ, startup_command())
        delete(APPROVED_KEY)  # un ancien « désactivé » du Gestionnaire des tâches ferait ignorer l'entrée
    else:
        delete(RUN_KEY)


def launch(script):
    """Lance engine.py / settings.py dans un processus indépendant et sans console (dans l'exe: Ruby.exe, avec --settings pour les réglages)."""
    if FROZEN:
        cmd = [sys.executable] + (["--settings"] if script == "settings.py" else [])
    else:
        exe = Path(sys.executable).with_name("pythonw.exe")
        cmd = [str(exe if exe.exists() else sys.executable), str(Path(__file__).parent / script)]
    subprocess.Popen(cmd, cwd=ROOT, creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP


def phrases(words):
    """« hi;hey » -> ['Hi Ruby', 'Hey Ruby']"""
    return [f"{w.strip().capitalize()} Ruby" for w in words.split(";") if w.strip()]


def load_cfg():
    cfg = dict(DEFAULT)
    if CFG_FILE.exists():
        try:
            saved = json.loads(CFG_FILE.read_text("utf-8"))
            cfg.update(saved)
            if "lang" in saved and "lang_auto" not in saved:
                cfg["lang_auto"] = False  # réglages d'avant la langue automatique: la langue qu'ils contiennent reste
        except ValueError:
            pass  # fichier à moitié écrit: on garde les valeurs par défaut, la prochaine lecture sera bonne
    loaded = cfg.get("paths") if isinstance(cfg.get("paths"), dict) else {}
    cfg["paths"] = {**DEFAULT["paths"], **loaded}  # nouveau dict à chaque lecture: jamais partagé avec DEFAULT
    # anciennes configs (Kokoro, Piper) ou valeurs invalides -> retour à un choix valide
    if cfg["lang_auto"]:  # suit Windows: changer sa langue d'affichage change Ruby, sans toucher à ses réglages
        cfg["lang"] = os_lang()
    elif cfg["lang"] not in LANGS:
        cfg["lang"] = DEFAULT["lang"]
    cfg.pop("ram", None)  # ancien réglage (modes mémoire): supprimé, le plafond est maintenant fixe
    if cfg["whisper"] not in WHISPER_SIZES:
        cfg["whisper"] = DEFAULT["whisper"]
    if cfg["engine"] not in VOICES:
        cfg["engine"] = DEFAULT["engine"]
    if cfg["voice"] not in VOICES[cfg["engine"]][cfg["lang"]]:
        cfg["voice"] = VOICES[cfg["engine"]][cfg["lang"]][0]
    return cfg


def save_cfg(cfg):
    tmp = CFG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), "utf-8")
    os.replace(tmp, CFG_FILE)  # remplacement atomique: le moteur ne lit jamais un fichier à moitié écrit
