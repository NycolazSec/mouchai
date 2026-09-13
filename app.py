"""Serveur web pour Mouche AI : interface de chat qui fait dialoguer
l'utilisateur avec le circuit cérébral simulé de Drosophila melanogaster
(fly_brain.py, inspiré du connectome FAFB de https://codex.flywire.ai)."""

import json
import os
import uuid
from datetime import datetime, timezone

from flask import Flask, Response, jsonify, request, send_from_directory

import memoire
from main import (
    converser_avec_mouche,
    definir_mouche_principale,
    donner_feedback,
    enseigner,
    exporter_cerveau,
    importer_cerveau,
    reinitialiser_mouche_principale,
)

app = Flask(__name__)

CATEGORIES_VALIDES = {"aversif", "appetitif", "courtship", "neutre"}

AUDIO_DIR = os.path.join(os.path.dirname(__file__), "static", "audio")
VIDEO_DIR = os.path.join(os.path.dirname(__file__), "static", "videos")
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)


@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True) or {}
    message = data.get("message")
    if not isinstance(message, str):
        return jsonify({"erreur": "Champ « message » invalide."}), 400
    message = message.strip()
    if not message:
        return jsonify({"erreur": "Message vide."}), 400
    if len(message) > 500:
        return jsonify({"erreur": "Message trop long (500 caractères max)."}), 400

    identifiant = uuid.uuid4().hex
    nom_wav = f"{identifiant}.wav"
    nom_mp4 = f"{identifiant}.mp4"
    chemin_wav = os.path.join(AUDIO_DIR, nom_wav)
    chemin_mp4 = os.path.join(VIDEO_DIR, nom_mp4)

    resultat = converser_avec_mouche(
        message, nom_fichier_wav=chemin_wav, nom_fichier_video=chemin_mp4
    )

    return jsonify(
        {
            "echange_id": resultat["echange_id"],
            "message_mouche": resultat["message_mouche"],
            "langage_mouche": resultat["langage_mouche"],
            "posture": resultat["posture"],
            "chimie": resultat["chimie"],
            "description": resultat["description"],
            "audio_url": f"/static/audio/{nom_wav}",
            "video_url": f"/static/videos/{nom_mp4}",
        }
    )


@app.route("/api/feedback", methods=["POST"])
def feedback():
    data = request.get_json(silent=True) or {}
    echange_id = data.get("echange_id")
    note = data.get("note")

    if not isinstance(echange_id, str) or not echange_id:
        return jsonify({"erreur": "Requête de feedback invalide."}), 400
    if not isinstance(note, int) or isinstance(note, bool) or note not in (1, -1):
        return jsonify({"erreur": "Requête de feedback invalide."}), 400

    try:
        stats = donner_feedback(echange_id, note)
    except ValueError as exc:
        return jsonify({"erreur": str(exc)}), 404

    return jsonify(stats)


@app.route("/api/enseigner", methods=["POST"])
def enseigner_route():
    data = request.get_json(silent=True) or {}
    mot = data.get("mot")
    categorie = data.get("categorie")

    if not isinstance(mot, str):
        return jsonify({"erreur": "Champ « mot » invalide."}), 400
    mot = mot.strip()
    if not mot:
        return jsonify({"erreur": "Mot vide."}), 400
    if len(mot) > 60:
        return jsonify({"erreur": "Mot trop long (60 caractères max)."}), 400
    if not isinstance(categorie, str) or categorie not in CATEGORIES_VALIDES:
        return jsonify({"erreur": "Catégorie invalide."}), 400

    try:
        resultat = enseigner(mot, categorie)
    except ValueError as exc:
        return jsonify({"erreur": str(exc)}), 400

    return jsonify({**resultat, "a_une_principale": memoire.a_une_principale()})


@app.route("/api/stats")
def stats():
    return jsonify({**memoire.statistiques(), "a_une_principale": memoire.a_une_principale()})


@app.route("/api/export")
def export_cerveau():
    donnees = exporter_cerveau()
    corps = json.dumps(donnees, ensure_ascii=False, indent=2)
    horodatage = datetime.now(timezone.utc).strftime("%Y-%m-%d_%Hh%M")
    return Response(
        corps,
        mimetype="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="mouche_cerveau_{horodatage}.json"'
        },
    )


@app.route("/api/import", methods=["POST"])
def import_cerveau():
    fichier = request.files.get("fichier")
    if fichier is None:
        return jsonify({"erreur": "Aucun fichier reçu."}), 400

    try:
        donnees = json.load(fichier.stream)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return jsonify({"erreur": "Fichier JSON invalide."}), 400

    try:
        importer_cerveau(donnees)
    except (ValueError, TypeError) as exc:
        return jsonify({"erreur": f"Cerveau importé invalide : {exc}"}), 400
    except Exception:
        # Filet de sécurité : un fichier importé est une entrée non fiable par
        # nature. Même si importer_etat() est censé tout valider, on ne laisse
        # jamais une exception imprévue remonter jusqu'au débogueur Werkzeug
        # (qui expose traces, chemins serveur et une console Python).
        return jsonify({"erreur": "Cerveau importé invalide."}), 400

    return jsonify({**memoire.statistiques(), "a_une_principale": memoire.a_une_principale()})


@app.route("/api/principale/definir", methods=["POST"])
def definir_principale():
    definir_mouche_principale()
    return jsonify({"ok": True})


@app.route("/api/principale/restaurer", methods=["POST"])
def restaurer_principale():
    try:
        reinitialiser_mouche_principale()
    except ValueError as exc:
        return jsonify({"erreur": str(exc)}), 404
    return jsonify({**memoire.statistiques(), "a_une_principale": memoire.a_une_principale()})


if __name__ == "__main__":
    app.run(debug=True, port=5001)
