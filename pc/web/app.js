/* ================================================================
   J.A.R.V.I.S. — ventana del orbe (JavaScript puro)
   Solo el orbe: estados, niveles y espectro de audio, subtítulo opcional.
   Ratón: arrastrar desde el orbe la mueve · clic: hablar · clic derecho: panel de ajustes/escenas/pantallas.
   Teclado: Esc oculta (o dice «no» a una confirmación) · Intro dice «sí» a una confirmación.
   ================================================================ */
const $ = (s) => document.querySelector(s);
let ws = null, estado = "iniciando", ajustes = {}, textoActual = "", confirmando = false, temporizadorSub = null;

// Los errores de JavaScript van al log de Jarvis (datos/jarvis.log)
window.addEventListener("error", (e) => enviar({ tipo: "error_js", texto: `${e.message} (${e.filename}:${e.lineno})` }));
window.addEventListener("unhandledrejection", (e) => enviar({ tipo: "error_js", texto: String(e.reason) }));

const orbe = () => window.orbe || { estado() {}, nivelMic() {}, nivelVoz() {}, espectro() {}, visible() {}, calidad() {}, estilo() {}, sombra() {}, aparecer() {}, info: {} };

function ponerEstado(nuevo) {
  estado = nuevo;
  orbe().estado(nuevo);
}

/* ---------------- Subtítulo (opcional: interfaz.subtitulos) ---------------- */
function subtitulo(texto, deUsuario = false, duracion = 7000) {
  const p = $("#subtitulo");
  clearTimeout(temporizadorSub);
  if (!texto) { p.classList.remove("visible"); return; }
  p.textContent = texto;
  p.classList.toggle("usuario", deUsuario);
  p.classList.add("visible");
  if (duracion) temporizadorSub = setTimeout(() => p.classList.remove("visible"), duracion);
}

/* ---------------- Ratón: arrastrar, clic (hablar), clic derecho (panel) ---------------- */
let arrastre = null;
document.addEventListener("mousedown", (e) => {
  if (e.button !== 0) return;
  arrastre = { x: e.clientX, y: e.clientY, sx: e.screenX, sy: e.screenY, movido: false };
});
document.addEventListener("mousemove", (e) => {
  if (!arrastre) return;
  if (!arrastre.movido && Math.hypot(e.screenX - arrastre.sx, e.screenY - arrastre.sy) < 4) return;
  arrastre.movido = true;
  // Mover la ventana con la función interna de pywebview (la misma que usan sus «zonas de arrastre»)
  window.pywebview?._jsApiCallback?.("pywebviewMoveWindow", [e.screenX - arrastre.x, e.screenY - arrastre.y], "move");
});
document.addEventListener("mouseup", () => {
  if (arrastre && !arrastre.movido) enviar({ tipo: "microfono" });  // clic en el orbe: te escucho
  if (arrastre?.movido) enviar({ tipo: "ventana", accion: "movida" });
  arrastre = null;
});
document.addEventListener("contextmenu", (e) => { e.preventDefault(); enviar({ tipo: "panel" }); });

/* ---------------- Teclado ---------------- */
document.addEventListener("keydown", (e) => {
  if (confirmando && (e.key === "Enter" || e.key === "Escape")) {
    enviar({ tipo: "confirmar", si: e.key === "Enter" });
    return;
  }
  if (e.key === "Escape") {
    if (estado === "hablando" || estado === "pensando") enviar({ tipo: "parar" });
    enviar({ tipo: "ventana", accion: "ocultar" });
  }
});

/* ---------------- Ajustes que afectan al orbe ---------------- */
function aplicarAjustes(a) {
  ajustes = a;
  orbe().estilo(a.estilo_orbe || "nucleo");
  orbe().calidad(a.orbe_calidad || "auto");
  orbe().sombra(a.sombra_orbe === false ? 0 : 0.72);
  document.body.classList.toggle("sin-subtitulos", !a.subtitulos);
}

/* ---------------- Conexión ---------------- */
function enviar(o) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(o)); }

function alMensaje(d) {
  switch (d.tipo) {
    case "inicial":
      aplicarAjustes(d.ajustes);
      document.body.classList.toggle("opaco", d.transparente === false);
      if (d.dormido) { ponerEstado("reposo"); orbe().visible(false); }
      else ponerEstado(d.carga.listo ? "reposo" : "despertando");
      break;
    case "ventana_transparente": document.body.classList.toggle("opaco", !d.transparente); break;
    case "despertando": ponerEstado("despertando"); orbe().aparecer(); break;
    case "mostrar": orbe().aparecer(); break;
    case "visibilidad":
      if (d.visible) enviar({ tipo: "diag", texto: `visibilidad recibida (document.hidden=${document.hidden})` });
      orbe().visible(d.visible); if (!d.visible) subtitulo(""); break;
    case "listo": if (estado === "despertando" || estado === "iniciando") ponerEstado("reposo"); break;
    case "error_fatal": ponerEstado("error"); subtitulo(d.texto, false, 0); break;
    case "estado": ponerEstado(d.estado); break;
    case "activado": subtitulo("Te escucho…", true, 0); break;
    case "usuario": textoActual = ""; subtitulo(`«${d.texto}»`, true); break;
    case "texto_parcial": textoActual += d.texto; subtitulo(textoActual, false, 0); break;
    case "respuesta": if (d.texto) subtitulo(d.texto); textoActual = ""; break;
    case "nivel_mic": orbe().nivelMic(d.nivel); if (d.espectro) orbe().espectro("mic", d.espectro); break;
    case "nivel_voz": orbe().nivelVoz(d.nivel); if (d.espectro) orbe().espectro("voz", d.espectro); break;
    case "ajustes": aplicarAjustes(d.ajustes); break;
    case "confirmar": confirmando = true; subtitulo(`${d.pregunta}  ·  di «sí» o «no» (Intro / Esc)`, false, 0); break;
    case "confirmar_fin": confirmando = false; subtitulo(""); break;
    case "aviso": subtitulo(d.texto, false, 10000); break;
    case "error": subtitulo(d.texto, false, 8000); break;
    case "interrumpido": textoActual = ""; break;
    case "demo": orbe().simular?.(d.simular); break;
    case "subtitulo": subtitulo(d.texto); break;
    case "diag_pedir":  // diagnóstico (GET /api/diag): estado real de la página y del orbe, al log
      enviar({ tipo: "diag", texto: JSON.stringify({ hidden: document.hidden, visibilidad: document.visibilityState,
        tam: [innerWidth, innerHeight], orbe: !!window.orbe, info: orbe().info, estado, webgl: !document.body.classList.contains("sin-webgl") }) });
      break;
  }
}
function conectar() {
  ws = new WebSocket(`ws://${location.host}/ws?vista=orbe`);
  ws.onmessage = (e) => alMensaje(JSON.parse(e.data));
  ws.onclose = () => setTimeout(conectar, 1500);
}
conectar();
// Diagnóstico de la aparición: cuándo se pinta el primer fotograma tras mostrarse (va al log)
window.alPrimerFotograma = () => enviar({ tipo: "diag", texto: `primer fotograma (document.hidden=${document.hidden})` });
document.addEventListener("visibilitychange", () => enviar({ tipo: "diag", texto: `visibilitychange hidden=${document.hidden}` }));
