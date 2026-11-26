"""Voix de Ruby: Supertonic (local, ONNX, CPU) ou Edge (en ligne), avec cache sur disque et lecture phrase par phrase."""
import asyncio
import hashlib
import logging
import os
import re
import threading
import wave
from concurrent.futures import ThreadPoolExecutor

import numpy as np

import audio
import config
import models
from config import EDGE, LANGS

LOG = logging.getLogger("ruby")
CACHE_MAX = 200  # fichiers gardés dans config.CACHE; les moins récemment utilisés sont effacés


def _file(key):
    return config.CACHE / (hashlib.sha1(repr(key).encode("utf-8")).hexdigest()[:24] + ".wav")


def cached(key):
    """(audio int16, fréquence) d'une phrase déjà dite, ou None. Charger la voix coûte 1-2 s et ≈410 Mo: relire un .wav, 1 ms."""
    f = _file(key)
    try:
        with wave.open(str(f)) as w:
            out = np.frombuffer(w.readframes(w.getnframes()), np.int16), w.getframerate()
        os.utime(f)  # « utilisé récemment »: c'est ce qui décide quoi effacer
        return out
    except (OSError, EOFError, wave.Error):  # absent ou abîmé: on recalcule
        return None


def store(key, x, sr):
    """Garde la phrase (en 16 bits, comme la lecture) et efface les plus anciennes au-delà de CACHE_MAX. Jamais bloquant: une erreur est ignorée."""
    x = np.asarray(x).squeeze()
    if x.dtype.kind == "f":
        x = np.clip(x * 32767, -32768, 32767)
    try:
        config.CACHE.mkdir(parents=True, exist_ok=True)
        f = _file(key)
        tmp = f.with_suffix(".tmp")
        with wave.open(str(tmp), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(int(sr))
            w.writeframes(x.astype(np.int16).tobytes())
        os.replace(tmp, f)  # le fichier final n'existe que complet
        old = sorted(config.CACHE.glob("*.wav"), key=lambda p: p.stat().st_mtime)
        for p in old[:max(0, len(old) - CACHE_MAX)]:
            p.unlink(missing_ok=True)
    except OSError:
        LOG.exception("cache de la voix")


class Speaker:
    def __init__(self):
        self.tts, self.tts_path, self.styles = None, None, {}
        self.lock = threading.Lock()  # préchargement et lecture ne doivent pas charger le modèle deux fois

    def load(self, cfg):
        """Charge la voix locale depuis son dossier (cfg['paths']['voice']); ne télécharge (~385 Mo) que si elle manque."""
        path = models.custom_or_none(cfg, "voice")
        with self.lock:
            if self.tts is None or self.tts_path != path:
                from supertonic import TTS
                self.tts = TTS(model_dir=path, auto_download=not models.installed(cfg, "voice"))
                self.tts_path, self.styles = path, {}

    def unload(self):
        """Libère le modèle (≈410 Mo). Les phrases déjà synthétisées restent sur disque: les rejouer ne le recharge pas."""
        with self.lock:
            self.tts, self.tts_path, self.styles = None, None, {}

    def render(self, text, cfg):
        """(audio, fréquence). Les phrases déjà dites (« Lecture ou pause. ») reviennent du disque: 0 délai, et la voix n'est pas chargée."""
        key = (cfg["engine"], cfg["voice"], cfg["speed"], cfg["tts_steps"], cfg["lang"], text)
        if (hit := cached(key)) is not None:
            return hit
        if cfg["engine"] == EDGE:
            try:
                out = self._edge(text, cfg), 24000
            except Exception as e:  # hors-ligne, service bloqué: Ruby parle quand même, avec la voix locale (non mise en cache)
                LOG.warning("Edge indisponible (%s): voix locale à la place", e)
                return self._local(text, dict(cfg, voice="F1"))
        else:
            out = self._local(text, cfg)
        store(key, *out)
        return out

    def _local(self, text, cfg):
        self.load(cfg)
        style = self.styles.setdefault(cfg["voice"], self.tts.get_voice_style(cfg["voice"]))
        wav, _ = self.tts.synthesize(text, voice_style=style, lang=LANGS[cfg["lang"]]["tts"],
                                     total_steps=cfg["tts_steps"], speed=1.05 * cfg["speed"])
        return np.asarray(wav, np.float32).squeeze(), self.tts.sample_rate

    def say(self, text, cfg):
        """Une phrase à la fois: la suivante est calculée pendant que la précédente est jouée (réponses longues)."""
        parts = [p for p in re.split(r"(?<=[.!?])\s+", text.strip()) if p]
        dev = audio.device_index(cfg["speaker"], "output")
        with ThreadPoolExecutor(1) as ex:
            nxt = ex.submit(self.render, parts[0], cfg) if parts else None
            for i in range(len(parts)):
                x, sr = nxt.result()
                if i + 1 < len(parts):
                    nxt = ex.submit(self.render, parts[i + 1], cfg)
                audio.play(x, sr, dev, cfg["volume"], tail=0.3 if i + 1 == len(parts) else 0.05)

    @staticmethod
    def _edge(text, cfg):
        import edge_tts
        import miniaudio

        async def mp3():
            data = b""
            rate = f"{round((cfg['speed'] - 1) * 100):+d}%"
            async for c in edge_tts.Communicate(text, cfg["voice"], rate=rate).stream():
                if c["type"] == "audio":
                    data += c["data"]
            return data

        return np.array(miniaudio.decode(asyncio.run(mp3()), nchannels=1, sample_rate=24000).samples, dtype=np.int16)
