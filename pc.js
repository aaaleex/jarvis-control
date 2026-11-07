/* ==========================================================================
   Jarvis · v2 · escenas editables, accesos, panel del PC y personalización
   Se carga después de app.js y usa sus utilidades ($, $$, call, cfg, toast…).

   Servidor (todas con Authorization: Bearer <token>):
     GET  /api/config              -> {scenes, sites, pins, prefs, caps}
     PUT  /api/config              {scenes, sites, pins, prefs}
     GET  /api/apps                -> {apps: [{id, name}]}
     POST /api/open                {url} | {app}
     GET/POST /api/volume          {level} | {delta} | {mute:true}
     POST /api/media               {key: playpause|next|prev|stop}
     GET/POST /api/clipboard       {text}
     GET  /api/screenshot          -> image/png
     GET  /api/processes           POST /api/kill {pid}
   En modo demo todo se simula y se guarda solo en el móvil.
   ========================================================================== */

/* ---------- utilidades de DOM (nunca innerHTML con datos del usuario) ---------- */
function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(props || {})) {
    if (v == null || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "text") el.textContent = v;
    else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const svgIcon = (d) => {
  const s = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  s.setAttribute("viewBox", "0 0 24 24");
  const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
  p.setAttribute("d", d);
  s.append(p);
  return s;
};
const ICON_EDIT = "M4 20h4L19 9l-4-4L4 16zM13.5 6.5l4 4";
const ICON_PLUS = "M12 5v14M5 12h14";
const ICON_X = "M6 6l12 12M18 6L6 18";
const clone = (o) => JSON.parse(JSON.stringify(o));
const slug = (s) => s.toLowerCase().normalize("NFD").replace(/[̀-ͯ]/g, "").replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "").slice(0, 30);

/* ==========================================================================
   1. Datos: escenas, sitios, apps fijadas y ajustes
   ========================================================================== */
const STORE_KEY = "jarvis-store";
const DEFAULT_STORE = {
  scenes: [
    { id: "trabajo", name: "Trabajo", icon: "💼", steps: [{ type: "open_url", url: "https://calendar.google.com" }, { type: "volume", level: 20 }] },
    { id: "cine", name: "Cine", icon: "🎬", steps: [{ type: "volume", level: 60 }, { type: "open_url", url: "https://www.youtube.com" }] },
    { id: "foco", name: "Foco", icon: "🎯", steps: [{ type: "mute" }] },
  ],
  sites: [
    { id: "youtube", name: "YouTube", icon: "▶️", url: "https://www.youtube.com" },
    { id: "gmail", name: "Gmail", icon: "✉️", url: "https://mail.google.com" },
    { id: "github", name: "GitHub", icon: "🐙", url: "https://github.com" },
    { id: "calendar", name: "Calendario", icon: "📅", url: "https://calendar.google.com" },
  ],
  pins: [],
  prefs: { accent: "#38d6ff", orb: "plasma", voice: true, rate: 1, lang: "es-ES", haptics: true },
};
const DEMO_CAPS = { platform: "demo", exec: false, dryRun: false, volumeRead: true, media: true };
const DEMO_APPS = ["Spotify", "Discord", "Steam", "Visual Studio Code", "Google Chrome", "Calculadora", "Explorador de archivos", "OBS Studio"]
  .map((n) => ({ id: "demo-" + slug(n), name: n }));

let store = Object.assign(clone(DEFAULT_STORE), readJSON(STORE_KEY, {}));
let caps = DEMO_CAPS;
let apps = [];
let storeOnline = false;        // ¿viene del servidor?

function persistLocal() { writeJSON(STORE_KEY, store); }

const cfgPayload = () => ({ scenes: store.scenes, sites: store.sites, pins: store.pins, prefs: store.prefs });

async function loadStore() {
  try {
    const r = cfg.demo ? Object.assign(clone(store), { caps: DEMO_CAPS }) : await call("/api/config");
    caps = r.caps || DEMO_CAPS;
    store = { scenes: r.scenes, sites: r.sites, pins: r.pins || [], prefs: Object.assign({}, store.prefs, r.prefs) };
    storeOnline = !cfg.demo;
    persistLocal();
  } catch (e) {
    storeOnline = false;
    if (!cfg.demo) toast("Sin conexión: se muestran tus datos guardados");
  }
  renderAll();
}

async function saveStore(next) {
  const prev = store;
  store = next;
  try {
    if (!cfg.demo) {
      const r = await call("/api/config", "PUT", cfgPayload());
      store = { scenes: r.scenes, sites: r.sites, pins: r.pins || [], prefs: r.prefs };
      caps = r.caps || caps;
    }
    persistLocal();
    renderAll();
  } catch (e) {
    store = prev;          // si el servidor lo rechaza, no cambiamos nada
    throw e;
  }
}

/* ==========================================================================
   2. API del PC (real o simulada)
   ========================================================================== */
const demoPC = { vol: 50, muted: false, clip: "" };
const pcApi = {
  async apps(refresh) {
    if (cfg.demo) return DEMO_APPS;
    return (await call("/api/apps" + (refresh ? "?refresh=1" : ""))).apps;
  },
  async open(body) {
    if (!cfg.demo) return call("/api/open", "POST", body);
    await sleep(350);
    return { ok: true, message: "Abriendo en el PC (simulado)" };
  },
  async volume(body) {
    if (!cfg.demo) return call(body ? "/api/volume" : "/api/volume", body ? "POST" : "GET", body);
    await sleep(80);
    if (body && body.mute) demoPC.muted = !demoPC.muted;
    if (body && body.level != null) demoPC.vol = body.level;
    if (body && body.delta != null) demoPC.vol = Math.max(0, Math.min(100, demoPC.vol + body.delta));
    return { ok: true, level: demoPC.vol, muted: demoPC.muted };
  },
  async media(key) {
    if (!cfg.demo) return call("/api/media", "POST", { key });
    await sleep(120);
    return { ok: true };
  },
  async clipGet() {
    if (!cfg.demo) return call("/api/clipboard");
    return { ok: true, text: demoPC.clip || "(el portapapeles del PC de ejemplo está vacío)" };
  },
  async clipSet(text) {
    if (!cfg.demo) return call("/api/clipboard", "POST", { text });
    demoPC.clip = text;
    return { ok: true };
  },
  async processes() {
    if (!cfg.demo) return call("/api/processes");
    await sleep(300);
    const names = ["chrome", "Code", "Discord", "Spotify", "steam", "obs64", "explorer", "ollama"];
    return { canKill: false, processes: names.map((n, i) => ({ pid: 1000 + i * 37, name: n, cpu: Math.round(Math.random() * 18 * (8 - i) / 8 * 10) / 10, mem: 900 - i * 90 })) };
  },
  async kill(pid) {
    if (!cfg.demo) return call("/api/kill", "POST", { pid });
    return { ok: false, message: "En modo demo no se cierra nada" };
  },
  async screenshot() {
    if (cfg.demo) return demoShot();
    const res = await fetch(cfg.url.replace(/\/$/, "") + "/api/screenshot", { headers: { Authorization: "Bearer " + cfg.token } });
    if (!res.ok) {
      let msg = "";
      try { msg = (await res.json()).error; } catch { /* sin detalle */ }
      throw new Error(msg || "El servidor respondió " + res.status);
    }
    return URL.createObjectURL(await res.blob());
  },
};

// Captura de ejemplo para el modo demo (dibujada en un canvas)
function demoShot() {
  const c = document.createElement("canvas");
  c.width = 640; c.height = 360;
  const x = c.getContext("2d");
  const g = x.createLinearGradient(0, 0, 640, 360);
  g.addColorStop(0, "#07162a"); g.addColorStop(1, "#02050a");
  x.fillStyle = g; x.fillRect(0, 0, 640, 360);
  x.strokeStyle = "rgba(61,227,255,.5)"; x.lineWidth = 1;
  for (let i = 0; i < 5; i++) x.strokeRect(30 + i * 22, 30 + i * 18, 360, 220);
  x.fillStyle = "rgba(61,227,255,.85)"; x.font = "20px monospace";
  x.fillText("Captura de ejemplo (modo demo)", 40, 320);
  return new Promise((res) => c.toBlob((b) => res(URL.createObjectURL(b))));
}

/* ==========================================================================
   3. Personalización (color, orbe, voz, vibración)
   ========================================================================== */
const ACCENTS = [["#38d6ff", "Cian"], ["#7dffea", "Menta"], ["#8b7bff", "Violeta"], ["#ff8a3d", "Naranja"], ["#ffc83d", "Dorado"], ["#ff5d9e", "Rosa"], ["#5dff8a", "Verde"]];

function hexToRgb(hex) {
  const n = parseInt(hex.slice(1), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

function applyPrefs() {
  const p = store.prefs;
  const rgb = hexToRgb(p.accent);
  const root = document.documentElement.style;
  root.setProperty("--accent", p.accent);
  root.setProperty("--accent-rgb", rgb.join(", "));
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta) meta.setAttribute("content", "#02050a");
  orb.setAccent(rgb);
  orb.setStyle(p.orb);
  hapticsOn = p.haptics !== false;
}

function paintSettings() {
  const p = store.prefs;
  const sw = $("#swatches");
  sw.replaceChildren(...ACCENTS.map(([hex, name]) =>
    h("button", {
      type: "button", class: "sw", role: "radio", "aria-label": name, "aria-checked": String(hex === p.accent), style: "--c:" + hex,
      onclick: () => { store.prefs.accent = hex; applyPrefs(); paintSettings(); vibrate(8); },
    })));
  $$("#orbStyles button").forEach((b) => b.setAttribute("aria-checked", String(b.dataset.orb === p.orb)));
  $("#setRate").value = cfg.rate;
  $("#rateVal").textContent = Number(cfg.rate).toFixed(1) + "×";
  paintRange($("#setRate"));
  $("#setLang").value = cfg.lang;
  $("#setHaptics").checked = p.haptics !== false;
}

$$("#orbStyles button").forEach((b) => b.addEventListener("click", () => { store.prefs.orb = b.dataset.orb; applyPrefs(); paintSettings(); }));
$("#setRate").addEventListener("input", (e) => { $("#rateVal").textContent = Number(e.target.value).toFixed(1) + "×"; paintRange(e.target); });
$("#openSettings").addEventListener("click", paintSettings);

$("#saveSettings").addEventListener("click", async () => {
  cfg.rate = Number($("#setRate").value);
  cfg.lang = $("#setLang").value;
  store.prefs.haptics = $("#setHaptics").checked;
  Object.assign(store.prefs, { rate: cfg.rate, lang: cfg.lang, voice: cfg.tts });
  writeJSON(CFG_KEY, cfg);
  applyPrefs();
  persistLocal();
  await loadStore().catch(() => {});             // recarga con la conexión nueva
  if (!cfg.demo && storeOnline) saveStore(clone(store)).catch(() => {});   // y guarda los ajustes en el PC
});

function paintRange(r) {
  const min = Number(r.min || 0), max = Number(r.max || 100);
  r.style.setProperty("--fill", ((r.value - min) / (max - min)) * 100 + "%");
}

/* ==========================================================================
   4. Escenas
   ========================================================================== */
const scenesEl = $("#scenes");

function renderScenes() {
  const tiles = store.scenes.map((sc) => {
    const btn = h("button", { class: "panel-btn hud", "data-scene": sc.id, onclick: () => runScene(sc, btn) },
      h("span", { class: "emoji", text: sc.icon || "✨", "aria-hidden": "true" }),
      h("strong", { text: sc.name }),
      h("small", { text: sc.steps.length + (sc.steps.length === 1 ? " paso" : " pasos") }));
    return h("div", { class: "scene" }, btn,
      h("button", { class: "edit", "aria-label": "Editar " + sc.name, onclick: () => openSceneEditor(sc) }, svgIcon(ICON_EDIT)));
  });
  tiles.push(h("button", { class: "add-tile", onclick: () => openSceneEditor(null) }, svgIcon(ICON_PLUS), "Nueva escena"));
  scenesEl.replaceChildren(...tiles);
}

async function runScene(sc, btn) {
  if (btn && btn.classList.contains("busy")) return;
  btn && btn.classList.add("busy");
  vibrate(15);
  try {
    const r = await api.scene(sc.id);
    const bad = (r.actions || []).find((a) => a.status === "error");
    toast(bad ? "Escena «" + sc.name + "»: " + bad.label + (bad.detail ? " — " + bad.detail : "") : r.message || "Escena activada");
  } catch (e) {
    toast("Error: " + e.message);
  } finally {
    btn && btn.classList.remove("busy");
  }
}

/* ---- editor de escena ---- */
const sceneDialog = $("#sceneDialog");
let draft = null;

const STEP_NAMES = { open_url: "Abrir web", open_app: "Abrir app", volume: "Volumen", mute: "Silenciar / activar sonido", media: "Multimedia", wait: "Esperar", command: "Comando propio" };

async function openSceneEditor(sc) {
  draft = sc ? clone(sc) : { id: null, name: "", icon: "✨", steps: [] };
  $("#sceneTitle").textContent = sc ? "Editar escena" : "Nueva escena";
  $("#scIcon").value = draft.icon;
  $("#scName").value = draft.name;
  $("#scError").textContent = "";
  $("#scDelete").hidden = !sc;
  $("#scCmdOpt").hidden = !caps.exec;
  renderSteps();
  sceneDialog.showModal();
  ensureApps();
}

function stepEditor(s, i) {
  const move = (d) => () => { const j = i + d; if (j < 0 || j >= draft.steps.length) return; [draft.steps[i], draft.steps[j]] = [draft.steps[j], draft.steps[i]]; renderSteps(); };
  let body = null;
  if (s.type === "open_url") {
    body = h("input", { type: "url", inputmode: "url", value: s.url || "", placeholder: "https://…", autocapitalize: "none", spellcheck: "false", "aria-label": "Dirección", oninput: (e) => { s.url = e.target.value.trim(); } });
  } else if (s.type === "open_app") {
    const sel = h("select", { "aria-label": "App", onchange: (e) => { s.app = e.target.value; s.name = e.target.selectedOptions[0].textContent; } },
      h("option", { value: "", text: apps.length ? "Elige una app…" : "Cargando apps…" }),
      ...apps.map((a) => h("option", { value: a.id, text: a.name })));
    if (s.app && !apps.some((a) => a.id === s.app)) sel.append(h("option", { value: s.app, text: (s.name || "App") + " (no encontrada)" }));
    sel.value = s.app || "";
    body = sel;
  } else if (s.type === "volume") {
    const label = h("small", { text: (s.level ?? 50) + " %" });
    const r = h("input", { type: "range", min: 0, max: 100, value: s.level ?? 50, "aria-label": "Volumen", oninput: (e) => { s.level = Number(e.target.value); label.textContent = s.level + " %"; paintRange(e.target); } });
    paintRange(r);
    body = h("div", {}, r, label);
  } else if (s.type === "media") {
    body = h("select", { "aria-label": "Tecla", onchange: (e) => { s.key = e.target.value; } },
      ...[["playpause", "Reproducir / pausar"], ["next", "Siguiente"], ["prev", "Anterior"], ["stop", "Parar"]].map(([v, t]) => h("option", { value: v, text: t, selected: s.key === v })));
  } else if (s.type === "wait") {
    body = h("input", { type: "number", min: 0, max: 10000, step: 100, value: s.ms ?? 1000, "aria-label": "Milisegundos", oninput: (e) => { s.ms = Number(e.target.value); } });
  } else if (s.type === "command") {
    body = h("input", { type: "text", value: s.cmd || "", placeholder: "comando del sistema", autocapitalize: "none", spellcheck: "false", "aria-label": "Comando", oninput: (e) => { s.cmd = e.target.value; } });
  }
  return h("div", { class: "step" },
    h("div", { class: "what", text: (i + 1) + " · " + STEP_NAMES[s.type] }),
    body || h("small", { text: "Sin opciones" }),
    h("div", { class: "ctl" },
      h("button", { type: "button", "aria-label": "Subir", onclick: move(-1), text: "↑" }),
      h("button", { type: "button", "aria-label": "Bajar", onclick: move(1), text: "↓" }),
      h("button", { type: "button", class: "del", "aria-label": "Quitar paso", onclick: () => { draft.steps.splice(i, 1); renderSteps(); } }, svgIcon(ICON_X))));
}

function renderSteps() {
  const box = $("#scSteps");
  if (!draft.steps.length) { box.replaceChildren(h("p", { class: "empty", text: "Sin pasos. Añade el primero abajo." })); return; }
  box.replaceChildren(...draft.steps.map(stepEditor));
}

$("#scAdd").addEventListener("click", () => {
  const type = $("#scAddType").value;
  const base = { open_url: { url: "https://" }, open_app: { app: "", name: "" }, volume: { level: 40 }, media: { key: "playpause" }, wait: { ms: 1000 }, command: { cmd: "" }, mute: {} }[type];
  if (draft.steps.length >= 20) { $("#scError").textContent = "Máximo 20 pasos por escena"; return; }
  draft.steps.push(Object.assign({ type }, base));
  renderSteps();
  if (type === "open_app") ensureApps();
  const box = $("#scSteps");
  box.scrollTop = box.scrollHeight;
});

function readDraft() {
  draft.name = $("#scName").value.trim();
  draft.icon = $("#scIcon").value.trim() || "✨";
  if (!draft.name) throw new Error("Ponle un nombre a la escena");
  if (!draft.steps.length) throw new Error("Añade al menos un paso");
  for (const [i, s] of draft.steps.entries()) {
    if (s.type === "open_app" && !s.app) throw new Error("Paso " + (i + 1) + ": elige una app");
  }
  if (!draft.id) {
    let base = slug(draft.name) || "escena", id = base, n = 2;
    while (store.scenes.some((x) => x.id === id)) id = base + "-" + n++;
    draft.id = id;
  }
}

async function saveDraft() {
  readDraft();
  const next = clone(store);
  const i = next.scenes.findIndex((x) => x.id === draft.id);
  if (i >= 0) next.scenes[i] = clone(draft); else next.scenes.push(clone(draft));
  await saveStore(next);
}

$("#scSave").addEventListener("click", async () => {
  try { await saveDraft(); sceneDialog.close(); toast("Escena guardada"); }
  catch (e) { $("#scError").textContent = e.message; }
});
$("#scTest").addEventListener("click", async () => {
  try { await saveDraft(); $("#scError").textContent = ""; await runScene(store.scenes.find((x) => x.id === draft.id)); }
  catch (e) { $("#scError").textContent = e.message; }
});
$("#scDelete").addEventListener("click", async () => {
  if (!(await askConfirmOver(sceneDialog, "¿Borrar la escena «" + draft.name + "»?"))) return;
  try { const next = clone(store); next.scenes = next.scenes.filter((x) => x.id !== draft.id); await saveStore(next); sceneDialog.close(); toast("Escena borrada"); }
  catch (e) { $("#scError").textContent = e.message; }
});
$("#scClose").addEventListener("click", () => sceneDialog.close());

// Confirmar encima de otro diálogo abierto
function askConfirmOver(_parent, text) { return askConfirm(text); }

/* ==========================================================================
   5. Accesos: webs y apps
   ========================================================================== */
async function ensureApps(refresh) {
  try {
    apps = await pcApi.apps(refresh);
    if (sceneDialog.open) renderSteps();
    if ($("#appsDialog").open) renderAppList();
  } catch (e) {
    if ($("#appsDialog").open) $("#appList").replaceChildren(h("p", { class: "empty", text: "No se pudo cargar la lista: " + e.message }));
  }
}

async function openOnPC(body, tile) {
  vibrate(12);
  tile && tile.classList.add("busy");
  try { const r = await pcApi.open(body); toast(r.message || (r.ok ? "Hecho" : "No se pudo")); }
  catch (e) { toast("Error: " + e.message); }
  finally { tile && tile.classList.remove("busy"); }
}

function renderSites() {
  const tiles = store.sites.map((s) => {
    const t = h("button", { class: "tile hud", onclick: () => openOnPC({ url: s.url }, t) },
      h("span", { class: "emoji", text: s.icon || "🌐", "aria-hidden": "true" }),
      h("span", { class: "name", text: s.name }));
    return h("div", { class: "tile-wrap" }, t,
      h("button", { class: "edit", "aria-label": "Editar " + s.name, onclick: () => openSiteEditor(s) }, svgIcon(ICON_EDIT)));
  });
  tiles.push(h("button", { class: "add-tile", onclick: () => openSiteEditor(null) }, svgIcon(ICON_PLUS), "Añadir"));
  $("#sites").replaceChildren(...tiles);

  const pinTiles = store.pins.map((p) => {
    const t = h("button", { class: "tile hud", onclick: () => openOnPC({ app: p.id }, t) },
      h("span", { class: "avatar", text: (p.name || "?").charAt(0).toUpperCase(), "aria-hidden": "true" }),
      h("span", { class: "name", text: p.name }));
    return t;
  });
  pinTiles.push(h("button", { class: "add-tile", onclick: openApps }, svgIcon(ICON_PLUS), "Apps"));
  $("#pins").replaceChildren(...pinTiles);
}

$("#urlForm").addEventListener("submit", (e) => {
  e.preventDefault();
  let v = $("#urlInput").value.trim();
  if (!v) return;
  if (!/^https?:\/\//i.test(v)) v = "https://" + v;
  openOnPC({ url: v });
  $("#urlInput").value = "";
  $("#urlInput").blur();
});

/* ---- editor de sitio ---- */
const siteDialog = $("#siteDialog");
let siteDraft = null;
function openSiteEditor(s) {
  siteDraft = s ? clone(s) : { id: null, name: "", icon: "🌐", url: "" };
  $("#siteTitle").textContent = s ? "Editar sitio" : "Nuevo sitio";
  $("#stIcon").value = siteDraft.icon;
  $("#stName").value = siteDraft.name;
  $("#stUrl").value = siteDraft.url;
  $("#stError").textContent = "";
  $("#stDelete").hidden = !s;
  siteDialog.showModal();
}
$("#stSave").addEventListener("click", async () => {
  try {
    let url = $("#stUrl").value.trim();
    if (url && !/^https?:\/\//i.test(url)) url = "https://" + url;
    try { new URL(url); } catch { throw new Error("Escribe una dirección válida"); }
    const name = $("#stName").value.trim() || new URL(url).hostname.replace(/^www\./, "");
    const next = clone(store);
    if (!siteDraft.id) {
      let base = slug(name) || "sitio", id = base, n = 2;
      while (next.sites.some((x) => x.id === id)) id = base + "-" + n++;
      siteDraft.id = id;
      next.sites.push({ id, name, icon: $("#stIcon").value.trim() || "🌐", url });
    } else {
      Object.assign(next.sites.find((x) => x.id === siteDraft.id), { name, icon: $("#stIcon").value.trim() || "🌐", url });
    }
    await saveStore(next);
    siteDialog.close();
    toast("Sitio guardado");
  } catch (e) { $("#stError").textContent = e.message; }
});
$("#stDelete").addEventListener("click", async () => {
  if (!(await askConfirm("¿Borrar «" + siteDraft.name + "»?"))) return;
  try { const next = clone(store); next.sites = next.sites.filter((x) => x.id !== siteDraft.id); await saveStore(next); siteDialog.close(); }
  catch (e) { $("#stError").textContent = e.message; }
});
$("#stClose").addEventListener("click", () => siteDialog.close());

/* ---- selector de apps ---- */
const appsDialog = $("#appsDialog");
function openApps() { appsDialog.showModal(); $("#appList").replaceChildren(h("p", { class: "empty", text: "Cargando apps del PC…" })); ensureApps(); }

function renderAppList() {
  const q = $("#appSearch").value.trim().toLowerCase();
  const list = apps.filter((a) => !q || a.name.toLowerCase().includes(q)).slice(0, 80);
  if (!list.length) { $("#appList").replaceChildren(h("p", { class: "empty", text: apps.length ? "Nada con ese nombre" : "No se encontraron apps" })); return; }
  $("#appList").replaceChildren(...list.map((a) => {
    const pinned = store.pins.some((p) => p.id === a.id);
    return h("div", { class: "app-row" },
      h("button", { class: "open", text: a.name, title: "Abrir en el PC", onclick: () => openOnPC({ app: a.id }) }),
      h("button", { class: "pin" + (pinned ? " on" : ""), "aria-label": pinned ? "Quitar de fijadas" : "Fijar", "aria-pressed": String(pinned), text: pinned ? "★" : "☆",
        onclick: async () => {
          const next = clone(store);
          next.pins = pinned ? next.pins.filter((p) => p.id !== a.id) : [...next.pins, { id: a.id, name: a.name }];
          try { await saveStore(next); renderAppList(); } catch (e) { toast("Error: " + e.message); }
        } }));
  }));
}
$("#appSearch").addEventListener("input", renderAppList);
$("#appsRefresh").addEventListener("click", () => ensureApps(true));
$("#appsClose").addEventListener("click", () => appsDialog.close());

/* ==========================================================================
   6. Panel del PC: sonido, multimedia, pantalla, portapapeles, procesos
   ========================================================================== */
const volRange = $("#volRange");
let volBusy = false, volTimer = 0;

function paintVolume(v) {
  if (v && typeof v.level === "number") { volRange.value = v.level; $("#volVal").textContent = v.level + " %" + (v.muted ? " · SILENCIO" : ""); }
  else if (v && v.level == null) $("#volVal").textContent = "no se puede leer en este PC";
  $("#volMute").classList.toggle("on", !!(v && v.muted));
  paintRange(volRange);
}
async function loadVolume() { try { paintVolume(await pcApi.volume()); } catch { $("#volVal").textContent = "–"; } }

async function sendVolume(body) {
  if (volBusy) return;
  volBusy = true;
  try { const r = await pcApi.volume(body); if (r.ok === false) toast(r.error || "No se pudo cambiar el volumen"); paintVolume(r); }
  catch (e) { toast("Error: " + e.message); }
  finally { volBusy = false; }
}
volRange.addEventListener("input", () => {
  paintRange(volRange);
  $("#volVal").textContent = volRange.value + " %";
  clearTimeout(volTimer);
  volTimer = setTimeout(() => { volBusy = false; sendVolume({ level: Number(volRange.value) }); }, 220);   // espera a que dejes de arrastrar
});
$("#volDown").addEventListener("click", () => { vibrate(8); sendVolume({ delta: -10 }); });
$("#volUp").addEventListener("click", () => { vibrate(8); sendVolume({ delta: 10 }); });
$("#volMute").addEventListener("click", () => { vibrate(10); sendVolume({ mute: true }); });

$$("[data-media]").forEach((b) => b.addEventListener("click", async () => {
  vibrate(10);
  try { const r = await pcApi.media(b.dataset.media); if (r.ok === false) toast(r.error || "No disponible en este PC"); }
  catch (e) { toast("Error: " + e.message); }
}));

/* ---- pantalla ---- */
let shotUrl = "";
$("#shotBtn").addEventListener("click", async () => {
  const btn = $("#shotBtn");
  btn.disabled = true; btn.textContent = "Capturando…";
  try {
    const url = await pcApi.screenshot();
    if (shotUrl) URL.revokeObjectURL(shotUrl);
    shotUrl = url;
    const img = h("img", { src: url, alt: "Pantalla del PC", onclick: () => { $("#shotFull").src = url; $("#shotDialog").showModal(); } });
    $("#shot").replaceChildren(img);
    $("#shotSave").disabled = false;
  } catch (e) {
    $("#shot").replaceChildren(h("span", { text: e.message }));
  } finally { btn.disabled = false; btn.textContent = "Actualizar captura"; }
});
$("#shotSave").addEventListener("click", () => {
  if (!shotUrl) return;
  const a = h("a", { href: shotUrl, download: "pantalla-" + new Date().toISOString().slice(0, 19).replace(/[:T]/g, "-") + ".png" });
  document.body.append(a); a.click(); a.remove();
});
$("#shotFullClose").addEventListener("click", () => $("#shotDialog").close());
$("#shotDialog").addEventListener("click", (e) => { if (e.target === e.currentTarget) e.currentTarget.close(); });

/* ---- portapapeles ---- */
$("#clipSend").addEventListener("click", async () => {
  const text = $("#clipText").value;
  if (!text) return toast("Escribe algo primero");
  try { const r = await pcApi.clipSet(text); toast(r.ok ? "Enviado al portapapeles del PC" : r.error || "No se pudo"); }
  catch (e) { toast("Error: " + e.message); }
});
$("#clipGet").addEventListener("click", async () => {
  try {
    const r = await pcApi.clipGet();
    if (!r.ok) return toast(r.error || "No se pudo leer");
    $("#clipText").value = r.text;
    try { await navigator.clipboard.writeText(r.text); toast("Traído y copiado en el móvil"); } catch { toast("Traído del PC"); }
  } catch (e) { toast("Error: " + e.message); }
});

/* ---- procesos ---- */
async function loadProcs() {
  const box = $("#procs");
  try {
    const r = await pcApi.processes();
    if (!r.processes.length) return box.replaceChildren(h("p", { class: "empty", text: "No hay datos de procesos" }));
    box.replaceChildren(...r.processes.map((p) => h("div", { class: "proc" },
      h("span", { class: "n", text: p.name }),
      h("span", { class: "m", text: (p.cpu == null ? "" : p.cpu + " % · ") + p.mem + " MB" }),
      r.canKill
        ? h("button", { class: "x", "aria-label": "Cerrar " + p.name, onclick: async () => {
            if (!(await askConfirm("¿Cerrar «" + p.name + "» (PID " + p.pid + ")? Se perderá lo que no esté guardado."))) return;
            try { const k = await pcApi.kill(p.pid); toast(k.message || "Hecho"); loadProcs(); } catch (e) { toast("Error: " + e.message); }
          } }, svgIcon(ICON_X))
        : h("span"))));
  } catch (e) { box.replaceChildren(h("p", { class: "empty", text: e.message })); }
}
$("#procsBtn").addEventListener("click", loadProcs);

/* ==========================================================================
   7. Portada: atajos con tus escenas
   ========================================================================== */
function renderChips() {
  const chips = [{ t: "¿Cómo está el PC?", label: "Estado del PC" }];
  store.scenes.slice(0, 2).forEach((s) => chips.push({ t: "Activa la escena " + s.name, label: s.name }));
  chips.push({ t: "Haz una captura de pantalla", label: "Captura" }, { t: "Bloquea el PC", label: "Bloquear" });
  $("#chips").replaceChildren(...chips.map((c) => h("button", { class: "chip", text: c.label, onclick: () => handleUtterance(c.t) })));
}

/* ==========================================================================
   8. Arranque
   ========================================================================== */
function renderAll() { applyPrefs(); renderScenes(); renderSites(); renderChips(); }

function onViewShown(name) {
  if (name === "pc") loadVolume();
  if (name === "links" || name === "control") { /* los datos ya están en memoria */ }
}

[sceneDialog, siteDialog, appsDialog].forEach((d) => d.addEventListener("click", (e) => { if (e.target === d) d.close(); }));
renderAll();
loadStore();
