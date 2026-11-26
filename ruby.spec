# -*- mode: python ; coding: utf-8 -*-
# PyInstaller recipe for Ruby.exe: a FOLDER (Ruby.exe + _internal), not a single file. A single ~400 MB exe would unpack itself into
# %TEMP% on every launch (10 s or more), while Ruby has to start fast and stay light.
# Build:  .venv\Scripts\pyinstaller ruby.spec --noconfirm      then check:  dist\Ruby\Ruby.exe --selftest  (writes selftest.txt)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [("assets", "assets"), ("sounds", "sounds")], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "sounddevice", "_sounddevice_data", "supertonic"):
    d, b, h = collect_all(pkg)  # data files (silero_vad.onnx...), native DLLs and dynamically loaded submodules
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

a = Analysis(["ruby.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "PIL", "openwakeword"])  # openwakeword: only used to test wake.py
exe = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name="Ruby", console=False, icon="assets/logo.ico", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Ruby", upx=False)
