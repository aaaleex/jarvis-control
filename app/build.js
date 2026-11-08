/* Genera config.js con la URL y la clave PÚBLICA de Supabase a partir de variables de entorno.
   En Vercel se ejecuta solo (vercel.json). En local:  SUPABASE_URL=... SUPABASE_ANON_KEY=... node build.js
   Variables: SUPABASE_URL y SUPABASE_ANON_KEY (también valen VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY).
   La clave pública (anon o sb_publishable_...) puede estar en el navegador: lo que protege los datos es RLS.
   La service role (sb_secret_... o JWT con role=service_role) NUNCA: si la ves aquí, el build falla. */
const fs = require("fs");
const path = require("path");

const url = (process.env.SUPABASE_URL || process.env.VITE_SUPABASE_URL || "").trim().replace(/\/$/, "");
const key = (process.env.SUPABASE_ANON_KEY || process.env.VITE_SUPABASE_ANON_KEY || "").trim();

function esSecreta(k) {
  if (k.startsWith("sb_secret_")) return true;
  if (!k.startsWith("eyJ")) return false;
  try {
    return JSON.parse(Buffer.from(k.split(".")[1], "base64url").toString()).role === "service_role";
  } catch {
    return false;
  }
}

if (esSecreta(key)) {
  console.error("\nSUPABASE_ANON_KEY contiene la clave SECRETA (service role). Pon la anon / publishable.\n");
  process.exit(1);
}
if (!url || !key) console.warn("Sin SUPABASE_URL / SUPABASE_ANON_KEY: la app funcionará sin Supabase (demo o servidor).");

fs.writeFileSync(path.join(__dirname, "config.js"),
  "// Generado por build.js. No editar.\nwindow.JARVIS_SUPABASE = " + JSON.stringify(url && key ? { url, key } : {}) + ";\n");
console.log("config.js generado" + (url ? " para " + url : " (vacío)"));
