"""Cerveau Groq: phrase parlée -> appels d'outils (API compatible OpenAI, offre gratuite).

ask() retourne (ok, phrase à dire), ou None si Groq est indisponible (pas de clé, réseau, quota):
l'appelant retombe alors sur les règles locales d'actions.act().
"""
import datetime
import json
import logging
import os
import time

import actions

LOG = logging.getLogger("ruby")
URL = "https://api.groq.com/openai/v1/chat/completions"


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
                                             "parameters": {"type": "object", "properties": props, "required": required}}}


TOOLS = [
    _tool("open_app", "Open an installed Windows application by name (e.g. Discord, Spotify, Chrome).", {"name": {"type": "string"}}, ["name"]),
    _tool("open_browser", "Open the default web browser.", {}, []),
    _tool("search_web", "Search Google in the browser. Query: only the topic, no filler words.", {"query": {"type": "string"}}, ["query"]),
    _tool("media", "Control the volume and music playback.", {"action": {"type": "string", "enum": list(actions.MEDIA_TOOL)}}, ["action"]),
    _tool("calculate", "Evaluate an arithmetic expression with + - * / **, e.g. 12*7. Use it for every calculation.", {"expression": {"type": "string"}}, ["expression"]),
]
SYSTEM = {
    "fr": "Tu es Ruby, un assistant vocal sur Windows. La phrase vient d'une reconnaissance vocale: elle peut contenir des erreurs "
          "(noms d'applications mal écrits). Utilise les outils pour agir sur l'ordinateur, plusieurs si la phrase contient plusieurs actions. "
          "Pour une simple question, réponds directement en une phrase courte, en français, sans markdown ni emoji (ce sera lu à voix haute). "
          "Date et heure: {now}.",
    "en": "You are Ruby, a voice assistant on Windows. The sentence comes from speech recognition and may contain errors (misspelled app names). "
          "Use the tools to act on the computer, several if the sentence has several actions. For a simple question, answer directly in one short "
          "sentence, in English, with no markdown or emoji (it will be read aloud). Date and time: {now}.",
}


def api_key(cfg):
    return cfg["groq_key"] or os.environ.get("GROQ_API_KEY", "")


def ask(text, L, cfg):
    key = api_key(cfg)
    if not key:
        return None
    import requests  # au 1er appel seulement: sans clé Groq, il n'est jamais chargé (≈9 Mo de mémoire)
    body = dict(model=cfg["groq_model"], temperature=0, tools=TOOLS, tool_choice="auto", messages=[
        {"role": "system", "content": SYSTEM[L["whisper"]].format(now=datetime.datetime.now().strftime("%A %d %B %Y, %H:%M"))},
        {"role": "user", "content": text}])
    if "gpt-oss" in cfg["groq_model"]:
        body["reasoning_effort"] = "low"  # réponse plus rapide; refusé par les modèles sans raisonnement
    try:
        r = requests.post(URL, headers={"Authorization": f"Bearer {key}"}, json=body, timeout=8)
        if not r.ok:
            LOG.warning("Groq HTTP %s: %s", r.status_code, r.text[:200])
            return None
        msg = r.json()["choices"][0]["message"]
    except (requests.RequestException, ValueError, KeyError, IndexError) as e:
        LOG.warning("Groq indisponible: %s", e)
        return None
    calls, content = msg.get("tool_calls") or [], (msg.get("content") or "").strip()
    LOG.info("Groq: outils=%s, texte=%r", [(c["function"]["name"], c["function"]["arguments"]) for c in calls], content)
    if not calls:
        return (True, content) if content else None
    results = []
    for i, c in enumerate(calls):
        try:
            args = json.loads(c["function"]["arguments"] or "{}")
        except ValueError:
            args = {}
        results.append(actions.run_tool(c["function"]["name"], args, L))
        if c["function"]["name"] == "open_app" and i < len(calls) - 1:
            time.sleep(3)  # laisse l'app démarrer avant l'action suivante (ex: lecture)
    return all(ok for ok, _ in results), " ".join(s for _, s in results if s) or None
