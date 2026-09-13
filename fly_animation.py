"""Génère une courte vidéo (mp4) montrant une mouche stylisée réagir
physiquement selon le comportement décidé par le circuit neuronal simulé
(fly_brain.py) : fuite, tapotement d'intérêt, parade nuptiale ou toilettage.
"""

from __future__ import annotations

import math
import subprocess

from PIL import Image, ImageDraw

LARGEUR, HAUTEUR = 360, 240
FPS = 20
COULEUR_FOND = (13, 15, 20)
COULEUR_ABDOMEN = (64, 42, 36)
COULEUR_THORAX = (84, 58, 50)
COULEUR_TETE = (48, 34, 30)
COULEUR_OEIL = (176, 30, 30)
COULEUR_PATTE = (28, 20, 18)
COULEUR_AILE = (205, 214, 245, 130)


def _dessiner_mouche(
    draw: ImageDraw.ImageDraw,
    cx: float,
    cy: float,
    angle_aile_gauche: float,
    angle_aile_droite: float,
    levee_pattes: float,
    inclinaison: float = 0.0,
) -> None:
    """Dessine une mouche vectorielle simplifiée à la position et pose donnée."""
    # Ailes (dessinées derrière le corps)
    for cote, angle in ((-1, angle_aile_gauche), (1, angle_aile_droite)):
        longueur = 62
        rad = math.radians(angle)
        x2 = cx + cote * 12 + math.cos(rad) * longueur * cote
        y2 = cy - 8 - math.sin(rad) * longueur
        draw.line([(cx + cote * 8, cy - 4), (x2, y2)], fill=COULEUR_AILE, width=13)

    # Pattes (3 paires) ; la paire avant s'anime avec `levee_pattes`
    for i, decalage_x in enumerate((-16, -4, 8)):
        levee = levee_pattes if i == 0 else levee_pattes * 0.15
        base = (cx + decalage_x, cy + 9)
        draw.line([base, (base[0] - 11, base[1] + 22 - levee)], fill=COULEUR_PATTE, width=3)
        draw.line([base, (base[0] + 9, base[1] + 22 - levee)], fill=COULEUR_PATTE, width=3)

    # Corps : abdomen, thorax, tête, yeux
    draw.ellipse([cx - 12, cy - 9 + inclinaison, cx + 22, cy + 15 + inclinaison], fill=COULEUR_ABDOMEN)
    draw.ellipse([cx - 21, cy - 13, cx - 2, cy + 7], fill=COULEUR_THORAX)
    draw.ellipse([cx - 30, cy - 9, cx - 15, cy + 6], fill=COULEUR_TETE)
    draw.ellipse([cx - 28, cy - 7, cx - 21, cy], fill=COULEUR_OEIL)


def _images_fuite(n: int) -> list[dict]:
    """Sursaut puis envol rapide en diagonale, ailes battant frénétiquement."""
    frames = []
    for i in range(n):
        t = i / max(1, n - 1)
        battement = 35 * math.sin(t * 50)
        frames.append(
            dict(
                dx=t * 190,
                dy=-t * 100,
                aile_g=155 + battement,
                aile_d=25 - battement,
                pattes=0.0,
            )
        )
    return frames


def _images_interet(n: int) -> list[dict]:
    """Tapotement rythmique des tarses antérieurs, ailes semi-repliées."""
    frames = []
    for i in range(n):
        t = i / max(1, n - 1)
        tap = abs(math.sin(t * 22)) * 11
        frames.append(dict(dx=0.0, dy=0.0, aile_g=150, aile_d=30, pattes=tap))
    return frames


def _images_parade(n: int) -> list[dict]:
    """Extension et vibration d'une aile (chant), léger balancement du corps."""
    frames = []
    for i in range(n):
        t = i / max(1, n - 1)
        vibration = 9 * math.sin(t * 55)
        frames.append(
            dict(
                dx=0.0,
                dy=math.sin(t * 8) * 2.5,
                aile_g=95 + vibration,
                aile_d=25,
                pattes=0.0,
            )
        )
    return frames


def _images_toilettage(n: int) -> list[dict]:
    """Balayage répété des pattes avant sur les yeux."""
    frames = []
    for i in range(n):
        t = i / max(1, n - 1)
        balayage = abs(math.sin(t * 12)) * 9
        frames.append(dict(dx=0.0, dy=0.0, aile_g=158, aile_d=22, pattes=balayage))
    return frames


GENERATEURS_PAR_CATEGORIE = {
    "aversif": _images_fuite,
    "appetitif": _images_interet,
    "courtship": _images_parade,
    "neutre": _images_toilettage,
}


def generer_video_reaction(categorie: str, duree_sec: float, nom_fichier: str) -> None:
    """Génère un fichier mp4 muet montrant la réaction physique de la mouche,
    de durée proche de `duree_sec` (pour se synchroniser avec l'audio)."""
    duree_sec = max(0.4, min(duree_sec, 4.0))
    n_frames = max(8, int(duree_sec * FPS))
    generateur = GENERATEURS_PAR_CATEGORIE.get(categorie, _images_toilettage)
    frames_params = generateur(n_frames)

    proc = subprocess.Popen(
        [
            "ffmpeg", "-y",
            "-f", "rawvideo", "-pix_fmt", "rgb24",
            "-s", f"{LARGEUR}x{HAUTEUR}", "-r", str(FPS),
            "-i", "-",
            "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p",
            "-loglevel", "error",
            nom_fichier,
        ],
        stdin=subprocess.PIPE,
    )

    cx_base, cy_base = LARGEUR * 0.32, HAUTEUR * 0.62
    for params in frames_params:
        img = Image.new("RGB", (LARGEUR, HAUTEUR), COULEUR_FOND)
        draw = ImageDraw.Draw(img, "RGBA")
        _dessiner_mouche(
            draw,
            cx_base + params["dx"],
            cy_base + params["dy"],
            params["aile_g"],
            params["aile_d"],
            params["pattes"],
        )
        proc.stdin.write(img.tobytes())

    proc.stdin.close()
    proc.wait()
