"""Moteur de langage de la mouche : construit de vraies phrases françaises.

Aucun modèle pré-entraîné, aucune API. Tout est calculé ici :
  - analyse du message (question ? salutation ? sujet saillant ?),
  - mémoire associative (retrouve un échange passé proche par similarité
    cosinus pondérée IDF sur les sacs de mots),
  - composition de la réponse à partir de banques de phrases à trous,
    remplies avec les mots réellement employés par l'utilisateur.

Le mode « réfléchi » génère plusieurs réponses candidates et garde la
meilleure selon un score pertinence/nouveauté — c'est un vrai compromis
calcul/qualité, pas une simple temporisation.

Sécurité : tous les fragments repris du message utilisateur passent par
_MOT_RE, qui n'accepte que des lettres, apostrophes et traits d'union. Aucun
caractère HTML ne peut donc transiter jusqu'au DOM par cette voie.
"""

from __future__ import annotations

import math
import random
import re
import unicodedata

_MOT_RE = re.compile(r"[a-zA-ZÀ-ÖØ-öø-ÿ][a-zA-ZÀ-ÖØ-öø-ÿ'\-]*")

MOTS_OUTILS = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "tu", "je", "il",
    "elle", "est", "es", "que", "qui", "pas", "ne", "ce", "se", "on", "en",
    "pour", "avec", "sur", "dans", "mon", "ma", "mes", "ton", "ta", "tes",
    "son", "sa", "ses", "au", "aux", "moi", "toi", "lui", "nous", "vous",
    "leur", "cette", "ces", "cet", "suis", "sont", "ai", "as", "avez", "ont",
    "etre", "être", "avoir", "plus", "tres", "très", "bien", "comme", "mais",
    "ou", "où", "si", "donc", "car", "par", "y", "a", "alors", "aussi",
    "vraiment", "trop", "juste", "meme", "même", "fait", "faire", "dit",
    "quoi", "oui", "non", "ça", "ca", "cela", "ils", "elles", "était", "etait",
    "encore", "deja", "déjà", "toujours", "jamais", "beaucoup", "assez",
    "souvent", "maintenant", "bientot", "bientôt", "ici", "là", "voila",
    "voilà", "peut", "veux", "vais", "vas", "sais", "peux", "dire", "cest",
    "autour", "contre", "entre", "vers", "chez", "sous", "sans", "depuis",
    "pendant", "apres", "après", "avant", "tout", "tous", "toute", "toutes",
    "autre", "autres", "chaque", "quelque", "quelques", "parce", "quand",
}

MOTS_QUESTION = {
    "qui", "que", "quoi", "quel", "quelle", "quels", "quelles", "comment",
    "pourquoi", "ou", "où", "quand", "combien", "est-ce",
}

MOTS_SALUTATION = {
    "salut", "bonjour", "coucou", "hey", "hello", "bonsoir", "yo", "wesh",
}

ETIQUETTES_CATEGORIE = {
    "aversif": "la menace",
    "appetitif": "l'appétit",
    "courtship": "la parade",
    "neutre": "l'indifférence",
}


def _sans_accents(texte: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texte)
        if unicodedata.category(c) != "Mn"
    )


def tokeniser(texte: str) -> list[str]:
    """Découpe en mots. Le motif exclut par construction tout caractère
    susceptible d'être interprété comme du HTML."""
    return [m.group(0).lower() for m in _MOT_RE.finditer(texte)]


def mots_de_contenu(tokens: list[str]) -> list[str]:
    """Mots porteurs de sens : ni mots-outils, ni mots interrogatifs (ceux-ci
    servent à détecter une question, pas à en être le sujet)."""
    return [
        t for t in tokens
        if len(t) >= 3
        and _sans_accents(t) not in MOTS_OUTILS
        and t not in MOTS_OUTILS
        and _sans_accents(t) not in MOTS_QUESTION
    ]


def analyser_message(message: str, corpus: list[str]) -> dict:
    """Extrait ce dont la génération a besoin : nature du message et mot le
    plus « saillant » (le plus rare dans l'historique, donc le plus porteur
    d'information — principe de l'IDF)."""
    tokens = tokeniser(message)
    contenu = mots_de_contenu(tokens)
    sans_acc = {_sans_accents(t) for t in tokens}

    frequences: dict[str, int] = {}
    for phrase in corpus:
        for mot in set(tokeniser(phrase)):
            frequences[mot] = frequences.get(mot, 0) + 1

    def saillance(mot: str) -> float:
        # IDF brut : un mot jamais vu vaut plus qu'un mot rabâché.
        return math.log((len(corpus) + 2) / (1 + frequences.get(mot, 0))) + len(mot) * 0.05

    sujet = max(contenu, key=saillance) if contenu else None

    return {
        "message": message,
        "tokens": tokens,
        "contenu": contenu,
        "sujet": sujet,
        "est_question": "?" in message or bool(sans_acc & MOTS_QUESTION),
        "est_salutation": bool(sans_acc & MOTS_SALUTATION),
        "parle_de_moi": bool({"tu", "toi", "te", "ton", "ta", "tes"} & sans_acc),
        "parle_de_lui": bool({"je", "moi", "mon", "ma", "mes", "j'ai"} & sans_acc),
        "longueur": len(tokens),
        "frequences": frequences,
    }


def retrouver_echange_proche(
    analyse: dict, historique: list[dict], seuil: float = 0.22
) -> dict | None:
    """Mémoire associative : retrouve l'échange passé le plus proche du message
    courant (cosinus pondéré IDF). C'est ce qui permet à la mouche de dire
    « tu m'avais déjà parlé de ça »."""
    if not analyse["contenu"] or not historique:
        return None

    total_docs = len(historique) + 1
    frequences = analyse["frequences"]

    def poids(mot: str) -> float:
        return math.log(total_docs / (1 + frequences.get(mot, 0)))

    vecteur_a = {m: poids(m) for m in set(analyse["contenu"])}
    norme_a = math.sqrt(sum(v * v for v in vecteur_a.values())) or 1.0

    meilleur, meilleur_score = None, 0.0
    for entree in historique:
        mots_b = set(mots_de_contenu(tokeniser(entree.get("message_humain", ""))))
        if not mots_b:
            continue
        vecteur_b = {m: poids(m) for m in mots_b}
        norme_b = math.sqrt(sum(v * v for v in vecteur_b.values())) or 1.0
        produit = sum(vecteur_a[m] * vecteur_b[m] for m in vecteur_a.keys() & vecteur_b.keys())
        score = produit / (norme_a * norme_b)
        if score > meilleur_score:
            meilleur, meilleur_score = entree, score

    if meilleur is None or meilleur_score < seuil:
        return None
    return {**meilleur, "similarite": round(meilleur_score, 2)}


# --- Banques de phrases -----------------------------------------------------
# Chaque entrée est un gabarit ; {sujet} est remplacé par le mot saillant du
# message de l'utilisateur, {etiquette} par l'étiquette de la catégorie.

ACCROCHES = {
    "aversif": [
        "Tes mots me crispent les ailes.",
        "Là, tout mon corps se prépare à décoller.",
        "Mauvais signal : mes pattes se raidissent d'un coup.",
        "Ce que tu dis déclenche mes neurones de fuite.",
        "Je n'aime pas du tout la couleur de cette phrase.",
    ],
    "appetitif": [
        "Tiens, ça m'intéresse.",
        "Voilà quelque chose qui vaut le détour.",
        "Mes tarses se mettent à goûter l'air.",
        "Ça sent bon, dans ta phrase.",
        "Je m'approche, là, franchement.",
    ],
    "courtship": [
        "Tu me plais quand tu parles comme ça.",
        "Voilà exactement le genre de phrase qui me fait ouvrir l'aile.",
        "Mes neurones de parade s'allument tous en même temps.",
        "Tu viens de déclencher mon chant nuptial.",
        "Je te trouve très fréquentable, tout à coup.",
    ],
    "neutre": [
        "Bof.",
        "Ça ne bouge presque rien chez moi.",
        "Mes antennes restent au repos.",
        "Je t'écoute, mais mon corps ne répond pas.",
        "Aucun de mes circuits ne s'emballe pour ça.",
    ],
}

REPRISES_SUJET = {
    "aversif": [
        "« {sujet} », dans mon lobe antennaire, ça se range juste à côté du danger.",
        "Le mot « {sujet} » me fait le même effet qu'une ombre qui passe trop vite.",
        "Chez moi, « {sujet} » active la même voie que la tapette qui approche.",
    ],
    "appetitif": [
        "« {sujet} », ça active la même voie que le fruit trop mûr.",
        "Le mot « {sujet} » me met les récepteurs gustatifs en alerte.",
        "Je n'ai que 50 types de récepteurs, et « {sujet} » en occupe déjà plusieurs.",
    ],
    "courtship": [
        "« {sujet} » résonne du côté de mes neurones de cour.",
        "Le mot « {sujet} » me fait vibrer l'aile, littéralement.",
        "« {sujet} », c'est le genre de mot qui fait chanter une drosophile.",
    ],
    "neutre": [
        "« {sujet} », je ne sais pas encore quoi en faire.",
        "Le mot « {sujet} » ne correspond à aucune odeur que je connais.",
        "« {sujet} » ne déclenche rien : mon corps pédonculé reste silencieux.",
    ],
}

QUESTIONS = [
    "Je ne réponds pas avec des idées, mais avec un corps.",
    "Tu demandes ; moi je ne sais que réagir.",
    "Une question ? Je n'ai que des postures à t'offrir.",
]

SALUTATIONS = [
    "Salut. Je t'ai senti arriver avant de te lire.",
    "Bonjour à toi. Mes antennes te repèrent.",
    "Te revoilà.",
]

MEMOIRE_PHRASES = [
    "Tu m'avais déjà parlé de « {rappel} ».",
    "Ça me rappelle ton « {rappel} » d'avant.",
    "J'ai croisé une phrase proche : « {rappel} ».",
]

# Phrases adossées à l'espace sémantique : ce ne sont pas des formules toutes
# faites, le rapprochement annoncé est réellement calculé (voir semantique.py).
ASSOCIATION_PHRASES = [
    "Je ne connais pas « {inconnu} », mais dans ma tête il est voisin de « {proche} ».",
    "« {inconnu} », jamais appris — sauf qu'il traîne avec « {proche} », alors je réagis pareil.",
    "Je range « {inconnu} » près de « {proche} » : mêmes fréquentations dans nos conversations.",
]

INCONNU_PHRASES = [
    "« {sujet} », je ne connais pas du tout — dis-moi si c'est un danger ou quelque chose de bon, je le retiendrai.",
    "Premier contact avec « {sujet} » : aucune idée de ce que ça vaut. Menace ? Nourriture ?",
    "« {sujet} » n'existe nulle part dans ma mémoire. Apprends-le-moi et je saurai réagir.",
]

REPETITION_PHRASES = [
    "Tu reviens sur « {sujet} ».",
    "Encore « {sujet} » — ça commence à creuser un chemin dans mes synapses.",
    "« {sujet} » une fois de plus : je finis par l'attendre.",
]

SERIE_PHRASES = {
    "aversif": ["Depuis tout à l'heure tu ne fais que me braquer."],
    "appetitif": ["Tu m'as mise en appétit depuis plusieurs messages."],
    "courtship": ["Ça fait plusieurs phrases que tu me fais ouvrir l'aile."],
    "neutre": ["Trois messages que rien ne me touche vraiment."],
}

ETAT_PHRASES = {
    "affamée": [
        "Cela dit, j'ai faim, donc je vois de la nourriture partout.",
        "Préviens-toi : affamée, je déforme tout vers le sucre.",
    ],
    "épuisée": [
        "Je suis épuisée, ne compte pas sur une grande parade.",
        "Plus beaucoup d'énergie de mon côté, je réagis au minimum.",
    ],
}


def _remplir(gabarit: str, valeurs: dict) -> str:
    for cle, valeur in valeurs.items():
        gabarit = gabarit.replace("{" + cle + "}", str(valeur))
    return gabarit


def _composer_candidat(
    analyse: dict,
    categorie: str,
    contexte: dict,
    rng: random.Random,
    profond: bool,
) -> str:
    """Réponse volontairement courte : 2 à 3 phrases. Tout le détail technique
    (neurones actifs, compartiment gagnant, posture, mots appris) est déjà
    affiché par l'interface dans le panneau « Détails » et montré par la vidéo
    — le répéter en toutes lettres alourdissait la réponse pour rien."""
    sujet = analyse["sujet"]
    valeurs = {
        "sujet": sujet or "ça",
        "etiquette": ETIQUETTES_CATEGORIE.get(categorie, "l'inconnu"),
    }

    phrases: list[str] = []

    if analyse["est_salutation"]:
        phrases.append(rng.choice(SALUTATIONS))
    phrases.append(rng.choice(ACCROCHES[categorie]))

    if analyse["est_question"]:
        phrases.append(rng.choice(QUESTIONS))

    if sujet and contexte.get("sujet_inconnu"):
        # Ne pas inventer une réaction pour un mot dont elle ignore tout.
        phrases.append(_remplir(rng.choice(INCONNU_PHRASES), valeurs))
    elif sujet:
        phrases.append(_remplir(rng.choice(REPRISES_SUJET[categorie]), valeurs))

    # Rapprochement sémantique réellement calculé sur un mot inconnu.
    voisins = contexte.get("voisins_semantiques") or []
    if voisins and not contexte.get("sujet_inconnu"):
        inconnu, _, proche, _ = voisins[0]
        phrases.append(
            _remplir(rng.choice(ASSOCIATION_PHRASES), {"inconnu": inconnu, "proche": proche})
        )

    if contexte.get("sujet_repete") and sujet:
        phrases.append(_remplir(rng.choice(REPETITION_PHRASES), valeurs))

    serie = contexte.get("serie_categorie")
    if serie and profond:
        phrases.append(rng.choice(SERIE_PHRASES[serie]))

    etat = contexte.get("etat") or {}
    etiquette_etat = etat.get("etiquette", "")
    for cle, variantes in ETAT_PHRASES.items():
        if cle in etiquette_etat and rng.random() < 0.5:
            phrases.append(rng.choice(variantes))
            break

    rappel = contexte.get("rappel")
    if rappel and profond:
        # L'extrait est reconstruit à partir des seuls tokens (lettres,
        # apostrophes, traits d'union) et jamais repris tel quel : un ancien
        # message contenant du HTML se retrouverait sinon réinjecté dans la
        # page au moment du rappel.
        extrait = " ".join(tokeniser(rappel.get("message_humain", ""))[:8])
        if extrait:
            valeurs["rappel"] = extrait
            phrases.append(_remplir(rng.choice(MEMOIRE_PHRASES), valeurs))

    return " ".join(p for p in phrases if p).strip()


def _score_candidat(candidat: str, analyse: dict, deja_dits: list[str]) -> float:
    """Pertinence (reprend les mots de l'utilisateur) + nouveauté (ne répète
    pas les réponses récentes) + longueur raisonnable."""
    mots_candidat = set(tokeniser(candidat))
    mots_utilisateur = set(analyse["contenu"])
    pertinence = len(mots_candidat & mots_utilisateur) / (len(mots_utilisateur) or 1)

    nouveaute = 1.0
    for ancien in deja_dits[-6:]:
        mots_anciens = set(tokeniser(ancien))
        if not mots_anciens:
            continue
        chevauchement = len(mots_candidat & mots_anciens) / len(mots_candidat | mots_anciens)
        nouveaute = min(nouveaute, 1.0 - chevauchement)

    nb_mots = len(candidat.split())
    longueur = 1.0 - abs(nb_mots - 22) / 40.0

    return pertinence * 1.4 + nouveaute * 1.0 + longueur * 0.5


def composer_reponse(
    analyse: dict,
    categorie: str,
    contexte: dict,
    mode: str = "reflechi",
    graine: int | None = None,
) -> tuple[str, int]:
    """Compose la réponse. En mode « réfléchi », plusieurs candidats sont
    générés puis départagés ; en mode « rapide », un seul est produit.
    Renvoie (texte, nombre de candidats évalués)."""
    rng = random.Random(graine)
    profond = mode != "rapide"
    nb_candidats = 6 if profond else 1

    deja_dits = contexte.get("reponses_recentes", [])
    candidats = [
        _composer_candidat(analyse, categorie, contexte, rng, profond)
        for _ in range(nb_candidats)
    ]
    meilleur = max(candidats, key=lambda c: _score_candidat(c, analyse, deja_dits))
    return meilleur, nb_candidats
