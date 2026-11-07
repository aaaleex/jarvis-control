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
const PLAT = process.platform; // "win32" | "linux" | "darwin"
// La app (index.html, app.js…) está en la carpeta de arriba. Solo se sirven estos archivos.
const WEB_DIR = process.env.WEB_DIR ? path.resolve(process.env.WEB_DIR) : path.join(__dirname, "..");
const WEB_FILES = new Set(["index.html", "styles.css", "app.js", "sw.js", "manifest.webmanifest", "icon.svg"]);
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

  // Escenas
  if (/\b(modo|escena|activa|pon)\b/.test(t)) {
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
  res.setHeader("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  res.setHeader("Access-Control-Allow-Private-Network", "true");
  res.setHeader("Access-Control-Max-Age", "600");
}

async function api(req, res, url) {
  cors(req, res);
  if (req.method === "OPTIONS") { res.writeHead(204); return res.end(); }  // la comprobación previa no lleva token
  if (!authorized(req, res)) return;
  try {
    if (req.method === "GET" && url.pathname === "/api/stats") return send(res, 200, stats());
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
        return send(res, 200, { ok: r.ok, message: r.message });
      }
      case "/api/action":
        return send(res, 200, await runAction(String(body.id || "")));
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
const CSP = "default-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'";

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
  console.log("Sistema: " + PLAT + " · terminal " + (ALLOW_EXEC ? "ACTIVADA" : "desactivada") + " · cerebro: " + (JARVIS_CHAT_URL ? JARVIS_CHAT_URL : "Ollama (" + OLLAMA_MODEL + ")"));
  if (ALLOWED_ORIGINS.length) console.log("Orígenes permitidos (CORS): " + ALLOWED_ORIGINS.join(", "));
  if (HOST === "127.0.0.1") console.log("Solo accesible desde este PC. Para el móvil: tailscale serve --bg " + PORT + "\n");
});
