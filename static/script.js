const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const statsText = document.getElementById("stats-text");
const modePicker = document.getElementById("mode-picker");

// --- Mode de réflexion (rapide / réfléchi), mémorisé entre les visites ---
let modeActuel = localStorage.getItem("mouche-mode") || "reflechi";

function appliquerMode(mode) {
  modeActuel = mode;
  localStorage.setItem("mouche-mode", mode);
  modePicker.querySelectorAll(".mode-btn").forEach((b) => {
    b.classList.toggle("is-active", b.dataset.mode === mode);
  });
}

modePicker.addEventListener("click", (e) => {
  const btn = e.target.closest(".mode-btn");
  if (btn) appliquerMode(btn.dataset.mode);
});
appliquerMode(modeActuel);

// --- Défilement : on ne force le bas que si l'utilisateur y est déjà ---
function estEnBas(tolerance = 90) {
  return chat.scrollHeight - chat.scrollTop - chat.clientHeight < tolerance;
}

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
}

function suivreLeBas(etaitEnBas) {
  if (etaitEnBas) scrollToBottom();
}

function formatterStats(s) {
  return `${s.echanges_en_memoire} échange${s.echanges_en_memoire > 1 ? "s" : ""} · ${s.mots_appris} mot${s.mots_appris > 1 ? "s" : ""} appris · 👍${s.total_feedback_positif} 👎${s.total_feedback_negatif}`;
}

async function rafraichirStats() {
  try {
    const res = await fetch("/api/stats");
    if (!res.ok) return;
    const s = await res.json();
    statsText.textContent = formatterStats(s);
    const btnRestaurer = document.getElementById("btn-restaurer-principale");
    if (btnRestaurer) btnRestaurer.disabled = !s.a_une_principale;
  } catch (err) {
    statsText.textContent = "mémoire indisponible";
  }
}

rafraichirStats();

function ajouterMessageUtilisateur(texte) {
  const div = document.createElement("div");
  div.className = "msg user";
  div.innerHTML = `
    <div class="msg-avatar">🧑</div>
    <div class="msg-body">
      <div class="bubble"><div class="bubble-text"></div></div>
    </div>
  `;
  div.querySelector(".bubble-text").textContent = texte;
  chat.appendChild(div);
  scrollToBottom();
}

const ETAPES_REFLEXION = [
  { nom: "ORN", texte: "perception du stimulus par les récepteurs olfactifs…" },
  { nom: "PN", texte: "relais vers le lobe antennaire…" },
  { nom: "KC", texte: "codage épars dans le corps pédonculé…" },
  { nom: "MBON", texte: "lecture du compartiment de sortie…" },
  { nom: "mémoire", texte: "recherche d'un échange similaire dans la mémoire…" },
];

function ajouterMessageMoucheEnAttente(mode) {
  // En mode rapide, la mouche ne fait pas de rappel mémoire : l'animation ne
  // montre donc que les étages réellement parcourus.
  const etapes = mode === "rapide" ? ETAPES_REFLEXION.slice(0, 4) : ETAPES_REFLEXION;

  const div = document.createElement("div");
  div.className = "msg fly";
  div.innerHTML = `
    <div class="msg-avatar">🪰</div>
    <div class="msg-body">
      <div class="bubble">
        <div class="thinking">
          <div class="thinking-stages">
            ${etapes
              .map(
                (e, i) =>
                  `<span class="stage" data-i="${i}">${e.nom}</span>` +
                  (i < etapes.length - 1 ? '<span class="stage-arrow">→</span>' : "")
              )
              .join("")}
          </div>
          <div class="thinking-status"></div>
        </div>
      </div>
    </div>
  `;
  chat.appendChild(div);
  scrollToBottom();

  const stages = div.querySelectorAll(".stage");
  const statusEl = div.querySelector(".thinking-status");
  let i = 0;

  const majEtape = () => {
    stages.forEach((s) => s.classList.remove("active", "done"));
    stages.forEach((s, idx) => {
      if (idx < i) s.classList.add("done");
      if (idx === i) s.classList.add("active");
    });
    statusEl.textContent = etapes[i].texte;
    statusEl.classList.remove("fade");
    void statusEl.offsetWidth; // relance l'animation de fondu
    statusEl.classList.add("fade");
    i = (i + 1) % etapes.length;
  };
  majEtape();
  const intervalle = setInterval(majEtape, mode === "rapide" ? 200 : 480);

  div._arreterReflexion = () => clearInterval(intervalle);
  return div;
}

// --- Rendu progressif du texte, comme sur les interfaces IA ---
function ecrireProgressivement(element, texte, vitesse) {
  return new Promise((resolve) => {
    element.textContent = "";
    element.classList.add("curseur");
    let position = 0;

    const ecrire = () => {
      const etait = estEnBas();
      // On avance par petits paquets : plus fluide et moins coûteux qu'un
      // caractère par image.
      position = Math.min(texte.length, position + vitesse);
      element.textContent = texte.slice(0, position);
      suivreLeBas(etait);

      if (position < texte.length) {
        setTimeout(ecrire, 16);
      } else {
        element.classList.remove("curseur");
        resolve();
      }
    };
    ecrire();
  });
}

async function remplirReponseMouche(div, data) {
  if (div._arreterReflexion) div._arreterReflexion();
  const bubble = div.querySelector(".bubble");

  // Le texte de la réponse est inséré via textContent (jamais innerHTML) :
  // même si un ancien message contenait du HTML, il ne peut pas s'exécuter.
  bubble.innerHTML = `
    <div class="bubble-text"></div>
    <div class="reponse-media" hidden>
      <video class="fly-video" muted playsinline></video>
      <div class="reaction-bar">
        <div class="sound-badge">
          <span class="bars"><span></span><span></span><span></span><span></span></span>
          réaction en cours
        </div>
        <button type="button" class="replay-btn" title="Revoir la réaction">↺ Rejouer</button>
      </div>
      <audio class="fly-audio"></audio>
      <div class="feedback-bar">
        <span class="feedback-label">Cette réaction te semble juste ?</span>
        <button type="button" class="feedback-btn" data-note="1" title="Bonne réaction, renforce cette association">👍</button>
        <button type="button" class="feedback-btn" data-note="-1" title="Mauvaise réaction, affaiblit cette association">👎</button>
        <span class="feedback-confirm" hidden></span>
      </div>
      <details class="tech-details">
        <summary>Détails du circuit neuronal</summary>
        <div class="tech-body">
          <div class="trace"></div>
          <span class="tech-posture"></span>
          <span class="tech-chimie"></span>
          <span class="tech-description"></span>
          <span class="tech-mode"></span>
        </div>
      </details>
    </div>
  `;

  const texteEl = bubble.querySelector(".bubble-text");
  const media = bubble.querySelector(".reponse-media");
  const video = bubble.querySelector(".fly-video");
  const audio = bubble.querySelector(".fly-audio");
  const badge = bubble.querySelector(".sound-badge");

  video.src = data.video_url;
  audio.src = data.audio_url;

  bubble.querySelector(".trace").textContent = data.langage_mouche;
  bubble.querySelector(".tech-posture").textContent = `Posture : ${data.posture}`;
  bubble.querySelector(".tech-chimie").textContent = `Chimiosensation : ${data.chimie}`;
  bubble.querySelector(".tech-description").textContent = data.description;
  const associations = (data.associations || [])
    .map((a) => `${a.mot}≈${a.proche} (${a.proximite})`)
    .join(", ");
  bubble.querySelector(".tech-mode").textContent =
    `Mode ${data.mode === "rapide" ? "rapide" : "réfléchi"} · ` +
    `${data.candidats_evalues} réponse(s) évaluée(s)` +
    (data.etat_interne ? ` · état : ${data.etat_interne.etiquette}` : "") +
    (data.rappel_trouve ? " · rappel mémoire" : "") +
    (associations ? ` · associations : ${associations}` : "") +
    (data.mots_decouverts && data.mots_decouverts.length
      ? ` · mots découverts : ${data.mots_decouverts.join(", ")}`
      : "");

  const lancerLecture = () => {
    video.currentTime = 0;
    audio.currentTime = 0;
    video.play().catch(() => {});
    audio.play().catch(() => {});
    badge.style.display = "inline-flex";
  };

  // La vidéo change la hauteur de la bulle en arrivant : sans ce recalage,
  // la fin du message se retrouvait sous la ligne de flottaison.
  video.addEventListener("loadeddata", () => {
    const etait = estEnBas();
    lancerLecture();
    suivreLeBas(etait);
  }, { once: true });

  video.addEventListener("ended", () => {
    badge.style.display = "none";
  });

  bubble.querySelector(".replay-btn").addEventListener("click", lancerLecture);

  const boutonsFeedback = bubble.querySelectorAll(".feedback-btn");
  const confirmation = bubble.querySelector(".feedback-confirm");
  boutonsFeedback.forEach((btn) => {
    btn.addEventListener("click", async () => {
      boutonsFeedback.forEach((b) => (b.disabled = true));
      try {
        const res = await fetch("/api/feedback", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            echange_id: data.echange_id,
            note: parseInt(btn.dataset.note, 10),
          }),
        });
        const stats = await res.json();
        if (res.ok) {
          if (stats.appris) {
            confirmation.textContent = stats.mots_touches.length
              ? `🧠 mémorisé (+ appris : ${stats.mots_touches.join(", ")})`
              : "🧠 association renforcée";
          } else {
            confirmation.textContent = stats.mots_touches.length
              ? `🧠 corrigé (oublié : ${stats.mots_touches.join(", ")})`
              : "🧠 association affaiblie, je corrige";
          }
          confirmation.hidden = false;
          statsText.textContent = formatterStats(stats);
        } else {
          confirmation.textContent = "⚠️ feedback non pris en compte";
          confirmation.hidden = false;
        }
      } catch (err) {
        confirmation.textContent = "⚠️ feedback non pris en compte";
        confirmation.hidden = false;
      }
    });
  });

  await ecrireProgressivement(
    texteEl,
    data.message_mouche,
    data.mode === "rapide" ? 4 : 2
  );

  const etait = estEnBas();
  media.hidden = false;
  suivreLeBas(etait);
}

function remplirErreurMouche(div, message) {
  if (div._arreterReflexion) div._arreterReflexion();
  const bubble = div.querySelector(".bubble");
  bubble.innerHTML = '<div class="bubble-text error-text"></div>';
  bubble.querySelector(".bubble-text").textContent = `⚠️ ${message}`;
}

function attendre(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// --- Composer façon Claude : textarea auto-extensible, Entrée pour envoyer ---
function redimensionnerInput() {
  input.style.height = "auto";
  input.style.height = Math.min(input.scrollHeight, 200) + "px";
}

function majEtatBouton() {
  sendBtn.disabled = input.value.trim().length === 0;
}

input.addEventListener("input", () => {
  redimensionnerInput();
  majEtatBouton();
});

input.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
    e.preventDefault();
    form.requestSubmit();
  }
});

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  const texte = input.value.trim();
  if (!texte) return;

  const mode = modeActuel;
  ajouterMessageUtilisateur(texte);
  input.value = "";
  redimensionnerInput();
  input.focus();
  sendBtn.disabled = true;

  const divMouche = ajouterMessageMoucheEnAttente(mode);
  // Le serveur répond en quelques dizaines de ms : sans plancher, l'animation
  // de réflexion serait invisible. Le mode rapide en garde le strict minimum.
  const dureeMin = mode === "rapide" ? 450 : 1900;

  try {
    const [res] = await Promise.all([
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: texte, mode }),
      }),
      attendre(dureeMin),
    ]);
    const data = await res.json();

    if (!res.ok) {
      remplirErreurMouche(divMouche, data.erreur || "Erreur inconnue.");
    } else {
      await remplirReponseMouche(divMouche, data);
      rafraichirStats();
    }
  } catch (err) {
    remplirErreurMouche(divMouche, "Impossible de contacter le serveur.");
  } finally {
    majEtatBouton();
  }
});

// --- Menu "Cerveau de la mouche" : export / import / mouche principale ---
const menuBtn = document.getElementById("menu-btn");
const menuPanel = document.getElementById("menu-panel");
const menuMsg = document.getElementById("menu-msg");
const inputImport = document.getElementById("input-import");

function afficherMenuMsg(texte, estErreur = false) {
  menuMsg.textContent = texte;
  menuMsg.hidden = false;
  menuMsg.classList.toggle("menu-msg-erreur", estErreur);
  clearTimeout(afficherMenuMsg._t);
  afficherMenuMsg._t = setTimeout(() => {
    menuMsg.hidden = true;
  }, 4000);
}

menuBtn.addEventListener("click", (e) => {
  e.stopPropagation();
  menuPanel.hidden = !menuPanel.hidden;
});

document.addEventListener("click", (e) => {
  if (!menuPanel.hidden && !menuPanel.contains(e.target) && e.target !== menuBtn) {
    menuPanel.hidden = true;
  }
});

document.getElementById("btn-export").addEventListener("click", () => {
  window.location.href = "/api/export";
  afficherMenuMsg("⬇️ Téléchargement lancé");
});

inputImport.addEventListener("change", async () => {
  const fichier = inputImport.files[0];
  if (!fichier) return;

  const donnees = new FormData();
  donnees.append("fichier", fichier);

  try {
    const res = await fetch("/api/import", { method: "POST", body: donnees });
    const resJson = await res.json();
    if (!res.ok) {
      afficherMenuMsg(`⚠️ ${resJson.erreur || "Import refusé."}`, true);
    } else {
      afficherMenuMsg("✅ Cerveau importé, mouche mise à jour");
      statsText.textContent = formatterStats(resJson);
      document.getElementById("btn-restaurer-principale").disabled = !resJson.a_une_principale;
    }
  } catch (err) {
    afficherMenuMsg("⚠️ Échec de l'import", true);
  }
  inputImport.value = "";
});

document.getElementById("btn-restaurer-principale").addEventListener("click", async () => {
  try {
    const res = await fetch("/api/principale/restaurer", { method: "POST" });
    const resJson = await res.json();
    if (!res.ok) {
      afficherMenuMsg(`⚠️ ${resJson.erreur || "Échec de la restauration."}`, true);
    } else {
      afficherMenuMsg("↺ Mouche réinitialisée à la version principale");
      statsText.textContent = formatterStats(resJson);
    }
  } catch (err) {
    afficherMenuMsg("⚠️ Échec de la restauration", true);
  }
});

document.getElementById("form-enseigner").addEventListener("submit", async (e) => {
  e.preventDefault();
  const motInput = document.getElementById("enseigner-mot");
  const categorie = document.getElementById("enseigner-categorie").value;
  const mot = motInput.value.trim();
  if (!mot) return;

  try {
    const res = await fetch("/api/enseigner", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mot, categorie }),
    });
    const resJson = await res.json();
    if (!res.ok) {
      afficherMenuMsg(`⚠️ ${resJson.erreur || "Échec de l'enseignement."}`, true);
    } else {
      afficherMenuMsg(`✅ « ${resJson.mot} » enseigné`);
      statsText.textContent = formatterStats(resJson);
      motInput.value = "";
    }
  } catch (err) {
    afficherMenuMsg("⚠️ Échec de l'enseignement", true);
  }
});
