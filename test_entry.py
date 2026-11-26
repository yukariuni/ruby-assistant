"""Auto-vérif du point d'entrée (ruby.py): l'autotest passe depuis les sources, le dossier de données est relogeable, le lanceur de l'exe.

Le même autotest sert à vérifier l'exe compilé:  dist\\Ruby\\Ruby.exe --selftest.  Lancer: .venv\\Scripts\\python test_entry.py
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).parent
tmp = Path(tempfile.mkdtemp(prefix="ruby_entry_"))

# python ruby.py --selftest: tout s'importe, sons / logo / VAD / scikit-learn / certificats sont là; il écrit dans RUBY_HOME, pas dans le projet
before = {p.name for p in ROOT.iterdir()}
r = subprocess.run([sys.executable, str(ROOT / "ruby.py"), "--selftest"], env=dict(os.environ, RUBY_HOME=str(tmp)), capture_output=True)
report = (tmp / "selftest.txt").read_text("utf-8")
assert r.returncode == 0 and "ÉCHEC" not in report and report.count("OK") >= 30, (r.returncode, report)
assert (tmp / "voice").is_dir(), "le dossier de données est créé là où RUBY_HOME le demande"
assert {p.name for p in ROOT.iterdir()} - before <= {"__pycache__"}, "rien n'est écrit dans le dossier du projet"

# un module manquant fait échouer l'autotest (code 1 + ÉCHEC dans le rapport), au lieu d'un exe qui plante plus tard chez quelqu'un d'autre
broken = tmp / "cassé"
(broken / "joblib").mkdir(parents=True)
(broken / "joblib" / "__init__.py").write_text("raise ImportError('manque')")
r = subprocess.run([sys.executable, str(ROOT / "ruby.py"), "--selftest"], env=dict(os.environ, RUBY_HOME=str(tmp), PYTHONPATH=str(broken)), capture_output=True)
assert r.returncode == 1 and "ÉCHEC  import joblib" in (tmp / "selftest.txt").read_text("utf-8")

# lanceur: depuis les sources « pythonw script.py »; dans l'exe, l'exe lui-même (Ruby.exe, et --settings pour les réglages)
import config
launched = []
config.subprocess.Popen = lambda cmd, **k: launched.append(cmd)
config.launch("engine.py")
config.launch("settings.py")
assert launched[0][1].endswith("engine.py") and launched[1][1].endswith("settings.py") and launched[0][0] == launched[1][0], launched
launched.clear()
config.FROZEN = True
config.launch("engine.py")
config.launch("settings.py")
assert launched == [[sys.executable], [sys.executable, "--settings"]], launched

shutil.rmtree(tmp, ignore_errors=True)
print("OK")
