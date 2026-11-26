"""Point d'entrée unique de Ruby (celui de l'exe aussi).

    ruby.py               le moteur: icône dans la barre des tâches, écoute du mot d'activation
    ruby.py --settings    la fenêtre de réglages (un processus à part: le moteur reste à ≈10 Mo)
    ruby.py --debug       le moteur, avec les journaux dans la console et chaque commande enregistrée dans logs/
    ruby.py --quit        demande à un Ruby qui tourne de s'arrêter (l'installateur s'en sert avant de remplacer ses fichiers)
    ruby.py --selftest    vérifie que tout est là (bibliothèques, sons, logo) et l'écrit dans selftest.txt (dossier de données);
                          avec --models, fait aussi tourner Whisper et la voix si tes modèles sont installés
"""
import os
import sys

for name in ("stdout", "stderr"):  # exe sans console (comme pythonw): une bibliothèque qui écrit dans stderr ne doit pas planter
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w"))

MODULES = ("PySide6.QtWidgets", "numpy", "sklearn.linear_model", "joblib", "onnxruntime", "ctranslate2", "av", "faster_whisper",
           "supertonic", "sounddevice", "miniaudio", "edge_tts", "rapidfuzz", "text_to_num", "requests", "certifi",
           "actions", "audio", "brain", "config", "engine", "models", "overlay", "settings", "tts", "wake")


def selftest():
    """Ce qu'un exe mal assemblé perd en silence: bibliothèques (natives comprises), fichiers livrés, certificats. 0 = tout va bien."""
    import importlib
    import traceback
    m, lines, failed = importlib.import_module, [], []

    def check(name):  # décorateur: exécute tout de suite, et un échec n'empêche jamais d'écrire le rapport
        def run(fn):
            try:
                lines.append(f"OK     {name} {fn() or ''}".rstrip())
            except Exception:
                failed.append(name)
                lines.append(f"ÉCHEC  {name}: {traceback.format_exc().strip().splitlines()[-1]}")
        return run

    for mod in MODULES:
        check("import " + mod)(lambda mod=mod: m(mod) and "")

    @check("sons livrés")
    def _():
        audio = m("audio")
        return ", ".join(f"{n} ({len(audio.read_wav(audio.SOUNDS / (n + '.wav'))[0])} échantillons)" for n in ("ready", "fail"))

    @check("logo")
    def _():
        assert (m("overlay").ASSETS / "icon_256.png").stat().st_size > 0

    @check("CTranslate2 (Whisper) en int8")
    def _():
        assert "int8" in m("ctranslate2").get_supported_compute_types("cpu")

    @check("détection de silence (VAD) livrée avec faster-whisper")
    def _():
        assert m("faster_whisper.vad").get_vad_model()

    @check("scikit-learn (apprentissage de ta voix)")
    def _():
        return m("sklearn.linear_model").LogisticRegression().fit(m("numpy").eye(4), [0, 1, 0, 1]).coef_.shape

    @check("certificats HTTPS")
    def _():
        assert os.path.exists(m("certifi").where())

    @check("dossier de données")
    def _():
        return m("config").ROOT

    if "--models" in sys.argv:  # avec tes vrais modèles (s'ils sont installés): le moteur d'inférence natif tourne aussi dans l'exe
        cfg, models, np = m("config").load_cfg(), m("models"), m("numpy")

        @check("Whisper (copie int8): transcrit 1 s de silence")
        def _():
            if not models.installed(cfg, "whisper", cfg["whisper"]):
                return "ignoré (pas installé)"
            w = m("faster_whisper").WhisperModel(models.whisper_source(cfg, cfg["whisper"]), device="cpu", compute_type="int8", local_files_only=True)
            list(w.transcribe(np.zeros(16000, np.float32), language="fr", temperature=0.0)[0])

        @check("voix Supertonic: synthétise « Bonjour. »")
        def _():
            if not models.installed(cfg, "voice"):
                return "ignoré (pas installée)"
            tts = m("supertonic").TTS(model_dir=models.custom_or_none(cfg, "voice"), auto_download=False)
            wav, _ = tts.synthesize("Bonjour.", voice_style=tts.get_voice_style("F1"), lang="fr", total_steps=2)
            assert len(wav[0]) > 0

    report = "\n".join(lines)
    (m("config").ROOT / "selftest.txt").write_text(report + "\n", "utf-8")
    print(report)
    return 1 if failed else 0


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    if "--quit" in sys.argv:
        import config
        config.QUIT_FILE.touch()
        sys.exit(0)
    if "--settings" in sys.argv:
        import settings
        settings.main()
    else:
        import engine
        engine.main()
