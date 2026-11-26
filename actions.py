"""Commandes vocales: texte reconnu -> action Windows.

Approche « mots-clés + matching flou » (comme Adapt / Home Assistant): pas de phrase exacte à dire,
on cherche un verbe-clé n'importe où dans la phrase et le nom d'app le plus proche, malgré les
erreurs de la reconnaissance vocale. act() retourne (ok, phrase à dire ou None).
"""
import ast
import ctypes
import datetime
import json
import logging
import operator
import re
import subprocess
import unicodedata
import webbrowser
from urllib.parse import quote_plus

from rapidfuzz import fuzz
from text_to_num import alpha2digit

LOG = logging.getLogger("ruby")
_apps = None

OPEN = r"\b(?:ouvr|lanc|demarr|open|launch|start)\w*"
SEARCH = r"\b(?:cherch|recherch|trouv|google|search|look up|find)\w*"
# mots à ignorer au début de la requête: « cherche-moi sur internet des recettes »
FILLER = r"(?:\W+|moi\b|me\b|pour moi\b|sur (?:internet|google|le web|le net)\b|on (?:the )?(?:internet|web|google)\b|a propos de\b|about\b|sur\b|pour\b|for\b|up\b|s il te plait\b|please\b|stp\b)*"
# « va sur internet », « go to google »: ouvrir le navigateur sans verbe « ouvre »
GO = r"\b(?:va|vas|aller|allez|go|goes)\b\W+(?:\w+\W+){0,2}?"
BROWSER = r"\b(?:navigat\w*|browser|internet|google|web|net|online)\b"


def fold(s):
    """Minuscules sans accents, de même longueur que s (les positions restent valables sur l'original)."""
    return "".join(unicodedata.normalize("NFD", c)[0] for c in s).lower()


def apps():
    """{nom replié: (nom, AppID)} de toutes les apps du menu Démarrer (classiques et Store)."""
    global _apps
    if _apps is None:
        out = subprocess.run(
            ["powershell", "-NoProfile", "-Command",
             "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json"],
            capture_output=True, encoding="utf-8").stdout
        data = json.loads(out)
        _apps = {fold(a["Name"]): (a["Name"], a["AppID"]) for a in (data if isinstance(data, list) else [data])}
    return _apps


def find_app(f):
    """App du menu Démarrer citée dans le texte replié f, ou None. Tolère les mots collés ou mal coupés."""
    glued, best = f.replace(" ", ""), None
    for name, app in apps().items():
        g = name.replace(" ", "")
        if len(g) < 4:  # « Mail », « Edge »… trop courts: faux positifs
            continue
        score = max(fuzz.partial_ratio(name, f) if len(name) <= len(f) else 0,
                    fuzz.partial_ratio(g, glued) if len(g) <= len(glued) else 0,
                    # « chrome » pour « Google Chrome »: le texte est une partie du nom (légèrement pénalisé)
                    0.95 * fuzz.partial_ratio(glued, g) if 5 <= len(glued) <= len(g) else 0)
        if score >= 85 and (best is None or (score, len(name)) > best[0]):
            best = ((score, len(name)), app)
    return best and best[1]


def has(f, *stems):
    return any(re.search(rf"\b{s}", f) for s in stems)


def _key(vk, times=1):
    for _ in range(times):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)


def _launch(name, appid, L):
    subprocess.Popen(["explorer.exe", "shell:AppsFolder\\" + appid])
    return True, L["opening"].format(name)


def _browser(L):
    webbrowser.open("https://www.google.com")
    return True, L["opening"].format(L["browser"])


def _open(text, f, end, L):
    rest = f[end:]
    if re.fullmatch(rf"(?:\W+|(?:le|la|l|un|une|mon|my|the|a)\b|{BROWSER})*", rest):  # « internet », « le navigateur »: pas Internet Explorer
        return _browser(L)
    if app := find_app(rest) or find_app(f):  # sinon une vraie app (« Google Chrome »)
        return _launch(*app, L)
    if re.search(BROWSER, rest):
        return _browser(L)
    name = re.sub(r"^(?:\W+|moi\b|le\b|la\b|les\b|l\b|the\b|application\b|app\b)*", "", rest)  # nom à annoncer
    name = text[len(f) - len(name):].strip(" .?!,")
    return False, L["noapp"].format(name) if name else None


def _search(text, f, end, L):
    q = text[end + re.match(FILLER, f[end:]).end():].strip(" .?!,")
    q = re.sub(r"\s+(?:sur|on)\s+(?:internet|google|le web|le net|the web|the internet)\W*$", "", q, flags=re.I)  # « … sur internet »
    q = re.sub(r"^(?:(?:un|une|des|du|de la|de l|le|la|les|l|a|an|the|some)\b\W*)+", "", q, flags=re.I)  # « une recette » -> « recette »
    return _google(q, L) if q else (False, None)


def _google(q, L):
    webbrowser.open("https://www.google.com/search?q=" + quote_plus(q))
    return True, L["searching"].format(q)


_OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.Pow: operator.pow}
# mots -> opérateurs (sur le texte replié, FR + EN)
MATH_WORDS = [
    (r"(\d+(?:\.\d+)?)\s*(?:%|pour 100|pour cent|percent)\s*(?:de|of)\s*", r"\1/100*"),
    (r"\bmultipli\w* (?:par|by)\b|\bfois\b|\btimes\b|(?<=\d)\s*x\s*(?=\d)", "*"),
    (r"\bdivi\w* (?:par|by)\b|\bover\b|÷", "/"),  # divisé / divided
    (r"\bpuissance\b|\bto the power of\b|\^", "**"),
    (r"\bplus\b", "+"),
    (r"\bmoins\b|\bminus\b", "-"),
]
CALC = r"\b(?:calcul|combien|ca fait|egal|what is|what s|how much|compute|equal|solve)"
EXPR = r"\d+(?:\.\d+)?(?:\s*(?:\*\*|[-+*/])\s*\d+(?:\.\d+)?)+"


def _eval(n):
    """Évalue un AST arithmétique (jamais eval() sur du texte parlé)."""
    if isinstance(n, ast.Constant) and isinstance(n.value, (int, float)):
        return n.value
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, (ast.USub, ast.UAdd)):
        return -_eval(n.operand) if isinstance(n.op, ast.USub) else _eval(n.operand)
    if isinstance(n, ast.BinOp) and type(n.op) in _OPS:
        a, b = _eval(n.left), _eval(n.right)
        if isinstance(n.op, ast.Pow) and abs(b) > 100:
            raise ValueError("exposant trop grand")
        return _OPS[type(n.op)](a, b)
    raise ValueError("expression non permise")


def _calc(text, L):
    """« combien font douze fois sept » -> (True, « Ça fait 84. »). None si ce n'est pas un calcul."""
    g = re.sub(r"(\d),(\d)", r"\1.\2", fold(alpha2digit(text, L["whisper"])))
    n = 0
    for rx, sym in MATH_WORDS:
        g, k = re.subn(rx, sym, g)
        n += k
    m = re.search(EXPR, g)
    if not m or not (n or re.search(CALC, g)):  # « 12-05 » sans mot de calcul: pas un calcul
        return None
    return _calc_expr(m.group(0), L)


def _calc_expr(expr, L):
    try:
        r = _eval(ast.parse(expr.strip(), mode="eval").body)
        out = str(int(r)) if float(r).is_integer() and abs(r) < 1e15 else str(round(r, 6)).replace(".", L["dec"])
    except (ValueError, ZeroDivisionError, OverflowError, SyntaxError):
        return False, L["calc_err"]
    return True, L["calc"].format(out)


def _media(vk, times, msg):
    def run(L):
        _key(vk, times)
        return True, L[msg]
    return run


def _time(L):
    return True, L["time"].format(datetime.datetime.now().strftime(L["clock"]))


VOLUME = (r"volume", r"son\b", r"sound")
# (test sur le texte replié, action). Ordre = priorité. FR + EN dans la même table.
MEDIA = [
    (lambda f: has(f, "mute", "muet", "silence") or (has(f, "coup", "cut") and has(f, r"son\b", "sound")), _media(0xAD, 1, "mute")),
    (lambda f: (has(f, *VOLUME) and has(f, "mont", "augment", r"up\b", "increas", "rais", "plus", "haut", "loud")) or has(f, "plus fort", "louder"), _media(0xAF, 5, "vol_up")),
    (lambda f: (has(f, *VOLUME) and has(f, "baiss", "diminu", r"down\b", "decreas", "lower", "moins", "quiet", "bas")) or has(f, "moins fort", "quieter"), _media(0xAE, 5, "vol_down")),
    (lambda f: has(f, "suivant", "prochain", "next", "skip"), _media(0xB0, 1, "next")),
    (lambda f: has(f, "precedent", "previous"), _media(0xB1, 1, "prev")),
    (lambda f: has(f, "pause", r"play\b", "lecture", "reprend", "resume", "continu"), _media(0xB3, 1, "playpause")),
    (lambda f: has(f, "heure", "what time", "time is it"), _time),
]


MEDIA_TOOL = {"play_pause": (0xB3, 1, "playpause"), "next": (0xB0, 1, "next"), "previous": (0xB1, 1, "prev"),
              "mute": (0xAD, 1, "mute"), "volume_up": (0xAF, 5, "vol_up"), "volume_down": (0xAE, 5, "vol_down")}


def run_tool(name, args, L):
    """Exécute un outil demandé par le LLM (brain.py). Retourne (ok, phrase) comme act()."""
    if name == "unclear":  # phrase inintelligible: aucune action, aucune phrase (le moteur joue le son d'échec)
        return False, None
    try:
        if name == "open_app":
            if app := find_app(fold(args["name"])):
                return _launch(*app, L)
            return (_browser(L) if re.fullmatch(rf"\W*{BROWSER}\W*", fold(args["name"])) else (False, L["noapp"].format(args["name"])))
        if name == "open_browser":
            return _browser(L)
        if name == "search_web":
            return _google(args["query"].strip(), L)
        if name == "media":
            return _media(*MEDIA_TOOL[args["action"]])(L)
        if name == "calculate":
            return _calc_expr(args["expression"], L)
    except (KeyError, TypeError, AttributeError):
        LOG.warning("outil invalide: %s %s", name, args)
    return False, None


def act(text, L):
    """Exécute la commande. Retourne (ok, phrase à dire): (False, None) = pas compris."""
    f = fold(text)
    found = list(re.finditer(SEARCH, f))
    s = next((m for m in found if m.group(0) != "google"), found[0] if found else None)  # « va sur Google et cherche X »: « cherche » gagne
    o = re.search(OPEN, f)
    LOG.debug("texte=%r, verbe chercher=%s, verbe ouvrir=%s", text, s and s.group(0), o and o.group(0))
    if s or o:  # un verbe d'action: celui qui vient en premier gagne (« ouvre Google Chrome » ouvre, « search how to start » cherche)
        res = _open(text, f, o.end(), L) if o and (not s or o.start() < s.start()) else _search(text, f, s.end(), L)
        if res != (False, None):  # sinon (« va sur Google »: « google » sans requête) on essaie la suite
            return res
    if (res := _calc(text, L)) is not None:
        return res
    if re.search(GO + BROWSER, f) or (len(f.split()) <= 4 and re.search(BROWSER, f)):  # « vas sur internet », « internet »
        return _browser(L)
    for test, run in MEDIA:
        if test(f):
            return run(L)
    if len(f.split()) <= 4 and (app := find_app(f)):  # juste « Discord »: seulement pour les phrases courtes
        return _launch(*app, L)
    return False, None
