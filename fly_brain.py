"""Simulation simplifiée du circuit cérébral de Drosophila melanogaster.

Inspiré de l'architecture réelle révélée par le connectome FAFB (FlyWire,
https://codex.flywire.ai/?dataset=fafb) : voie olfactive ORN -> PN -> Kenyon
cells (corps pédonculé) -> MBON -> neurones descendants -> muscles moteurs.

FlyWire ne fournit pas d'API publique pour télécharger le graphe de connexions
complet sans compte Google authentifié : ce module ne rejoue donc pas les
139 255 neurones et 3,7M connexions réelles, mais un circuit réduit qui respecte
les mêmes étages, les mêmes ordres de grandeur relatifs et le même codage
"sparse" observé dans le corps pédonculé. Le message de l'utilisateur sert de
stimulus (comme une odeur) qui active ce circuit ; le résultat est une trace de
neurones activés (le "langage" de la mouche) traduite en comportement.
"""

from __future__ import annotations

import hashlib
import math
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass

import numpy as np

import memoire
import physiologie
import semantique

# Mots vides ignorés lors de l'apprentissage de vocabulaire (on ne veut retenir
# que des mots porteurs de sens, pas des articles/pronoms).
MOTS_VIDES = {
    "le", "la", "les", "de", "des", "du", "un", "une", "et", "tu", "je", "il",
    "elle", "est", "es", "a", "que", "qui", "pas", "ne", "ce", "se", "on",
    "en", "pour", "avec", "sur", "dans", "mon", "ma", "ton", "ta", "son",
    "sa", "au", "aux", "moi", "toi", "lui", "nous", "vous", "leur", "leurs",
    "cette", "ces", "cet", "suis", "es", "sont", "ai", "as", "avons", "avez",
    "ont", "etre", "avoir", "plus", "tres", "bien", "comme", "mais", "ou",
    "si", "quand", "donc", "car", "par", "y", "d", "l", "j", "qu", "c",
    "vraiment", "trop", "assez", "genre", "juste", "franchement",
    "carrement", "meme", "plutot", "encore", "alors", "aussi", "voila",
    "quand", "toujours", "jamais", "peu",
}

# --- Compréhension du langage : lexique français -> intention perçue ---
# Une vraie odeur (phéromone, nourriture, danger) déclenche un type précis de
# récepteur olfactif chez la mouche. Ici, le sens des mots du message joue le
# même rôle : il détermine quelle "odeur" (catégorie) est présentée au circuit,
# avant que celui-ci ne la propage biologiquement jusqu'au comportement.
LEXIQUE_INTENTIONS: dict[str, set[str]] = {
    "aversif": {
        "attention", "danger", "stop", "non", "arrete", "peur", "fuis", "fuir",
        "sale", "degage", "menace", "colere", "cri", "crie", "aie", "mal",
        "tape", "frappe", "va-t-en", "vat-en", "sors", "dehors", "interdit",
        "mechant", "mechante", "deteste", "haine", "tue", "casse",
    },
    "appetitif": {
        "manger", "mange", "sucre", "sucre", "fruit", "miel", "faim",
        "goute", "gouter", "interessant", "curieux", "curieuse", "odeur",
        "sent", "nourriture", "boire", "jus", "banane", "pomme", "sucree",
        "salut", "bonjour", "coucou", "hey", "regarde", "viens",
    },
    "courtship": {
        "amour", "aime", "aimes", "aimer", "belle", "beau", "coeur", "bisous",
        "bisou", "charme", "seduire", "mignon", "mignonne", "cherie", "cheri",
        "love", "embrasse", "cool", "adorable", "sexy", "danse",
    },
}


def _sans_accents(texte: str) -> str:
    normalise = unicodedata.normalize("NFD", texte)
    return "".join(c for c in normalise if unicodedata.category(c) != "Mn")


def _correspond(mot_utilisateur: str, mot_connu: str) -> bool:
    """Fait correspondre un mot à une entrée de lexique en tolérant les
    variantes morphologiques courantes du français (conjugaisons, pluriels,
    féminin/masculin) via un préfixe commun, plutôt qu'une égalité stricte.
    Sans ça, apprendre "aime" ne reconnaît jamais "aimes"/"aiment"/"aimer" —
    ce qui rendait l'apprentissage très difficile à généraliser."""
    if mot_utilisateur == mot_connu:
        return True
    prefixe = min(len(mot_utilisateur), len(mot_connu), 6)
    return prefixe >= 4 and mot_utilisateur[:prefixe] == mot_connu[:prefixe]


# Vocabulaire appris dynamiquement via le feedback utilisateur (👍/👎) ou
# enseigné directement, chargé depuis la mémoire persistante au démarrage
# puis enrichi en direct pendant que le processus tourne :
# {categorie: {mot: nb_confirmations}}.
_LEXIQUE_APPRIS: dict[str, dict[str, int]] = memoire.charger_lexique_appris()

# Statistiques mot/catégorie alimentées automatiquement à chaque échange
# (apprentissage par co-occurrence, sans attendre un 👍) et utilisées comme
# classifieur bayésien naïf : {categorie: {mot: poids}}.
_STATS_MOTS: dict[str, dict[str, float]] = memoire.charger_stats_mots()

MAX_VOCABULAIRE_PAR_CATEGORIE = 3000


def score_bayesien(tokens: list[str]) -> dict[str, float]:
    """Classifieur bayésien naïf maison sur les co-occurrences accumulées.
    Contrairement au lexique (correspondance de mots), il généralise : un mot
    jamais confirmé mais souvent croisé dans des phrases d'une catégorie finit
    par peser en sa faveur. Lissage de Laplace pour les mots rares."""
    scores: dict[str, float] = {}
    if not _STATS_MOTS:
        return scores

    vocabulaire = {mot for mots in _STATS_MOTS.values() for mot in mots}
    taille_vocab = len(vocabulaire) or 1

    # Seuls les mots déjà rencontrés sont notés. Sinon, le lissage donne
    # mécaniquement l'avantage à la catégorie la moins entraînée (probabilité
    # plus forte pour un mot inconnu), et une phrase de mots inconnus élit la
    # catégorie la plus pauvre — exactement l'inverse du comportement voulu.
    tokens_connus = [t for t in tokens if t in vocabulaire]
    if not tokens_connus:
        return {}

    # Prior uniforme volontairement : la fréquence d'entraînement d'une
    # catégorie est ici un artefact d'usage, pas une probabilité a priori.
    for categorie, mots in _STATS_MOTS.items():
        total_categorie = sum(mots.values()) or 1.0
        score = 0.0
        for token in tokens_connus:
            poids = mots.get(token, 0.0)
            score += math.log((poids + 0.3) / (total_categorie + 0.3 * taille_vocab))
        scores[categorie] = score
    return scores


def _mots_du_lexique_de_base() -> dict[str, str]:
    return {
        mot: categorie
        for categorie, lexique in LEXIQUE_INTENTIONS.items()
        for mot in lexique
    }


def purger_conflits_lexique() -> int:
    """Supprime des co-occurrences apprises les mots qui appartiennent au
    lexique de base d'une AUTRE catégorie. Sans ça, une erreur de
    classification pouvait enregistrer « peur » du côté de la parade, et le
    classifieur verrouillait ensuite l'erreur définitivement."""
    base = _mots_du_lexique_de_base()
    supprimes = 0
    for categorie, mots in _STATS_MOTS.items():
        for mot in list(mots):
            if base.get(mot, categorie) != categorie:
                del mots[mot]
                supprimes += 1
    for categorie, lexique in _LEXIQUE_APPRIS.items():
        for mot in list(lexique):
            if base.get(mot, categorie) != categorie:
                del lexique[mot]
                supprimes += 1
    return supprimes


def apprendre_cooccurrence(message: str, categorie: str, force: float = 0.5) -> list[str]:
    """Apprentissage rapide : quand la catégorie d'un message est établie avec
    certitude (mot du lexique reconnu), tous les autres mots porteurs de sens
    de la phrase gagnent du crédit pour cette catégorie — sans attendre un 👍.
    C'est de la propagation d'étiquette par co-occurrence : une seule phrase
    « attention le chat arrive » suffit à rapprocher « chat » du danger.
    Renvoie les mots réellement découverts (inconnus jusqu'ici)."""
    base = _mots_du_lexique_de_base()
    # Un mot du lexique de base ne se réapprend jamais ailleurs : c'est la
    # seule vérité terrain dont dispose la mouche.
    mots = [
        m for m in mots_candidats_apprentissage(message)
        if base.get(m, categorie) == categorie
    ]
    if not mots:
        return []

    stats = _STATS_MOTS.setdefault(categorie, {})
    connus = {mot for m in _STATS_MOTS.values() for mot in m}
    nouveaux = [mot for mot in mots if mot not in connus]

    for mot in mots:
        stats[mot] = stats.get(mot, 0.0) + force

    if len(stats) > MAX_VOCABULAIRE_PAR_CATEGORIE:
        gardes = sorted(stats.items(), key=lambda kv: kv[1], reverse=True)
        _STATS_MOTS[categorie] = dict(gardes[:MAX_VOCABULAIRE_PAR_CATEGORIE])

    return nouveaux


def categorie_connue(mot: str) -> str | None:
    """Catégorie déjà associée à un mot, tous mécanismes confondus."""
    for categorie, lexique in LEXIQUE_INTENTIONS.items():
        if mot in lexique:
            return categorie
    for categorie, lexique in _LEXIQUE_APPRIS.items():
        if mot in lexique:
            return categorie
    meilleure, poids_max = None, 0.0
    for categorie, mots in _STATS_MOTS.items():
        poids = mots.get(mot, 0.0)
        if poids > poids_max:
            meilleure, poids_max = categorie, poids
    return meilleure


def est_totalement_inconnu(mot: str) -> bool:
    """Vrai si le mot n'est ni au lexique, ni dans les co-occurrences, ni
    plaçable dans l'espace sémantique. Dans ce cas la mouche ne devine pas :
    elle le dit et demande — ça vaut mieux qu'une réaction au hasard, et ça
    accélère l'apprentissage."""
    if categorie_connue(mot) is not None:
        return False
    corpus = memoire.charger_corpus()
    return mot not in semantique.modele(corpus)


def voisinages_semantiques(tokens: list[str]) -> list[tuple[str, str, str, float]]:
    """Pour chaque mot dont la mouche ignore tout, cherche ses plus proches
    voisins dans l'espace sémantique appris et lui fait hériter de leur
    catégorie. Renvoie (mot, categorie, voisin, proximité)."""
    corpus = memoire.charger_corpus()
    if len(corpus) < 6:
        return []

    connus = {
        mot
        for lexique in LEXIQUE_INTENTIONS.values()
        for mot in lexique
    }
    connus |= {mot for lex in _LEXIQUE_APPRIS.values() for mot in lex}
    connus |= {mot for stats in _STATS_MOTS.values() for mot in stats}
    if not connus:
        return []

    resultats = []
    for token in tokens:
        if token in connus or len(token) < 3 or token in MOTS_VIDES:
            continue
        for proche, proximite in semantique.voisins(token, corpus, candidats=connus, k=2):
            categorie = categorie_connue(proche)
            if categorie:
                resultats.append((token, categorie, proche, proximite))
    return resultats


def detecter_intention(message: str) -> tuple[str | None, list[str]]:
    """Analyse le sens du message pour deviner l'intention de l'utilisateur
    (aversif / appétitif / courtship), comme la mouche reconnaît une odeur
    précise (phéromone, nourriture, danger) plutôt qu'un bruit aléatoire.
    Combine le lexique de base et le vocabulaire appris par renforcement, avec
    tolérance aux variantes morphologiques (voir _correspond).
    Renvoie (catégorie ou None, mots reconnus, certitude issue du lexique de
    base). La certitude conditionne l'apprentissage automatique : on ne
    propage une étiquette que depuis une décision fiable, jamais depuis une
    déduction statistique — sinon les erreurs se renforcent elles-mêmes."""
    tokens = re.findall(r"[a-zàâäéèêëïîôöùûüçñ']+", _sans_accents(message.lower()))
    # defaultdict : le vocabulaire appris peut couvrir des catégories absentes
    # du lexique de base (ex. "neutre", jamais dans LEXIQUE_INTENTIONS) — un
    # dict normal ferait planter le += ci-dessous sur une clé inconnue.
    scores: dict[str, float] = defaultdict(float, {cat: 0.0 for cat in LEXIQUE_INTENTIONS})
    mots_reconnus: list[str] = []

    certitude_lexique = False
    for token in tokens:
        reconnu = False

        for categorie, lexique in LEXIQUE_INTENTIONS.items():
            if any(_correspond(token, mot) for mot in lexique):
                # Le lexique de base est la vérité terrain : il pèse plus lourd
                # que tout ce qui est appris statistiquement (≤1.2) ou déduit
                # par le bayésien (≤0.95), qui eux peuvent être bruités.
                scores[categorie] += 2.5
                reconnu = True
                certitude_lexique = True

        for categorie, lexique_appris in _LEXIQUE_APPRIS.items():
            mot_proche = next((m for m in lexique_appris if _correspond(token, m)), None)
            if mot_proche is not None:
                # Un mot appris pèse un peu moins qu'un mot du lexique de base
                # tant qu'il n'a pas été confirmé plusieurs fois.
                confirmations = lexique_appris[mot_proche]
                scores[categorie] += min(1.2, 0.4 + 0.25 * confirmations)
                reconnu = True

        if reconnu:
            mots_reconnus.append(token)

    # Généralisation sémantique : les mots inconnus héritent de la réaction de
    # leurs voisins dans l'espace appris (voir semantique.py). C'est ce qui
    # permet de réagir correctement à un mot jamais enseigné.
    for token, categorie, proche, proximite in voisinages_semantiques(tokens):
        scores[categorie] += 0.8 * proximite
        mots_reconnus.append(f"{token}~{proche}")

    # Apport du classifieur bayésien : il ne peut pas décider seul (sinon le
    # moindre bruit statistique l'emporterait), mais il départage et permet de
    # trancher sur des phrases dont aucun mot n'est explicitement au lexique.
    bayes = score_bayesien(tokens)
    if bayes:
        meilleur_bayes = max(bayes, key=bayes.get)
        second = sorted(bayes.values(), reverse=True)
        marge = (second[0] - second[1]) if len(second) > 1 else 0.0
        # Marge normalisée : plus le bayésien est tranché, plus il pèse. Le
        # plafond reste sous le poids d'un mot du lexique de base (1.0), qui
        # garde donc le dernier mot en cas de conflit.
        scores[meilleur_bayes] += min(0.95, marge / 3.0)

    meilleure_categorie = max(scores, key=scores.get)
    if scores[meilleure_categorie] <= 0:
        return None, [], False
    return meilleure_categorie, mots_reconnus, certitude_lexique


def mots_candidats_apprentissage(message: str) -> list[str]:
    """Extrait les mots porteurs de sens d'un message (hors mots vides) : ce
    sont les candidats que la mouche peut retenir si l'utilisateur confirme
    sa réaction comme correcte."""
    tokens = re.findall(r"[a-zàâäéèêëïîôöùûüçñ']+", _sans_accents(message.lower()))
    return [t for t in tokens if len(t) >= 3 and t not in MOTS_VIDES]

# --- Étage 1 : récepteurs olfactifs (ORN), un type par glomérule de l'antenne ---
ORN_TYPES = [
    "Or42b", "Or59b", "Or47a", "Or22a", "Or85a", "Or43b", "Or67a", "Or35a",
    "Or49a", "Or98a", "Or92a", "Or88a", "Or67b", "Or13a", "Or82a", "Or47b",
    "Or65a", "Or56a", "Or69a", "Or71a",
]
N_ORN = len(ORN_TYPES)

# --- Étage 2 : neurones de projection (PN), relais antennal lobe -> corps pédonculé ---
N_PN = 40

# --- Étage 3 : cellules de Kenyon (KC), codage épars dans le corps pédonculé ---
N_KC = 400
KC_SPARSITY = 0.05  # ~5% des KC actifs, comme dans le vrai corps pédonculé

# --- Étage 4 : neurones de sortie du corps pédonculé (MBON), par compartiment ---
MBON_COMPARTMENTS = [
    ("MBON-g1pedc", "aversif"),      # évitement / alarme
    ("MBON-a2sc", "appetitif"),      # approche / intérêt
    ("MBON-b'2mp", "courtship"),     # parade nuptiale
    ("MBON-g4-g5", "neutre"),        # indifférence / toilettage
]

# --- Étage 5 : neurones descendants -> effecteurs moteurs ---
DN_TO_COMPORTEMENT = {
    "aversif": {
        "message": "⚠️ Danger perçu ! Je sursaute et je bats des ailes pour m'écarter — signal de fuite.",
        "posture": "Sursaut et battement d'ailes bilatéral d'évitement",
        "chimie": "Dispersion d'alarme (neurones DN-alarme -> muscles d'aile)",
        "type_chant": "pulse_rapide",
        "nb_pulses_base": 6,
        "ipi_base": 20.0,
    },
    "appetitif": {
        "message": "👅 Tiens, quelque chose d'intéressant. Je tâte le terrain avec mes tarses.",
        "posture": "Tapotement des tarses antérieurs (toucher récepteur)",
        "chimie": "Détection gustative de phéromones sur le substrat",
        "type_chant": "pulse",
        "nb_pulses_base": 14,
        "ipi_base": 36.0,
    },
    "courtship": {
        "message": "💃 Tu me plais. J'ouvre l'aile et je chante pour toi (parade nuptiale).",
        "posture": "Extension unilatérale de l'aile droite à 90°",
        "chimie": "Émission d'hydrocarbures cuticulaires (cis-vaccenyl acetate)",
        "type_chant": "sine",
        "freq_base": 160.0,
        "duree_base": 0.8,
    },
    "neutre": {
        "message": "🧹 Bof. Ton message ne m'intéresse pas vraiment, je fais ma toilette.",
        "posture": "Toilettage des yeux avec les pattes antérieures",
        "chimie": "Neutre",
        "type_chant": "toilettage",
    },
}


@dataclass
class TraceActivation:
    stimulus: str
    orn_actives: list[str]
    pn_activite: np.ndarray
    kc_indices_actifs: np.ndarray
    mbon_scores: dict[str, float]
    compartiment_gagnant: str
    intensite: float
    intention_detectee: str | None
    certitude_lexique: bool
    mots_reconnus: list[str]
    voisins_semantiques: list[tuple[str, str, str, float]]

    def langage_mouche(self) -> str:
        """Formate la trace neuronale comme une phrase dans le "langage" natif
        de la mouche : les identifiants réels de neurones qui se sont activés."""
        orn_str = "+".join(self.orn_actives[:6])
        kc_str = f"KC[{len(self.kc_indices_actifs)}/{N_KC}]"
        mbon_str = ", ".join(
            f"{nom}:{self.mbon_scores[nom]:+.2f}" for nom, _ in MBON_COMPARTMENTS
        )
        trace = (
            f"ORN({orn_str}) -> PN -> {kc_str} -> MBON[{mbon_str}] "
            f"=> DN:{self.compartiment_gagnant}"
        )
        if self.mots_reconnus:
            trace += f" | compris: {'+'.join(self.mots_reconnus)}"
        return trace


def _seed_depuis_texte(texte: str) -> int:
    digest = hashlib.sha256(texte.encode("utf-8")).digest()
    return int.from_bytes(digest[:4], "big")


def _matrice_fixe(
    rng_seed: int, n_in: int, n_out: int, densite: float, signee: bool = False
) -> np.ndarray:
    """Connectivité fixe et reproductible (comme les synapses câblées d'un vrai
    circuit), tirée une fois pour toutes à partir d'une graine constante.
    `signee=True` autorise des poids inhibiteurs (nécessaire aux MBON, dont les
    compartiments réels sont soit appétitifs soit aversifs selon leur cible)."""
    rng = np.random.default_rng(rng_seed)
    poids = rng.normal(0.0, 1.0, (n_out, n_in)) if signee else rng.random((n_out, n_in))
    masque = rng.random((n_out, n_in)) < densite
    return poids * masque


# Connectivité "anatomique" fixe du circuit (indépendante du message et de la
# mémoire — ce sont les "câbles" innés, jamais réécrits par l'apprentissage).
_W_PN_ORN = _matrice_fixe(rng_seed=1, n_in=N_ORN, n_out=N_PN, densite=0.3)
_W_KC_PN = _matrice_fixe(rng_seed=2, n_in=N_PN, n_out=N_KC, densite=0.15)  # ~6 claws/KC


def _construire_poids_mbon_kc_base() -> dict[str, np.ndarray]:
    return {
        nom: _matrice_fixe(
            rng_seed=_seed_depuis_texte(nom), n_in=N_KC, n_out=1, densite=1.0, signee=True
        ).flatten()
        for nom, _ in MBON_COMPARTMENTS
    }


def _appliquer_overrides_poids() -> None:
    for nom, overrides in memoire.charger_poids_appris().items():
        if nom in _W_MBON_KC:
            for idx, poids in overrides.items():
                if 0 <= idx < N_KC:
                    _W_MBON_KC[nom][idx] = poids


# Plasticité : les synapses KC -> MBON modifiées par un feedback antérieur
# (mécanisme réel de l'apprentissage associatif dans le corps pédonculé, piloté
# in vivo par les neurones dopaminergiques) remplacent leur valeur d'origine.
_W_MBON_KC = _construire_poids_mbon_kc_base()
_appliquer_overrides_poids()

_NOM_PAR_CATEGORIE = {categorie: nom for nom, categorie in MBON_COMPARTMENTS}


def recharger_depuis_memoire() -> None:
    """Recharge poids synaptiques appris et lexique appris depuis la mémoire
    persistante, à chaud (après un import ou une réinitialisation), sans avoir
    à redémarrer le serveur."""
    global _W_MBON_KC, _LEXIQUE_APPRIS, _STATS_MOTS
    _W_MBON_KC = _construire_poids_mbon_kc_base()
    _appliquer_overrides_poids()
    _LEXIQUE_APPRIS = memoire.charger_lexique_appris()
    _STATS_MOTS = memoire.charger_stats_mots()
    purger_conflits_lexique()


def stats_mots_actuelles() -> dict[str, dict[str, float]]:
    """Expose l'état courant des co-occurrences pour persistance."""
    return _STATS_MOTS


def simuler_stimulus(message: str, etat_interne: dict | None = None) -> TraceActivation:
    """Propage le message (comme une odeur) à travers le circuit simplifié et
    renvoie la trace complète d'activation, étage par étage. `etat_interne`
    (faim, énergie) module les sorties, comme la physiologie module les
    comportements d'une vraie drosophile."""
    rng = np.random.default_rng(_seed_depuis_texte(message))

    # Chaque mot du message est haché vers un récepteur olfactif précis (comme
    # une molécule odorante active un glomérule donné) : le contenu du message
    # détermine directement quelles ORN s'activent, pas seulement du bruit.
    mots = message.lower().split() or ["_silence_"]
    activation_orn = rng.random(N_ORN) * 0.15  # bruit de fond
    for mot in mots:
        idx = _seed_depuis_texte(mot) % N_ORN
        activation_orn[idx] += 1.0
    orn_actives_idx = np.where(activation_orn >= 0.5)[0]
    orn_actives = [ORN_TYPES[i] for i in orn_actives_idx]

    # Propagation ORN -> PN (relais + normalisation, comme le vrai lobe antennaire)
    activite_pn = _W_PN_ORN @ activation_orn
    activite_pn = activite_pn / (activite_pn.max() + 1e-9)

    # Propagation PN -> KC puis codage épars (winner-take-all du corps pédonculé)
    activite_kc = _W_KC_PN @ activite_pn
    n_actifs = max(1, int(N_KC * KC_SPARSITY))
    kc_indices_actifs = np.argsort(activite_kc)[-n_actifs:]

    # Lecture KC -> MBON par compartiment
    mbon_scores = {}
    for nom, _ in MBON_COMPARTMENTS:
        poids = _W_MBON_KC[nom][kc_indices_actifs]
        mbon_scores[nom] = float(poids.mean())

    # Compréhension du langage : si le message contient des mots reconnus, on
    # présente au circuit la "vraie" odeur associée à cette intention (comme
    # une phéromone identifiée), ce qui force le compartiment MBON correspondant
    # à dominer — la mouche répond alors bien au SENS du message, pas au hasard.
    intention_detectee, mots_reconnus, certitude = detecter_intention(message)
    if intention_detectee is not None:
        nom_compartiment = _NOM_PAR_CATEGORIE[intention_detectee]
        # Le bonus doit garantir la victoire du sens détecté : avec un bonus
        # fixe, un compartiment dont les synapses ont beaucoup été renforcées
        # finissait par passer devant, et un mot aussi explicite que « peur »
        # pouvait déclencher une parade nuptiale.
        ecart = max(mbon_scores.values()) - mbon_scores[nom_compartiment]
        mbon_scores[nom_compartiment] += max(3.0, ecart + 1.5)

    # Modulation par l'état interne : affamée, elle penche vers la nourriture ;
    # épuisée, elle abandonne la parade. Un même message ne donne donc pas
    # toujours la même réaction.
    if etat_interne:
        for categorie, biais in physiologie.modulation(etat_interne).items():
            if biais:
                mbon_scores[_NOM_PAR_CATEGORIE[categorie]] += biais

    # Le compartiment MBON le plus activé détermine le comportement de sortie
    nom_gagnant = max(mbon_scores, key=mbon_scores.get)
    categorie_gagnante = dict(MBON_COMPARTMENTS)[nom_gagnant]
    intensite = float(np.clip(mbon_scores[nom_gagnant], 0.0, 1.0))

    return TraceActivation(
        stimulus=message,
        orn_actives=orn_actives,
        pn_activite=activite_pn,
        kc_indices_actifs=kc_indices_actifs,
        mbon_scores=mbon_scores,
        compartiment_gagnant=categorie_gagnante,
        intensite=intensite,
        intention_detectee=intention_detectee,
        certitude_lexique=certitude,
        mots_reconnus=[m for m in mots_reconnus if "~" not in m],
        voisins_semantiques=voisinages_semantiques(
            re.findall(r"[a-zàâäéèêëïîôöùûüçñ']+", _sans_accents(message.lower()))
        ),
    )


def comportement_depuis_trace(trace: TraceActivation) -> dict:
    """Traduit la trace neuronale en paramètres comportementaux/acoustiques,
    modulés par l'intensité d'activation du compartiment MBON gagnant."""
    base = dict(DN_TO_COMPORTEMENT[trace.compartiment_gagnant])
    intensite = 0.5 + trace.intensite  # facteur de modulation [0.5, 1.5]

    if base["type_chant"] == "sine":
        base["freq"] = base.pop("freq_base") * intensite
        base["duree"] = base.pop("duree_base") * intensite
    elif base["type_chant"] in ("pulse", "pulse_rapide"):
        base["nb_pulses"] = max(1, int(base.pop("nb_pulses_base") * intensite))
        base["ipi"] = base.pop("ipi_base") / intensite

    base["description"] = (
        f"Compartiment MBON dominant : {trace.compartiment_gagnant} "
        f"(intensité {trace.intensite:.2f})"
    )

    if trace.mots_reconnus:
        mots = ", ".join(sorted(set(trace.mots_reconnus)))
        base["message"] += f" (j'ai reconnu : {mots})"

    return base


TAUX_APPRENTISSAGE = 0.2


def appliquer_feedback_sur_echange(
    message_humain: str, kc_indices: list[int], categorie: str, note: int
) -> tuple[dict[str, dict[int, float]], list[str]]:
    """Renforcement synaptique : un 👍 (note=+1) consolide les synapses entre les
    cellules de Kenyon activées par ce message et le compartiment MBON gagnant
    (elle deviendra plus encline à répéter cette réaction pour un stimulus
    similaire) ; un 👎 (note=-1) les affaiblit. C'est le même principe que le
    conditionnement associatif réel chez la drosophile (signal dopaminergique
    modulant les synapses KC->MBON pendant l'apprentissage).

    Cette plasticité synaptique seule ne généralise pas (le pattern de KC actifs
    dépend des mots exacts employés), donc le vocabulaire est ajusté en parallèle :
    un 👍 apprend les mots du message pour cette catégorie ; un 👎 les désapprend
    (contrairement à avant, où un mauvais mot appris n'était jamais corrigé).

    Renvoie (poids_modifies, mots_modifies) pour persistance dans memoire.py.
    `mots_modifies` sont les mots appris si note>0, désappris si note<0.
    """
    nom_compartiment = _NOM_PAR_CATEGORIE[categorie]
    poids_modifies: dict[str, dict[int, float]] = {nom_compartiment: {}}

    for idx in kc_indices:
        ancien = float(_W_MBON_KC[nom_compartiment][idx])
        nouveau = float(np.clip(ancien + TAUX_APPRENTISSAGE * note, -4.0, 4.0))
        _W_MBON_KC[nom_compartiment][idx] = nouveau
        poids_modifies[nom_compartiment][idx] = nouveau

    candidats = mots_candidats_apprentissage(message_humain)
    lex = _LEXIQUE_APPRIS.setdefault(categorie, {})
    mots_modifies: list[str] = []

    if note > 0:
        for mot in candidats:
            lex[mot] = lex.get(mot, 0) + 1
            mots_modifies.append(mot)
    else:
        for mot in candidats:
            if mot in lex:
                lex[mot] -= 1
                if lex[mot] <= 0:
                    del lex[mot]
                mots_modifies.append(mot)

    return poids_modifies, mots_modifies


def enseigner_mot(mot: str, categorie: str, confiance: int = 3) -> str:
    """Enseignement direct et déterministe : associe immédiatement un mot à
    une catégorie de comportement, sans attendre qu'il apparaisse par hasard
    dans une phrase suivie d'un 👍. Beaucoup plus rapide et fiable que le seul
    apprentissage par renforcement conversationnel."""
    if categorie not in DN_TO_COMPORTEMENT:
        raise ValueError(f"Catégorie inconnue : {categorie}")
    mot_normalise = re.sub(r"[^a-z'-]", "", _sans_accents(mot.strip().lower()))
    if not mot_normalise:
        raise ValueError("Mot vide après normalisation.")
    lex = _LEXIQUE_APPRIS.setdefault(categorie, {})
    lex[mot_normalise] = max(lex.get(mot_normalise, 0), confiance)
    return mot_normalise
