"""Générateur de texte par chaîne de Markov, entraîné sur l'historique réel
des échanges (mémoire persistante). Aucun modèle pré-entraîné : le vocabulaire
et les enchaînements de mots proviennent uniquement de ce que la mouche a
"vécu" dans ses conversations passées — plus il y a d'échanges, plus les
phrases générées sont variées et personnalisées.
"""

from __future__ import annotations

import random
import re

SEUIL_MIN_BIGRAMMES = 12  # en dessous, le corpus est trop pauvre pour générer


def _tokeniser(texte: str) -> list[str]:
    return re.findall(r"[\wàâäéèêëïîôöùûüç'-]+", texte.lower())


def construire_bigrammes(corpus: list[str]) -> dict[str, dict[str, int]]:
    modele: dict[str, dict[str, int]] = {}
    for phrase in corpus:
        mots = _tokeniser(phrase)
        for a, b in zip(mots, mots[1:]):
            suivants = modele.setdefault(a, {})
            suivants[b] = suivants.get(b, 0) + 1
    return modele


def generer_phrase(
    corpus: list[str], mot_amorce: str | None = None, longueur_max: int = 9
) -> str | None:
    """Génère une phrase en suivant les enchaînements de mots appris depuis le
    corpus. Renvoie None si le vocabulaire est encore trop pauvre."""
    modele = construire_bigrammes(corpus)
    if len(modele) < SEUIL_MIN_BIGRAMMES:
        return None

    mot_amorce = mot_amorce.lower() if mot_amorce else None
    if mot_amorce in modele:
        courant = mot_amorce
    else:
        courant = random.choice(list(modele.keys()))

    resultat = [courant]
    for _ in range(longueur_max - 1):
        suivants = modele.get(courant)
        if not suivants:
            break
        mots, poids = zip(*suivants.items())
        courant = random.choices(mots, weights=poids, k=1)[0]
        resultat.append(courant)
        if len(set(resultat)) == 1 and len(resultat) > 4:
            break  # évite les boucles du type "mot mot mot mot"

    if len(resultat) < 3:
        return None
    return " ".join(resultat)
