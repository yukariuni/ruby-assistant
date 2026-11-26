"""Moteur de Ruby: écoute, comprend, agit. Tourne sans fenêtre (icône dans la barre des tâches + lueur d'écran).

Lancé par Ruby.bat. Les réglages (settings.py) sont un processus séparé qui écrit config.json:
le moteur relit ce fichier à chaud. `python engine.py --debug` affiche les logs dans la console.

Mémoire (plafond config.MEM_LIMIT = 500 Mo pour tout Ruby): au repos seul le détecteur du mot d'activation est en mémoire (≈10 Mo mesurés).
Whisper (pic ≈425 Mo) se charge quand tu dis le mot d'activation, pendant ta phrase (1,2 s: caché par ta voix), et est libéré dès que la phrase
est transcrite. La voix (pic ≈430 Mo) ne se charge qu'ensuite, et seulement si la réponse n'est pas déjà sur disque (tts.cached): les deux modèles
ne sont JAMAIS en mémoire en même temps (à eux deux ils feraient ≈700 Mo).
"""
import gc
import json
import logging
import logging.handlers
import os
import queue
import subprocess
import sys
import threading
import time
import wave
from collections import deque

import numpy as np
from PySide6.QtCore import QLockFile, QObject, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

import actions
import audio
import brain
import config
import models
import wake
from config import LANGS, phrases
from memory import private_mb, trim
from overlay import Glow, make_icon
from tts import Speaker

LOG = logging.getLogger("ruby")
DEBUG = "--debug" in sys.argv  # console + sauvegarde de chaque commande vocale en .wav dans logs/
QUIET_CHUNKS = 9  # ~0,7 s de silence = fin de phrase (plus court = plus réactif, mais coupe les pauses)


class Worker(threading.Thread):
    """Boucle d'écoute: mot d'activation -> enregistrement -> transcription -> action."""

    def __init__(self, cfg, on_state):
        super().__init__(daemon=True)
        self.cfg, self.on_state = cfg, on_state
        self.speaker, self.whisper, self.whisper_key = Speaker(), None, None
        self.stop, self.score, self.text, self.reply, self.detail = threading.Event(), 0.0, "", "", ""
        self.load_lock, self.last_trim, self.voice_loading = threading.Lock(), 0.0, None  # voice_loading: thread qui charge la voix d'avance

    # -- état partagé avec l'interface
    def state(self, s, score=None, detail=""):
        """detail: précision affichée sous l'état dans les réglages (ex. le modèle en cours de téléchargement)."""
        if score is not None:
            self.score = score
        self.detail = detail
        self.on_state(s)

    def ready(self):
        ph = phrases(self.cfg["words"])
        return config.MODEL_FILE.exists() and bool(ph) and phrases(self.cfg["synced"]) == ph

    def loaded(self):
        """Ce qui occupe de la mémoire en ce moment (affiché dans les réglages)."""
        key = self.whisper_key  # lu une seule fois: le thread de chargement le change pendant que l'interface lit
        return ([f"Whisper {key[0]}"] if key and self.whisper is not None else []) + (["voix"] if self.speaker.tts is not None else [])

    # -- modèles: téléchargés une fois, chargés à la demande, libérés après une pause
    def migrate(self):
        """Ancienne voix apprise (scikit-learn) -> numpy, dans un processus à part: scikit-learn ne doit jamais entrer dans la mémoire du moteur."""
        # shortcut: pas dans l'exe (il ne sait pas relancer Python en « -c » et n'a pas ce vieux format à convertir), seulement depuis les sources
        if not config.FROZEN and config.LEGACY_MODEL.exists() and not config.MODEL_FILE.exists():
            LOG.info("conversion de l'ancienne voix apprise")
            subprocess.run([sys.executable, "-c", "import sys, wake; wake.migrate_legacy(sys.argv[1], sys.argv[2])",
                            str(config.LEGACY_MODEL), str(config.MODEL_FILE)], cwd=os.path.dirname(os.path.abspath(__file__)), creationflags=0x08000000, check=False)  # CREATE_NO_WINDOW

    def ensure_whisper(self):
        """Whisper téléchargé ET converti en int8 (une fois, ≈3 s): sans cette copie son chargement monte à 680 Mo (voir models.quantize_ct2)."""
        name, root = self.cfg["whisper"], models.custom_or_none(self.cfg, "whisper")
        if not models.installed(self.cfg, "whisper", name):
            self.state("downloading", detail=f"Whisper {name} ({models.WHISPER_APPROX.get(name, '')})")
            LOG.info("téléchargement de Whisper %s dans %s", name, root or models.folder(self.cfg, "whisper"))
            from faster_whisper.utils import download_model
            download_model(name, cache_dir=root)
        if models.whisper_source(self.cfg, name) == name:  # pas encore de copie int8
            self.state("downloading", detail=f"Optimisation de Whisper {name} (mémoire réduite, une seule fois)")
            try:
                models.ensure_int8(self.cfg, name)
            except Exception:  # Ruby marche quand même avec le fichier d'origine: seul le chargement dépasse le plafond (≈680 Mo, 1 s)
                LOG.exception("conversion de Whisper en int8")

    def ensure_downloaded(self):
        """Télécharge ce qui manque (état « Téléchargement… » visible dans les réglages) sans rien charger en mémoire."""
        self.ensure_whisper()
        if not models.installed(self.cfg, "wake"):
            self.state("downloading", detail="Détection du mot d'activation (≈2,4 Mo)")
            models.ensure_wake(models.folder(self.cfg, "wake"))
        if self.cfg["engine"] != config.EDGE and not models.installed(self.cfg, "voice"):
            self.state("downloading", detail="Voix Supertonic (≈385 Mo)")
            LOG.info("téléchargement de la voix dans %s", models.folder(self.cfg, "voice"))
            try:
                from supertonic.loader import download_model as download_voice
                download_voice(models.folder(self.cfg, "voice"))
            except Exception:  # sans la voix locale Ruby agit quand même, en silence
                LOG.exception("téléchargement de la voix")
        self.state("starting")

    def model(self):
        """Modèle Whisper du réglage actuel, chargé à la demande depuis sa copie int8 (rechargé si la taille ou le dossier a changé).

        Déjà installé: aucun accès réseau (≈1,2 s). Pas de « préchauffage »: mesuré, il ne rend pas la 1re commande plus rapide."""
        key = (self.cfg["whisper"], models.custom_or_none(self.cfg, "whisper"))
        with self.load_lock:  # le préchargement et la commande peuvent le demander en même temps
            if self.whisper_key != key:
                from faster_whisper import WhisperModel
                name, root = key
                self.whisper = self.whisper_key = None  # libère l'ancien avant de charger le nouveau
                try:
                    self.whisper = WhisperModel(models.whisper_source(self.cfg, name), device="cpu", compute_type="int8",
                                                download_root=root, local_files_only=True)
                except Exception:  # supprimé pendant que Ruby tournait: on le retélécharge (et le reconvertit)
                    self.ensure_whisper()
                    self.whisper = WhisperModel(models.whisper_source(self.cfg, name), device="cpu", compute_type="int8", download_root=root)
                self.whisper_key = key
                LOG.info("Whisper %s chargé (mémoire %d Mo)", name, private_mb())
            return self.whisper

    def preload(self):
        """« Hey Ruby » détecté: Whisper se charge pendant que tu parles. La voix, elle, attend la fin de la transcription."""
        def load():
            try:
                self.model()
            except Exception:
                LOG.exception("préchargement")
        self.release_voice()  # déjà libérée après la réponse: ceinture et bretelles, Whisper et la voix ne doivent jamais coexister
        threading.Thread(target=load, daemon=True).start()

    def preload_voice(self):
        """Groq va répondre par une phrase inédite (donc pas sur disque): la voix se charge pendant qu'il réfléchit (≈1 s). Whisper est déjà libéré."""
        def load():
            try:
                self.speaker.load(self.cfg)
            except Exception:
                LOG.exception("préchargement de la voix")
        if self.cfg["engine"] != config.EDGE and self.voice_loading is None:
            self.voice_loading = threading.Thread(target=load, daemon=True)
            self.voice_loading.start()

    def settle(self):
        """Démarrage terminé: si rien de gros n'est en mémoire, on rend à Windows ce qui ne sert plus (jamais si des modèles sont chargés:
        leurs poids partiraient sur le disque)."""
        if not self.loaded():
            trim()

    def tidy(self):
        """Toutes les 30 s, sans modèle chargé: Windows reprend les pages que Ruby n'a plus touchées. Mesuré: le noyau actif du moteur
        à l'écoute ne pèse que ≈9 Mo; sans ça il garde les pages du démarrage (≈20 Mo)."""
        if not self.loaded() and time.time() - self.last_trim > 30:
            self.last_trim = time.time()
            trim()

    def freed(self, what):
        gc.collect()
        LOG.info("%s (mémoire avant le vidage: %d Mo)", what, private_mb())  # mesurée avant, sinon on lirait toujours ≈0
        trim()  # Windows reprend aussi les pages des bibliothèques devenues inutiles

    def release_whisper(self):
        """Whisper (≈290 Mo, pic ≈425) est libéré dès que la phrase est transcrite: c'est ce qui laisse la place à la voix. Mesuré: vraiment rendu."""
        with self.load_lock:  # attend la fin d'un chargement encore en cours (parole très courte)
            if self.whisper is None:
                return
            self.whisper = self.whisper_key = None
        self.freed("Whisper libéré")

    def release_voice(self):
        """Voix (≈415 Mo) libérée dès que Ruby a fini de parler: elle ne sert plus à rien avant la prochaine phrase inédite."""
        t, self.voice_loading = self.voice_loading, None
        if t:
            t.join()  # chargement d'avance pas fini: on le laisse finir, puis on libère
        if self.speaker.tts is not None:
            self.speaker.unload()
            self.freed("Voix libérée")

    def release(self):
        self.release_whisper()
        self.release_voice()

    # -- boucle principale
    def run(self):
        self.state("starting")
        while not self.stop.is_set():
            try:
                self.migrate()
                if not self.ready():
                    self.state("needs_sync")
                    time.sleep(1)
                    continue
                actions.apps()
                self.ensure_downloaded()
                LOG.info("prêt (mémoire %d Mo)", private_mb())
                self.settle()
                self.listen()
            except Exception as e:
                LOG.exception("moteur")
                self.state("error")
                self.text = f"Erreur: {e}"
                time.sleep(3)
        self.state("stopped")

    def listen(self):
        det = wake.Detector(wake.Classifier.load(config.MODEL_FILE), models.custom_or_none(self.cfg, "wake"))
        mtime = lambda: config.MODEL_FILE.stat().st_mtime if config.MODEL_FILE.exists() else 0
        key = lambda: (mtime(), self.cfg["mic"], self.cfg["words"], self.cfg["synced"], self.cfg["whisper"],
                       models.custom_or_none(self.cfg, "whisper"), models.custom_or_none(self.cfg, "wake"))
        k0, checked = key(), time.time()
        q, ambient, cool = queue.Queue(), deque(maxlen=60), 0.0
        with audio.sd.InputStream(samplerate=wake.SR, channels=1, dtype="int16", blocksize=wake.CHUNK,
                                  device=audio.device_index(self.cfg["mic"], "input"),
                                  callback=lambda x, *_: q.put(x[:, 0].copy())):
            LOG.info("écoute: %s", " / ".join(phrases(self.cfg["synced"])))
            self.state("listening")
            while not self.stop.is_set():
                if time.time() - checked > 1:
                    checked = time.time()
                    if key() != k0 or not self.ready():  # micro, mots, modèles ou dossiers changés: on repart proprement
                        return
                    self.tidy()
                try:
                    chunk = q.get(timeout=0.2)
                except queue.Empty:
                    continue
                ambient.append(wake._rms(chunk).mean())
                self.score = round(det.score(chunk), 2)
                if self.score > 0.3:
                    LOG.debug("score mot d'activation: %.2f (seuil %.2f)", self.score, self.cfg["threshold"])
                if self.score >= self.cfg["threshold"] and time.time() > cool:
                    self.preload()  # Whisper se charge pendant que tu parles
                    self.command(q, float(np.median(ambient)))
                    with q.mutex:
                        q.queue.clear()
                    det.reset()
                    cool = time.time() + 1
                    self.state("listening", score=0.0)

    def command(self, q, noise):
        """Un tour complet: enregistre ta phrase puis la traite. Quoi qu'il arrive, aucun modèle ne reste en mémoire après."""
        try:
            pcm = self.record(q, noise)
            if pcm is not None:
                self.handle(pcm)
        finally:
            self.release()

    def record(self, q, noise):
        """Enregistre jusqu'au silence. Retourne le son (int16 16 kHz), ou None si personne n'a parlé."""
        out, vol = audio.device_index(self.cfg["speaker"], "output"), self.cfg["volume"]
        self.state("recording")  # la lueur d'écran s'allume: Ruby est prête
        audio.play_sound("ready", out, vol)
        with q.mutex:
            q.queue.clear()  # ne pas enregistrer le son
        buf, speech, quiet, t0 = [], False, 0, time.time()
        while time.time() - t0 < 10 and not self.stop.is_set():
            try:
                c = q.get(timeout=0.2)
            except queue.Empty:
                continue
            buf.append(c)
            if wake._rms(c).mean() > max(3 * noise, 150):
                speech, quiet = True, 0
            else:
                quiet += 1
            if quiet >= (QUIET_CHUNKS if speech else 40):  # silence après la parole, ou ~3 s si rien
                break
        LOG.debug("enregistrement: %d chunks, parole=%s, bruit ambiant=%.0f", len(buf), speech, noise)
        if not speech:
            self.state("listening")
            audio.play_sound("fail", out, vol)
            return None
        pcm = np.concatenate(buf)
        if DEBUG:
            with wave.open(str(config.LOGS / time.strftime("cmd-%H%M%S.wav")), "wb") as f:
                f.setnchannels(1)
                f.setsampwidth(2)
                f.setframerate(wake.SR)
                f.writeframes(pcm.astype(np.int16).tobytes())
        return pcm

    def handle(self, pcm):
        """Transcrit, agit, répond. L'ordre est celui du plafond de mémoire: Whisper, puis (Whisper libéré) la voix, jamais les deux ensemble."""
        L, out, vol = LANGS[self.cfg["lang"]], audio.device_index(self.cfg["speaker"], "output"), self.cfg["volume"]
        self.state("thinking")
        # temperature=0.0: pas de « repli » quand Whisper doute. Par défaut il relance 5 décodages échantillonnés (best_of=5), ce qui
        # duplique les caches du décodeur: mesuré, le pic passe de 430 à 850 Mo (plafond: 500). Un seul essai est aussi déterministe.
        segs, info = self.model().transcribe(pcm.astype(np.float32) / 32768, language=L["whisper"],
                                             vad_filter=True, initial_prompt=L["prompt"], temperature=0.0)
        text = " ".join(s.text for s in segs).strip()
        LOG.info("transcription: %r (langue %s, confiance %.2f)", text, info.language, info.language_probability)
        self.text = text
        self.release_whisper()  # AVANT Groq et la voix
        if text and brain.api_key(self.cfg):
            self.preload_voice()  # Groq répond par une phrase inédite: la voix se charge pendant qu'il réfléchit
        try:
            # Groq d'abord (comprend n'importe quelle phrase); sans clé ou hors-ligne: règles locales
            ok, say = brain.ask(text, L, self.cfg) or actions.act(text, L)  # l'action part tout de suite, la phrase vient après
            LOG.info("compris=%s, réponse: %r", ok, say)
            self.reply = say or ""
            if not ok:
                audio.play_sound("fail", out, vol)
            if say:
                self.state("speaking")
                self.speaker.say(say, self.cfg)  # sur disque si déjà dite: la voix n'est même pas chargée
        except Exception:
            LOG.exception("action")
        finally:
            self.release_voice()


class Engine(QObject):
    state_changed = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.cfg, self.cfg_mtime, self.last_status = config.load_cfg(), 0, {}
        self.glows = [Glow(s) for s in app.screens()]
        self.worker = Worker(self.cfg, self.state_changed.emit)
        self.state_changed.connect(self.on_state)  # signal: le thread d'écoute ne touche jamais à l'interface directement
        self.tray = QSystemTrayIcon(make_icon(), self)
        menu = QMenu()
        menu.addAction(QAction("Réglages", menu, triggered=lambda: config.launch("settings.py")))
        menu.addAction(QAction("Quitter Ruby", menu, triggered=app.quit))
        self.tray.setContextMenu(menu)
        self.tray.setToolTip("Ruby")
        self.tray.activated.connect(lambda r: r == QSystemTrayIcon.ActivationReason.Trigger and config.launch("settings.py"))
        self.tray.show()
        self.timer = QTimer(self, interval=250, timeout=self.tick)
        self.timer.start()
        app.aboutToQuit.connect(self.shutdown)
        self.worker.start()

    def on_state(self, s):
        glow = self.cfg["glow"]
        speed = {"recording": 2.0, "thinking": 6.0, "speaking": 1.5}.get(s)
        for g in self.glows:
            g.set_active(bool(glow and speed), speed or 2.0)
        self.write_status(s)

    def tick(self):
        if config.QUIT_FILE.exists():
            config.QUIT_FILE.unlink(missing_ok=True)
            QApplication.quit()
            return
        try:
            m = config.CFG_FILE.stat().st_mtime
            if m != self.cfg_mtime:  # réglages modifiés: appliqués à chaud, sans redémarrer
                self.cfg_mtime = m
                self.cfg.clear()
                self.cfg.update(config.load_cfg())
        except OSError:
            pass
        self.write_status()

    def write_status(self, state=None):
        st = dict(state=state or self.last_status.get("state", "starting"), score=self.worker.score, text=self.worker.text,
                  reply=self.worker.reply, detail=self.worker.detail, pid=os.getpid(), loaded=self.worker.loaded(),
                  mem=round(private_mb() / 5) * 5,  # arrondi: la valeur ne change pas à chaque tick (pas d'écriture inutile)
                  groq=bool(self.cfg["groq_key"] or os.environ.get("GROQ_API_KEY")))
        if st == {k: v for k, v in self.last_status.items() if k != "ts"} and time.time() - self.last_status.get("ts", 0) < 1:
            return  # rien de nouveau: seulement un battement par seconde
        self.last_status = dict(st, ts=time.time())
        tmp = config.STATUS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.last_status), "utf-8")
        os.replace(tmp, config.STATUS_FILE)

    def shutdown(self):
        self.worker.stop.set()
        config.STATUS_FILE.unlink(missing_ok=True)


def main():
    config.LOGS.mkdir(exist_ok=True)
    handlers = [logging.handlers.RotatingFileHandler(config.LOGS / "engine.log", maxBytes=512_000, backupCount=2, encoding="utf-8")]
    if DEBUG:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s", datefmt="%H:%M:%S", handlers=handlers)
    LOG.setLevel(logging.DEBUG if DEBUG else logging.INFO)
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Ruby.Assistant")
    app = QApplication(sys.argv)
    app.setWindowIcon(make_icon())
    app.setQuitOnLastWindowClosed(False)
    lock = QLockFile(str(config.ROOT / "engine.lock"))
    if not lock.tryLock(100):  # déjà lancé: une seule instance (sinon deux micros, deux voix)
        sys.exit(0)
    engine = Engine(app)  # noqa: F841 (garde la référence)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
