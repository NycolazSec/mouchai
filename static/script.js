const chat = document.getElementById("chat");
const form = document.getElementById("composer");
const input = document.getElementById("prompt-input");
const sendBtn = document.getElementById("send-btn");
const statsText = document.getElementById("stats-text");

function scrollToBottom() {
  chat.scrollTop = chat.scrollHeight;
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
];

function ajouterMessageMoucheEnAttente() {
  const div = document.createElement("div");
  div.className = "msg fly";
  div.innerHTML = `
    <div class="msg-avatar">🪰</div>
    <div class="msg-body">
      <div class="bubble">
        <div class="thinking">
          <div class="thinking-stages">
            ${ETAPES_REFLEXION.map(
              (e, i) =>
                `<span class="stage" data-i="${i}">${e.nom}</span>` +
                (i < ETAPES_REFLEXION.length - 1 ? '<span class="stage-arrow">→</span>' : "")
            ).join("")}
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
    statusEl.textContent = ETAPES_REFLEXION[i].texte;
    statusEl.classList.remove("fade");
    void statusEl.offsetWidth; // relance l'animation de fondu
    statusEl.classList.add("fade");
    i = (i + 1) % ETAPES_REFLEXION.length;
  };
  majEtape();
  const intervalle = setInterval(majEtape, 480);

  div.dataset.arreterReflexion = "1";
  div._arreterReflexion = () => clearInterval(intervalle);

  return div;
}

function remplirReponseMouche(div, data) {
  if (div._arreterReflexion) div._arreterReflexion();
  const bubble = div.querySelector(".bubble");
  bubble.innerHTML = `
    <div class="bubble-text">${data.message_mouche}</div>
    <video class="fly-video" src="${data.video_url}" muted playsinline></video>
    <div class="reaction-bar">
      <div class="sound-badge">
        <span class="bars"><span></span><span></span><span></span><span></span></span>
        réaction en cours
      </div>
      <button type="button" class="replay-btn" title="Revoir la réaction">↺ Rejouer</button>
    </div>
    <audio class="fly-audio" src="${data.audio_url}"></audio>
    <div class="feedback-bar">
      <span class="feedback-label">Cette réaction te semble juste ?</span>
      <button type="button" class="feedback-btn" data-note="1" title="Bonne réaction, renforce cette association">👍</button>
      <button type="button" class="feedback-btn" data-note="-1" title="Mauvaise réaction, affaiblit cette association">👎</button>
      <span class="feedback-confirm" hidden></span>
    </div>
    <details class="tech-details">
      <summary>Détails du circuit neuronal</summary>
      <div class="tech-body">
        <div class="trace">${data.langage_mouche}</div>
        <span><b>Posture :</b> ${data.posture}</span>
        <span><b>Chimiosensation :</b> ${data.chimie}</span>
        <span>${data.description}</span>
      </div>
    </details>
  `;

  const video = bubble.querySelector(".fly-video");
  const audio = bubble.querySelector(".fly-audio");
  const badge = bubble.querySelector(".sound-badge");

  const lancerLecture = () => {
    video.currentTime = 0;
    audio.currentTime = 0;
    video.play().catch(() => {});
    audio.play().catch(() => {});
    badge.style.display = "inline-flex";
  };

  if (video.readyState >= 2) {
    lancerLecture();
  } else {
    video.addEventListener("loadeddata", lancerLecture, { once: true });
  }

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

  scrollToBottom();
}

function remplirErreurMouche(div, message) {
  if (div._arreterReflexion) div._arreterReflexion();
  div.querySelector(".bubble").innerHTML = `<div class="bubble-text error-text">⚠️ ${message}</div>`;
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

  ajouterMessageUtilisateur(texte);
  input.value = "";
  redimensionnerInput();
  input.focus();
  sendBtn.disabled = true;

  const divMouche = ajouterMessageMoucheEnAttente();
  const DUREE_MIN_REFLEXION = 1900; // laisse le temps de voir l'animation, même si la réponse est instantanée

  try {
    const [res] = await Promise.all([
      fetch("/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: texte }),
      }),
      attendre(DUREE_MIN_REFLEXION),
    ]);
    const data = await res.json();

    if (!res.ok) {
      remplirErreurMouche(divMouche, data.erreur || "Erreur inconnue.");
    } else {
      remplirReponseMouche(divMouche, data);
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
