"""Auto-vérif du cerveau Groq avec de fausses réponses de l'API (aucun appel réseau, aucune clé).

Lancer: .venv\\Scripts\\python test_brain.py
"""
import json

import requests

import actions
import brain
import config

launched, keys, urls, sent = [], [], [], []
actions._apps = {"discord": ("Discord", "ID-DISCORD"), "spotify": ("Spotify", "ID-SPOTIFY")}
actions.subprocess.Popen = lambda cmd: launched.append(cmd[-1])
actions._key = lambda vk, times=1: keys.append(vk)
actions.webbrowser.open = urls.append
brain.time.sleep = lambda s: None
FR = config.LANGS["Français"]
CFG = dict(config.DEFAULT, groq_key="gsk_test")


class Resp:
    def __init__(self, msg, status=200):
        self.status_code, self._msg, self.ok, self.text = status, msg, status == 200, "boom"

    def json(self):
        return {"choices": [{"message": self._msg}]}


def call(tool, **args):
    return {"function": {"name": tool, "arguments": json.dumps(args)}}


def ask(msg, status=200, cfg=CFG, text="peu importe"):
    launched.clear(), keys.clear(), urls.clear(), sent.clear()
    requests.post = lambda url, **kw: sent.append(kw) or Resp(msg, status)
    return brain.ask(text, FR, cfg)


assert ask({"tool_calls": [call("open_app", name="Discord")]}) == (True, "J'ouvre Discord.") and launched == ["shell:AppsFolder\\ID-DISCORD"]
body = sent[0]["json"]
assert body["model"] == "openai/gpt-oss-20b" and body["reasoning_effort"] == "low" and sent[0]["headers"]["Authorization"] == "Bearer gsk_test"
assert {t["function"]["name"] for t in body["tools"]} == {"open_app", "open_browser", "search_web", "media", "calculate", "unclear"}
assert all("unclear" in v for v in brain.SYSTEM.values()), "le prompt doit dire au modèle d'appeler `unclear` plutôt que de répondre « je n'ai pas compris »"
# plusieurs actions dans une phrase: toutes exécutées, toutes décrites
assert ask({"tool_calls": [call("open_app", name="Spotify"), call("media", action="play_pause")]}) == (True, "J'ouvre Spotify. Lecture ou pause.")
assert launched == ["shell:AppsFolder\\ID-SPOTIFY"] and keys == [0xB3]
assert ask({"tool_calls": [call("search_web", query="recette de pâte forestière")]}) == (True, "Je cherche recette de pâte forestière sur Google.")
assert urls == ["https://www.google.com/search?q=recette+de+p%C3%A2te+foresti%C3%A8re"]
assert ask({"tool_calls": [call("calculate", expression="12*7")]}) == (True, "Ça fait 84.")
assert ask({"tool_calls": [call("calculate", expression="-3 + 5")]}) == (True, "Ça fait 2.")
assert ask({"tool_calls": [call("calculate", expression="__import__('os').system('echo hi')")]}) == (False, "Je ne peux pas calculer ça.")
assert ask({"tool_calls": [call("open_browser")]}) == (True, "J'ouvre le navigateur.") and urls == ["https://www.google.com"]
assert ask({"tool_calls": [call("open_app", name="Photoshop")]}) == (False, "Je ne trouve pas Photoshop.")
assert ask({"tool_calls": [call("media", action="explose")]}) == (False, None) and not keys  # action inconnue
assert ask({"tool_calls": [call("format_disk")]}) == (False, None)  # outil inconnu
# phrase inintelligible: l'outil `unclear` = aucune action et AUCUNE phrase (le moteur joue seulement le son d'échec)
assert ask({"tool_calls": [call("unclear")]}) == (False, None) and not launched and not keys and not urls
# le modèle répond quand même « je n'ai pas compris » en texte (c'est arrivé: « Je ne comprends pas la demande. »): pareil, rien n'est dit
for said in ("Je ne comprends pas la demande.", "Je n'ai pas compris.", "Je n’ai pas bien compris votre demande.", "Désolé, je ne comprends pas.",
             "Pouvez-vous répéter ?", "I didn't understand that.", "Sorry, I don’t understand.", "Could you repeat that?", "I'm not sure what you mean."):
    assert ask({"content": said}) == (False, None), said
# réponse directe (question)
assert ask({"content": " Paris. "}) == (True, "Paris.")
for said in ("D'accord.", "De rien.", "Il est quatorze heures trente."):
    assert ask({"content": said}) == (True, said), said
long = "Le ciel est bleu à cause de la diffusion de Rayleigh, et si tu ne comprends pas ce terme, je peux te l'expliquer plus simplement si tu veux."
assert ask({"content": long}) == (True, long), "une longue réponse qui mentionne « ne comprend pas » reste dite"
assert ask({"content": ""}) is None  # rien d'utile: les règles locales prennent le relais
# indisponible -> None (l'appelant retombe sur actions.act)
assert ask({}, status=429) is None
assert ask({}, cfg=dict(CFG, groq_key="")) is None and not sent
requests.post = lambda *a, **k: (_ for _ in ()).throw(requests.ConnectionError("hors-ligne"))
assert brain.ask("x", FR, CFG) is None
print("OK")
