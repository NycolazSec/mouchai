"""Espace sémantique appris par la mouche, entièrement calculé ici.

Méthode : matrice de co-occurrence sur fenêtre glissante → pondération PPMI
(Positive Pointwise Mutual Information) → réduction de dimension par SVD
tronquée. C'est de l'analyse sémantique latente (LSA), la technique qui a
précédé word2vec : elle a l'énorme avantage de fonctionner sur de très petits
corpus, ce qui est exactement le cas ici (les messages de l'utilisateur).

Ce que ça change concrètement : la mouche ne reconnaît plus seulement les mots
qu'on lui a appris, elle place chaque mot dans un espace et peut donc dire
qu'un mot inconnu ressemble à un mot connu. « splendide » n'a jamais été
enseigné, mais s'il apparaît dans les mêmes contextes que « beau », il finit
à côté de lui — et hérite de sa réaction.

Aucun modèle pré-entraîné : tout est appris sur les conversations réelles.
La qualité augmente donc avec le nombre d'échanges.
"""

from __future__ import annotations

import numpy as np

from langage import MOTS_OUTILS, tokeniser

DIMENSIONS = 24
FENETRE = 4
# Un mot prononcé une seule fois doit pouvoir être placé : c'est précisément
# le cas qu'on veut couvrir (réagir à un mot jamais vu avant). On garde donc
# tout le vocabulaire, borné en taille pour que la SVD reste instantanée.
MIN_OCCURRENCES = 1
VOCABULAIRE_MAX = 600
SEUIL_VOISINAGE = 0.2

_cache: dict = {"signature": None, "vecteurs": {}, "vocabulaire": []}


def _construire(corpus: list[str]) -> dict[str, np.ndarray]:
    phrases = [tokeniser(p) for p in corpus]
    phrases = [p for p in phrases if p]
    if len(phrases) < 3:
        return {}

    occurrences: dict[str, int] = {}
    for tokens in phrases:
        for mot in tokens:
            occurrences[mot] = occurrences.get(mot, 0) + 1

    vocabulaire = sorted(
        (m for m, c in occurrences.items() if c >= MIN_OCCURRENCES),
        key=lambda m: -occurrences[m],
    )[:VOCABULAIRE_MAX]
    if len(vocabulaire) < 6:
        return {}

    index = {mot: i for i, mot in enumerate(vocabulaire)}
    taille = len(vocabulaire)
    cooc = np.zeros((taille, taille), dtype=np.float64)

    for tokens in phrases:
        positions = [(i, index[m]) for i, m in enumerate(tokens) if m in index]
        for rang, (i, idx_a) in enumerate(positions):
            for j, idx_b in positions[rang + 1:]:
                if abs(j - i) > FENETRE:
                    continue
                poids = 1.0 / abs(j - i)  # les mots proches comptent davantage
                cooc[idx_a, idx_b] += poids
                cooc[idx_b, idx_a] += poids

    total = cooc.sum()
    if total <= 0:
        return {}

    # PPMI : met en avant les associations plus fréquentes que le hasard.
    marges = cooc.sum(axis=1, keepdims=True)
    attendu = (marges @ marges.T) / total
    with np.errstate(divide="ignore", invalid="ignore"):
        pmi = np.log(np.divide(cooc, attendu, out=np.zeros_like(cooc), where=attendu > 0))
    ppmi = np.nan_to_num(np.maximum(pmi, 0.0), nan=0.0, posinf=0.0, neginf=0.0)

    dimensions = min(DIMENSIONS, taille - 1)
    u, s, _ = np.linalg.svd(ppmi, full_matrices=False)
    vecteurs_bruts = u[:, :dimensions] * np.sqrt(s[:dimensions])

    normes = np.linalg.norm(vecteurs_bruts, axis=1, keepdims=True)
    normes[normes == 0] = 1.0
    vecteurs_normes = vecteurs_bruts / normes

    return {mot: vecteurs_normes[i] for mot, i in index.items()}


def modele(corpus: list[str]) -> dict[str, np.ndarray]:
    """Renvoie les vecteurs de mots, recalculés uniquement quand le corpus a
    changé (la SVD est peu coûteuse à cette taille, mais inutile de la refaire
    à chaque message)."""
    signature = (len(corpus), sum(len(p) for p in corpus))
    if _cache["signature"] != signature:
        _cache["vecteurs"] = _construire(corpus)
        _cache["signature"] = signature
    return _cache["vecteurs"]


def similarite(mot_a: str, mot_b: str, corpus: list[str]) -> float:
    vecteurs = modele(corpus)
    if mot_a not in vecteurs or mot_b not in vecteurs:
        return 0.0
    return float(np.dot(vecteurs[mot_a], vecteurs[mot_b]))


def voisins(
    mot: str, corpus: list[str], candidats: set[str] | None = None, k: int = 3
) -> list[tuple[str, float]]:
    """Mots les plus proches dans l'espace sémantique. `candidats` permet de
    restreindre aux mots dont la mouche connaît déjà la catégorie."""
    vecteurs = modele(corpus)
    if mot not in vecteurs:
        return []

    reference = vecteurs[mot]
    scores = []
    for autre, vecteur in vecteurs.items():
        if autre == mot or len(autre) < 3 or autre in MOTS_OUTILS:
            continue
        if candidats is not None and autre not in candidats:
            continue
        scores.append((autre, float(np.dot(reference, vecteur))))

    scores.sort(key=lambda kv: kv[1], reverse=True)
    return [(m, s) for m, s in scores[:k] if s > SEUIL_VOISINAGE]
