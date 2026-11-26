"""Single entry point of Ruby (the installed application uses it too).

    ruby.py               the engine: tray icon, wake-word listening
    ruby.py --settings    the settings window (a separate process, so the engine stays at about 10 MB)
    ruby.py --debug       the engine, with logs in the console and every voice command saved to logs/
    ruby.py --quit        asks a running Ruby to stop (the installer uses it before replacing files)
    ruby.py --selftest    checks that everything is in place (libraries, sounds, logo) and writes selftest.txt (data folder);
                          with --models, also runs Whisper and the voice if their models are installed
"""
import os
import sys

for name in ("stdout", "stderr"):  # no console (like pythonw): a library that writes to stderr must not crash
    if getattr(sys, name) is None:
        setattr(sys, name, open(os.devnull, "w"))

MODULES = ("PySide6.QtWidgets", "numpy", "sklearn.linear_model", "joblib", "onnxruntime", "ctranslate2", "av", "faster_whisper",
           "supertonic", "sounddevice", "miniaudio", "edge_tts", "rapidfuzz", "text_to_num", "requests", "certifi",
           "actions", "audio", "brain", "config", "engine", "models", "overlay", "settings", "tts", "wake")


def selftest():
    """What a badly assembled bundle silently loses: libraries (native ones included), shipped files, certificates. 0 means all good."""
    import importlib
    import traceback
    m, lines, failed = importlib.import_module, [], []

    def check(name):  # decorator: runs at once, and a failure never prevents the report from being written
        def run(fn):
            try:
                lines.append(f"OK     {name} {fn() or ''}".rstrip())
            except Exception:
                failed.append(name)
                lines.append(f"FAIL   {name}: {traceback.format_exc().strip().splitlines()[-1]}")
        return run

    for mod in MODULES:
        check("import " + mod)(lambda mod=mod: m(mod) and "")

    @check("bundled sounds")
    def _():
        audio = m("audio")
        return ", ".join(f"{n} ({len(audio.read_wav(audio.SOUNDS / (n + '.wav'))[0])} samples)" for n in ("ready", "fail"))

    @check("logo")
    def _():
        assert (m("overlay").ASSETS / "icon_256.png").stat().st_size > 0

    @check("CTranslate2 (Whisper) int8")
    def _():
        assert "int8" in m("ctranslate2").get_supported_compute_types("cpu")

    @check("voice activity detection shipped with faster-whisper")
    def _():
        assert m("faster_whisper.vad").get_vad_model()

    @check("scikit-learn (voice enrollment)")
    def _():
        return m("sklearn.linear_model").LogisticRegression().fit(m("numpy").eye(4), [0, 1, 0, 1]).coef_.shape

    @check("HTTPS certificates")
    def _():
        assert os.path.exists(m("certifi").where())

    @check("data folder")
    def _():
        return m("config").ROOT

    if "--models" in sys.argv:  # with the real models (when installed): the native inference engines run inside the bundle too
        cfg, models, np = m("config").load_cfg(), m("models"), m("numpy")

        @check("Whisper (int8 copy): transcribes 1 s of silence")
        def _():
            if not models.installed(cfg, "whisper", cfg["whisper"]):
                return "skipped (not installed)"
            w = m("faster_whisper").WhisperModel(models.whisper_source(cfg, cfg["whisper"]), device="cpu", compute_type="int8", local_files_only=True)
            list(w.transcribe(np.zeros(16000, np.float32), language="fr", temperature=0.0)[0])

        @check("Supertonic voice: synthesizes a short sentence")
        def _():
            if not models.installed(cfg, "voice"):
                return "skipped (not installed)"
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
