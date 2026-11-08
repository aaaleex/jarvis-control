/* ==========================================================================
   Jarvis · conexión por Supabase (buzón «comandos»)
   Se carga después de app.js y usa sus utilidades ($, toast, askConfirm, setConn…).

   Con sesión iniciada, todo lo que dices o escribes en el orbe:
     1. se inserta como fila «pendiente» en la tabla comandos (solo con la clave pública + tu sesión)
     2. el PC la recoge por Realtime, la pasa a «ejecutando» y luego a «hecho» / «error» con la respuesta
     3. aquí se sigue en directo (Realtime, y cada 3 s una consulta por si se cortó)
   Si Jarvis pregunta «¿seguro?» la fila queda en «confirmar»: sale el diálogo y se envía «sí» o «no».
   La URL y la clave pública vienen de config.js (lo genera build.js en Vercel). Sin config.js, no hace nada.
   ========================================================================== */
var nube = (() => {   // var: así app.js puede comprobar window.nube aunque este archivo no exista
  const conf = window.JARVIS_SUPABASE || {};
  const cliente = conf.url && conf.key && window.supabase
    ? window.supabase.createClient(conf.url, conf.key, { auth: { persistSession: true, autoRefreshToken: true } })
    : null;

  let sesion = null;
  let canal = null;
  let conectado = false;
  const esperas = new Map();                 // id de fila -> función que recibe cada cambio
  const FINALES = ["hecho", "error", "confirmar"];

  /* ---------- sesión ---------- */
  async function iniciar() {
    if (!cliente) return;
    const { data } = await cliente.auth.getSession();
    cambiarSesion(data.session);
    cliente.auth.onAuthStateChange((_evento, s) => cambiarSesion(s));
    if (!sesion) abrirLogin();
  }

  function cambiarSesion(s) {
    const antes = sesion && sesion.user.id;
    sesion = s;
    pintarCuenta();
    if ((s && s.user.id) === antes) return;
    if (canal) { cliente.removeChannel(canal); canal = null; conectado = false; }
    if (s) suscribir();
    refreshStats();
  }

  // Cambios en directo de MIS filas (RLS: el servidor solo me envía las mías)
  function suscribir() {
    canal = cliente
      .channel("mis-comandos")
      .on("postgres_changes", { event: "*", schema: "public", table: "comandos", filter: "user_id=eq." + sesion.user.id },
        (cambio) => recibir(cambio.new))
      .subscribe((estado) => {
        conectado = estado === "SUBSCRIBED";
        refreshStats();
      });
  }

  function recibir(fila) {
    if (!fila || !fila.id) return;
    const f = esperas.get(fila.id);
    if (f) f(fila);
    if (historyDialog.open && activa()) pintarHistorial($("#historyList"));
  }

  /* ---------- enviar una orden y esperar su resultado ---------- */
  async function insertar(texto) {
    const { data, error } = await cliente.from("comandos").insert({ texto }).select().single();
    if (error) throw new Error(error.message);
    return data;
  }

  // Espera a que la fila llegue a hecho / error / confirmar. Si el PC no la recoge en 20 s, avisa.
  function seguir(id) {
    return new Promise((resolve) => {
      const inicio = Date.now();
      let fin = false;
      const terminar = (fila) => {
        if (fin) return;
        fin = true;
        esperas.delete(id);
        clearInterval(sondeo);
        resolve(fila);
      };
      const mirar = (fila) => {
        if (fila.estado === "ejecutando") setPhase("executing");
        if (FINALES.includes(fila.estado)) terminar(fila);
      };
      esperas.set(id, mirar);
      const sondeo = setInterval(async () => {
        const { data } = await cliente.from("comandos").select("*").eq("id", id).maybeSingle();
        if (data) mirar(data);
        const segundos = (Date.now() - inicio) / 1000;
        if (!fin && data && data.estado === "pendiente" && segundos > 20)
          terminar({ ...data, estado: "sin_pc" });
        else if (!fin && segundos > 130)
          terminar({ ...(data || {}), estado: "sin_pc" });
      }, 3000);
    });
  }

  async function chat(texto) {
    let fila = await insertar(texto);
    const id = fila.id;
    fila = await seguir(id);
    // Jarvis pide confirmación: diálogo Sí/No y la respuesta va como una orden más
    while (fila.estado === "confirmar") {
      const ok = await askConfirm(fila.respuesta || "¿Seguro?");
      await insertar(ok ? "sí" : "no");
      fila = await seguir(id);
    }
    if (fila.estado === "sin_pc")
      return { reply: "Tu PC no ha recogido la orden (¿está apagado o sin internet?). Si se enciende antes de 1 hora, la hará; míralo en el registro." };
    if (fila.estado === "error")
      return { reply: fila.respuesta || "Ha fallado en el PC.", actions: [{ label: "Error en el PC", detail: fila.respuesta || "", status: "error" }] };
    return { reply: fila.respuesta || "Hecho.", actions: fila.acciones || [] };
  }

  /* ---------- historial (de Supabase) ---------- */
  const ETIQUETAS = { pendiente: "PENDIENTE", ejecutando: "EJECUTANDO", confirmar: "ESPERA TU OK", hecho: "HECHO", error: "ERROR" };

  async function pintarHistorial(lista) {
    const { data, error } = await cliente.from("comandos").select("*").order("created_at", { ascending: false }).limit(50);
    lista.innerHTML = "";
    if (error) return (lista.textContent = "No puedo leer el historial: " + error.message);
    if (!data.length) {
      lista.innerHTML = '<div class="log-empty">Todavía no hay comandos</div>';
      return;
    }
    for (const c of data.reverse()) {
      const yo = document.createElement("div");
      yo.className = "log-line user";
      const cab = document.createElement("small");
      const hora = new Date(c.created_at).toLocaleString("es-ES", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
      cab.textContent = "TÚ · " + hora + " · ";
      const etiqueta = document.createElement("b");
      etiqueta.className = "log-estado " + c.estado;
      etiqueta.textContent = ETIQUETAS[c.estado] || c.estado;
      cab.appendChild(etiqueta);
      yo.append(cab, document.createTextNode(c.texto));
      lista.appendChild(yo);
      if (c.respuesta) {
        const el = document.createElement("div");
        el.className = "log-line bot";
        const quien = document.createElement("small");
        quien.textContent = "JARVIS";
        el.append(quien, document.createTextNode(c.respuesta));
        lista.appendChild(el);
      }
    }
    lista.scrollTop = lista.scrollHeight;
  }

  /* ---------- login ---------- */
  const loginDialog = $("#loginDialog");

  function abrirLogin() {
    $("#loginError").textContent = "";
    if (!loginDialog.open) loginDialog.showModal();
  }

  $("#loginForm").addEventListener("submit", async (e) => {
    e.preventDefault();
    const boton = $("#loginBtn");
    boton.disabled = true;
    $("#loginError").textContent = "";
    const { error } = await cliente.auth.signInWithPassword({
      email: $("#loginEmail").value.trim(),
      password: $("#loginPass").value,
    });
    boton.disabled = false;
    if (error) {
      $("#loginError").textContent = error.message === "Invalid login credentials" ? "Correo o contraseña incorrectos." : error.message;
      return;
    }
    $("#loginPass").value = "";
    loginDialog.close();
    toast("Sesión iniciada");
  });
  $("#loginCancel").addEventListener("click", () => loginDialog.close());

  function pintarCuenta() {
    const caja = $("#accountRow");
    if (!caja) return;
    caja.hidden = !cliente;
    $("#accountText").textContent = sesion ? sesion.user.email : "Sin sesión";
    $("#accountBtn").textContent = sesion ? "Cerrar sesión" : "Iniciar sesión";
  }
  $("#accountBtn").addEventListener("click", async () => {
    if (sesion) {
      await cliente.auth.signOut();
      toast("Sesión cerrada");
    } else {
      settingsDialog.close();
      abrirLogin();
    }
  });

  const activa = () => !!(cliente && sesion);
  const api = { activa, conectada: () => conectado, chat, pintarHistorial, configurada: () => !!cliente };
  if (cliente) iniciar();
  pintarCuenta();
  return api;
})();
