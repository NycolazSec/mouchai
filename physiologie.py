"""État interne de la mouche : faim, énergie, humeur.

Chez la vraie drosophile, un même stimulus ne déclenche pas le même
comportement selon l'état physiologique : la faim lève l'inhibition des
circuits de recherche de nourriture, la fatigue éteint la parade. C'est une
modulation dopaminergique des sorties du corps pédonculé, bien documentée.

Ici, ça a une conséquence concrète : la réponse ne dépend plus seulement du
message, mais aussi du temps écoulé depuis la dernière visite et du ton des
échanges précédents. Deux fois la même phrase peuvent donner deux réactions.
"""

from __future__ import annotations

from datetime import datetime, timezone

# Valence affective de chaque comportement, utilisée pour l'humeur moyenne.
VALENCE = {
    "aversif": -1.0,
    "neutre": 0.0,
    "appetitif": 0.5,
    "courtship": 1.0,
}

FAIM_PAR_HEURE = 0.25       # la faim monte pendant l'absence
ENERGIE_PAR_HEURE = 0.8     # l'énergie se recharge pendant l'absence
# Calibré pour qu'une longue conversation la fatigue progressivement (~60
# messages avant épuisement) sans qu'une séance de test la mette à plat.
COUT_ENERGIE_ECHANGE = 0.015
INERTIE_HUMEUR = 0.75       # moyenne glissante : l'humeur ne saute pas d'un coup


def _heures_ecoulees(derniere_visite: str | None) -> float:
    if not derniere_visite:
        return 0.0
    try:
        precedent = datetime.fromisoformat(derniere_visite)
    except ValueError:
        return 0.0
    if precedent.tzinfo is None:
        precedent = precedent.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - precedent
    return max(0.0, delta.total_seconds() / 3600.0)


def faire_deriver(etat: dict) -> dict:
    """Applique le temps écoulé depuis la dernière visite."""
    heures = _heures_ecoulees(etat.get("derniere_visite"))
    return {
        **etat,
        "faim": min(1.0, etat.get("faim", 0.4) + FAIM_PAR_HEURE * heures),
        "energie": min(1.0, etat.get("energie", 1.0) + ENERGIE_PAR_HEURE * heures),
        "heures_absence": heures,
    }


def appliquer_echange(etat: dict, categorie: str) -> dict:
    """Met à jour l'état après une interaction."""
    faim = etat.get("faim", 0.4)
    if categorie == "appetitif":
        faim = max(0.0, faim - 0.12)  # manger (ou croire manger) rassasie un peu

    humeur = etat.get("humeur", 0.0)
    humeur = INERTIE_HUMEUR * humeur + (1 - INERTIE_HUMEUR) * VALENCE.get(categorie, 0.0)

    return {
        **etat,
        "faim": min(1.0, faim + 0.01),
        "energie": max(0.0, etat.get("energie", 1.0) - COUT_ENERGIE_ECHANGE),
        "humeur": humeur,
    }


def modulation(etat: dict) -> dict[str, float]:
    """Biais ajouté aux scores des compartiments MBON selon l'état interne.
    Affamée, la mouche voit de la nourriture partout ; épuisée, elle laisse
    tomber la parade et se contente de se toiletter."""
    faim = etat.get("faim", 0.4)
    energie = etat.get("energie", 1.0)
    return {
        "appetitif": 1.2 * max(0.0, faim - 0.35),
        "courtship": 0.8 * (energie - 0.5),
        "neutre": 1.0 * max(0.0, 0.45 - energie),
        "aversif": 0.4 * max(0.0, 0.4 - energie),  # épuisée, elle sursaute plus vite
    }


def resumer(etat: dict) -> dict:
    """Version lisible pour l'interface."""
    faim = etat.get("faim", 0.4)
    energie = etat.get("energie", 1.0)
    humeur = etat.get("humeur", 0.0)
    if faim > 0.75:
        etiquette_faim = "affamée"
    elif faim > 0.45:
        etiquette_faim = "un peu affamée"
    else:
        etiquette_faim = "repue"

    if energie < 0.35:
        etiquette_energie = "épuisée"
    elif energie < 0.7:
        etiquette_energie = "fatiguée"
    else:
        etiquette_energie = "en forme"

    if humeur > 0.35:
        etiquette_humeur = "de bonne humeur"
    elif humeur < -0.35:
        etiquette_humeur = "sur la défensive"
    else:
        etiquette_humeur = "neutre"

    return {
        "faim": round(faim, 2),
        "energie": round(energie, 2),
        "humeur": round(humeur, 2),
        "etiquette": f"{etiquette_faim}, {etiquette_energie}, {etiquette_humeur}",
    }
