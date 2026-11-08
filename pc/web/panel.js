/* ================================================================
   Panel de Jarvis (ventana aparte): actividad, escenas, pantallas y ajustes.
   Se abre con clic derecho en el orbe o desde el menú del icono de la bandeja.
   ================================================================ */
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);
const ESTADOS = { reposo: "En espera", escuchando: "Escuchando", pensando: "Pensando", hablando: "Hablando",
  iniciando: "Iniciando", despertando: "Despertando", error: "Error" };
let ws = null, ajustes = {}, burbuja = null, textoActual = "";
let pantallas = { pantallas: [], ventanas: [] };

window.addEventListener("error", (e) => enviar({ tipo: "error_js", texto: `panel: ${e.message} (${e.filename}:${e.lineno})` }));
window.addEventListener("unhandledrejection", (e) => enviar({ tipo: "error_js", texto: `panel: ${String(e.reason)}` }));

/* ---------------- Navegación ---------------- */
function irA(seccion) {
  $$("#menu button").forEach((b) => b.classList.toggle("activa", b.dataset.seccion === seccion));
  $$(".seccion").forEach((s) => s.classList.toggle("activa", s.id === seccion));
  if (seccion === "pantallas") enviar({ tipo: "pantallas" });
  if (seccion === "escenas") enviar({ tipo: "escenas" });
}
$$("#menu button").forEach((b) => (b.onclick = () => irA(b.dataset.seccion)));

/* ---------------- Conversación ---------------- */
const hora = () => new Date().toLocaleTimeString("es-ES", { hour: "2-digit", minute: "2-digit" });
function mensaje(clase, texto, etiqueta) {
  $("#mensajes .vacio")?.remove();
  const div = document.createElement("div");
  div.className = `msg ${clase}`;
  div.innerHTML = "<small></small><span></span>";
  div.querySelector("small").textContent = `${etiqueta} · ${hora()}`;
  div.querySelector("span").textContent = texto;
  $("#mensajes").append(div);
  $("#mensajes").scrollTop = 1e9;
  while ($("#mensajes").children.length > 150) $("#mensajes").firstChild.remove();
  return div.querySelector("span");
}
function trozo(t) {
  if (!burbuja) { burbuja = mensaje("jarvis", "", "Jarvis"); textoActual = ""; }
  textoActual += t;
  burbuja.textContent = textoActual;
}
function respuestaFinal(texto, rapido) {
  if (burbuja) burbuja.textContent = texto || textoActual;
  else if (texto) mensaje("jarvis", texto, rapido ? "Jarvis · camino rápido" : "Jarvis");
  burbuja = null; textoActual = "";
}

/* ---------------- Acciones ---------------- */
const enCurso = {};
function accionInicio(d) {
  const lista = $("#lista-acciones");
  lista.querySelector(".vacio")?.remove();
  const li = document.createElement("li");
  li.className = "corriendo";
  li.innerHTML = "<b></b><time></time><p></p>";
  li.querySelector("b").textContent = d.nombre.replaceAll("_", " ");
  if (d.rapido) li.querySelector("b").insertAdjacentHTML("beforeend", '<span class="etiqueta">rápido</span>');
  li.querySelector("time").textContent = hora();
  li.querySelector("p").textContent = Object.entries(d.argumentos || {}).filter(([, v]) => v !== null && v !== "").map(([k, v]) => `${k}: ${v}`).join(" · ");
  lista.prepend(li);
  enCurso[d.nombre] = li;
  while (lista.children.length > 60) lista.lastChild.remove();
}
function accionFin(d) {
  const li = enCurso[d.nombre];
  if (!li) return;
  li.className = d.ok ? "ok" : "fallo";
  li.querySelector("p").textContent = d.resultado || "";
  li.title = d.resultado || "";
  delete enCurso[d.nombre];
}
function sistema(d) {
  $("#v-cpu").textContent = `${Math.round(d.cpu)} %`;
  $("#v-ram").textContent = `${d.ram_usada} / ${d.ram_total} GB`;
  if (d.gpu) {
    $("#v-gpu").textContent = `${d.gpu.uso} % · ${d.gpu.temp} °C`;
    $("#v-vram").textContent = `${d.gpu.vram_usada.toFixed(1)} / ${d.gpu.vram_total.toFixed(0)} GB`;
  }
}

/* ---------------- Pantallas ---------------- */
function dibujarPantallas(d) {
  pantallas = d;
  const mapa = $("#mapa-pantallas");
  mapa.innerHTML = "";
  if (!d.pantallas.length) return;
  const minX = Math.min(...d.pantallas.map((p) => p.x)), minY = Math.min(...d.pantallas.map((p) => p.y));
  const maxX = Math.max(...d.pantallas.map((p) => p.x + p.ancho)), maxY = Math.max(...d.pantallas.map((p) => p.y + p.alto));
  const W = mapa.clientWidth - 24, H = mapa.clientHeight - 24;
  const e = Math.min(W / (maxX - minX), H / (maxY - minY));
  const ox = 12 + (W - (maxX - minX) * e) / 2, oy = 12 + (H - (maxY - minY) * e) / 2;
  for (const p of d.pantallas) {
    const div = document.createElement("div");
    div.className = "mini-pantalla" + (p.principal ? " principal" : "");
    Object.assign(div.style, { left: `${ox + (p.x - minX) * e}px`, top: `${oy + (p.y - minY) * e}px`, width: `${p.ancho * e - 4}px`, height: `${p.alto * e - 4}px` });
    div.innerHTML = "<span></span>";
    div.querySelector("span").textContent = `${p.numero}${p.nombre ? " · " + p.nombre : ""}${p.principal ? " · principal" : ""}`;
    d.ventanas.filter((v) => v.pantalla === p.numero).reverse().forEach((v) => {
      const w = document.createElement("div");
      w.className = "mini-ventana";
      Object.assign(w.style, { left: `${Math.max(0, (v.x - p.x) * e)}px`, top: `${Math.max(0, (v.y - p.y) * e)}px`,
        width: `${Math.min(p.ancho, v.ancho) * e}px`, height: `${Math.min(p.alto, v.alto) * e}px` });
      w.textContent = v.proceso;
      w.title = v.titulo;
      div.append(w);
    });
    mapa.append(div);
  }
  const lista = $("#lista-pantallas");
  lista.innerHTML = "";
  for (const p of d.pantallas) {
    const fila = document.createElement("div");
    fila.className = "fila-pantalla";
    fila.innerHTML = "<b></b><input placeholder=\"Nombre propio (opcional)\"><small></small>";
    fila.querySelector("b").textContent = `Pantalla ${p.numero}`;
    fila.querySelector("small").textContent = `${p.principal ? "principal · " : ""}${p.posicion} · ${p.ancho}×${p.alto} · escala ${p.escala} %`;
    const input = fila.querySelector("input");
    input.value = p.nombre || "";
    input.onchange = () => enviar({ tipo: "renombrar_pantalla", numero: p.numero, nombre: input.value.trim() });
    lista.append(fila);
  }
}
$("#btn-refrescar-pantallas").onclick = () => enviar({ tipo: "pantallas" });

/* ---------------- Escenas ---------------- */
function dibujarEscenas(lista) {
  const cont = $("#lista-escenas");
  cont.innerHTML = lista.length ? "" : '<p class="vacio">No hay escenas todavía.</p>';
  for (const e of lista) {
    const div = document.createElement("div");
    div.className = "escena";
    div.innerHTML = `<header><b></b><button class="mini">Probar</button><button class="mini secundario">Editar</button><button class="mini secundario">Borrar</button></header><div class="frases"></div><div class="pasos"></div>`;
    div.querySelector("b").textContent = e.clave.replaceAll("_", " ");
    div.querySelector(".frases").textContent = `«${e.frases.join("», «")}»`;
    div.querySelector(".pasos").textContent = e.accion === "cerrar_anterior" ? "Cierra lo que abrió la última escena"
      : e.pasos.map((p) => `${p.abrir} → pantalla ${p.pantalla || "—"}, ${(p.tamano || "").replace("_", " ")}`).join("   ·   ");
    const [probar, editar, borrar] = div.querySelectorAll("button");
    probar.onclick = () => enviar({ tipo: "probar_escena", clave: e.clave });
    editar.onclick = () => abrirEditor(e);
    borrar.onclick = () => { if (confirm(`¿Borrar la escena «${e.clave}»?`)) enviar({ tipo: "borrar_escena", clave: e.clave }); };
    if (e.accion === "cerrar_anterior") editar.remove();
    cont.append(div);
  }
}
function filaPaso(p = {}) {
  const fila = document.createElement("div");
  fila.className = "paso-editor";
  fila.innerHTML = `<input placeholder="app o web" class="p-abrir"><select class="p-pantalla"></select><select class="p-tamano"></select><button class="mini secundario">Quitar</button>`;
  const opciones = ["principal", "izquierda", "centro", "derecha", ...pantallas.pantallas.map((x) => String(x.numero))];
  fila.querySelector(".p-pantalla").innerHTML = opciones.map((o) => `<option>${o}</option>`).join("");
  fila.querySelector(".p-tamano").innerHTML = ["maximizar", "mitad_izquierda", "mitad_derecha", "centrar", "normal"].map((o) => `<option value="${o}">${o.replace("_", " ")}</option>`).join("");
  fila.querySelector(".p-abrir").value = p.abrir || "";
  fila.querySelector(".p-pantalla").value = p.pantalla || "principal";
  fila.querySelector(".p-tamano").value = p.tamano || "maximizar";
  fila.querySelector("button").onclick = () => fila.remove();
  $("#esc-pasos").append(fila);
}
function abrirEditor(e = { clave: "", frases: [], pasos: [] }) {
  if (!pantallas.pantallas.length) enviar({ tipo: "pantallas" });
  $("#editor-escena").classList.remove("oculto");
  $("#btn-nueva-escena").classList.add("oculto");
  $("#esc-clave").value = e.clave;
  $("#esc-frases").value = e.frases.join(", ");
  $("#esc-pasos").innerHTML = "";
  (e.pasos.length ? e.pasos : [{}]).forEach(filaPaso);
}
function cerrarEditor() { $("#editor-escena").classList.add("oculto"); $("#btn-nueva-escena").classList.remove("oculto"); }
$("#btn-nueva-escena").onclick = () => abrirEditor();
$("#esc-anadir").onclick = () => filaPaso();
$("#esc-cancelar").onclick = cerrarEditor;
$("#esc-guardar").onclick = () => {
  const clave = $("#esc-clave").value.trim();
  if (!clave) { toast("Ponle un nombre a la escena."); return; }
  const pasos = [...$$("#esc-pasos .paso-editor")].map((f) => ({
    abrir: f.querySelector(".p-abrir").value.trim(), pantalla: f.querySelector(".p-pantalla").value, tamano: f.querySelector(".p-tamano").value,
  })).filter((p) => p.abrir);
  const frases = $("#esc-frases").value.split(",").map((s) => s.trim()).filter(Boolean);
  enviar({ tipo: "guardar_escena", clave, frases: frases.length ? frases : [clave.replaceAll("_", " ")], pasos });
  cerrarEditor();
};

/* ---------------- Ajustes ---------------- */
function rellenar(sel, opciones, actual) {
  sel.innerHTML = "";
  opciones.forEach((o) => { const op = document.createElement("option"); op.value = o; op.textContent = o; sel.append(op); });
  sel.value = actual;
}
function mostrarAjustes(a) {
  ajustes = a;
  rellenar($("#sel-modelo"), a.modelos || [], a.modelo);
  rellenar($("#sel-voz"), a.voces || [], a.voz_edge);
  rellenar($("#sel-personalidad"), a.personalidades || [], a.personalidad);
  $$("[data-ajuste]").forEach((el) => {
    const v = a[el.dataset.ajuste];
    if (v === undefined) return;
    if (el.type === "checkbox") el.checked = !!v;
    else if (document.activeElement !== el) el.value = v;
  });
  $("#nota-atajos").textContent = `Atajo global: ${a.atajo} (se cambia en config.yaml › vigilante.atajo). Clic derecho en el orbe abre este panel.`;
}
$$("[data-ajuste]").forEach((el) => el.addEventListener("change", () => {
  let v = el.type === "checkbox" ? el.checked : el.value;
  if (el.type === "range" || el.inputMode === "numeric") v = Number(v) || 0;
  enviar({ tipo: "ajuste", clave: el.dataset.ajuste, valor: v });
}));

function toast(texto, tipo = "") {
  const d = document.createElement("div");
  d.className = `toast ${tipo}`;
  d.textContent = texto;
  $("#avisos").append(d);
  setTimeout(() => d.remove(), 6000);
}

/* ---------------- Conexión ---------------- */
function enviar(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }
function historial(d) {
  if (d.tipo === "usuario") mensaje("usuario", d.texto, "Tú");
  else if (d.tipo === "respuesta") mensaje("jarvis", d.texto, "Jarvis");
  else if (d.tipo === "herramienta_inicio") accionInicio(d);
  else if (d.tipo === "herramienta_fin") accionFin(d);
  else if (d.tipo === "error") mensaje("error", d.texto, "Sistema");
  else if (d.tipo === "aviso") mensaje("sistema", d.texto, "Aviso");
}
function alMensaje(d) {
  switch (d.tipo) {
    case "inicial":
      mostrarAjustes(d.ajustes);
      $("#mensajes").innerHTML = "";
      d.historial.forEach(historial);
      if (!$("#mensajes").children.length) $("#mensajes").innerHTML = '<p class="vacio">Todavía no hay conversación.</p>';
      if (d.seccion) irA(d.seccion);
      break;
    case "ir_a": irA(d.seccion); break;
    case "estado": $("#texto-estado").textContent = ESTADOS[d.estado] || d.estado; break;
    case "usuario": respuestaFinal(""); mensaje("usuario", d.texto, { voz: "Tú · voz", telegram: "Tú · móvil", sistema: "Automático" }[d.origen] || "Tú"); break;
    case "texto_parcial": trozo(d.texto); break;
    case "respuesta": respuestaFinal(d.texto, d.rapido); break;
    case "herramienta_inicio": accionInicio(d); break;
    case "herramienta_fin": accionFin(d); break;
    case "sistema": sistema(d); break;
    case "ajustes": mostrarAjustes(d.ajustes); break;
    case "pantallas": dibujarPantallas(d); break;
    case "escenas": dibujarEscenas(d.lista || []); break;
    case "escena_lista": toast(`Escena lista en ${d.segundos} s` + (d.fallos?.length ? ` (avisos: ${d.fallos.join(" ")})` : "")); break;
    case "aviso": mensaje("sistema", d.texto, "Aviso"); toast(d.texto); break;
    case "aviso_ui": toast(d.texto); break;
    case "error": mensaje("error", d.texto, "Sistema"); toast(d.texto, "error"); break;
    case "info_orbe": $("#info-orbe").textContent = d.texto; break;
  }
}
function conectar() {
  ws = new WebSocket(`ws://${location.host}/ws?vista=panel`);
  ws.onopen = () => { document.body.classList.add("conectado"); $("#texto-estado").textContent = "Conectado"; };
  ws.onmessage = (e) => alMensaje(JSON.parse(e.data));
  ws.onclose = () => { document.body.classList.remove("conectado"); $("#texto-estado").textContent = "Reconectando"; setTimeout(conectar, 1500); };
}
conectar();
$("#chat").addEventListener("submit", (e) => {
  e.preventDefault();
  const t = $("#entrada").value.trim();
  if (!t) return;
  enviar({ tipo: "texto", texto: t });
  $("#entrada").value = "";
});
document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !$("#editor-escena").classList.contains("oculto")) cerrarEditor(); });
