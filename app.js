/* ==========================================================================
   Jarvis · frontend móvil
   Todo el contacto con el servidor está en el objeto `api` (sección 2).
   En modo demo responde con datos simulados; en modo real llama a:

     POST /api/chat    {text}   -> {reply, actions?, confirm?}
         reply    texto que Jarvis dice
         actions  [{label, detail?, status?: "ok"|"error"}]  lo que ya ha ejecutado en el PC
         confirm  {id, text}  acción peligrosa que necesita tu visto bueno (apagar, reiniciar…)
     GET  /api/stats            -> {cpu, ram, temp, disk, uptime}
     POST /api/scene   {id}     -> {ok, message}
     POST /api/action  {id}     -> {ok, message}
     POST /api/exec    {cmd}    -> {output, error?}

   Todas llevan la cabecera  Authorization: Bearer <token>
   ========================================================================== */

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const vibrate = (ms = 10) => navigator.vibrate && navigator.vibrate(ms);
const TAU = Math.PI * 2;

/* ==========================================================================
   1. Configuración (se guarda en el móvil)
   ========================================================================== */
const CFG_KEY = "jarvis-cfg";
const HIST_KEY = "jarvis-chat";

const cfg = Object.assign({ demo: true, url: "", token: "", tts: false }, readJSON(CFG_KEY, {}));

function readJSON(key, fallback) {
  try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
}
function writeJSON(key, value) {
  try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* almacenamiento no disponible */ }
}

/* ==========================================================================
   2. API (demo o real)
   ========================================================================== */
const demoStats = { cpu: 14, ram: 38, temp: 42, disk: 61, uptime: 12 * 86400 + 3 * 3600 + 41 * 60 };

function walk(value, step, min, max) {
  return Math.round(Math.min(max, Math.max(min, value + (Math.random() - 0.5) * step)));
}

async function call(path, method = "GET", body) {
  const res = await fetch(cfg.url.replace(/\/$/, "") + path, {
    method,
    headers: { "Content-Type": "application/json", Authorization: "Bearer " + cfg.token },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) throw new Error("El servidor respondió " + res.status);
  return res.json();
}

const api = {
  async chat(text) {
    if (!cfg.demo) return call("/api/chat", "POST", { text });
    await sleep(800 + Math.random() * 500);
    return demoUnderstand(text);
  },

  async stats() {
    if (!cfg.demo) return call("/api/stats");
    demoStats.cpu = walk(demoStats.cpu, 18, 3, 95);
    demoStats.ram = walk(demoStats.ram, 4, 25, 80);
    demoStats.temp = walk(demoStats.temp, 4, 35, 78);
    demoStats.uptime += 4;
    return { ...demoStats };
  },

  async scene(id) {
    if (!cfg.demo) return call("/api/scene", "POST", { id });
    await sleep(700);
    return { ok: true, message: "Escena «" + id + "» activada (simulado)" };
  },

  async action(id) {
    if (!cfg.demo) return call("/api/action", "POST", { id });
    await sleep(500);
    return { ok: true, message: "Acción «" + id + "» enviada (simulado)" };
  },

  async exec(cmd) {
    if (!cfg.demo) return call("/api/exec", "POST", { cmd });
    await sleep(250);
    return demoExec(cmd);
  },
};

// "Entiende" órdenes sencillas para poder probar la interfaz sin servidor.
function demoUnderstand(text) {
  const t = text.toLowerCase();
  const s = demoStats;
  const cap = (x) => x.charAt(0).toUpperCase() + x.slice(1);

  if (/apaga|reinicia/.test(t)) {
    const reboot = /reinicia/.test(t);
    return {
      reply: "Eso es delicado. Necesito que lo confirmes tú.",
      confirm: {
        id: reboot ? "reboot" : "shutdown",
        text: reboot ? "¿Reiniciar el PC? Se cerrarán las apps abiertas." : "¿Apagar el PC? No podrás volver a encenderlo desde el móvil.",
      },
    };
  }
  if (/gaming|jugar|jugamos/.test(t))
    return { reply: "Escena Gaming lista. A jugar.", actions: [
      { label: "Epic Games", detail: "Pantalla 1 · primer plano" },
      { label: "Discord", detail: "Pantalla 2" },
      { label: "Spotify", detail: "Pantalla 3" },
    ] };
  if (/trabajo|trabajar|estudiar/.test(t))
    return { reply: "Modo trabajo activado.", actions: [
      { label: "VS Code", detail: "Pantalla 1" },
      { label: "Navegador", detail: "Pantalla 2" },
      { label: "Obsidian", detail: "Pantalla 3" },
    ] };
  if (/modo noche|dormir/.test(t))
    return { reply: "Modo noche activado. Descansa.", actions: [
      { label: "Brillo al 15 %", detail: "Todas las pantallas" },
      { label: "Notificaciones silenciadas" },
    ] };
  if (/captura|pantallazo/.test(t))
    return { reply: "Captura hecha.", actions: [{ label: "Captura de pantalla", detail: "Guardada en Imágenes" }] };
  if (/bloquea/.test(t))
    return { reply: "PC bloqueado.", actions: [{ label: "Bloquear sesión", detail: "thinkcentre-m920q" }] };
  if (/volumen|silencia|mute/.test(t))
    return { reply: "Hecho.", actions: [{ label: /silencia|mute/.test(t) ? "Audio silenciado" : "Volumen ajustado", detail: "Salida principal" }] };

  const open = t.match(/(?:abre|abrir|ábreme|lanza|inicia)\s+(?:el |la |los |las )?(.+)/);
  if (open) {
    const app = cap(open[1].replace(/[.?!]+$/, "").trim());
    return { reply: "Abriendo " + app + ".", actions: [{ label: "Abrir " + app, detail: "Pantalla principal" }] };
  }
  if (/estado|cpu|ram|temperatura|cómo está|como esta/.test(t))
    return { reply: "Todo en orden. CPU al " + s.cpu + " %, memoria al " + s.ram + " % y " + s.temp + " grados. El disco va al " + s.disk + " %." };
  if (/hora/.test(t))
    return { reply: "Son las " + new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" }) + "." };
  if (/hola|buenas|hey/.test(t)) return { reply: "Hola Alex. Aquí Jarvis, a tu servicio." };
  if (/gracias/.test(t)) return { reply: "Para eso estoy." };

  return { reply: "Estoy en modo demo, así que no puedo ejecutar eso todavía. Cuando conectemos el servidor, lo haré en tu PC." };
}

function demoExec(cmd) {
  const c = cmd.trim();
  const now = new Date();
  const table = {
    uptime: " " + now.toLocaleTimeString("es-ES") + " up 12 days, 3:41, 1 user, load average: 0.42, 0.38, 0.35",
    "free -h": "               total        used        free      shared  buff/cache   available\nMem:            15Gi       5.8Gi       4.1Gi       312Mi       5.2Gi       9.0Gi\nSwap:          2.0Gi          0B       2.0Gi",
    "df -h": "Filesystem      Size  Used Avail Use% Mounted on\n/dev/nvme0n1p2  233G  142G   79G  65% /\n/dev/nvme0n1p1  511M  6.1M  505M   2% /boot/efi",
    ls: "bridge  jarvis  logs  models  scripts",
    "ollama list": "NAME         ID              SIZE      MODIFIED\ngemma3:4b    a2af6cc3eb7f    3.3 GB    2 weeks ago",
    whoami: "jarvis",
    hostname: "thinkcentre-m920q",
    date: now.toString(),
    help: "Comandos de la demo: uptime, free -h, df -h, ls, ollama list, whoami, hostname, date, clear",
  };
  if (c in table) return { output: table[c] };
  return { output: "", error: "bash: " + c.split(" ")[0] + ": comando no encontrado" };
}

/* ==========================================================================
   3. Pestañas, avisos y confirmaciones
   ========================================================================== */
const app = $("#app");

function showView(name) {
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + name));
  $$(".tab").forEach((t) => {
    const on = t.dataset.view === name;
    t.classList.toggle("active", on);
    t.setAttribute("aria-selected", on);
  });
  if (name === "control") refreshStats();
  vibrate(6);
}
$$(".tab").forEach((t) => t.addEventListener("click", () => showView(t.dataset.view)));

let toastTimer;
function toast(text) {
  const el = $("#toast");
  el.textContent = text;
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), 2400);
}

const confirmDialog = $("#confirmDialog");
function askConfirm(text) {
  return new Promise((resolve) => {
    $("#confirmText").textContent = text;
    confirmDialog.returnValue = "";
    confirmDialog.addEventListener("close", () => resolve(confirmDialog.returnValue === "ok"), { once: true });
    confirmDialog.showModal();
  });
}

/* ==========================================================================
   4. El orbe (canvas 2D con proyección 3D)
   ========================================================================== */
const orb = (() => {
  const canvas = $("#orb");
  const ctx = canvas.getContext("2d");
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // Esfera de partículas (espiral de Fibonacci). Cada punto nace disperso y se ensambla al arrancar.
  const N = 420;
  const pts = [];
  for (let i = 0; i < N; i++) {
    const y = 1 - (i / (N - 1)) * 2;
    const r = Math.sqrt(1 - y * y);
    const th = Math.PI * (3 - Math.sqrt(5)) * i;
    pts.push({
      x: Math.cos(th) * r, y, z: Math.sin(th) * r,
      sx: (Math.random() * 2 - 1) * 2.6, sy: (Math.random() * 2 - 1) * 2.6, sz: (Math.random() * 2 - 1) * 2.6,
    });
  }

  // Conexiones: cada punto se une a sus 2 vecinos más cercanos (se calcula una sola vez).
  const edges = [];
  const seen = new Set();
  for (let i = 0; i < N; i++) {
    const best = [];
    for (let j = 0; j < N; j++) {
      if (j === i) continue;
      const dx = pts[i].x - pts[j].x, dy = pts[i].y - pts[j].y, dz = pts[i].z - pts[j].z;
      const d = dx * dx + dy * dy + dz * dz;
      if (best.length < 2 || d < best[best.length - 1][1]) {
        best.push([j, d]);
        best.sort((a, b) => a[1] - b[1]);
        if (best.length > 2) best.pop();
      }
    }
    for (const [j] of best) {
      const key = i < j ? i * N + j : j * N + i;
      if (!seen.has(key)) { seen.add(key); edges.push([i, j]); }
    }
  }

  const params = {
    idle:      { color: [61, 227, 255],  spin: 0.00018, energy: 0.025, ring: 1 },
    listening: { color: [125, 255, 234], spin: 0.00028, energy: 0.05,  ring: 1.6 },
    thinking:  { color: [139, 123, 255], spin: 0.0009,  energy: 0.05,  ring: 5 },
    executing: { color: [255, 184, 77],  spin: 0.0005,  energy: 0.05,  ring: 2.6 },
    speaking:  { color: [61, 227, 255],  spin: 0.00032, energy: 0.04,  ring: 1.4 },
    error:     { color: [255, 93, 115],  spin: 0.0001,  energy: 0.06,  ring: 0.6 },
  };

  let state = "idle";
  let color = [...params.idle.color];
  let angle = 0, spinVel = 0, ringAngle = 0;
  let level = 0, levelTarget = 0, pulseV = 0;
  let last = 0, t0 = 0;
  let w = 0, h = 0, dpr = 1;
  const X = new Float32Array(N), Y = new Float32Array(N), Z = new Float32Array(N), B = new Uint8Array(N);

  function resize() {
    const r = canvas.getBoundingClientRect();
    dpr = Math.min(window.devicePixelRatio || 1, 2);
    w = r.width; h = r.height;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
  }
  new ResizeObserver(resize).observe(canvas);

  // Anillo 3D inclinado. Devuelve la posición del punto en la fase `phase` para poder poner un satélite.
  function ring(cx, cy, R, m, tiltX, tiltZ, rot, alpha, rgb, width, dash, phase) {
    const M = 96;
    const cX = Math.cos(tiltX), sX = Math.sin(tiltX), cZ = Math.cos(tiltZ), sZ = Math.sin(tiltZ);
    const px = new Array(M + 1), py = new Array(M + 1), pz = new Array(M + 1);
    for (let i = 0; i <= M; i++) {
      const a = rot + (i / M) * TAU;
      const x = Math.cos(a) * m, z = Math.sin(a) * m;
      const y1 = -z * sX, z1 = z * cX;
      const x2 = x * cZ - y1 * sZ, y2 = x * sZ + y1 * cZ;
      const zn = z1 / m;
      const persp = 1 / (1 - zn * 0.26);
      px[i] = cx + x2 * R * persp; py[i] = cy + y2 * R * persp; pz[i] = zn;
    }
    const front = new Path2D(), back = new Path2D();
    for (let i = 0; i < M; i++) {
      const p = (pz[i] + pz[i + 1]) / 2 >= 0 ? front : back;
      p.moveTo(px[i], py[i]); p.lineTo(px[i + 1], py[i + 1]);
    }
    ctx.setLineDash(dash || []);
    ctx.lineWidth = width;
    ctx.strokeStyle = `rgba(${rgb},${alpha * 0.2})`; ctx.stroke(back);
    ctx.strokeStyle = `rgba(${rgb},${alpha})`; ctx.stroke(front);
    ctx.setLineDash([]);
    if (phase !== undefined) {
      const k = Math.floor(((phase % TAU + TAU) % TAU) / TAU * M);
      return [px[k], py[k], pz[k]];
    }
  }

  function frame(t) {
    requestAnimationFrame(frame);
    if (!w || !h) return;
    if (!t0) t0 = t;
    const dt = Math.min(48, t - last || 16);
    last = t;

    const P = params[state];
    for (let k = 0; k < 3; k++) color[k] += (P.color[k] - color[k]) * 0.07;
    const rgb = color.map(Math.round).join(",");

    const assemble = reduced ? 1 : Math.min(1, (t - t0) / 2100);
    const e = 1 - Math.pow(1 - assemble, 3);

    levelTarget *= 0.93;
    level += (levelTarget - level) * 0.25;
    pulseV *= 0.92;

    const energy = P.energy + level * 0.24 + pulseV * 0.1 + (state === "idle" ? Math.sin(t / 1200) * 0.012 : 0);
    const slow = reduced ? 0.3 : 1;
    spinVel *= 0.95;
    angle += (P.spin * slow + spinVel) * dt;
    ringAngle += P.ring * 0.0006 * slow * dt;
    const tilt = 0.38 + Math.sin(t / 4200) * 0.05;

    const cx = w / 2, cy = h / 2;
    const R = Math.min(w, h) * 0.255 * (1 + Math.sin(t / 1300) * 0.012 + pulseV * 0.05);

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    ctx.globalCompositeOperation = "lighter";

    // Resplandor
    const g = ctx.createRadialGradient(cx, cy, R * 0.15, cx, cy, R * 2.3);
    g.addColorStop(0, `rgba(${rgb},${0.24 + energy * 1.2})`);
    g.addColorStop(0.5, `rgba(${rgb},${0.07 + energy * 0.4})`);
    g.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, w, h);

    // Proyección de la esfera
    const cosA = Math.cos(angle), sinA = Math.sin(angle), cosT = Math.cos(tilt), sinT = Math.sin(tilt);
    for (let i = 0; i < N; i++) {
      const p = pts[i];
      const x0 = p.x * e + p.sx * (1 - e), y0 = p.y * e + p.sy * (1 - e), z0 = p.z * e + p.sz * (1 - e);
      const x1 = x0 * cosA + z0 * sinA, z1 = -x0 * sinA + z0 * cosA;
      const y2 = y0 * cosT - z1 * sinT, z2 = y0 * sinT + z1 * cosT;
      const wob = 1 + energy * Math.sin(i * 1.7 + t / 170);
      const persp = 1 / (1 - Math.max(-1.5, Math.min(1.5, z2)) * 0.28);
      X[i] = cx + x1 * R * wob * persp;
      Y[i] = cy + y2 * R * wob * persp;
      const d = Math.min(1, Math.max(0, (z2 + 1) / 2));
      Z[i] = d;
      B[i] = Math.min(4, (d * 5) | 0);
    }

    // Anillos de fondo
    ring(cx, cy, R, 1.34, 1.15, 0.5, ringAngle, 0.5 * e, rgb, 1.1);

    // Red de conexiones (solo la cara visible)
    ctx.lineWidth = 0.6;
    ctx.strokeStyle = `rgba(${rgb},${(0.13 + energy * 0.9) * e})`;
    ctx.beginPath();
    for (let k = 0; k < edges.length; k++) {
      const a = edges[k][0], b = edges[k][1];
      if (Z[a] > 0.42 && Z[b] > 0.42) { ctx.moveTo(X[a], Y[a]); ctx.lineTo(X[b], Y[b]); }
    }
    ctx.stroke();

    // Partículas, agrupadas por profundidad para dibujarlas en 5 pasadas
    for (let b = 0; b < 5; b++) {
      ctx.beginPath();
      const rad = 0.7 + b * 0.45;
      for (let i = 0; i < N; i++) {
        if (B[i] !== b) continue;
        ctx.moveTo(X[i] + rad, Y[i]);
        ctx.arc(X[i], Y[i], rad, 0, TAU);
      }
      ctx.fillStyle = `rgba(${rgb},${0.14 + b * 0.2})`;
      ctx.fill();
    }

    // Núcleo
    const cr = R * (0.3 + energy * 0.9);
    const core = ctx.createRadialGradient(cx, cy, 0, cx, cy, cr * 2.2);
    core.addColorStop(0, "rgba(255,255,255,0.95)");
    core.addColorStop(0.18, `rgba(${rgb},0.8)`);
    core.addColorStop(1, `rgba(${rgb},0)`);
    ctx.fillStyle = core;
    ctx.beginPath(); ctx.arc(cx, cy, cr * 2.2, 0, TAU); ctx.fill();

    // Anillos de primer plano + satélite
    const s1 = ring(cx, cy, R, 1.2, 0.42, -0.35, -ringAngle * 1.3, 0.75 * e, rgb, 1.4, null, -ringAngle * 1.3 + 1.2);
    ring(cx, cy, R, 1.52, 1.0, 0.95, ringAngle * 0.8, 0.5 * e, rgb, 1.1, [3, 9]);
    ring(cx, cy, R, 1.72, 0.2, 0.15, -ringAngle * 0.5, 0.3 * e, rgb, 1, [1, 6]);
    if (s1) {
      const sg = ctx.createRadialGradient(s1[0], s1[1], 0, s1[0], s1[1], 9);
      sg.addColorStop(0, "rgba(255,255,255,0.95)"); sg.addColorStop(0.3, `rgba(${rgb},0.8)`); sg.addColorStop(1, `rgba(${rgb},0)`);
      ctx.fillStyle = sg;
      ctx.beginPath(); ctx.arc(s1[0], s1[1], 9, 0, TAU); ctx.fill();
    }

    // Anillo de voz: reacciona al nivel (lo que oye o lo que dice)
    ctx.lineWidth = 1.4;
    ctx.strokeStyle = `rgba(${rgb},${(0.2 + level * 0.7) * e})`;
    ctx.beginPath();
    const SEG = 140, vr = R * 1.1;
    for (let i = 0; i <= SEG; i++) {
      const a = (i / SEG) * TAU;
      const rr = vr + level * R * 0.16 * Math.sin(a * 7 + t / 70) * Math.sin(a * 3 - t / 130) + pulseV * R * 0.05;
      const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr;
      i ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
    }
    ctx.stroke();

    ctx.globalCompositeOperation = "source-over";
  }
  requestAnimationFrame(frame);

  return {
    set(next) { state = next; },
    bump(v = 0.7) { levelTarget = Math.max(levelTarget, v); },   // "volumen" de la voz
    pulse() { pulseV = 1; },                                     // latido al tocar
    spin(dx) { spinVel += dx * 0.00002; },                       // arrastrar para girar
    assembleNow() { t0 = -1e6; },                                // saltar la animación de arranque
  };
})();

/* ==========================================================================
   5. Estado del asistente (qué está haciendo Jarvis ahora mismo)
   ========================================================================== */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
const LABELS = {
  idle: SR ? "TOCA PARA HABLAR" : "TOCA PARA ESCRIBIR",
  listening: "ESCUCHANDO",
  thinking: "PROCESANDO",
  executing: "EJECUTANDO",
  speaking: "RESPONDIENDO",
  error: "SIN ENLACE",
};

const heardEl = $("#heard");
const replyEl = $("#reply");
const tasksEl = $("#tasks");
let phase = "idle";
let session = 0;               // cada orden nueva (o cancelación) sube el número; lo antiguo se descarta

function setPhase(p) {
  phase = p;
  app.dataset.state = p;
  orb.set(p);
  $("#orbStatus").textContent = LABELS[p];
}

/* ---------- historial ---------- */
let history = readJSON(HIST_KEY, []);
function saveHistory(role, text) {
  history.push({ role, text });
  history = history.slice(-60);
  writeJSON(HIST_KEY, history);
}

/* ---------- tarjetas de ejecución ---------- */
const ICON_OK = '<svg viewBox="0 0 24 24"><path d="M5 12.5l4.5 4.5L19 7.5"/></svg>';
const ICON_ERR = '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>';

function clearTasks() { tasksEl.innerHTML = ""; }

async function showTask(a) {
  const el = document.createElement("div");
  el.className = "task running";
  el.innerHTML = '<span class="t-icon"></span><span class="t-text"><b></b><small></small></span>';
  el.querySelector("b").textContent = a.label;
  el.querySelector("small").textContent = a.detail || "";
  if (!a.detail) el.querySelector("small").remove();
  tasksEl.appendChild(el);
  vibrate(8);
  await sleep(450 + Math.random() * 350);
  const ok = a.status !== "error";
  el.className = "task " + (ok ? "ok" : "error");
  el.querySelector(".t-icon").innerHTML = ok ? ICON_OK : ICON_ERR;
  await sleep(200);
}

/* ---------- voz de salida ---------- */
function speak(text) {
  return new Promise((resolve) => {
    if (!cfg.tts || !("speechSynthesis" in window)) return resolve();
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "es-ES";
    u.onboundary = () => orb.bump(0.8);
    u.onend = u.onerror = () => resolve();
    speechSynthesis.cancel();
    speechSynthesis.speak(u);
  });
}
function stopSpeaking() { if ("speechSynthesis" in window) speechSynthesis.cancel(); }

async function typeReply(text, my) {
  replyEl.textContent = "";
  const step = Math.max(1, Math.round(text.length / 110));
  for (let i = 0; i < text.length; i += step) {
    if (my !== session) return;
    replyEl.textContent = text.slice(0, i + step);
    orb.bump(0.4 + Math.random() * 0.4);
    await sleep(20);
  }
  replyEl.textContent = text;
}

/* ---------- el flujo completo de una orden ---------- */
async function handleUtterance(text) {
  text = (text || "").trim();
  if (!text) return setPhase("idle");
  const my = ++session;

  heardEl.textContent = text;
  replyEl.textContent = "";
  clearTasks();
  closeTextbar();
  saveHistory("user", text);
  setPhase("thinking");

  let res;
  try {
    res = await api.chat(text);
  } catch (err) {
    if (my !== session) return;
    const msg = "No consigo hablar con el PC. " + err.message;
    replyEl.textContent = msg;
    saveHistory("bot", msg);
    setConn("off");
    setPhase("error");
    await sleep(2600);
    if (my === session) setPhase("idle");
    return;
  }
  if (my !== session) return;
  if (typeof res === "string") res = { reply: res };

  if (res.actions && res.actions.length) {
    setPhase("executing");
    for (const a of res.actions) {
      if (my !== session) return;
      await showTask(a);
    }
  }

  if (my !== session) return;
  setPhase("speaking");
  const reply = res.reply || "Hecho.";
  await Promise.all([typeReply(reply, my), speak(reply)]);
  if (my !== session) return;
  saveHistory("bot", reply);

  if (res.confirm) {
    const ok = await askConfirm(res.confirm.text);
    if (my !== session) return;
    if (ok) {
      setPhase("executing");
      try {
        const r = await api.action(res.confirm.id);
        await showTask({ label: r.message || "Hecho" });
      } catch (err) {
        await showTask({ label: "Error: " + err.message, status: "error" });
      }
    } else {
      await showTask({ label: "Cancelado por ti", status: "error" });
    }
  }
  if (my === session) setPhase("idle");
}

/* ==========================================================================
   6. Entrada: tocar el orbe, voz y texto
   ========================================================================== */
let rec = null;
let heard = "";
let srBlocked = false;

if (SR) {
  rec = new SR();
  rec.lang = "es-ES";
  rec.interimResults = true;
  rec.onspeechstart = () => orb.bump(0.8);
  rec.onresult = (e) => {
    heard = [...e.results].map((r) => r[0].transcript).join("");
    heardEl.textContent = heard;
    orb.bump(0.7);
  };
  rec.onerror = (e) => {
    if (e.error === "no-speech") toast("No te he oído");
    else if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      srBlocked = true;
      toast("Sin permiso de micrófono. Escribe la orden.");
      openTextbar();
    } else if (e.error !== "aborted") toast("Error de voz: " + e.error);
  };
  rec.onend = () => {
    if (phase !== "listening") return;
    const text = heard.trim();
    heard = "";
    if (text) handleUtterance(text);
    else setPhase("idle");
  };
}

function startListening() {
  if (!rec || srBlocked) {
    toast(rec ? "Escribe la orden" : "Este navegador no permite dictado");
    return openTextbar();
  }
  session++;
  stopSpeaking();
  heard = "";
  heardEl.textContent = "";
  replyEl.textContent = "";
  clearTasks();
  setPhase("listening");
  try { rec.start(); } catch { /* ya estaba escuchando */ }
}

function onOrbTap() {
  vibrate(14);
  orb.pulse();
  if (phase === "listening") return rec.stop();
  if (phase === "speaking") { session++; stopSpeaking(); return setPhase("idle"); }
  if (phase === "thinking") { session++; toast("Cancelado"); return setPhase("idle"); }
  if (phase === "executing") return toast("Ejecutando…");
  startListening();
}

// Tocar = hablar. Arrastrar = girar el orbe.
(() => {
  const stage = $("#stage");
  let down = null, moved = false;
  stage.addEventListener("pointerdown", (e) => { down = { x: e.clientX }; moved = false; stage.setPointerCapture(e.pointerId); });
  stage.addEventListener("pointermove", (e) => {
    if (!down) return;
    const dx = e.clientX - down.x;
    if (Math.abs(dx) > 6) moved = true;
    if (moved) { orb.spin(dx); down.x = e.clientX; }
  });
  stage.addEventListener("pointerup", () => { if (down && !moved) onOrbTap(); down = null; });
  stage.addEventListener("pointercancel", () => { down = null; });
  stage.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onOrbTap(); } });
})();

// Barra de texto
const textbar = $("#textbar");
const textInput = $("#textInput");
function openTextbar() { textbar.hidden = false; textInput.focus(); }
function closeTextbar() { textbar.hidden = true; textInput.value = ""; textInput.blur(); }
$("#dockKeyboard").addEventListener("click", () => (textbar.hidden ? openTextbar() : closeTextbar()));
textbar.addEventListener("submit", (e) => {
  e.preventDefault();
  const text = textInput.value;
  if (rec && phase === "listening") rec.abort();
  handleUtterance(text);
});

// Atajos
$$("#chips .chip").forEach((c) => c.addEventListener("click", () => handleUtterance(c.dataset.text)));

// Voz de Jarvis (activar o silenciar)
const dockSpeaker = $("#dockSpeaker");
function paintSpeaker() {
  dockSpeaker.classList.toggle("on", cfg.tts);
  dockSpeaker.setAttribute("aria-pressed", cfg.tts);
}
dockSpeaker.addEventListener("click", () => {
  cfg.tts = !cfg.tts;
  writeJSON(CFG_KEY, cfg);
  if (!cfg.tts) stopSpeaking();
  paintSpeaker();
  toast(cfg.tts ? "Jarvis hablará en voz alta" : "Jarvis en silencio");
});
paintSpeaker();

/* ---------- registro de conversación ---------- */
const historyDialog = $("#historyDialog");
$("#dockHistory").addEventListener("click", () => {
  const list = $("#historyList");
  list.innerHTML = "";
  if (!history.length) {
    list.innerHTML = '<div class="log-empty">Todavía no hay conversación</div>';
  } else {
    history.forEach((m) => {
      const el = document.createElement("div");
      el.className = "log-line " + m.role;
      const who = document.createElement("small");
      who.textContent = m.role === "user" ? "TÚ" : "JARVIS";
      el.appendChild(who);
      el.appendChild(document.createTextNode(m.text));
      list.appendChild(el);
    });
  }
  historyDialog.showModal();
  list.scrollTop = list.scrollHeight;
});
$("#clearChat").addEventListener("click", () => {
  history = [];
  writeJSON(HIST_KEY, history);
  historyDialog.close();
  toast("Registro borrado");
});

/* ==========================================================================
   7. Conexión y estado del PC
   ========================================================================== */
function setConn(state) {
  const labels = { ok: "Online", off: "Sin enlace", demo: "Demo" };
  $("#conn").dataset.state = state;
  $("#connText").textContent = labels[state];
  $("#teleLink").textContent = { ok: "ONLINE", off: "CAÍDO", demo: "DEMO" }[state];
  $("#termMode").textContent = { ok: "CONECTADO", off: "SIN ENLACE", demo: "DEMO" }[state];
}

function formatUptime(sec) {
  const d = Math.floor(sec / 86400);
  const h = Math.floor((sec % 86400) / 3600);
  const m = Math.floor((sec % 3600) / 60);
  return (d ? d + " D " : "") + h + " H " + m + " MIN";
}

const GAUGE_C = 2 * Math.PI * 32;
function paintGauge(key, value, unit, max) {
  const g = $('.gauge[data-key="' + key + '"]');
  const pct = Math.min(1, value / max);
  g.querySelector(".g-arc").style.strokeDashoffset = GAUGE_C * (1 - pct);
  g.querySelector(".g-val").textContent = value + unit;
  g.classList.toggle("hot", pct >= 0.85);
  g.classList.toggle("warm", pct >= 0.65 && pct < 0.85);
}

async function refreshStats() {
  try {
    const s = await api.stats();
    paintGauge("cpu", s.cpu, " %", 100);
    paintGauge("ram", s.ram, " %", 100);
    paintGauge("temp", s.temp, " °C", 90);
    paintGauge("disk", s.disk, " %", 100);
    $("#uptime").textContent = "TIEMPO ENCENDIDO · " + formatUptime(s.uptime);
    $("#teleCpu").textContent = s.cpu + " %";
    $("#teleRam").textContent = s.ram + " %";
    $("#teleTemp").textContent = s.temp + " °";
    setConn(cfg.demo ? "demo" : "ok");
  } catch {
    setConn("off");
  }
}
setInterval(() => { if (!document.hidden) refreshStats(); }, 4000);
refreshStats();

function tickClock() {
  const hh = new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
  $("#sysLine").textContent = "EN LÍNEA · " + hh;
}
tickClock();
setInterval(tickClock, 20000);

/* ==========================================================================
   8. Escenas y acciones rápidas
   ========================================================================== */
$$("#scenes .panel-btn").forEach((btn) => {
  btn.addEventListener("click", async () => {
    if (btn.classList.contains("busy")) return;
    btn.classList.add("busy");
    vibrate(15);
    try {
      const r = await api.scene(btn.dataset.scene);
      toast(r.message || "Escena activada");
    } catch (err) {
      toast("Error: " + err.message);
    } finally {
      btn.classList.remove("busy");
    }
  });
});

$$("#actions .action").forEach((btn) => {
  btn.addEventListener("click", async () => {
    vibrate(15);
    if (btn.dataset.confirm && !(await askConfirm(btn.dataset.confirm))) return;
    try {
      const r = await api.action(btn.dataset.action);
      toast(r.message || "Hecho");
    } catch (err) {
      toast("Error: " + err.message);
    }
  });
});

/* ==========================================================================
   9. Terminal
   ========================================================================== */
const termEl = $("#term");
const termInput = $("#termInput");
const cmdHistory = [];
let cmdIndex = 0;

function termPrint(text, cls) {
  const line = document.createElement("div");
  line.className = cls;
  line.textContent = text;
  termEl.appendChild(line);
  termEl.scrollTop = termEl.scrollHeight;
}

async function runCommand(cmd) {
  cmd = cmd.trim();
  if (!cmd) return;
  cmdHistory.push(cmd);
  cmdIndex = cmdHistory.length;
  termPrint("$ " + cmd, "cmd");
  termInput.value = "";

  if (cmd === "clear") { termEl.innerHTML = ""; return; }

  try {
    const r = await api.exec(cmd);
    if (r.output) termPrint(r.output, "out");
    if (r.error) termPrint(r.error, "err");
  } catch (err) {
    termPrint("Error de conexión: " + err.message, "err");
    setConn("off");
  }
}

$("#termForm").addEventListener("submit", (e) => {
  e.preventDefault();
  runCommand(termInput.value);
});
termInput.addEventListener("keydown", (e) => {
  if (e.key === "ArrowUp" && cmdIndex > 0) { termInput.value = cmdHistory[--cmdIndex]; e.preventDefault(); }
  if (e.key === "ArrowDown" && cmdIndex < cmdHistory.length) { termInput.value = cmdHistory[++cmdIndex] || ""; e.preventDefault(); }
});
$$("#termChips .chip").forEach((c) => c.addEventListener("click", () => runCommand(c.dataset.cmd)));

termPrint("Terminal de Jarvis. Escribe «help» para ver los comandos.", "sys");

/* ==========================================================================
   10. Ajustes
   ========================================================================== */
const settingsDialog = $("#settingsDialog");

$("#openSettings").addEventListener("click", () => {
  $("#setDemo").checked = cfg.demo;
  $("#setUrl").value = cfg.url;
  $("#setToken").value = cfg.token;
  $("#setTts").checked = cfg.tts;
  settingsDialog.showModal();
});

$("#saveSettings").addEventListener("click", () => {
  cfg.demo = $("#setDemo").checked;
  cfg.url = $("#setUrl").value.trim();
  cfg.token = $("#setToken").value;
  cfg.tts = $("#setTts").checked;
  writeJSON(CFG_KEY, cfg);
  paintSpeaker();
  toast(cfg.demo ? "Modo demo activado" : "Ajustes guardados");
  refreshStats();
});

// Cerrar los diálogos al tocar fuera
[confirmDialog, settingsDialog, historyDialog].forEach((d) =>
  d.addEventListener("click", (e) => { if (e.target === d) d.close("cancel"); })
);

/* ==========================================================================
   11. Arranque
   ========================================================================== */
(async () => {
  const lines = $("#bootLines");
  const steps = ["INICIANDO NÚCLEO", "ENLACE SEGURO <i>OK</i>", "SISTEMAS EN LÍNEA <i>OK</i>"];
  for (const s of steps) {
    const d = document.createElement("div");
    d.innerHTML = s;
    lines.appendChild(d);
    await sleep(560);
  }
  $("#boot").classList.add("done");
  setTimeout(() => $("#boot").remove(), 700);
})();

setPhase("idle");

if ("serviceWorker" in navigator && location.protocol.startsWith("http")) {
  navigator.serviceWorker.register("sw.js").catch(() => { /* sin service worker no pasa nada */ });
}
