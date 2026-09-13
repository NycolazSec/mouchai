/* Mouche décorative qui erre en permanence sur la page, fuit le curseur, et
 * bourdonne (Web Audio, synthétisé en direct — pas de fichier audio). Purement
 * visuel/sonore (pointer-events: none), indépendant du chat. */
(function () {
  const pet = document.createElement("div");
  pet.className = "fly-pet";
  pet.innerHTML = `
    <div class="fly-pet-direction">
      <div class="fly-pet-rig">
        <span class="fly-pet-wing fly-pet-wing-left"></span>
        <span class="fly-pet-wing fly-pet-wing-right"></span>
        <span class="fly-pet-leg fly-pet-leg-1"></span>
        <span class="fly-pet-leg fly-pet-leg-2"></span>
        <span class="fly-pet-abdomen"></span>
        <span class="fly-pet-thorax"></span>
        <span class="fly-pet-head"><span class="fly-pet-eye"></span></span>
      </div>
    </div>
  `;
  document.body.appendChild(pet);

  const direction = pet.querySelector(".fly-pet-direction");
  const wingL = pet.querySelector(".fly-pet-wing-left");
  const wingR = pet.querySelector(".fly-pet-wing-right");
  const legs = pet.querySelectorAll(".fly-pet-leg");

  // --- Déplacement : errance permanente + fuite au survol du curseur ---
  const MARGE = 30;
  const VITESSE_ERRANCE = 1.4;
  const VITESSE_FUITE_MAX = 9.5;
  const RAYON_FUITE = 130;
  const RAYON_BOURDONNEMENT = 280; // zone plus large où le son commence à monter
  const FRICTION = 0.92;

  let x = window.innerWidth * 0.5;
  let y = window.innerHeight * 0.3;
  let vx = 0;
  let vy = 0;
  let cibleX = x;
  let cibleY = y;
  const souris = { x: -9999, y: -9999, active: false };
  let enFuite = false;
  let etaitEnFuite = false;
  let horloge = 0;

  function nouvelleCible() {
    cibleX = MARGE + Math.random() * (window.innerWidth - 2 * MARGE);
    cibleY = MARGE + Math.random() * (window.innerHeight - 2 * MARGE);
  }
  nouvelleCible();
  setInterval(() => {
    if (!enFuite) nouvelleCible();
  }, 2600);

  window.addEventListener("mousemove", (e) => {
    souris.x = e.clientX;
    souris.y = e.clientY;
    souris.active = true;
  });
  window.addEventListener("mouseleave", () => {
    souris.active = false;
  });
  window.addEventListener("resize", nouvelleCible);

  // --- Son : bourdonnement synthétisé en Web Audio, aucune API/fichier ---
  let ctx = null;
  let gainMaitre, osc, lfo, lfoGain, filtre;

  function initAudio() {
    if (ctx) return;
    const AC = window.AudioContext || window.webkitAudioContext;
    if (!AC) return;
    ctx = new AC();

    gainMaitre = ctx.createGain();
    gainMaitre.gain.value = 0;
    gainMaitre.connect(ctx.destination);

    filtre = ctx.createBiquadFilter();
    filtre.type = "lowpass";
    filtre.frequency.value = 900;
    filtre.connect(gainMaitre);

    osc = ctx.createOscillator();
    osc.type = "sawtooth";
    osc.frequency.value = 190; // ~fréquence de battement d'aile réelle (Hz)
    osc.connect(filtre);

    // LFO qui module le filtre : donne la texture "vrombissante" du vol
    lfo = ctx.createOscillator();
    lfo.frequency.value = 45;
    lfoGain = ctx.createGain();
    lfoGain.gain.value = 350;
    lfo.connect(lfoGain);
    lfoGain.connect(filtre.frequency);

    osc.start();
    lfo.start();
  }

  function debloquerAudio() {
    initAudio();
    if (ctx && ctx.state === "suspended") ctx.resume();
  }
  ["pointerdown", "keydown", "touchstart"].forEach((evt) =>
    window.addEventListener(evt, debloquerAudio, { once: true })
  );

  function majAudio(proximite, dt) {
    if (!ctx) return;
    const t = ctx.currentTime;
    const volumeCible = 0.012 + proximite * 0.075 + (enFuite ? 0.05 : 0);
    const freqCible = enFuite ? 255 : 185 + proximite * 25;
    const lfoCible = enFuite ? 95 : 42 + proximite * 20;

    gainMaitre.gain.setTargetAtTime(volumeCible, t, 0.08);
    osc.frequency.setTargetAtTime(freqCible, t, 0.12);
    lfo.frequency.setTargetAtTime(lfoCible, t, 0.12);

    // Sursaut sonore au moment exact où elle prend peur
    if (enFuite && !etaitEnFuite) {
      osc.frequency.setTargetAtTime(340, t, 0.01);
      gainMaitre.gain.setTargetAtTime(Math.max(volumeCible, 0.14), t, 0.01);
    }
  }

  // --- Boucle d'animation ---
  function step(tsMs) {
    const dt = 16.6; // approx ms par frame, suffisant pour cette animation
    horloge += dt;

    const dxSouris = x - souris.x;
    const dySouris = y - souris.y;
    const distSouris = Math.hypot(dxSouris, dySouris);

    etaitEnFuite = enFuite;
    enFuite = souris.active && distSouris < RAYON_FUITE;
    const proximite = souris.active
      ? Math.max(0, 1 - distSouris / RAYON_BOURDONNEMENT)
      : 0;

    if (enFuite) {
      const force = (1 - distSouris / RAYON_FUITE) * VITESSE_FUITE_MAX;
      const nx = dxSouris / (distSouris || 1);
      const ny = dySouris / (distSouris || 1);
      vx += nx * force * 0.35;
      vy += ny * force * 0.35;
    } else {
      const dxCible = cibleX - x;
      const dyCible = cibleY - y;
      const distCible = Math.hypot(dxCible, dyCible) || 1;
      vx += (dxCible / distCible) * VITESSE_ERRANCE * 0.12;
      vy += (dyCible / distCible) * VITESSE_ERRANCE * 0.12;
    }

    vx *= FRICTION;
    vy *= FRICTION;
    x += vx;
    y += vy;

    x = Math.max(10, Math.min(window.innerWidth - 10, x));
    y = Math.max(10, Math.min(window.innerHeight - 10, y));

    const vitesse = Math.hypot(vx, vy);
    if (vitesse > 0.15) {
      const inclinaison = Math.max(-25, Math.min(25, vy * 2.2));
      const flip = vx < 0 ? -1 : 1;
      direction.style.transform = `scaleX(${flip}) rotate(${flip < 0 ? -inclinaison : inclinaison}deg)`;
    }

    // Battement d'ailes : rapide en vol normal, frénétique en fuite
    const freqFlap = enFuite ? 42 : 16;
    const phase = Math.sin((horloge / 1000) * freqFlap * Math.PI * 2);
    const angleBase = enFuite ? 55 : 38;
    wingL.style.transform = `rotate(${-18 - angleBase * (phase * 0.5 + 0.5)}deg)`;
    wingR.style.transform = `rotate(${18 + angleBase * (phase * 0.5 + 0.5)}deg)`;

    // Pattes : légère oscillation pendant l'errance
    if (!enFuite) {
      const legPhase = Math.sin((horloge / 1000) * 6 * Math.PI * 2);
      legs.forEach((leg, i) => {
        leg.style.transform = `rotate(${legPhase * (i === 0 ? 6 : -6)}deg)`;
      });
    }

    majAudio(proximite, dt);

    pet.style.transform = `translate(${x}px, ${y}px)`;
    requestAnimationFrame(step);
  }

  requestAnimationFrame(step);
})();
