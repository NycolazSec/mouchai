"""Mémoire persistante de la mouche : ce qui lui permet de vraiment apprendre
d'une session à l'autre, sans aucun modèle pré-entraîné ni API externe.

Trois choses sont sauvegardées sur disque (fichier JSON local) :
  1. Les poids synaptiques KC -> MBON appris (renforcement de type dopaminergique,
     le mécanisme réel de l'apprentissage associatif dans le corps pédonculé).
  2. Le lexique appris : des mots que l'utilisateur a employés et confirmés
     (via le feedback 👍/👎) comme associés à une catégorie de comportement.
  3. L'historique des échanges, qui sert à la fois de mémoire associative
     (retrouver un sujet déjà abordé, voir langage.py) et de corpus de
     vocabulaire.
  4. Les co-occurrences mot/catégorie du classifieur bayésien (stats_mots).
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone

CHEMIN_MEMOIRE = os.path.join(os.path.dirname(__file__), "memoire_mouche.json")
# La mouche principale : une sauvegarde de référence jamais écrasée par un
# import. Sert de socle pour quiconque n'a pas (encore) sa propre mouche
# entraînée, et permet de revenir en arrière après avoir importé un cerveau
# tiers sans perdre l'original.
CHEMIN_PRINCIPALE = os.path.join(os.path.dirname(__file__), "memoire_mouche_principale.json")
_verrou = threading.Lock()

_ETAT_PAR_DEFAUT = {
    "poids_mbon_kc": {},       # nom_compartiment -> {indice_kc(str): poids appris}
    "lexique_appris": {},      # categorie -> {mot: nb_confirmations}
    "historique": [],          # [{message_humain, message_mouche, categorie, feedback, ts}]
    "stats": {"total_echanges": 0, "total_feedback_positif": 0, "total_feedback_negatif": 0},
}

# Champs ajoutés après coup : absents des cerveaux exportés avant leur
# introduction, donc optionnels à l'import (sinon les anciens fichiers, dont
# la mouche principale déjà sauvegardée, deviendraient tous invalides).
_CHAMPS_OPTIONNELS = {
    "stats_mots": {},          # categorie -> {mot: poids de co-occurrence}
    # État physiologique persistant : chez la vraie drosophile, la faim et la
    # fatigue conditionnent les comportements déclenchés par un même stimulus
    # (modulation dopaminergique des sorties du corps pédonculé).
    "etat_interne": {
        "faim": 0.4,
        "energie": 1.0,
        "humeur": 0.0,
        "derniere_visite": None,
    },
}


def _lire() -> dict:
    if not os.path.exists(CHEMIN_MEMOIRE):
        # Pas encore de mouche personnelle : on hérite de la mouche principale
        # si elle existe, plutôt que de repartir d'un cerveau vide.
        if os.path.exists(CHEMIN_PRINCIPALE):
            try:
                with open(CHEMIN_PRINCIPALE, "r", encoding="utf-8") as f:
                    donnees = json.load(f)
                for cle, valeur in _ETAT_PAR_DEFAUT.items():
                    donnees.setdefault(cle, json.loads(json.dumps(valeur)))
                return donnees
            except (json.JSONDecodeError, OSError):
                pass
        return json.loads(json.dumps(_ETAT_PAR_DEFAUT))
    try:
        with open(CHEMIN_MEMOIRE, "r", encoding="utf-8") as f:
            donnees = json.load(f)
    except (json.JSONDecodeError, OSError):
        return json.loads(json.dumps(_ETAT_PAR_DEFAUT))
    for cle, valeur in {**_ETAT_PAR_DEFAUT, **_CHAMPS_OPTIONNELS}.items():
        donnees.setdefault(cle, json.loads(json.dumps(valeur)))
    return donnees


def _ecrire(donnees: dict) -> None:
    tmp = CHEMIN_MEMOIRE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHEMIN_MEMOIRE)


def charger_poids_appris() -> dict[str, dict[int, float]]:
    with _verrou:
        donnees = _lire()
    return {
        nom: {int(idx): poids for idx, poids in poids_dict.items()}
        for nom, poids_dict in donnees["poids_mbon_kc"].items()
    }


def charger_stats_mots() -> dict[str, dict[str, float]]:
    with _verrou:
        donnees = _lire()
    return {
        categorie: {mot: float(poids) for mot, poids in mots.items()}
        for categorie, mots in donnees["stats_mots"].items()
        if isinstance(mots, dict)
    }


def sauver_stats_mots(stats_mots: dict[str, dict[str, float]]) -> None:
    """Persiste les co-occurrences mot/catégorie apprises automatiquement."""
    with _verrou:
        donnees = _lire()
        donnees["stats_mots"] = {
            categorie: {mot: float(poids) for mot, poids in mots.items()}
            for categorie, mots in stats_mots.items()
        }
        _ecrire(donnees)


def charger_lexique_appris() -> dict[str, dict[str, int]]:
    with _verrou:
        donnees = _lire()
    return donnees["lexique_appris"]


def charger_etat_interne() -> dict:
    with _verrou:
        donnees = _lire()
    etat = dict(_CHAMPS_OPTIONNELS["etat_interne"])
    source = donnees.get("etat_interne")
    if isinstance(source, dict):
        for cle in ("faim", "energie", "humeur"):
            try:
                etat[cle] = float(source.get(cle, etat[cle]))
            except (TypeError, ValueError):
                pass
        visite = source.get("derniere_visite")
        etat["derniere_visite"] = visite if isinstance(visite, str) else None
    return etat


def sauver_etat_interne(etat: dict) -> None:
    with _verrou:
        donnees = _lire()
        donnees["etat_interne"] = {
            "faim": float(etat.get("faim", 0.4)),
            "energie": float(etat.get("energie", 1.0)),
            "humeur": float(etat.get("humeur", 0.0)),
            "derniere_visite": datetime.now(timezone.utc).isoformat(),
        }
        _ecrire(donnees)


def charger_historique(limite: int = 400) -> list[dict]:
    """Derniers échanges complets, utilisés par la mémoire associative du
    moteur de langage (retrouver un sujet déjà abordé)."""
    with _verrou:
        donnees = _lire()
    return [e for e in donnees["historique"][-limite:] if isinstance(e, dict)]


def charger_corpus() -> list[str]:
    """Corpus d'entraînement du générateur de phrases : uniquement les messages
    de l'utilisateur. On exclut volontairement les réponses de la mouche pour
    éviter une boucle dégénérative où elle réapprendrait indéfiniment ses
    propres formules ("j'ai reconnu...", "ce que ça m'évoque...")."""
    with _verrou:
        donnees = _lire()
    return [e["message_humain"] for e in donnees["historique"]]


def statistiques() -> dict:
    with _verrou:
        donnees = _lire()
    nb_mots_appris = sum(len(m) for m in donnees["lexique_appris"].values())
    return {
        **donnees["stats"],
        "mots_appris": nb_mots_appris,
        "echanges_en_memoire": len(donnees["historique"]),
    }


def enregistrer_echange(
    message_humain: str, message_mouche: str, categorie: str, kc_indices: list[int]
) -> str:
    """Ajoute l'échange à l'historique et renvoie son identifiant (utilisé pour
    rattacher un feedback ultérieur, même si l'historique est ensuite purgé)."""
    with _verrou:
        donnees = _lire()
        identifiant = f"{len(donnees['historique'])}-{datetime.now(timezone.utc).timestamp()}"
        donnees["historique"].append(
            {
                "id": identifiant,
                "message_humain": message_humain,
                "message_mouche": message_mouche,
                "categorie": categorie,
                "kc_indices": kc_indices,
                "feedback": None,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        donnees["historique"] = donnees["historique"][-2000:]  # borne la taille du fichier
        donnees["stats"]["total_echanges"] += 1
        _ecrire(donnees)
    return identifiant


def obtenir_echange(identifiant: str) -> dict | None:
    with _verrou:
        donnees = _lire()
    for entree in reversed(donnees["historique"]):
        if entree.get("id") == identifiant:
            return entree
    return None


def appliquer_feedback(
    identifiant_echange: str,
    note: int,
    poids_mis_a_jour: dict[str, dict[int, float]] | None,
    mots_modifies: list[str] | None,
    categorie: str | None,
) -> None:
    """Persiste le résultat d'un feedback 👍(+1)/👎(-1) : poids synaptiques mis
    à jour, et mots appris (note>0) ou désappris (note<0) pour la catégorie
    concernée — miroir exact de ce que fly_brain.appliquer_feedback_sur_echange
    vient de faire en mémoire vive."""
    with _verrou:
        donnees = _lire()

        for entree in donnees["historique"]:
            if entree.get("id") == identifiant_echange:
                entree["feedback"] = note
                break

        if poids_mis_a_jour:
            for nom, poids_dict in poids_mis_a_jour.items():
                cible = donnees["poids_mbon_kc"].setdefault(nom, {})
                for idx, poids in poids_dict.items():
                    cible[str(idx)] = poids

        if mots_modifies and categorie:
            lex = donnees["lexique_appris"].setdefault(categorie, {})
            if note > 0:
                for mot in mots_modifies:
                    lex[mot] = lex.get(mot, 0) + 1
            else:
                for mot in mots_modifies:
                    if mot in lex:
                        lex[mot] -= 1
                        if lex[mot] <= 0:
                            del lex[mot]

        if note > 0:
            donnees["stats"]["total_feedback_positif"] += 1
        elif note < 0:
            donnees["stats"]["total_feedback_negatif"] += 1

        _ecrire(donnees)


def definir_mot_appris(categorie: str, mot: str, confiance: int) -> None:
    """Persiste un enseignement direct (mot -> catégorie), en miroir de
    fly_brain.enseigner_mot appliqué en mémoire vive."""
    with _verrou:
        donnees = _lire()
        lex = donnees["lexique_appris"].setdefault(categorie, {})
        lex[mot] = max(lex.get(mot, 0), confiance)
        _ecrire(donnees)


def exporter_etat() -> dict:
    """Renvoie l'état complet de la mouche active, tel quel — c'est ce fichier
    qu'on télécharge pour partager ou sauvegarder son cerveau."""
    with _verrou:
        return _lire()


def _entier_positif(valeur, defaut: int = 0) -> int:
    try:
        v = int(valeur)
        return v if v >= 0 else defaut
    except (TypeError, ValueError):
        return defaut


def importer_etat(donnees: dict) -> dict:
    """Remplace la mouche active par un cerveau importé (fichier exporté
    précédemment, par soi-même ou par quelqu'un d'autre — donc une entrée non
    fiable par nature). Reconstruit un état entièrement neuf en revalidant
    chaque champ jusque dans ses structures imbriquées, plutôt que de faire
    confiance aux types de premier niveau : un fichier dont les clés de
    premier niveau sont correctes mais dont le contenu interne est corrompu
    (ex. "poids_mbon_kc" pointant vers une chaîne au lieu d'un dict) pouvait
    auparavant passer la validation et faire planter le serveur plus tard,
    lors d'une conversation normale — avec la console de debug Werkzeug
    exposée en conséquence. Toute entrée invalide est ici silencieusement
    ignorée plutôt que de lever une exception non contrôlée. En cas de fichier
    corrompu au point de ne rien pouvoir en tirer, rien n'est écrit sur disque."""
    if not isinstance(donnees, dict):
        raise ValueError("Le fichier doit contenir un objet JSON.")

    manquants = [cle for cle in _ETAT_PAR_DEFAUT if cle not in donnees]
    if manquants:
        raise ValueError(
            "Ce n'est pas un fichier de cerveau de mouche valide "
            f"(champs manquants : {', '.join(manquants)})."
        )

    # poids_mbon_kc : nom(str) -> {indice(str castable en int) -> poids(float)}
    poids_source = donnees["poids_mbon_kc"]
    if not isinstance(poids_source, dict):
        raise ValueError("Champ « poids_mbon_kc » invalide.")
    poids_valides: dict[str, dict[str, float]] = {}
    for nom, poids_dict in poids_source.items():
        if not isinstance(nom, str) or not isinstance(poids_dict, dict):
            continue
        cible = {}
        for idx, poids in poids_dict.items():
            try:
                cible[str(int(idx))] = float(poids)
            except (TypeError, ValueError):
                continue
        poids_valides[nom] = cible

    # lexique_appris : categorie(str) -> {mot(str) -> confirmations(int)}
    lexique_source = donnees["lexique_appris"]
    if not isinstance(lexique_source, dict):
        raise ValueError("Champ « lexique_appris » invalide.")
    lexique_valide: dict[str, dict[str, int]] = {}
    for categorie, mots in lexique_source.items():
        if not isinstance(categorie, str) or not isinstance(mots, dict):
            continue
        cible = {}
        for mot, confirmations in mots.items():
            if not isinstance(mot, str):
                continue
            cible[mot] = _entier_positif(confirmations, defaut=1)
        lexique_valide[categorie] = cible

    # historique : liste d'échanges bien formés — les entrées corrompues sont
    # ignorées individuellement plutôt que de faire échouer tout l'import.
    historique_source = donnees["historique"]
    if not isinstance(historique_source, list):
        raise ValueError("Champ « historique » invalide.")
    historique_valide = []
    for entree in historique_source:
        if not isinstance(entree, dict):
            continue
        try:
            feedback = entree.get("feedback")
            historique_valide.append(
                {
                    "id": str(entree.get("id", "")),
                    "message_humain": str(entree.get("message_humain", "")),
                    "message_mouche": str(entree.get("message_mouche", "")),
                    "categorie": str(entree.get("categorie", "")),
                    "kc_indices": [int(i) for i in entree.get("kc_indices", [])],
                    "feedback": feedback if feedback in (1, -1) else None,
                    "ts": str(entree.get("ts", "")),
                }
            )
        except (TypeError, ValueError):
            continue

    # stats_mots : champ optionnel (absent des cerveaux exportés avant son
    # introduction), mêmes règles de validation que le lexique.
    stats_mots_valides: dict[str, dict[str, float]] = {}
    stats_mots_source = donnees.get("stats_mots")
    if isinstance(stats_mots_source, dict):
        for categorie, mots in stats_mots_source.items():
            if not isinstance(categorie, str) or not isinstance(mots, dict):
                continue
            cible = {}
            for mot, poids in mots.items():
                if not isinstance(mot, str):
                    continue
                try:
                    cible[mot] = float(poids)
                except (TypeError, ValueError):
                    continue
            stats_mots_valides[categorie] = cible

    stats_source = donnees["stats"] if isinstance(donnees["stats"], dict) else {}
    etat = {
        "poids_mbon_kc": poids_valides,
        "lexique_appris": lexique_valide,
        "stats_mots": stats_mots_valides,
        "historique": historique_valide[-2000:],
        "stats": {
            "total_echanges": _entier_positif(stats_source.get("total_echanges")),
            "total_feedback_positif": _entier_positif(stats_source.get("total_feedback_positif")),
            "total_feedback_negatif": _entier_positif(stats_source.get("total_feedback_negatif")),
        },
    }

    with _verrou:
        _ecrire(etat)
    return etat


def definir_comme_principale() -> None:
    """Fige l'état actuel comme « mouche principale » : le socle de secours
    utilisé par quiconque n'a pas encore sa propre mouche entraînée."""
    with _verrou:
        donnees = _lire()
    tmp = CHEMIN_PRINCIPALE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    os.replace(tmp, CHEMIN_PRINCIPALE)


def a_une_principale() -> bool:
    return os.path.exists(CHEMIN_PRINCIPALE)


def reinitialiser_depuis_principale() -> dict:
    """Restaure la mouche active à partir de la mouche principale sauvegardée."""
    if not os.path.exists(CHEMIN_PRINCIPALE):
        raise ValueError("Aucune mouche principale n'a encore été définie.")
    with open(CHEMIN_PRINCIPALE, "r", encoding="utf-8") as f:
        donnees = json.load(f)
    with _verrou:
        _ecrire(donnees)
    return donnees
