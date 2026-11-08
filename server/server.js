/* ==========================================================================
   Jarvis · servidor
   Sin dependencias: solo Node 18.15 o superior.

   Qué hace:
     - Sirve la app del móvil (los archivos de la carpeta de arriba)
     - Protege todo /api/* con un token
     - /api/chat    habla con Jarvis (Ollama por defecto, o tu propio Jarvis con JARVIS_CHAT_URL)
     - /api/stats   CPU, RAM, temperatura y disco reales
     - /api/scene   escenas (se definen en actions.json)
     - /api/action  bloquear, suspender, reiniciar, apagar, silenciar (+ las tuyas)
     - /api/exec    terminal (desactivada salvo que pongas ALLOW_EXEC=1)
     - v2: /api/config (escenas, sitios y ajustes editables desde el móvil), /api/apps,
           /api/open, /api/volume, /api/media, /api/clipboard, /api/screenshot,
           /api/processes, /api/kill

   Uso:   node server.js            (antes, crea el .env: mira el README)
          node server.js --gen-token   imprime un token nuevo
   ========================================================================== */

const http = require("http");
const fs = require("fs");
const os = require("os");
const path = require("path");
const crypto = require("crypto");
const { exec, spawn } = require("child_process");

/* ---------- .env (lector mínimo, sin dependencias) ---------- */
try {
  for (const line of fs.readFileSync(path.join(__dirname, ".env"), "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*?)\s*$/);
    if (m && !(m[1] in process.env)) process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
  }
} catch { /* sin .env: se usan variables del sistema */ }

if (process.argv.includes("--gen-token")) {
  console.log(crypto.randomBytes(32).toString("hex"));
  process.exit(0);
}

const PORT = Number(process.env.PORT) || 3000;
const HOST = process.env.HOST || "127.0.0.1";
const TOKEN = process.env.JARVIS_TOKEN || "";
const ALLOW_EXEC = process.env.ALLOW_EXEC === "1";
const OLLAMA_URL = (process.env.OLLAMA_URL || "http://127.0.0.1:11434").replace(/\/$/, "");
const OLLAMA_MODEL = process.env.OLLAMA_MODEL || "gemma3:4b";
const JARVIS_CHAT_URL = process.env.JARVIS_CHAT_URL || "";
const JARVIS_CHAT_TOKEN = process.env.JARVIS_CHAT_TOKEN || "";
const DRY_RUN = process.env.JARVIS_DRY_RUN === "1";   // pruebas: registra lo que haría, sin tocar el PC
const DATA_DIR = process.env.JARVIS_DATA_DIR ? path.resolve(process.env.JARVIS_DATA_DIR) : path.join(__dirname, "data");
const PLAT = process.platform; // "win32" | "linux" | "darwin"
// La app (index.html, app.js…) está en ../app. Solo se sirven estos archivos.
const WEB_DIR = process.env.WEB_DIR ? path.resolve(process.env.WEB_DIR) : path.join(__dirname, "..", "app");
const WEB_FILES = new Set(["index.html", "styles.css", "app.js", "pc.js", "sw.js", "manifest.webmanifest", "icon.svg"]);
// Si la app está alojada en otro sitio (p. ej. Vercel), pon aquí su dirección. Varias, separadas por comas.
const ALLOWED_ORIGINS = (process.env.ALLOWED_ORIGIN || "").split(",").map((o) => o.trim().replace(/\/$/, "")).filter(Boolean);

if (TOKEN.length < 24) {
  console.error("\nFalta JARVIS_TOKEN en el archivo .env (mínimo 24 caracteres).");
  console.error("Genera uno con:   node server.js --gen-token\n");
  process.exit(1);
}

/* ---------- configuración de acciones, escenas y apps ---------- */
let conf = { actions: {}, scenes: {}, apps: {} };
try {
  conf = Object.assign(conf, JSON.parse(fs.readFileSync(path.join(__dirname, "actions.json"), "utf8")));
} catch (e) {
  if (e.code !== "ENOENT") console.error("actions.json no es válido:", e.message);
}

const DEFAULT_ACTIONS = {
  lock: {
    win32: "rundll32.exe user32.dll,LockWorkStation",
    linux: "loginctl lock-session",
    darwin: "pmset displaysleepnow",
  },
  sleep: {
    win32: "rundll32.exe powrprof.dll,SetSuspendState 0,1,0",
    linux: "systemctl suspend",
    darwin: "pmset sleepnow",
  },
  reboot: { win32: "shutdown /r /t 5", linux: "systemctl reboot", darwin: "sudo shutdown -r now" },
  shutdown: { win32: "shutdown /s /t 5", linux: "systemctl poweroff", darwin: "sudo shutdown -h now" },
  mute: {
    win32: 'powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).SendKeys([char]173)"',
    linux: "pactl set-sink-mute @DEFAULT_SINK@ toggle",
    darwin: "osascript -e 'set volume output muted true'",
  },
};

// Un comando puede ser un texto o un objeto {win32, linux, darwin}
const pick = (c) => (typeof c === "string" ? c : c && c[PLAT]) || "";
const has = (obj, key) => Object.prototype.hasOwnProperty.call(obj, key);

/* ---------- utilidades ---------- */
function audit(kind, detail) {
  const line = new Date().toISOString() + " " + kind + " " + detail + "\n";
  process.stdout.write(line);
  fs.appendFile(path.join(__dirname, "audit.log"), line, () => {});
}

// Ejecuta y espera el resultado (para acciones y terminal)
function run(cmd) {
  return new Promise((resolve) => {
    exec(cmd, { timeout: 15000, maxBuffer: 1024 * 1024, windowsHide: true, cwd: os.homedir() }, (err, stdout, stderr) => {
      resolve({
        ok: !err,
        out: String(stdout || "").trimEnd(),
        err: String(stderr || "").trimEnd() || (err ? (err.killed ? "Tiempo agotado (15 s)" : err.message) : ""),
      });
    });
  });
}

// Lanza una app y no espera a que se cierre
function launch(cmd) {
  return new Promise((resolve) => {
    try {
      const p = spawn(cmd, { shell: true, detached: true, stdio: "ignore", windowsHide: true });
      p.on("error", (e) => resolve({ ok: false, err: e.message }));
      p.unref();
      setTimeout(() => resolve({ ok: true }), 200);
    } catch (e) {
      resolve({ ok: false, err: e.message });
    }
  });
}

/* ---------- estadísticas del PC ---------- */
function cpuTimes() {
  let idle = 0, total = 0;
  for (const c of os.cpus()) {
    for (const k in c.times) total += c.times[k];
    idle += c.times.idle;
  }
  return { idle, total };
}
let lastCpu = cpuTimes();
let cpuPct = 0;
setInterval(() => {
  const n = cpuTimes();
  const dt = n.total - lastCpu.total, di = n.idle - lastCpu.idle;
  cpuPct = dt > 0 ? Math.round(100 * (1 - di / dt)) : 0;
  lastCpu = n;
}, 2000).unref();

function ramPct() {
  let available = os.freemem();
  if (PLAT === "linux") {
    try {
      const m = fs.readFileSync("/proc/meminfo", "utf8").match(/MemAvailable:\s+(\d+)/);
      if (m) available = Number(m[1]) * 1024;
    } catch { /* usamos freemem */ }
  }
  return Math.round(100 * (1 - available / os.totalmem()));
}

function tempC() {
  if (PLAT !== "linux") return null; // en Windows no hay una forma fiable sin programas extra
  try {
    const base = "/sys/class/thermal";
    let max = 0;
    for (const d of fs.readdirSync(base)) {
      if (!d.startsWith("thermal_zone")) continue;
      const v = parseInt(fs.readFileSync(base + "/" + d + "/temp", "utf8"), 10) / 1000;
      if (v > max) max = v;
    }
    return max ? Math.round(max) : null;
  } catch { return null; }
}

function diskPct() {
  try {
    const s = fs.statfsSync(PLAT === "win32" ? "C:\\" : "/");
    return Math.round(100 * (1 - (s.bavail * s.bsize) / (s.blocks * s.bsize)));
  } catch { return 0; }
}

const caps = () => ({ platform: PLAT, exec: ALLOW_EXEC, dryRun: DRY_RUN, volumeRead: PLAT !== "win32", media: PLAT !== "darwin" });
const stats = () => ({ cpu: cpuPct, ram: ramPct(), temp: tempC(), disk: diskPct(), uptime: Math.round(os.uptime()) });

/* ---------- acciones y escenas ---------- */
async function runAction(id) {
  const source = has(conf.actions, id) ? conf.actions : has(DEFAULT_ACTIONS, id) ? DEFAULT_ACTIONS : null;
  const cmd = source ? pick(source[id]) : "";
  if (!cmd) return { ok: false, message: "La acción «" + id + "» no está configurada en este sistema" };
  audit("ACTION", id + " → " + cmd);
  const r = await run(cmd);
  return r.ok ? { ok: true, message: "Hecho: " + id } : { ok: false, message: "No se pudo: " + (r.err || id) };
}

async function runScene(id) {
  const v2 = await runSceneV2(id);
  if (v2) return v2;
  const steps = has(conf.scenes, id) ? conf.scenes[id] : null;
  if (!Array.isArray(steps) || !steps.length)
    return { ok: false, message: "La escena «" + id + "» no está configurada en actions.json", actions: [] };
  const actions = [];
  for (const s of steps) {
    const cmd = pick(s.cmd);
    if (!cmd) { actions.push({ label: s.label, detail: "Sin comando para este sistema", status: "error" }); continue; }
    audit("SCENE", id + " → " + cmd);
    const r = await launch(cmd);
    actions.push({ label: s.label, detail: r.ok ? s.detail : r.err, status: r.ok ? "ok" : "error" });
  }
  return { ok: true, message: "Escena «" + id + "» activada", actions };
}

/* ==========================================================================
   v2 · control del PC desde el móvil
   Reglas: el móvil nunca manda comandos sueltos (salvo la terminal avanzada).
   Manda ids y valores; el servidor decide qué se ejecuta.
   ========================================================================== */

// Ejecuta un programa SIN shell (los argumentos no pueden inyectar nada). Con DRY_RUN solo lo registra.
function proc(cmd, args, opts) {
  opts = opts || {};
  if (DRY_RUN && !opts.real) { audit("DRY", cmd + " " + args.join(" ")); return Promise.resolve({ ok: true, out: opts.dryOut || "", err: "", dry: true }); }
  return new Promise((resolve) => {
    let child;
    try {
      child = require("child_process").execFile(cmd, args, { timeout: opts.timeout || 15000, maxBuffer: 20 * 1024 * 1024, windowsHide: true, encoding: opts.binary ? "buffer" : "utf8" },
        (err, stdout, stderr) => resolve({ ok: !err, out: opts.binary ? stdout : String(stdout || "").trimEnd(), err: String(stderr || "").trimEnd() || (err ? err.message : "") }));
    } catch (e) { return resolve({ ok: false, out: "", err: e.message }); }
    if (opts.input != null && child.stdin) { child.stdin.on("error", () => {}); child.stdin.end(opts.input); }
  });
}
const ps = (script, opts) => proc("powershell.exe", ["-NoProfile", "-NonInteractive", "-Command", script], opts);
const which = async (bin) => (await proc(PLAT === "win32" ? "where" : "which", [bin], { dryOut: bin })).ok;

/* ---- almacén: escenas, sitios, apps fijadas y ajustes ---- */
const ID_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const STEP_TYPES = ["open_url", "open_app", "volume", "mute", "media", "wait", "command"];
const SAFE_ACTIONS = ["lock", "mute"];
const DEFAULT_CONFIG = {
  version: 2,
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
  pins: [],   // ids de apps fijadas en el panel
  prefs: { accent: "#38d6ff", orb: "plasma", voice: true, rate: 1, lang: "es-ES", haptics: true },
};
const clone = (o) => JSON.parse(JSON.stringify(o));
const str = (v, max) => String(v == null ? "" : v).trim().slice(0, max);
const bad = (m) => Object.assign(new Error(m), { status: 400 });

function isHttpUrl(u) {
  try { const x = new URL(u); return (x.protocol === "https:" || x.protocol === "http:") && !!x.hostname; } catch { return false; }
}

function cleanStep(s, i) {
  if (!s || typeof s !== "object" || !STEP_TYPES.includes(s.type)) throw bad("Paso " + (i + 1) + ": tipo no válido");
  switch (s.type) {
    case "open_url":
      if (!isHttpUrl(s.url) || String(s.url).length > 500) throw bad("Paso " + (i + 1) + ": la dirección debe empezar por http:// o https://");
      return { type: "open_url", url: new URL(s.url).href };
    case "open_app": {
      const id = str(s.app, 40);
      if (!id) throw bad("Paso " + (i + 1) + ": falta la app");
      return { type: "open_app", app: id, name: str(s.name, 60) };
    }
    case "volume": {
      const n = Number(s.level);
      if (!Number.isFinite(n) || n < 0 || n > 100) throw bad("Paso " + (i + 1) + ": volumen entre 0 y 100");
      return { type: "volume", level: Math.round(n) };
    }
    case "mute": return { type: "mute" };
    case "media":
      if (!["playpause", "next", "prev", "stop"].includes(s.key)) throw bad("Paso " + (i + 1) + ": tecla multimedia no válida");
      return { type: "media", key: s.key };
    case "wait": {
      const n = Number(s.ms);
      if (!Number.isFinite(n) || n < 0 || n > 10000) throw bad("Paso " + (i + 1) + ": espera entre 0 y 10000 ms");
      return { type: "wait", ms: Math.round(n) };
    }
    case "command":
      if (!ALLOW_EXEC) throw bad("Paso " + (i + 1) + ": los comandos propios necesitan ALLOW_EXEC=1 en el servidor");
      if (!str(s.cmd, 500)) throw bad("Paso " + (i + 1) + ": comando vacío");
      return { type: "command", cmd: str(s.cmd, 500) };
  }
}

function cleanConfig(input) {
  if (!input || typeof input !== "object") throw bad("Configuración no válida");
  const out = { version: 2, scenes: [], sites: [], pins: [], prefs: clone(DEFAULT_CONFIG.prefs) };
  const seen = new Set();
  const uid = (id, what) => {
    if (!ID_RE.test(id)) throw bad(what + ": identificador no válido («" + id + "»)");
    if (seen.has(what + id)) throw bad(what + ": identificador repetido («" + id + "»)");
    seen.add(what + id);
    return id;
  };
  if (!Array.isArray(input.scenes) || input.scenes.length > 40) throw bad("Máximo 40 escenas");
  for (const sc of input.scenes) {
    if (!Array.isArray(sc.steps) || sc.steps.length > 20) throw bad("Cada escena admite hasta 20 pasos");
    out.scenes.push({ id: uid(str(sc.id, 40), "Escena"), name: str(sc.name, 40) || "Escena", icon: str(sc.icon, 8) || "✨", steps: sc.steps.map(cleanStep) });
  }
  const sites = Array.isArray(input.sites) ? input.sites : [];
  if (sites.length > 80) throw bad("Máximo 80 sitios");
  for (const st of sites) {
    if (!isHttpUrl(st.url) || String(st.url).length > 500) throw bad("Sitio «" + str(st.name, 30) + "»: dirección no válida (http:// o https://)");
    out.sites.push({ id: uid(str(st.id, 40), "Sitio"), name: str(st.name, 40) || new URL(st.url).hostname, icon: str(st.icon, 8) || "🌐", url: new URL(st.url).href });
  }
  const pins = Array.isArray(input.pins) ? input.pins : [];
  if (pins.length > 60) throw bad("Máximo 60 apps fijadas");
  out.pins = pins.map((p) => ({ id: str(p && p.id, 40), name: str(p && p.name, 60) })).filter((p) => p.id);
  const p = input.prefs && typeof input.prefs === "object" ? input.prefs : {};
  const d = out.prefs;
  if (/^#[0-9a-fA-F]{6}$/.test(p.accent)) d.accent = p.accent.toLowerCase();
  if (["plasma", "anillos", "cristal"].includes(p.orb)) d.orb = p.orb;
  if (typeof p.voice === "boolean") d.voice = p.voice;
  if (typeof p.haptics === "boolean") d.haptics = p.haptics;
  if (Number.isFinite(Number(p.rate))) d.rate = Math.min(1.6, Math.max(0.6, Number(p.rate)));
  if (/^[a-z]{2}(-[A-Z]{2})?$/.test(p.lang)) d.lang = p.lang;
  return out;
}

const CONFIG_FILE = () => path.join(DATA_DIR, "config.json");
let config;
function loadConfig() {
  try { config = cleanConfig(JSON.parse(fs.readFileSync(CONFIG_FILE(), "utf8"))); }
  catch (e) {
    if (e.code !== "ENOENT") console.error("data/config.json no es válido, se usan los valores por defecto:", e.message);
    config = clone(DEFAULT_CONFIG);
  }
}
function saveConfig(next) {
  config = next;
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const tmp = CONFIG_FILE() + ".tmp";
  fs.writeFileSync(tmp, JSON.stringify(config, null, 2));
  fs.renameSync(tmp, CONFIG_FILE());   // escritura atómica: nunca queda a medias
}
loadConfig();

/* ---- apps instaladas ---- */
let appCache = { at: 0, list: [], map: new Map() };
const appId = (name, key) => crypto.createHash("sha1").update(name + "|" + key).digest("hex").slice(0, 10);

function desktopEntries() {
  const dirs = ["/usr/share/applications", "/usr/local/share/applications", path.join(process.env.HOME || os.homedir(), ".local/share/applications"), "/var/lib/flatpak/exports/share/applications", "/var/lib/snapd/desktop/applications"];
  const out = [];
  for (const dir of dirs) {
    let files = [];
    try { files = fs.readdirSync(dir); } catch { continue; }
    for (const f of files) {
      if (!f.endsWith(".desktop")) continue;
      let txt;
      try { txt = fs.readFileSync(path.join(dir, f), "utf8"); } catch { continue; }
      const sec = txt.split(/\n\[/)[0];                    // solo [Desktop Entry]
      const g = (k) => { const m = sec.match(new RegExp("^" + k + "=(.*)$", "m")); return m ? m[1].trim() : ""; };
      if (g("Type") !== "Application" || g("NoDisplay") === "true" || g("Hidden") === "true" || !g("Name")) continue;
      out.push({ name: g("Name"), key: f.replace(/\.desktop$/, "") });
    }
  }
  return out;
}

async function discoverApps(force) {
  if (!force && Date.now() - appCache.at < 5 * 60 * 1000 && appCache.list.length) return appCache.list;
  let found = [];
  if (PLAT === "linux") found = desktopEntries().map((e) => ({ name: e.name, key: e.key, launch: ["gtk-launch", [e.key]] }));
  else if (PLAT === "darwin") {
    for (const dir of ["/Applications", "/System/Applications", path.join(os.homedir(), "Applications")]) {
      try { for (const f of fs.readdirSync(dir)) if (f.endsWith(".app")) found.push({ name: f.slice(0, -4), key: f, launch: ["open", ["-a", path.join(dir, f)]] }); } catch { /* carpeta ausente */ }
    }
  } else if (PLAT === "win32") {
    const r = await ps("Get-StartApps | Sort-Object Name | ConvertTo-Json -Compress", { timeout: 30000 });
    try {
      let j = JSON.parse(r.out || "[]");
      if (!Array.isArray(j)) j = [j];
      found = j.filter((a) => a && a.Name && a.AppID).map((a) => ({ name: String(a.Name), key: String(a.AppID), launch: ["explorer.exe", ["shell:AppsFolder\\" + a.AppID]] }));
    } catch { /* sin lista */ }
  }
  const map = new Map();
  for (const a of found) {
    const id = appId(a.name, a.key);
    if (!map.has(id)) map.set(id, { id, name: a.name, launch: a.launch });
  }
  const list = [...map.values()].map((a) => ({ id: a.id, name: a.name })).sort((a, b) => a.name.localeCompare(b.name, "es"));
  appCache = { at: Date.now(), list, map };
  return list;
}

async function openApp(id) {
  await discoverApps(false);
  const a = appCache.map.get(id);
  if (!a) return { ok: false, message: "Esa app ya no está en la lista. Recarga las apps." };
  audit("OPEN_APP", a.name);
  const r = await proc(a.launch[0], a.launch[1], { timeout: 10000 });
  return r.ok ? { ok: true, message: "Abriendo " + a.name } : { ok: false, message: "No se pudo abrir " + a.name + (r.err ? ": " + r.err.slice(0, 120) : "") };
}

async function openUrl(u) {
  if (!isHttpUrl(u)) return { ok: false, message: "Solo se pueden abrir direcciones http:// o https://" };
  const href = new URL(u).href;
  audit("OPEN_URL", href);
  const [cmd, args] = PLAT === "win32" ? ["explorer.exe", [href]] : PLAT === "darwin" ? ["open", [href]] : ["xdg-open", [href]];
  const r = await proc(cmd, args, { timeout: 10000 });
  // explorer.exe devuelve código 1 aunque abra bien
  return r.ok || (PLAT === "win32" && !r.err.includes("ENOENT")) ? { ok: true, message: "Abriendo " + new URL(href).hostname } : { ok: false, message: "No se pudo abrir la web: " + r.err.slice(0, 120) };
}

/* ---- sonido y multimedia ---- */
async function getVolume() {
  if (DRY_RUN) return { level: 50, muted: false };
  if (PLAT === "linux") {
    const v = await proc("pactl", ["get-sink-volume", "@DEFAULT_SINK@"]);
    const m = await proc("pactl", ["get-sink-mute", "@DEFAULT_SINK@"]);
    const lv = (v.out.match(/(\d+)%/) || [])[1];
    return { level: lv == null ? null : Number(lv), muted: /yes|sí/i.test(m.out) };
  }
  if (PLAT === "darwin") {
    const r = await proc("osascript", ["-e", "output volume of (get volume settings) & \",\" & output muted of (get volume settings)"]);
    const [l, m] = r.out.split(",");
    return { level: Number(l) || 0, muted: /true/.test(m || "") };
  }
  return { level: null, muted: null };   // Windows no permite leerlo sin programas extra
}

async function setVolume(level) {
  level = Math.min(100, Math.max(0, Math.round(level)));
  audit("VOLUME", String(level));
  if (PLAT === "linux") return proc("pactl", ["set-sink-volume", "@DEFAULT_SINK@", level + "%"]);
  if (PLAT === "darwin") return proc("osascript", ["-e", "set volume output volume " + level]);
  // Windows: las teclas de volumen suben/bajan de 2 en 2. Bajamos al mínimo y subimos.
  return ps("$s=New-Object -ComObject WScript.Shell; 1..50|%{$s.SendKeys([char]174)}; 1.." + Math.round(level / 2) + "|%{$s.SendKeys([char]175)}");
}

async function stepVolume(delta) {
  const cur = await getVolume();
  if (cur.level == null) {
    audit("VOLUME", "paso " + delta);
    return ps("$s=New-Object -ComObject WScript.Shell; 1.." + Math.round(Math.abs(delta) / 2) + "|%{$s.SendKeys([char]" + (delta > 0 ? 175 : 174) + ")}");
  }
  return setVolume(cur.level + delta);
}

async function toggleMute() {
  audit("MUTE", "toggle");
  if (PLAT === "linux") return proc("pactl", ["set-sink-mute", "@DEFAULT_SINK@", "toggle"]);
  if (PLAT === "darwin") { const c = await getVolume(); return proc("osascript", ["-e", "set volume output muted " + (c.muted ? "false" : "true")]); }
  return ps("(New-Object -ComObject WScript.Shell).SendKeys([char]173)");
}

const MEDIA = { playpause: [179, "play-pause"], next: [176, "next"], prev: [177, "previous"], stop: [178, "stop"] };
async function mediaKey(key) {
  if (!has(MEDIA, key)) return { ok: false, err: "Tecla desconocida" };
  audit("MEDIA", key);
  if (PLAT === "win32") return ps("(New-Object -ComObject WScript.Shell).SendKeys([char]" + MEDIA[key][0] + ")");
  if (PLAT === "linux") return proc("playerctl", [MEDIA[key][1]]);
  return { ok: false, err: "Los controles multimedia no están disponibles en este sistema" };
}

/* ---- portapapeles y captura ---- */
async function clipGet() {
  if (PLAT === "win32") return ps("Get-Clipboard -Raw");
  if (PLAT === "darwin") return proc("pbpaste", []);
  const wl = await which("wl-paste");
  return wl ? proc("wl-paste", ["--no-newline"]) : proc("xclip", ["-selection", "clipboard", "-o"]);
}
async function clipSet(text) {
  audit("CLIP_SET", text.length + " caracteres");
  if (PLAT === "win32") return ps("$t=[Console]::In.ReadToEnd(); Set-Clipboard -Value $t", { input: text });
  if (PLAT === "darwin") return proc("pbcopy", [], { input: text });
  const wl = await which("wl-copy");
  return wl ? proc("wl-copy", [], { input: text }) : proc("xclip", ["-selection", "clipboard"], { input: text });
}

const PNG_1PX = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==", "base64");
async function screenshot() {
  audit("SCREENSHOT", "");
  if (DRY_RUN) return { ok: true, png: PNG_1PX };
  const file = path.join(os.tmpdir(), "jarvis-" + crypto.randomBytes(6).toString("hex") + ".png");
  let r;
  if (PLAT === "win32") {
    r = await ps("Add-Type -AssemblyName System.Windows.Forms,System.Drawing; $b=[System.Windows.Forms.SystemInformation]::VirtualScreen; $bmp=New-Object System.Drawing.Bitmap $b.Width,$b.Height; $g=[System.Drawing.Graphics]::FromImage($bmp); $g.CopyFromScreen($b.Left,$b.Top,0,0,$bmp.Size); $bmp.Save($env:JARVIS_SHOT,[System.Drawing.Imaging.ImageFormat]::Png); $g.Dispose(); $bmp.Dispose()".replace("$env:JARVIS_SHOT", "'" + file.replace(/'/g, "''") + "'"), { timeout: 20000 });
  } else if (PLAT === "darwin") {
    r = await proc("screencapture", ["-x", file]);
  } else {
    const tools = [["grim", [file]], ["gnome-screenshot", ["-f", file]], ["spectacle", ["-b", "-n", "-o", file]], ["scrot", ["-o", file]], ["import", ["-window", "root", file]]];
    r = { ok: false, err: "No hay ninguna herramienta de captura (instala grim, scrot o gnome-screenshot)" };
    for (const [bin, args] of tools) { if (await which(bin)) { r = await proc(bin, args, { timeout: 20000 }); if (r.ok) break; } }
  }
  try {
    const png = fs.readFileSync(file);
    fs.unlink(file, () => {});
    return { ok: true, png };
  } catch {
    return { ok: false, err: (r && r.err) || "No se pudo hacer la captura (¿hay una sesión de escritorio activa?)" };
  }
}

/* ---- procesos ---- */
async function topProcesses() {
  let rows = [];
  if (PLAT === "win32") {
    const r = await ps("Get-Process | Sort-Object WorkingSet64 -Descending | Select-Object -First 14 Id,ProcessName,@{n='mem';e={[math]::Round($_.WorkingSet64/1MB)}} | ConvertTo-Json -Compress", { timeout: 20000, real: true });
    try { let j = JSON.parse(r.out || "[]"); if (!Array.isArray(j)) j = [j]; rows = j.map((p) => ({ pid: p.Id, name: p.ProcessName, cpu: null, mem: p.mem })); } catch { /* vacío */ }
  } else {
    const args = PLAT === "darwin" ? ["-Aceo", "pid,pcpu,rss,comm", "-r"] : ["-eo", "pid,pcpu,rss,comm", "--sort=-pcpu"];
    const r = await proc("ps", args, { real: true });
    rows = r.out.split("\n").slice(1, 15).map((l) => {
      const m = l.trim().match(/^(\d+)\s+([\d.,]+)\s+(\d+)\s+(.+)$/);
      return m ? { pid: Number(m[1]), name: m[4], cpu: Number(m[2].replace(",", ".")), mem: Math.round(Number(m[3]) / 1024) } : null;
    }).filter(Boolean);
  }
  return rows.filter((p) => p.pid !== process.pid);
}

async function killProcess(pid) {
  if (!ALLOW_EXEC) return { ok: false, message: "Cerrar procesos necesita ALLOW_EXEC=1 en el servidor." };
  if (!Number.isInteger(pid) || pid <= 4 || pid === process.pid || pid === process.ppid) return { ok: false, message: "Ese proceso está protegido." };
  const known = (await topProcesses()).some((p) => p.pid === pid);
  if (!known) return { ok: false, message: "Ese proceso ya no está entre los principales. Actualiza la lista." };
  audit("KILL", String(pid));
  if (DRY_RUN) return { ok: true, message: "Proceso " + pid + " cerrado (simulado)" };
  try { process.kill(pid); return { ok: true, message: "Proceso " + pid + " cerrado" }; }
  catch (e) { return { ok: false, message: "No se pudo cerrar: " + e.message }; }
}

/* ---- escenas v2 ---- */
async function runStep(s) {
  switch (s.type) {
    case "open_url": { const r = await openUrl(s.url); return { ok: r.ok, label: "Abrir " + new URL(s.url).hostname, detail: r.ok ? "" : r.message }; }
    case "open_app": { const r = await openApp(s.app); return { ok: r.ok, label: "Abrir " + (s.name || "app"), detail: r.ok ? "" : r.message }; }
    case "volume": { const r = await setVolume(s.level); return { ok: r.ok, label: "Volumen al " + s.level + " %", detail: r.ok ? "" : r.err }; }
    case "mute": { const r = await toggleMute(); return { ok: r.ok, label: "Silenciar / activar sonido", detail: r.ok ? "" : r.err }; }
    case "media": { const r = await mediaKey(s.key); return { ok: r.ok, label: "Multimedia: " + s.key, detail: r.ok ? "" : r.err }; }
    case "wait": await new Promise((r) => setTimeout(r, DRY_RUN ? 0 : s.ms)); return { ok: true, label: "Esperar " + s.ms + " ms", detail: "" };
    case "command": {
      if (!ALLOW_EXEC) return { ok: false, label: "Comando propio", detail: "Necesita ALLOW_EXEC=1" };
      audit("SCENE_CMD", s.cmd);
      const r = DRY_RUN ? { ok: true } : await run(s.cmd);
      return { ok: r.ok, label: "Comando: " + s.cmd.slice(0, 40), detail: r.ok ? "" : r.err };
    }
  }
  return { ok: false, label: s.type, detail: "Paso desconocido" };
}

async function runSceneV2(id) {
  const sc = config.scenes.find((x) => x.id === id);
  if (!sc) return null;
  audit("SCENE", sc.id);
  const actions = [];
  for (const s of sc.steps) {
    const r = await runStep(s);
    actions.push({ label: r.label, detail: r.detail, status: r.ok ? "ok" : "error" });
  }
  return { ok: actions.every((a) => a.status === "ok"), message: "Escena «" + sc.name + "» activada", actions };
}

/* ---------- chat ---------- */
const SYSTEM_PROMPT =
  "Eres Jarvis, el asistente personal de Alex, que funciona en su ordenador de casa. " +
  "Responde siempre en español, de forma breve (una o dos frases), directa y amable, como en una conversación hablada. " +
  "No uses listas ni markdown.";
const memory = [];

async function askLLM(text) {
  memory.push({ role: "user", content: text });
  while (memory.length > 12) memory.shift();

  if (JARVIS_CHAT_URL) {
    const headers = { "Content-Type": "application/json" };
    if (JARVIS_CHAT_TOKEN) headers.Authorization = "Bearer " + JARVIS_CHAT_TOKEN;
    let r;
    try {
      r = await fetch(JARVIS_CHAT_URL, { method: "POST", headers, body: JSON.stringify({ text }), signal: AbortSignal.timeout(120000) });
    } catch {
      throw new Error("No puedo conectar con tu Jarvis en " + JARVIS_CHAT_URL);
    }
    if (!r.ok) throw new Error("Tu Jarvis respondió " + r.status);
    const j = await r.json();
    return typeof j === "string" ? { reply: j } : j;
  }

  let r;
  try {
    r = await fetch(OLLAMA_URL + "/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ model: OLLAMA_MODEL, stream: false, messages: [{ role: "system", content: SYSTEM_PROMPT }, ...memory] }),
      signal: AbortSignal.timeout(120000),
    });
  } catch {
    throw new Error("No puedo conectar con Ollama en " + OLLAMA_URL + ". ¿Está arrancado?");
  }
  if (!r.ok) throw new Error("Ollama respondió " + r.status + " (¿existe el modelo " + OLLAMA_MODEL + "?)");
  const j = await r.json();
  const reply = ((j.message && j.message.content) || "").trim() || "No se me ocurre qué decir.";
  memory.push({ role: "assistant", content: reply });
  return { reply };
}

async function chat(text) {
  const t = text.toLowerCase();

  // Acciones peligrosas: nunca se ejecutan solas, el móvil pide confirmación antes.
  if (/\bapaga(r)?\b/.test(t))
    return { reply: "Eso es delicado. Necesito que lo confirmes tú.", confirm: { id: "shutdown", text: "¿Apagar el PC? No podrás volver a encenderlo desde el móvil." } };
  if (/\breinicia(r)?\b/.test(t))
    return { reply: "Eso es delicado. Necesito que lo confirmes tú.", confirm: { id: "reboot", text: "¿Reiniciar el PC? Se cerrarán las apps abiertas." } };
  if (/\bsuspende(r)?\b/.test(t))
    return { reply: "Necesito que lo confirmes.", confirm: { id: "sleep", text: "¿Suspender el PC? Tendrás que despertarlo en persona." } };

  // Si hay un Jarvis propio conectado (JARVIS_CHAT_URL), él se encarga de todo lo demás:
  // escenas, apps, pantallas... Con LOCAL_INTENTS=1 se usan también las de actions.json.
  if (JARVIS_CHAT_URL && process.env.LOCAL_INTENTS !== "1") return askLLM(text);

  // Escenas
  if (/\b(modo|escena|activa|pon)\b/.test(t)) {
    for (const sc of config.scenes) {
      if (t.includes(sc.id) || t.includes(sc.name.toLowerCase())) {
        const r = await runSceneV2(sc.id);
        return { reply: "Escena " + sc.name + " lista.", actions: r.actions };
      }
    }
    for (const id of Object.keys(conf.scenes)) {
      if (t.includes(id.toLowerCase())) {
        const r = await runScene(id);
        return r.ok ? { reply: "Escena " + id + " lista.", actions: r.actions } : { reply: r.message };
      }
    }
  }

  // Acciones simples
  if (/\bbloquea(r)?\b/.test(t)) {
    const r = await runAction("lock");
    return { reply: r.ok ? "PC bloqueado." : r.message, actions: [{ label: "Bloquear sesión", status: r.ok ? "ok" : "error" }] };
  }
  if (/\b(silencia|silenciar|mute)\b/.test(t)) {
    const r = await runAction("mute");
    return { reply: r.ok ? "Hecho." : r.message, actions: [{ label: "Silenciar audio", status: r.ok ? "ok" : "error" }] };
  }
  if (/\b(captura|pantallazo)\b/.test(t) && (has(conf.actions, "screenshot"))) {
    const r = await runAction("screenshot");
    return { reply: r.ok ? "Captura hecha." : r.message, actions: [{ label: "Captura de pantalla", status: r.ok ? "ok" : "error" }] };
  }

  // Abrir apps (solo las que tú has definido en actions.json)
  const open = t.match(/(?:abre|abrir|ábreme|lanza|inicia)\s+(?:el |la |los |las )?(.+?)[.?!]*$/);
  if (open) {
    const name = open[1].trim();
    const key = Object.keys(conf.apps).find((k) => k.toLowerCase() === name);
    if (!key) return { reply: "No tengo «" + name + "» configurado todavía. Añádelo en actions.json." };
    const cmd = pick(conf.apps[key]);
    if (!cmd) return { reply: "«" + name + "» no tiene comando para este sistema." };
    audit("OPEN", key + " → " + cmd);
    const r = await launch(cmd);
    return { reply: r.ok ? "Abriendo " + key + "." : "No he podido abrir " + key + ".", actions: [{ label: "Abrir " + key, status: r.ok ? "ok" : "error", detail: r.ok ? "" : r.err }] };
  }

  return askLLM(text);
}

/* ---------- HTTP ---------- */
const fails = new Map(); // ip -> {n, until}

function send(res, status, body, extraHeaders) {
  const data = typeof body === "string" ? body : JSON.stringify(body);
  res.writeHead(status, Object.assign({
    "Content-Type": typeof body === "string" ? "text/plain; charset=utf-8" : "application/json; charset=utf-8",
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
  }, extraHeaders));
  res.end(data);
}

function authorized(req, res) {
  const ip = req.socket.remoteAddress;
  const f = fails.get(ip);
  if (f && f.until > Date.now()) { send(res, 429, { error: "Demasiados intentos. Espera un minuto." }); return false; }
  const h = req.headers.authorization || "";
  const given = h.startsWith("Bearer ") ? h.slice(7) : "";
  const a = crypto.createHash("sha256").update(given).digest();
  const b = crypto.createHash("sha256").update(TOKEN).digest();
  if (crypto.timingSafeEqual(a, b)) { fails.delete(ip); return true; }
  const n = (f ? f.n : 0) + 1;
  fails.set(ip, { n, until: n >= 8 ? Date.now() + 60000 : 0 });
  audit("AUTH_FAIL", ip);
  send(res, 401, { error: "Token incorrecto" });
  return false;
}

function readBody(req) {
  return new Promise((resolve, reject) => {
    let d = "";
    req.on("data", (c) => {
      d += c;
      if (d.length > 100000) { reject(Object.assign(new Error("Petición demasiado grande"), { status: 413 })); req.destroy(); }
    });
    req.on("end", () => {
      try { resolve(d ? JSON.parse(d) : {}); } catch { reject(Object.assign(new Error("JSON no válido"), { status: 400 })); }
    });
    req.on("error", reject);
  });
}

// CORS: solo para los orígenes que tú has permitido en ALLOWED_ORIGIN
function cors(req, res) {
  const origin = req.headers.origin;
  if (!origin || !ALLOWED_ORIGINS.includes(origin)) return;
  res.setHeader("Access-Control-Allow-Origin", origin);
  res.setHeader("Vary", "Origin");
  res.setHeader("Access-Control-Allow-Headers", "Authorization, Content-Type");
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, OPTIONS");
  res.setHeader("Access-Control-Allow-Private-Network", "true");
  res.setHeader("Access-Control-Max-Age", "600");
}

async function api(req, res, url) {
  cors(req, res);
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }  // la comprobación previa no lleva token
  if (!authorized(req, res)) return;
  try {
    if (req.method === "GET") {
      switch (url.pathname) {
        case "/api/stats": return send(res, 200, stats());
        case "/api/config": return send(res, 200, Object.assign({ caps: caps() }, config));
        case "/api/apps": return send(res, 200, { apps: await discoverApps(url.searchParams.get("refresh") === "1") });
        case "/api/volume": return send(res, 200, await getVolume());
        case "/api/clipboard": { const r = await clipGet(); return send(res, 200, { ok: r.ok, text: r.ok ? r.out.slice(0, 20000) : "", error: r.ok ? "" : r.err }); }
        case "/api/processes": return send(res, 200, { processes: await topProcesses(), canKill: ALLOW_EXEC });
        case "/api/screenshot": {
          const r = await screenshot();
          if (!r.ok) return send(res, 500, { error: r.err });
          res.writeHead(200, { "Content-Type": "image/png", "Cache-Control": "no-store", "X-Content-Type-Options": "nosniff" });
          return res.end(r.png);
        }
        default: return send(res, 404, { error: "No existe" });
      }
    }
    if (req.method === "PUT" && url.pathname === "/api/config") {
      const next = cleanConfig(await readBody(req));
      saveConfig(next);
      audit("CONFIG", next.scenes.length + " escenas, " + next.sites.length + " sitios");
      return send(res, 200, Object.assign({ caps: caps() }, config));
    }
    if (req.method !== "POST") return send(res, 404, { error: "No existe" });

    const body = await readBody(req);
    switch (url.pathname) {
      case "/api/chat": {
        const text = String(body.text || "").trim().slice(0, 2000);
        if (!text) return send(res, 400, { error: "Mensaje vacío" });
        audit("CHAT", text);
        return send(res, 200, await chat(text));
      }
      case "/api/scene": {
        const r = await runScene(String(body.id || ""));
        return send(res, 200, { ok: r.ok, message: r.message, actions: r.actions || [] });
      }
      case "/api/open": {
        if (body.url) return send(res, 200, await openUrl(String(body.url)));
        if (body.app) return send(res, 200, await openApp(String(body.app)));
        return send(res, 400, { error: "Indica url o app" });
      }
      case "/api/volume": {
        let r;
        if (body.mute) r = await toggleMute();
        else if (body.level != null) r = await setVolume(Number(body.level));
        else if (body.delta != null) r = await stepVolume(Math.max(-100, Math.min(100, Number(body.delta) || 0)));
        else return send(res, 400, { error: "Indica level, delta o mute" });
        return send(res, 200, Object.assign({ ok: r.ok, error: r.ok ? "" : r.err }, await getVolume()));
      }
      case "/api/media": {
        const r = await mediaKey(String(body.key || ""));
        return send(res, 200, { ok: r.ok, error: r.ok ? "" : r.err });
      }
      case "/api/clipboard": {
        const r = await clipSet(String(body.text == null ? "" : body.text).slice(0, 20000));
        return send(res, 200, { ok: r.ok, error: r.ok ? "" : r.err });
      }
      case "/api/kill":
        return send(res, 200, await killProcess(Number(body.pid)));
      case "/api/action": {
        const id = String(body.id || "");
        // Desde el móvil solo se aceptan acciones conocidas (las del servidor o las de actions.json)
        if (!has(conf.actions, id) && !has(DEFAULT_ACTIONS, id)) return send(res, 404, { ok: false, message: "Acción desconocida" });
        return send(res, 200, await runAction(id));
      }
      case "/api/exec": {
        if (!ALLOW_EXEC) return send(res, 200, { output: "", error: "La terminal está desactivada. Pon ALLOW_EXEC=1 en el .env para activarla." });
        const cmd = String(body.cmd || "").slice(0, 1000);
        audit("EXEC", cmd);
        const r = await run(cmd);
        return send(res, 200, { output: r.out, error: r.ok ? "" : r.err });
      }
      default:
        return send(res, 404, { error: "No existe" });
    }
  } catch (e) {
    send(res, e.status || 502, { error: e.message });
  }
}

const MIME = {
  ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8", ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml", ".webmanifest": "application/manifest+json", ".png": "image/png", ".ico": "image/x-icon",
};
const CSP = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data: blob:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'";

function serveStatic(req, res, url) {
  if (req.method !== "GET" && req.method !== "HEAD") return send(res, 405, "Método no permitido");
  let rel;
  try { rel = decodeURIComponent(url.pathname); } catch { return send(res, 400, "Petición no válida"); }
  rel = rel === "/" ? "index.html" : rel.replace(/^\//, "");
  if (!WEB_FILES.has(rel)) return send(res, 404, "No encontrado");   // lista cerrada: nada más se sirve
  const file = path.join(WEB_DIR, rel);
  fs.readFile(file, (err, data) => {
    if (err) return send(res, 404, "No encontrado");
    res.writeHead(200, {
      "Content-Type": MIME[path.extname(file)] || "application/octet-stream",
      "Cache-Control": "no-cache",
      "X-Content-Type-Options": "nosniff",
      "Referrer-Policy": "no-referrer",
      "Content-Security-Policy": CSP,
    });
    res.end(req.method === "HEAD" ? undefined : data);
  });
}

http.createServer((req, res) => {
  try {
    const url = new URL(req.url, "http://localhost");
    if (url.pathname.startsWith("/api/")) return api(req, res, url);
    serveStatic(req, res, url);
  } catch {
    send(res, 500, { error: "Error interno" });
  }
}).listen(PORT, HOST, () => {
  console.log("\nJarvis escuchando en http://" + HOST + ":" + PORT);
  if (DRY_RUN) console.log("MODO PRUEBA: no se ejecuta nada en el PC.");
  console.log("Sistema: " + PLAT + " · terminal " + (ALLOW_EXEC ? "ACTIVADA" : "desactivada") + " · cerebro: " + (JARVIS_CHAT_URL ? JARVIS_CHAT_URL : "Ollama (" + OLLAMA_MODEL + ")"));
  if (ALLOWED_ORIGINS.length) console.log("Orígenes permitidos (CORS): " + ALLOWED_ORIGINS.join(", "));
  if (HOST === "127.0.0.1") console.log("Solo accesible desde este PC. Para el móvil: tailscale serve --bg " + PORT + "\n");
});
