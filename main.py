import math
import random
import struct
import wave

import memoire
from fly_animation import generer_video_reaction
from fly_brain import (
    appliquer_feedback_sur_echange,
    comportement_depuis_trace,
    enseigner_mot,
    recharger_depuis_memoire,
    simuler_stimulus,
)
from texte_genere import generer_phrase

SAMPLE_RATE = 44100  # 44.1 kHz standard


def generer_sine_song(
    duree_sec: float, freq: float = 160.0, amplitude: float = 0.4
) -> list[float]:
    """Génère le chant sinusoïdal (vibration continue d'aile ~160 Hz)."""
    echantillons = int(SAMPLE_RATE * duree_sec)
    signal = []
    for i in range(echantillons):
        t = i / SAMPLE_RATE
        # Modulation d'enveloppe douce au début et à la fin pour éviter les clics
        enveloppe = math.sin(math.pi * (i / echantillons))
        valeur = amplitude * enveloppe * math.sin(2 * math.pi * freq * t)
        signal.append(valeur)
    return signal


def generer_pulse(duree_pulse_ms: float = 10.0, freq: float = 240.0) -> list[float]:
    """Génère une impulsion individuelle (un battement brusque d'aile)."""
    nb_pts = int(SAMPLE_RATE * (duree_pulse_ms / 1000.0))
    signal = []
    for i in range(nb_pts):
        t = i / SAMPLE_RATE
        # Enveloppe asymétrique typique d'une décharge biomécanique
        enveloppe = math.exp(-6.0 * (i / nb_pts)) * math.sin(
            math.pi * (i / nb_pts)
        )
        valeur = 0.8 * enveloppe * math.sin(2 * math.pi * freq * t)
        signal.append(valeur)
    return signal


def generer_pulse_song(nb_pulses: int, ipi_ms: float = 35.0) -> list[float]:
    """Génère un train de pulses espacés par l'IPI (Inter-Pulse Interval, ~35 ms)."""
    signal = []
    silence_inter_pulse = [0.0] * int(SAMPLE_RATE * (ipi_ms / 1000.0))

    for _ in range(nb_pulses):
        signal.extend(generer_pulse(duree_pulse_ms=8.0, freq=220.0))
        signal.extend(silence_inter_pulse)

    return signal


def exporter_wav(nom_fichier: str, echantillons: list[float]) -> None:
    """Écrit le flux audio 16-bit PCM dans un fichier WAV."""
    with wave.open(nom_fichier, "w") as wav_file:
        wav_file.setnchannels(1)  # Mono
        wav_file.setsampwidth(2)  # 16 bits (2 octets)
        wav_file.setframerate(SAMPLE_RATE)

        data = bytearray()
        for s in echantillons:
            # Clamping entre -1.0 et 1.0 puis conversion 16-bit signé
            s = max(-1.0, min(1.0, s))
            val = int(s * 32767.0)
            data.extend(struct.pack("<h", val))

        wav_file.writeframes(data)


def generer_toilettage(nb_frottements: int = 5) -> list[float]:
    """Génère le crissement discret des pattes qui se frottent (toilettage) :
    de courtes bouffées de bruit filtré, bien plus douces qu'un chant d'aile,
    pour que l'indifférence de la mouche reste malgré tout audible."""
    signal = []
    silence_court = [0.0] * int(SAMPLE_RATE * 0.08)
    for _ in range(nb_frottements):
        nb_pts = int(SAMPLE_RATE * 0.04)
        for i in range(nb_pts):
            enveloppe = math.sin(math.pi * (i / nb_pts))
            bruit = random.uniform(-1.0, 1.0)
            signal.append(0.12 * enveloppe * bruit)
        signal.extend(silence_court)
    return signal


def synthetiser_audio(reponse: dict) -> list[float]:
    """Génère l'échantillonnage audio correspondant au type de chant décidé
    par le circuit neuronal simulé. Chaque comportement produit toujours un
    son audible (même l'indifférence a son crissement de toilettage)."""
    if reponse["type_chant"] == "sine":
        return generer_sine_song(duree_sec=reponse["duree"], freq=reponse["freq"])
    if reponse["type_chant"] == "pulse":
        return generer_pulse_song(nb_pulses=reponse["nb_pulses"], ipi_ms=reponse["ipi"])
    if reponse["type_chant"] == "pulse_rapide":
        return generer_pulse_song(nb_pulses=reponse["nb_pulses"], ipi_ms=reponse["ipi"])
    if reponse["type_chant"] == "toilettage":
        return generer_toilettage()
    return generer_toilettage()


def converser_avec_mouche(
    message_humain: str,
    nom_fichier_wav: str = "reponse_mouche.wav",
    nom_fichier_video: str | None = None,
) -> dict:
    """Fait "parler" la mouche : propage le message dans le circuit neuronal
    simulé (fly_brain), en tire un comportement, synthétise le signal audio
    correspondant, et génère une courte vidéo de sa réaction physique.
    Renvoie un dict prêt à être affiché ou renvoyé en JSON."""
    trace = simuler_stimulus(message_humain)
    reponse = comportement_depuis_trace(trace)

    audio = synthetiser_audio(reponse)
    exporter_wav(nom_fichier_wav, audio)

    message_mouche = reponse["message"]

    # Génération apprise : une fois assez d'échanges accumulés, la mouche
    # tente d'ajouter une phrase composée à partir des mots qu'elle a
    # réellement "entendus" dans ses conversations passées (pas de modèle
    # pré-entraîné, uniquement le vocabulaire de son propre historique).
    corpus = memoire.charger_corpus()
    mots_du_message = message_humain.split()
    amorce = mots_du_message[-1] if mots_du_message else None
    phrase_apprise = generer_phrase(corpus, mot_amorce=amorce)
    if phrase_apprise:
        message_mouche += f"\n🧠 (ce que ça m'évoque : « {phrase_apprise} »)"

    kc_indices = trace.kc_indices_actifs.tolist()
    echange_id = memoire.enregistrer_echange(
        message_humain, message_mouche, trace.compartiment_gagnant, kc_indices
    )

    resultat = {
        "echange_id": echange_id,
        "message_humain": message_humain,
        "message_mouche": message_mouche,
        "langage_mouche": trace.langage_mouche(),
        "posture": reponse["posture"],
        "chimie": reponse["chimie"],
        "description": reponse["description"],
        "audio_path": nom_fichier_wav,
    }

    if nom_fichier_video:
        duree_audio = len(audio) / SAMPLE_RATE
        generer_video_reaction(trace.compartiment_gagnant, duree_audio, nom_fichier_video)
        resultat["video_path"] = nom_fichier_video

    return resultat


def donner_feedback(echange_id: str, note: int) -> dict:
    """Applique un feedback 👍(+1)/👎(-1) à un échange passé : renforce ou
    affaiblit les synapses KC->MBON impliquées, et fait éventuellement
    progresser le vocabulaire appris. Renvoie les statistiques mises à jour."""
    echange = memoire.obtenir_echange(echange_id)
    if echange is None:
        raise ValueError("Échange introuvable (mémoire peut-être purgée).")

    poids_modifies, mots_modifies = appliquer_feedback_sur_echange(
        echange["message_humain"], echange["kc_indices"], echange["categorie"], note
    )
    memoire.appliquer_feedback(
        echange_id, note, poids_modifies, mots_modifies, echange["categorie"]
    )
    return {"mots_touches": mots_modifies, "appris": note > 0, **memoire.statistiques()}


def enseigner(mot: str, categorie: str) -> dict:
    """Enseignement direct : associe immédiatement un mot à une catégorie,
    sans dépendre du hasard d'une réponse suivie d'un feedback."""
    mot_normalise = enseigner_mot(mot, categorie)
    memoire.definir_mot_appris(categorie, mot_normalise, confiance=3)
    return {"mot": mot_normalise, **memoire.statistiques()}


def exporter_cerveau() -> dict:
    return memoire.exporter_etat()


def importer_cerveau(donnees: dict) -> dict:
    """Remplace la mouche active par un cerveau importé, puis recharge les
    poids synaptiques et le lexique en mémoire vive (à chaud)."""
    etat = memoire.importer_etat(donnees)
    recharger_depuis_memoire()
    return etat


def definir_mouche_principale() -> None:
    memoire.definir_comme_principale()


def reinitialiser_mouche_principale() -> dict:
    etat = memoire.reinitialiser_depuis_principale()
    recharger_depuis_memoire()
    return etat


if __name__ == "__main__":
    msg = input("Parle à la mouche : ")
    resultat = converser_avec_mouche(msg)

    print(f"\n[Toi] : {resultat['message_humain']}")
    print(f"\n[Mouche] : {resultat['message_mouche']}")
    print("\n--- Langage natif de la mouche (trace neuronale) ---")
    print(resultat["langage_mouche"])
    print("\n--- Traduction comportementale (éthogramme) ---")
    print(f"• Posture : {resultat['posture']}")
    print(f"• Chimiosensation : {resultat['chimie']}")
    print(f"• {resultat['description']}")
    print(f"\n-> Signal audio synthétisé généré dans « {resultat['audio_path']} ».")