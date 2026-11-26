# Ruby

Assistant vocal pour Windows, dans l'esprit de Siri: « *Hey Ruby, ouvre Discord* », « *cherche une recette de pâtes forestières* », « *combien font 12 fois 7 ?* ».

Tout tourne sur ton PC (reconnaissance vocale, voix, mot d'activation). Seul le « cerveau » Groq est en ligne, et il est facultatif: sans clé, Ruby utilise des règles locales.

## Comment ça marche

1. **Mot d'activation**: tu dis ton mot (« hi », « hey », « salut »… suivi de « Ruby »). Un petit classifieur appris sur *ta* voix (`Apprendre ma voix`) décide si c'est toi. Un halo s'allume autour de l'écran et un petit son te dit de parler.
2. **Reconnaissance**: Whisper (faster-whisper, modèle `small`, int8) transcrit ta phrase.
3. **Compréhension**: Groq (tool calling, clé gratuite) ou des règles floues locales (ouvrir une appli, chercher, volume, musique, heure, calcul).
4. **Réponse**: Ruby agit puis le dit à voix haute (Supertonic, voix locale; ou Edge en ligne).

## Mémoire: 500 Mo maximum

Au repos le moteur pèse ≈10 Mo. Quand tu parles, Whisper se charge pendant ta phrase puis est libéré, et seulement après la voix: jamais les deux ensemble (à eux deux ils feraient 700 Mo). Les phrases déjà dites sont gardées sur disque (`cache/tts`) et rejouées sans recharger la voix.

Mesuré (jeu de travail privé, comme le Gestionnaire des tâches): pic du moteur 475 à 478 Mo à la 1re commande, 425 à 453 Mo ensuite; fenêtre de réglages ≈10 Mo. Les choix qui tiennent ce plafond:

- Whisper est chargé depuis une copie **int8 pré-convertie** (`models.quantize_ct2`, créée une fois): charger le fichier float16 monte à 681 Mo.
- Whisper décode avec `temperature=0.0`: son « repli » par défaut (5 décodages échantillonnés) monte à 850 Mo.
- `medium` n'est plus proposé (≈800 Mo).

`tools/measure_budget.py` et `tools/e2e_listen.py` rejouent des vrais cycles avec tes modèles et mesurent le pic toutes les 5 ms. Le plafond est `config.MEM_LIMIT`.

## Lancer depuis les sources

Python **3.12** (onnxruntime n'a pas de version pour les Python plus récents).

```bat
py -3.12 -m venv .venv
.venv\Scripts\pip install -r requirements.txt
.venv\Scripts\pythonw ruby.py              :: le moteur (icône dans la barre des tâches)
.venv\Scripts\pythonw ruby.py --settings   :: les réglages (un processus à part)
```

Au premier lancement, ouvre les réglages: *Écoute > Apprendre ma voix* (≈1 minute). Les modèles se téléchargent une seule fois (Whisper ≈480 Mo, voix ≈385 Mo), dans le dossier de ton choix (*Modèles > Gérer*). `ruby.py --debug` affiche les journaux et enregistre chaque commande dans `logs/`.

## Compiler `Ruby.exe`

```bat
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\pyinstaller ruby.spec --noconfirm
dist\Ruby\Ruby.exe --selftest
```

C'est un **dossier** (`dist\Ruby\Ruby.exe` + `_internal`), pas un fichier unique: un exe unique de ≈400 Mo se décompresserait dans `%TEMP%` à chaque lancement. `Ruby.exe` lance le moteur, `Ruby.exe --settings` les réglages. `--selftest` vérifie bibliothèques, sons, logo et certificats, et écrit `selftest.txt`.

Dans l'exe, réglages, voix apprise, journaux et cache vivent dans `%APPDATA%\Ruby` (variable `RUBY_HOME` pour changer de dossier, par exemple en mode portable). Pour reprendre ta config des sources: copie `config.json` et `voice\` dans ce dossier.

## Tests

```bat
for %t in (models wake engine_paths settings sync actions brain audio entry) do .venv\Scripts\python test_%t.py
```

Chaque fichier affiche `OK`. Ils travaillent dans des dossiers temporaires: aucun de tes modèles ni réglages n'est touché. `test_wake.py` compare l'extracteur de `wake.py` au paquet `openwakeword` d'origine (`requirements-dev.txt`).

## Tes données ne partent jamais dans git

`config.json` (clé Groq **en clair**), `voice/` (ta voix apprise), `logs/` (tes commandes enregistrées), `cache/`, `models/` sont dans `.gitignore`.

## Fichiers

| | |
|---|---|
| `ruby.py` | point d'entrée (moteur, `--settings`, `--debug`, `--selftest`) |
| `engine.py` | moteur: écoute, enregistre, transcrit, agit, répond; icône de la barre et halo d'écran |
| `settings.py` | fenêtre de réglages (Qt) |
| `wake.py` | mot d'activation appris sur ta voix |
| `actions.py`, `brain.py` | règles locales / cerveau Groq |
| `tts.py`, `audio.py` | voix (+ cache disque), sons et périphériques |
| `models.py` | où sont les modèles, déplacer / supprimer, copie int8 de Whisper |
| `config.py`, `memory.py`, `overlay.py` | réglages partagés, mesure de mémoire, halo |
| `ruby.spec` | recette de compilation de l'exe |
| `tools/` | mesures réelles de mémoire |

## Crédits

[faster-whisper](https://github.com/SYSTRAN/faster-whisper) / CTranslate2 (reconnaissance), [Supertonic](https://huggingface.co/Supertone/supertonic-3) (voix), [openWakeWord](https://github.com/dscripka/openWakeWord) (extraction des caractéristiques du mot d'activation, Apache-2.0), [Groq](https://groq.com) (cerveau en ligne), sons de [Kenney](https://kenney.nl) (CC0).
