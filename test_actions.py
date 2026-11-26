"""Auto-vérif des commandes (rien n'est vraiment lancé). Lancer: .venv\\Scripts\\python test_actions.py"""
import actions
import config

launched, keys, urls = [], [], []
actions.subprocess.Popen = lambda cmd: launched.append(cmd[-1])
actions._key = lambda vk, times=1: keys.append(vk)
actions.webbrowser.open = urls.append
FR, EN = config.LANGS["Français"], config.LANGS["English"]
actions._apps = {"discord": ("Discord", "ID-DISCORD"), "discord canary": ("Discord Canary", "ID-CANARY"),
                 "spotify": ("Spotify", "ID-SPOTIFY"), "google chrome": ("Google Chrome", "ID-CHROME"),
                 "notepad": ("Notepad", "ID-NOTEPAD"), "mail": ("Mail", "ID-MAIL")}


def run(text, L=FR):
    launched.clear(), keys.clear(), urls.clear()
    return actions.act(text, L)


def opens(text, appid, L=FR):
    ok, say = run(text, L)
    assert ok and launched == ["shell:AppsFolder\\" + appid], (text, launched, say)
    return say


# ouvrir: pas besoin de la phrase exacte
for t in ("Ouvre Discord.", "Ruby, ouvre Discord", "Ouvre-moi Discord", "Peux-tu ouvrir Discord ?", "Ouvre l'application Discord",
          "J'aimerais lancer Discord s'il te plaît", "Est-ce que tu peux m'ouvrir Discord", "Discord", "Discord stp"):
    assert opens(t, "ID-DISCORD") == "J'ouvre Discord.", t
opens("Lance le Spotify", "ID-SPOTIFY")
opens("Open Chrome", "ID-CHROME", EN)
opens("Ouvre Google Chrome", "ID-CHROME")  # « google » dans un nom d'app ne lance pas une recherche
opens("Ouvre notre pad", "ID-NOTEPAD")  # mal entendu par la reco vocale
assert opens("Open Spotify", "ID-SPOTIFY", EN) == "Opening Spotify."
# app inconnue: pas compris + on dit pourquoi
ok, say = run("Ouvre Photoshop")
assert not ok and "Photoshop" in say and not launched, (ok, say)
# navigateur
ok, say = run("Ouvre le navigateur")
assert ok and urls == ["https://www.google.com"] and say == "J'ouvre le navigateur."
for t in ("Vas sur internet", "Va sur Internet.", "Vas-y, va sur internet", "Ouvre internet", "Va sur Google", "Internet", "Lance le navigateur"):
    ok, say = run(t)
    assert ok and urls == ["https://www.google.com"] and say == "J'ouvre le navigateur.", (t, urls, say)
ok, say = actions.act("Go on the internet", EN)
assert ok and say == "Opening the browser."
# chercher
ok, say = run("Cherche des recettes de crêpes.")
assert ok and urls == ["https://www.google.com/search?q=recettes+de+cr%C3%AApes"] and say == "Je cherche recettes de crêpes sur Google.", (urls, say)
run("Peux-tu chercher sur internet la météo à Paris ?")
assert urls == ["https://www.google.com/search?q=m%C3%A9t%C3%A9o+%C3%A0+Paris"], urls
for t, q in (("Vas sur internet et recherche des recettes de crêpes", "recettes+de+cr%C3%AApes"),
             ("Va sur internet et rechercher la météo", "m%C3%A9t%C3%A9o"),
             ("Va sur Google et cherche des chats", "chats"),
             ("Fais une recherche sur la guerre de 14", "guerre+de+14"),
             ("Cherche des chats sur internet", "chats"),
             ("Recherche pour moi des vélos", "v%C3%A9los")):
    ok, say = run(t)
    assert ok and urls == ["https://www.google.com/search?q=" + q], (t, urls)
run("Search how to start a business", EN)
assert urls and not launched, "« start » au milieu d'une phrase ne doit pas ouvrir d'app"
assert run("Cherche")[0] is False  # rien à chercher
# les articles du début de la requête sont retirés, « sur internet » aussi
ok, say = run("Salut Ruby, recherche une recette de pâte forestière sur internet")
assert urls == ["https://www.google.com/search?q=recette+de+p%C3%A2te+foresti%C3%A8re"] and say == "Je cherche recette de pâte forestière sur Google.", (urls, say)
# calcul (chiffres ou mots, FR + EN)
for t, res in (("Combien font 12 fois 7 ?", "84"), ("Combien font douze fois sept", "84"), ("Calcule 15 plus 20", "35"), ("100 divisé par 8", "12,5"),
               ("Quinze pour cent de deux cents", "30"), ("2 puissance 10", "1024"), ("Calcule 10 moins 25", "-15"), ("12 x 3", "36"),
               ("Vingt et un plus trois virgule cinq", "24,5")):
    assert run(t) == (True, f"Ça fait {res}."), (t, run(t))
assert actions.act("What is twelve times seven", EN) == (True, "That's 84."), actions.act("What is twelve times seven", EN)
assert actions.act("What is 7 divided by 2", EN) == (True, "That's 3.5.")
assert run("10 divisé par 0") == (False, "Je ne peux pas calculer ça.")
assert run("Calcule 9 puissance 99999") == (False, "Je ne peux pas calculer ça.")  # exposant refusé
assert run("Il est 12-05") == (False, None)  # pas de mot de calcul: pas un calcul
assert not keys and not urls and not launched
# volume / musique / heure
for t, vk in (("Mets pause", 0xB3), ("Monte le volume", 0xAF), ("Augmente le son", 0xAF), ("Plus fort", 0xAF), ("Baisse le volume", 0xAE),
              ("Mets moins fort", 0xAE), ("Coupe le son", 0xAD), ("Piste suivante", 0xB0), ("Le précédent", 0xB1), ("Volume up", 0xAF)):
    ok, say = run(t)
    assert ok and keys == [vk] and say, (t, keys)
assert run("Quelle heure est-il ?")[1].startswith("Il est ")
# pas compris: pas d'action, pas de phrase
for t in ("blablabla", "", "en mail. Road. youcarry.no. at. Road. on.", "Est-ce que le chat dort sur le canapé"):
    assert run(t) == (False, None), t
    assert not (launched or keys or urls), t

print("OK")
