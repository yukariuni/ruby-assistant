# -*- mode: python ; coding: utf-8 -*-
# Recette PyInstaller de Ruby.exe: un DOSSIER (Ruby.exe + _internal), pas un fichier unique. Un exe unique de ≈400 Mo se décompresserait dans
# %TEMP% à chaque lancement (10 s et plus) alors que Ruby doit démarrer vite et rester léger.
# Compiler:  .venv\Scripts\pyinstaller ruby.spec --noconfirm      puis vérifier:  dist\Ruby\Ruby.exe --selftest  (écrit selftest.txt)
from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [("assets", "assets"), ("sounds", "sounds")], [], []
for pkg in ("faster_whisper", "ctranslate2", "onnxruntime", "av", "sounddevice", "_sounddevice_data", "supertonic"):
    d, b, h = collect_all(pkg)  # données (silero_vad.onnx…), DLL natives et sous-modules chargés dynamiquement
    datas, binaries, hiddenimports = datas + d, binaries + b, hiddenimports + h

a = Analysis(["ruby.py"], pathex=["."], binaries=binaries, datas=datas, hiddenimports=hiddenimports,
             excludes=["tkinter", "matplotlib", "IPython", "pytest", "PIL", "openwakeword"])  # openwakeword: seulement pour tester wake.py
exe = EXE(PYZ(a.pure), a.scripts, [], exclude_binaries=True, name="Ruby", console=False, icon="assets/logo.ico", upx=False)
coll = COLLECT(exe, a.binaries, a.datas, name="Ruby", upx=False)
