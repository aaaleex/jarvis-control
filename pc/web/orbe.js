/* ================================================================
   J.A.R.V.I.S. — orbe 3D (Three.js r170 local, shaders propios)

   Tres estilos (config.yaml › interfaz.estilo_orbe):
     nucleo : esfera de energía deformable (normales calculadas en el shader), núcleo volumétrico
              con raymarching, partículas finas y onda circular que sigue el espectro de la voz.
     anillo : anillo de partículas que se abre con el espectro, alrededor de un núcleo.
     malla  : esfera de líneas (meridianos y paralelos) ondulante con núcleo.
   Postproceso propio: bloom en 5 niveles, aberración cromática muy leve, curva tonal suave
   y tramado (dithering) para que los degradados no hagan bandas. Salida con alfa real
   (premultiplicada) para flotar sobre el escritorio.

   API (window.orbe): estado(n), nivelMic(v), nivelVoz(v), espectro(fuente, [16 bandas 0-1]),
   visible(bool), calidad(auto|alta|media|baja), estilo(nucleo|anillo|malla), simular(bool), info
   ================================================================ */
import * as THREE from "./lib/three.module.min.js";

const lienzo = document.getElementById("orbe");

// ---------- Estados: color de acento, energía, frecuencia del ruido, remolino, tamaño ----------
const ESTADOS = {
  reposo:      { a: "#3fc8ff", b: "#0b2f7a", energia: 0.22, frec: 1.15, remolino: 0.0, tam: 1.0,  brillo: 0.85, vel: 0.35 },
  escuchando:  { a: "#5ad8ff", b: "#0d3a8c", energia: 0.45, frec: 1.35, remolino: 0.15, tam: 0.93, brillo: 1.05, vel: 0.55 },
  pensando:    { a: "#7fe3ff", b: "#123f94", energia: 0.55, frec: 2.1,  remolino: 1.0, tam: 0.97, brillo: 1.0,  vel: 0.9 },
  hablando:    { a: "#4fd8ff", b: "#0d3a8c", energia: 0.5,  frec: 1.3,  remolino: 0.2, tam: 1.02, brillo: 1.1,  vel: 0.6 },
  error:       { a: "#ffb86b", b: "#6e2a12", energia: 0.3,  frec: 1.2,  remolino: 0.0, tam: 0.97, brillo: 0.85, vel: 0.35 },
  iniciando:   { a: "#3fc8ff", b: "#0b2f7a", energia: 0.3,  frec: 1.2,  remolino: 0.3, tam: 0.96, brillo: 0.7,  vel: 0.5 },
  despertando: { a: "#6fdcff", b: "#0d3a8c", energia: 0.45, frec: 1.3,  remolino: 0.25, tam: 1.0, brillo: 1.0,  vel: 0.6 },
};
const CALIDADES = {
  alta:  { pixeles: Math.min(window.devicePixelRatio || 1, 1.25), pasos: 18, particulas: 1.0, muestras: 4 },
  media: { pixeles: 0.85, pasos: 12, particulas: 0.6, muestras: 2 },
  baja:  { pixeles: 0.6,  pasos: 7,  particulas: 0.3, muestras: 0 },
};

// ---------- GLSL compartido: ruido simplex 3D (Ashima Arts, dominio público) + fbm ----------
const RUIDO = `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0); const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy)); vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz); vec3 l=1.0-g; vec3 i1=min(g.xyz,l.zxy); vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx; vec3 x2=x0-i2+C.yyy; vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857; vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z); vec4 x_=floor(j*ns.z); vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy; vec4 y=y_*ns.x+ns.yyyy; vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy); vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0; vec4 s1=floor(b1)*2.0+1.0; vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy; vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x); vec3 p1=vec3(a0.zw,h.y); vec3 p2=vec3(a1.xy,h.z); vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x; p1*=norm.y; p2*=norm.z; p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0); m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
`;
// Deformación de la superficie: ruido con el dominio deformado por otro ruido (más orgánico que un ruido simple)
// y un remolino que gira las capas a distinta velocidad según la latitud (estado «pensando»).
const DEFORMACION = `
uniform float uTiempo, uFrec, uRemolino, uAmp, uNivel;
uniform float uEsp[16];
float banda(float x){ // x 0-1 -> espectro suavizado
  float f = clamp(x, 0.0, 1.0) * 15.0; int i = int(floor(f)); float t = fract(f);
  return mix(uEsp[i], uEsp[min(i + 1, 15)], t * t * (3.0 - 2.0 * t));
}
vec3 girar(vec3 p, float a){ float c = cos(a), s = sin(a); return vec3(c*p.x + s*p.z, p.y, -s*p.x + c*p.z); }
float desp(vec3 p){
  float t = uTiempo;
  // giro acotado: rígido con el tiempo + torsión que oscila (si la torsión creciera con t, la superficie
  // acabaría rayada en espiral tras unos minutos)
  vec3 q = girar(p, uRemolino * (t * 0.5 + p.y * 1.1 * sin(t * 0.35))) * uFrec;
  vec3 w = vec3(snoise(q * 0.8 + vec3(0.0, t * 0.13, 0.0)), snoise(q * 0.8 + vec3(5.2, -t * 0.11, 1.3)),
                snoise(q * 0.8 + vec3(2.1, 7.7, t * 0.12)));
  q += w * 0.4;
  float n = snoise(q + vec3(0.0, 0.0, t * 0.21)) * 0.82 + snoise(q * 1.9 - vec3(t * 0.17)) * 0.18;
  // la voz: abomba la superficie por bandas (graves en el ecuador, agudos hacia los polos)
  n += banda(abs(p.y)) * uNivel * 0.9 * (0.75 + 0.25 * snoise(q * 0.9 + t * 0.6));
  return n;
}
`;
const ADITIVO = { transparent: true, depthWrite: false, depthTest: false, blending: THREE.CustomBlending,
  blendSrc: THREE.OneFactor, blendDst: THREE.OneFactor, blendSrcAlpha: THREE.OneFactor, blendDstAlpha: THREE.OneFactor };

// ---------- Renderizador ----------
let renderer = null;
try {
  renderer = new THREE.WebGLRenderer({ canvas: lienzo, antialias: false, alpha: true, premultipliedAlpha: true,
    powerPreference: "high-performance", preserveDrawingBuffer: false });
  renderer.setClearColor(0x000000, 0);
  renderer.autoClear = false;
} catch (e) {
  console.warn("WebGL no disponible:", e);
  document.body.classList.add("sin-webgl");
}

const escena = new THREE.Scene();
const camara = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
camara.position.set(0, 0, 7.6);

const U = {  // uniforms compartidos por todo
  uTiempo: { value: 0 }, uFrec: { value: 1.2 }, uRemolino: { value: 0 }, uAmp: { value: 0.06 }, uNivel: { value: 0 },
  uEsp: { value: new Float32Array(16) }, uEnergia: { value: 0.25 }, uBrillo: { value: 1 },
  uColorA: { value: new THREE.Color(ESTADOS.reposo.a) }, uColorB: { value: new THREE.Color(ESTADOS.reposo.b) },
  uAparicion: { value: 0 }, uHabla: { value: 0 }, uPixeles: { value: 1 }, uPasos: { value: 18 }, uVelPart: { value: 0.35 },
};
const grupo = new THREE.Group();
escena.add(grupo);

// ================================================================
//  PIEZAS (se combinan según el estilo)
// ================================================================
// --- Caparazón de energía: esfera muy subdividida, deformada en el shader con normales correctas ---
function caparazon() {
  const g = new THREE.Group();
  const geo = new THREE.IcosahedronGeometry(1, 40);
  const hacer = (lado, intensidad) => new THREE.Mesh(geo, new THREE.ShaderMaterial({
    ...ADITIVO, side: lado,
    uniforms: { ...U, uIntensidad: { value: intensidad } },
    vertexShader: `${RUIDO}${DEFORMACION}
      varying vec3 vN, vV; varying float vD;
      void main(){
        vec3 n0 = normalize(position);
        vec3 t = normalize(cross(n0, abs(n0.y) < 0.99 ? vec3(0.0, 1.0, 0.0) : vec3(1.0, 0.0, 0.0)));
        vec3 b = cross(n0, t);
        float e = 0.012;
        float d0 = desp(n0);
        vec3 p0 = n0 * (1.0 + uAmp * d0);
        vec3 a1 = normalize(n0 + t * e); vec3 p1 = a1 * (1.0 + uAmp * desp(a1));
        vec3 a2 = normalize(n0 + b * e); vec3 p2 = a2 * (1.0 + uAmp * desp(a2));
        vec3 n = normalize(cross(p1 - p0, p2 - p0));
        if (dot(n, n0) < 0.0) n = -n;
        vD = d0;
        vec4 mv = modelViewMatrix * vec4(p0, 1.0);
        vN = normalize(normalMatrix * n);
        vV = normalize(-mv.xyz);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uColorA, uColorB; uniform float uIntensidad, uBrillo, uAparicion, uNivel, uEnergia, uTiempo;
      varying vec3 vN, vV; varying float vD;
      void main(){
        float ndv = abs(dot(normalize(vN), normalize(vV)));
        float fres = pow(1.0 - ndv, 2.2);
        // vidrio luminoso: borde intenso que pasa a blanco, cuerpo casi transparente con un velo azul profundo
        vec3 col = uColorB * 0.018 * (0.6 + 0.4 * vD) + uColorA * pow(fres, 1.4) * 0.5 + vec3(1.0) * pow(fres, 7.0) * 0.7;
        // vetas de energía muy suaves que recorren la superficie
        float veta = smoothstep(0.2, 0.0, abs(fract(vD * 1.2 + uTiempo * 0.03) - 0.5)) * 0.035 * (0.4 + uEnergia);
        col += uColorA * veta * (1.0 - fres);
        col *= uIntensidad * uBrillo * (1.0 + uNivel * 0.35) * uAparicion;
        gl_FragColor = vec4(col, 0.0);
      }`,
  }));
  g.add(hacer(THREE.BackSide, 0.16), hacer(THREE.FrontSide, 1.0));
  return g;
}

// --- Núcleo volumétrico: plano que mira a la cámara; dentro, raymarching por un plasma de ruido ---
function nucleo(radio = 0.78, intensidad = 1.0) {
  const m = new THREE.Mesh(new THREE.PlaneGeometry(2 * radio, 2 * radio), new THREE.ShaderMaterial({
    ...ADITIVO,
    uniforms: { ...U, uIntensidad: { value: intensidad } },
    vertexShader: `varying vec2 vUv; void main(){ vUv = uv * 2.0 - 1.0; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: `${RUIDO}
      uniform vec3 uColorA, uColorB; uniform float uTiempo, uRemolino, uNivel, uEnergia, uBrillo, uAparicion, uIntensidad, uPasos;
      varying vec2 vUv;
      vec3 girar(vec3 p, float a){ float c = cos(a), s = sin(a); return vec3(c*p.x + s*p.z, p.y, -s*p.x + c*p.z); }
      void main(){
        float r2 = dot(vUv, vUv);
        if (r2 >= 1.0) discard;
        float h = sqrt(1.0 - r2);
        vec3 acc = vec3(0.0);
        float t = uTiempo;
        for (int i = 0; i < 18; i++) {
          if (float(i) >= uPasos) break;
          float z = mix(-h, h, (float(i) + 0.5) / uPasos);
          vec3 p = vec3(vUv, z);
          float r = length(p);
          // remolino: cuanto más cerca del centro, más gira (estado «pensando»)
          p = girar(p, (0.25 + uRemolino * 0.9) * t + (0.3 + uRemolino * 1.6) * (1.2 - r) * sin(t * 0.45));
          float n = snoise(p * 2.3 + vec3(0.0, t * 0.25, 0.0)) * 0.6 + snoise(p * 4.7 - vec3(t * 0.35)) * 0.4;
          float fil = 1.0 - abs(n); fil = pow(fil, 5.0);  // filamentos finos en vez de una nube plana
          float dens = (fil * 0.75 + smoothstep(0.2, 0.9, n) * 0.25) * pow(max(1.0 - r, 0.0), 1.3);
          vec3 c = mix(uColorB, uColorA, smoothstep(0.05, 0.4, dens)) + vec3(1.0) * smoothstep(0.35, 0.8, dens) * 0.5;
          acc += c * dens;
        }
        acc *= (2.0 * h / uPasos) * 1.1;
        // corazón: un punto de luz blanca muy concentrado que late con la voz
        float corazon = exp(-r2 * (70.0 - uNivel * 25.0)) * (0.5 + uEnergia * 0.4 + uNivel * 0.5) + exp(-r2 * 9.0) * 0.06;
        acc += mix(uColorA, vec3(1.0), 0.75) * corazon;
        acc *= uIntensidad * uBrillo * uAparicion;
        gl_FragColor = vec4(acc, 0.0);
      }`,
  }));
  m.userData.cartel = true;  // mira siempre a la cámara
  return m;
}

// --- Partículas finas: un velo de polvo luminoso alrededor ---
function particulas(cantidad, rMin, rMax, aplanado = 1.0, tamano = 1.0) {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(cantidad * 3), sem = new Float32Array(cantidad * 4);
  for (let i = 0; i < cantidad; i++) {
    const u = Math.random() * 2 - 1, th = Math.random() * Math.PI * 2, s = Math.sqrt(1 - u * u);
    const r = rMin + Math.pow(Math.random(), 1.8) * (rMax - rMin);
    pos.set([r * s * Math.cos(th), r * u * aplanado, r * s * Math.sin(th)], i * 3);
    sem.set([Math.random(), Math.random(), (0.05 + Math.random() * 0.25) * (Math.random() < 0.5 ? 1 : -1), 0.5 + Math.random() * tamano], i * 4);
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aSem", new THREE.BufferAttribute(sem, 4));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4);
  const p = new THREE.Points(geo, new THREE.ShaderMaterial({
    ...ADITIVO, uniforms: U,
    vertexShader: `
      uniform float uTiempo, uNivel, uEnergia, uPixeles, uVelPart, uAparicion;
      attribute vec4 aSem; varying float vB;
      void main(){
        float a = uTiempo * aSem.z * uVelPart;
        float c = cos(a), s = sin(a);
        vec3 p = vec3(c * position.x + s * position.z, position.y, -s * position.x + c * position.z);
        p *= 1.0 + sin(uTiempo * 0.5 + aSem.x * 30.0) * 0.015 - uNivel * 0.06;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vB = (0.25 + 0.75 * pow(0.5 + 0.5 * sin(uTiempo * (0.6 + aSem.y) + aSem.x * 40.0), 3.0)) * (0.5 + uEnergia);
        gl_PointSize = aSem.w * uPixeles * 2.2 * (6.0 / -mv.z);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uColorA; uniform float uAparicion, uBrillo; varying float vB;
      void main(){
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d);
        gl_FragColor = vec4(mix(uColorA, vec3(1.0), 0.45) * a * a * vB * 0.55 * uBrillo * uAparicion, 0.0);
      }`,
  }));
  p.userData.total = cantidad;
  return p;
}

// --- Onda circular de audio: cinta fina (con borde suave) cuyo radio sigue el espectro ---
function ondaCircular(radio, desfase, intensidad, color) {
  const N = 384;
  const geo = new THREE.BufferGeometry();
  const ang = new Float32Array((N + 1) * 2), lado = new Float32Array((N + 1) * 2);
  const idx = [];
  for (let i = 0; i <= N; i++) {
    ang[i * 2] = ang[i * 2 + 1] = (i / N) * Math.PI * 2;
    lado[i * 2] = -1; lado[i * 2 + 1] = 1;
    if (i < N) idx.push(i * 2, i * 2 + 1, i * 2 + 2, i * 2 + 1, i * 2 + 3, i * 2 + 2);
  }
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array((N + 1) * 6), 3));
  geo.setAttribute("aAng", new THREE.BufferAttribute(ang, 1));
  geo.setAttribute("aLado", new THREE.BufferAttribute(lado, 1));
  geo.setIndex(idx);
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4);
  const m = new THREE.Mesh(geo, new THREE.ShaderMaterial({
    ...ADITIVO, side: THREE.DoubleSide,
    uniforms: { ...U, uRadio: { value: radio }, uDesfase: { value: desfase }, uIntensidad: { value: intensidad },
      uColor: { value: new THREE.Color(color || "#ffffff") }, uMezcla: { value: color ? 0 : 1 } },
    vertexShader: `${RUIDO}
      uniform float uTiempo, uNivel, uEnergia, uRadio, uDesfase, uHabla; uniform float uEsp[16];
      attribute float aAng, aLado; varying float vLado, vAmp;
      float banda(float x){ float f = clamp(x, 0.0, 1.0) * 15.0; int i = int(floor(f)); float t = fract(f);
        return mix(uEsp[i], uEsp[min(i + 1, 15)], t * t * (3.0 - 2.0 * t)); }
      void main(){
        // espectro reflejado: graves arriba y abajo, agudos a los lados (simétrico, como una onda viva)
        float giro = uDesfase + uTiempo * (uDesfase > 0.0 ? -0.07 : 0.05);  // las ondas giran despacio, cada una a un lado
        float x = abs(fract((aAng + giro) / 6.2831853) * 2.0 - 1.0);
        float e = banda(x);
        float ruido = snoise(vec3(cos(aAng) * 1.6, sin(aAng) * 1.6, uTiempo * 0.5 + uDesfase)) ;
        float amp = e * uNivel * (0.07 + uHabla * 0.08) * (uDesfase > 0.0 ? 0.6 : 1.0) + ruido * (0.006 + uEnergia * 0.012 + uNivel * 0.02);
        vAmp = e * uNivel;
        float r = uRadio + amp;
        float ancho = 0.0095 + uNivel * 0.006;
        vec3 p = vec3(cos(aAng), sin(aAng), 0.0) * (r + aLado * ancho);
        vLado = aLado;
        gl_Position = projectionMatrix * viewMatrix * vec4(p, 1.0);  // en el plano de la pantalla
      }`,
    fragmentShader: `
      uniform vec3 uColorA, uColor; uniform float uIntensidad, uBrillo, uAparicion, uEnergia, uNivel, uMezcla;
      varying float vLado, vAmp;
      void main(){
        float a = 1.0 - abs(vLado); a = a * a;
        vec3 c = mix(uColorA, uColor, uMezcla * 0.35 + 0.3);  // onda principal: acento con un punto de blanco
        float k = (0.16 + uEnergia * 0.25 + vAmp * 0.8 + uNivel * 0.22) * uIntensidad * uBrillo * uAparicion;
        gl_FragColor = vec4(c * a * k, 0.0);
      }`,
  }));
  return m;
}

// --- Anillo de partículas (estilo «anillo») ---
function anilloParticulas(cantidad) {
  const geo = new THREE.BufferGeometry();
  const pos = new Float32Array(cantidad * 3), sem = new Float32Array(cantidad * 4);
  for (let i = 0; i < cantidad; i++) {
    const g = () => (Math.random() + Math.random() + Math.random() - 1.5) / 1.5;  // ~gaussiana
    pos.set([Math.random() * Math.PI * 2, g() * 0.07, g() * 0.07], i * 3);
    sem.set([Math.random(), Math.random(), 0.04 + Math.random() * 0.1, 0.4 + Math.random() * 1.1], i * 4);
  }
  geo.setAttribute("position", new THREE.BufferAttribute(pos, 3));
  geo.setAttribute("aSem", new THREE.BufferAttribute(sem, 4));
  geo.boundingSphere = new THREE.Sphere(new THREE.Vector3(), 4);
  const p = new THREE.Points(geo, new THREE.ShaderMaterial({
    ...ADITIVO, uniforms: U,
    vertexShader: `${RUIDO}
      uniform float uTiempo, uNivel, uEnergia, uPixeles, uVelPart, uRemolino; uniform float uEsp[16];
      attribute vec4 aSem; varying float vB;
      float banda(float x){ float f = clamp(x, 0.0, 1.0) * 15.0; int i = int(floor(f)); float t = fract(f);
        return mix(uEsp[i], uEsp[min(i + 1, 15)], t * t * (3.0 - 2.0 * t)); }
      void main(){
        float ang = position.x + uTiempo * aSem.z * uVelPart * (1.0 + uRemolino * 2.0);
        float x = abs(fract(ang / 6.2831853) * 2.0 - 1.0);
        float onda = banda(x) * uNivel * 0.18 + snoise(vec3(cos(ang) * 1.5, sin(ang) * 1.5, uTiempo * 0.3)) * (0.03 + uEnergia * 0.05);
        float r = 1.12 + onda + position.y * (1.0 + uNivel * 2.0);
        vec3 p = vec3(cos(ang) * r, sin(ang) * r, position.z * 2.0);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vB = 0.35 + 0.65 * pow(0.5 + 0.5 * sin(uTiempo * (0.8 + aSem.y * 2.0) + aSem.x * 50.0), 2.0);
        gl_PointSize = aSem.w * uPixeles * 2.0 * (6.0 / -mv.z) * (1.0 + uNivel * 0.6);
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uColorA; uniform float uAparicion, uBrillo, uEnergia; varying float vB;
      void main(){
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.05, d);
        gl_FragColor = vec4(mix(uColorA, vec3(1.0), 0.3) * a * vB * (0.45 + uEnergia * 0.5) * uBrillo * uAparicion, 0.0);
      }`,
  }));
  p.userData.total = cantidad;
  return p;
}

// --- Malla de líneas (estilo «malla») ---
function mallaLineas() {
  const puntos = [];
  const LAT = 22, LON = 36, SEG = 128;
  for (let i = 1; i < LAT; i++) {           // paralelos
    const v = (i / LAT) * Math.PI;
    for (let j = 0; j < SEG; j++) {
      const u1 = (j / SEG) * Math.PI * 2, u2 = ((j + 1) / SEG) * Math.PI * 2;
      puntos.push(Math.sin(v) * Math.cos(u1), Math.cos(v), Math.sin(v) * Math.sin(u1), Math.sin(v) * Math.cos(u2), Math.cos(v), Math.sin(v) * Math.sin(u2));
    }
  }
  for (let j = 0; j < LON; j++) {           // meridianos
    const u = (j / LON) * Math.PI * 2;
    for (let i = 0; i < SEG / 2; i++) {
      const v1 = (i / (SEG / 2)) * Math.PI, v2 = ((i + 1) / (SEG / 2)) * Math.PI;
      puntos.push(Math.sin(v1) * Math.cos(u), Math.cos(v1), Math.sin(v1) * Math.sin(u), Math.sin(v2) * Math.cos(u), Math.cos(v2), Math.sin(v2) * Math.sin(u));
    }
  }
  const geo = new THREE.BufferGeometry();
  geo.setAttribute("position", new THREE.BufferAttribute(new Float32Array(puntos), 3));
  return new THREE.LineSegments(geo, new THREE.ShaderMaterial({
    ...ADITIVO, uniforms: U,
    vertexShader: `${RUIDO}${DEFORMACION}
      varying float vF, vD;
      void main(){
        vec3 n0 = normalize(position);
        float d = desp(n0);
        vec4 mv = modelViewMatrix * vec4(n0 * (1.0 + uAmp * d), 1.0);
        vec3 nv = normalize(normalMatrix * n0);
        vF = pow(1.0 - abs(dot(nv, normalize(-mv.xyz))), 1.5);
        vD = d;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: `
      uniform vec3 uColorA, uColorB; uniform float uBrillo, uAparicion, uNivel; varying float vF, vD;
      void main(){
        vec3 c = mix(uColorB, uColorA, vF) * (0.12 + vF * 0.55) + vec3(1.0) * pow(vF, 5.0) * 0.25;
        c *= (0.8 + 0.2 * vD) * uBrillo * (1.0 + uNivel * 0.4) * uAparicion;
        gl_FragColor = vec4(c, 0.0);
      }`,
  }));
}

// ---------- Construcción de cada estilo ----------
let piezasParticulas = [];
function construir(estilo) {
  while (grupo.children.length) {
    const h = grupo.children.pop();
    h.traverse?.((o) => { o.geometry?.dispose(); o.material?.dispose(); });
  }
  piezasParticulas = [];
  const anadir = (o) => { grupo.add(o); return o; };
  if (estilo === "anillo") {
    anadir(nucleo(0.62, 1.15));
    piezasParticulas.push(anadir(anilloParticulas(14000)));
    piezasParticulas.push(anadir(particulas(900, 1.35, 2.05, 0.9, 0.8)));
    anadir(ondaCircular(1.12, 0.0, 0.55));
  } else if (estilo === "malla") {
    anadir(nucleo(0.7, 0.9));
    anadir(mallaLineas());
    piezasParticulas.push(anadir(particulas(1200, 1.2, 2.0, 1.0, 0.9)));
    anadir(ondaCircular(1.3, 0.0, 0.7));
  } else {  // nucleo (por defecto)
    anadir(nucleo(0.8, 1.0));
    anadir(caparazon());
    piezasParticulas.push(anadir(particulas(1600, 1.18, 2.1, 0.95, 1.0)));
    anadir(ondaCircular(1.24, 0.0, 0.85));
    anadir(ondaCircular(1.24, 2.1, 0.22, "#d8f6ff"));
  }
  info.estilo = estilo;
}

// ================================================================
//  POSTPROCESO: bloom en varios niveles + composición con alfa
// ================================================================
const camPost = new THREE.OrthographicCamera(-1, 1, 1, -1, 0, 1);
const escenaPost = new THREE.Scene();
const cuadro = new THREE.Mesh(new THREE.PlaneGeometry(2, 2));
cuadro.frustumCulled = false;
escenaPost.add(cuadro);
const VERT_POST = `varying vec2 vUv; void main(){ vUv = uv; gl_Position = vec4(position.xy, 0.0, 1.0); }`;
const matBajar = new THREE.ShaderMaterial({
  uniforms: { tFuente: { value: null }, uTexel: { value: new THREE.Vector2() } }, vertexShader: VERT_POST,
  fragmentShader: `uniform sampler2D tFuente; uniform vec2 uTexel; varying vec2 vUv;
    void main(){ // filtro de 13 muestras (estilo Call of Duty): reduce sin parpadeos ni bloques
      vec3 a = texture2D(tFuente, vUv + uTexel * vec2(-2.0, 2.0)).rgb, b = texture2D(tFuente, vUv + uTexel * vec2(0.0, 2.0)).rgb;
      vec3 c = texture2D(tFuente, vUv + uTexel * vec2(2.0, 2.0)).rgb, d = texture2D(tFuente, vUv + uTexel * vec2(-2.0, 0.0)).rgb;
      vec3 e = texture2D(tFuente, vUv).rgb, f = texture2D(tFuente, vUv + uTexel * vec2(2.0, 0.0)).rgb;
      vec3 g = texture2D(tFuente, vUv + uTexel * vec2(-2.0, -2.0)).rgb, h = texture2D(tFuente, vUv + uTexel * vec2(0.0, -2.0)).rgb;
      vec3 i = texture2D(tFuente, vUv + uTexel * vec2(2.0, -2.0)).rgb, j = texture2D(tFuente, vUv + uTexel * vec2(-1.0, 1.0)).rgb;
      vec3 k = texture2D(tFuente, vUv + uTexel * vec2(1.0, 1.0)).rgb, l = texture2D(tFuente, vUv + uTexel * vec2(-1.0, -1.0)).rgb;
      vec3 m = texture2D(tFuente, vUv + uTexel * vec2(1.0, -1.0)).rgb;
      vec3 r = e * 0.125 + (a + c + g + i) * 0.03125 + (b + d + f + h) * 0.0625 + (j + k + l + m) * 0.125;
      gl_FragColor = vec4(r, 1.0);
    }`,
});
const matSubir = new THREE.ShaderMaterial({
  uniforms: { tFuente: { value: null }, tBase: { value: null }, uTexel: { value: new THREE.Vector2() }, uPeso: { value: 1 } },
  vertexShader: VERT_POST,
  fragmentShader: `uniform sampler2D tFuente, tBase; uniform vec2 uTexel; uniform float uPeso; varying vec2 vUv;
    void main(){ // filtro tienda 3x3 al subir, sumado al nivel de más resolución
      vec3 s = texture2D(tFuente, vUv + uTexel * vec2(-1.0, 1.0)).rgb + texture2D(tFuente, vUv + uTexel * vec2(0.0, 1.0)).rgb * 2.0
             + texture2D(tFuente, vUv + uTexel * vec2(1.0, 1.0)).rgb + texture2D(tFuente, vUv + uTexel * vec2(-1.0, 0.0)).rgb * 2.0
             + texture2D(tFuente, vUv).rgb * 4.0 + texture2D(tFuente, vUv + uTexel * vec2(1.0, 0.0)).rgb * 2.0
             + texture2D(tFuente, vUv + uTexel * vec2(-1.0, -1.0)).rgb + texture2D(tFuente, vUv + uTexel * vec2(0.0, -1.0)).rgb * 2.0
             + texture2D(tFuente, vUv + uTexel * vec2(1.0, -1.0)).rgb;
      gl_FragColor = vec4(texture2D(tBase, vUv).rgb + s / 16.0 * uPeso, 1.0);
    }`,
});
const matFinal = new THREE.ShaderMaterial({
  uniforms: { tEscena: { value: null }, tBloom: { value: null }, uTiempo: { value: 0 }, uBloom: { value: 0.9 },
    uAberracion: { value: 0.0006 }, uSombra: { value: 0.72 }, uResol: { value: new THREE.Vector2(1, 1) }, uAparicion: { value: 0 } },
  vertexShader: VERT_POST,
  fragmentShader: `uniform sampler2D tEscena, tBloom; uniform float uTiempo, uBloom, uAberracion, uSombra, uAparicion; uniform vec2 uResol;
    varying vec2 vUv;
    float hash(vec2 p){ return fract(sin(dot(p, vec2(12.9898, 78.233))) * 43758.5453); }
    void main(){
      vec2 c = vUv - 0.5;
      float dist = length(c);
      // aberración cromática radial, solo perceptible en los bordes del brillo
      vec2 off = c * uAberracion * dist * dist * 8.0;
      vec3 col = vec3(texture2D(tEscena, vUv + off).r, texture2D(tEscena, vUv).g, texture2D(tEscena, vUv - off).b);
      col += texture2D(tBloom, vUv).rgb * uBloom;
      // curva tonal suave: los brillos se acercan al blanco sin cortarse en seco
      col = vec3(1.0) - exp(-col * 1.35);
      // tramado: ±1,5/255 de ruido para que los degradados del brillo no hagan bandas
      float n = hash(vUv * uResol + fract(uTiempo) * 61.0) - 0.5;
      col = max(col + n * (1.5 / 255.0), 0.0);
      // alfa: la luz es opaca donde brilla y se desvanece con ella (sobre el escritorio queda un resplandor real)
      float luz = max(col.r, max(col.g, col.b));
      float alfa = clamp(luz * 1.15, 0.0, 1.0);
      // sombra muy suave detrás (opcional) para que se lea sobre fondos claros
      float sombra = uSombra * pow(smoothstep(0.46, 0.18, dist), 1.3) * uAparicion;
      // sombra de azul noche (no gris): sobre un fondo claro el orbe queda dentro de un velo oscuro y conserva el contraste
      float a2 = alfa + sombra * (1.0 - alfa);
      col = col + vec3(0.008, 0.016, 0.035) * sombra * (1.0 - alfa);
      gl_FragColor = vec4(min(col, vec3(a2)), a2);
    }`,
});

let rtEscena = null, rtNiveles = [];
function crearDestinos(w, h, muestras) {
  rtEscena?.dispose(); rtNiveles.forEach((r) => r.dispose());
  const opciones = { type: THREE.HalfFloatType, depthBuffer: false, minFilter: THREE.LinearFilter, magFilter: THREE.LinearFilter };
  rtEscena = new THREE.WebGLRenderTarget(w, h, { ...opciones, samples: muestras });
  rtNiveles = [];
  let a = w, b = h;
  for (let i = 0; i < 5; i++) {
    a = Math.max(2, a >> 1); b = Math.max(2, b >> 1);
    rtNiveles.push(new THREE.WebGLRenderTarget(a, b, opciones));
  }
  rtNiveles.forEach((r) => (r.subida = new THREE.WebGLRenderTarget(r.width, r.height, opciones)));
}
function pasada(material, destino) {
  cuadro.material = material;
  renderer.setRenderTarget(destino);
  renderer.clear();
  renderer.render(escenaPost, camPost);
}
function renderizar() {
  renderer.setRenderTarget(rtEscena);
  renderer.clear();
  renderer.render(escena, camara);
  // bajar: escena -> 1/2 -> 1/4 ... -> 1/32
  let fuente = rtEscena.texture, w = rtEscena.width, h = rtEscena.height;
  for (const r of rtNiveles) {
    matBajar.uniforms.tFuente.value = fuente;
    matBajar.uniforms.uTexel.value.set(1 / w, 1 / h);
    pasada(matBajar, r);
    fuente = r.texture; w = r.width; h = r.height;
  }
  // subir sumando: el bloom tiene halo ancho y núcleo nítido a la vez
  let arriba = rtNiveles[rtNiveles.length - 1].texture;
  for (let i = rtNiveles.length - 2; i >= 0; i--) {
    const r = rtNiveles[i];
    matSubir.uniforms.tFuente.value = arriba;
    matSubir.uniforms.tBase.value = r.texture;
    matSubir.uniforms.uTexel.value.set(1 / rtNiveles[i + 1].width, 1 / rtNiveles[i + 1].height);
    matSubir.uniforms.uPeso.value = 0.85;
    pasada(matSubir, r.subida);
    arriba = r.subida.texture;
  }
  matFinal.uniforms.tEscena.value = rtEscena.texture;
  matFinal.uniforms.tBloom.value = arriba;
  pasada(matFinal, null);
}

// ================================================================
//  ESTADO, AUDIO, CALIDAD Y BUCLE
// ================================================================
for (const e of Object.values(ESTADOS)) { e.colA = new THREE.Color(e.a); e.colB = new THREE.Color(e.b); }
const actual = { ...ESTADOS.iniciando };
let objetivo = ESTADOS.iniciando, nombreEstado = "iniciando";
let mic = 0, vozJarvis = 0, nivel = 0, simulando = false, cambioEstado = performance.now();
const espMic = new Float32Array(16), espVoz = new Float32Array(16), espSuave = new Float32Array(16);
let visible = !document.hidden, corriendo = false, ultimo = performance.now(), tAparicion = 0;
let calidadPedida = "auto", calidad = "alta", ultimoCambio = performance.now(), proxima = 0;
const cuenta = { n: 0, desde: performance.now(), tranquilo: false };
const info = { calidad, fps: 0, ms: 0, estilo: "nucleo", gpu: "" };
const reloj = { t: 0 };

function aplicarCalidad(nombre) {
  calidad = nombre;
  info.calidad = nombre;
  const c = CALIDADES[nombre];
  U.uPixeles.value = c.pixeles;
  U.uPasos.value = c.pasos;
  for (const p of piezasParticulas) p.geometry.setDrawRange(0, Math.floor(p.userData.total * c.particulas));
  redimensionar(true);
}

function redimensionar(forzar = false) {
  if (!renderer) return;
  const w = lienzo.clientWidth || 1, h = lienzo.clientHeight || 1;
  const px = CALIDADES[calidad].pixeles;
  renderer.setPixelRatio(px);
  renderer.setSize(w, h, false);
  camara.aspect = w / h;
  camara.updateProjectionMatrix();
  const W = Math.round(w * px), H = Math.round(h * px);
  if (forzar || !rtEscena || rtEscena.width !== W || rtEscena.height !== H) crearDestinos(W, H, CALIDADES[calidad].muestras);
  matFinal.uniforms.uResol.value.set(W, H);
}
new ResizeObserver(() => redimensionar()).observe(lienzo);

// Voz simulada (para capturas y la demo): sílabas de 120-260 ms con espectro de voz humana
let sim = { t: 0, sig: 0, env: 0 };
function simularAudio(dt) {
  sim.t += dt;
  if (sim.t > sim.sig) { sim.sig = sim.t + 0.12 + Math.random() * 0.16; sim.objetivo = Math.random() < 0.18 ? 0.01 : 0.06 + Math.random() * 0.12; }
  sim.env += ((sim.objetivo || 0) - sim.env) * Math.min(1, dt * 18);
  for (let i = 0; i < 16; i++) {
    const formante = Math.exp(-((i - 3.5) ** 2) / 6) + 0.6 * Math.exp(-((i - 8) ** 2) / 4) + 0.25 * Math.exp(-((i - 12) ** 2) / 5);
    const v = Math.min(1, formante * sim.env * 9 * (0.7 + 0.6 * Math.random()));
    espVoz[i] = v; espMic[i] = v;
  }
  vozJarvis = mic = sim.env;
}

function fotograma(ahora) {
  if (!corriendo) return;
  requestAnimationFrame(fotograma);
  const tranquilo = nombreEstado === "reposo" && nivel < 0.02;
  // reposo: 30 fps; activo: 60 fps (aunque el monitor vaya a 144/165 Hz). Con un «próximo turno» acumulado
  // la media sale exacta aunque el refresco del monitor no sea múltiplo.
  const intervalo = tranquilo ? 1000 / 30 : 1000 / 60;
  if (ahora + 3 < proxima) return;
  proxima = ahora - proxima > intervalo ? ahora + intervalo : proxima + intervalo;
  const dt = Math.min((ahora - ultimo) / 1000, 0.1);
  ultimo = ahora;
  const t0 = performance.now();

  // FPS y calidad automática (baja si no llega; nunca sube sola para no oscilar)
  // (se compara con el objetivo de ese momento: 30 o 60; no con el refresco del monitor)
  cuenta.n++;
  if (tranquilo !== cuenta.tranquilo || ahora - cambioEstado < 500) { cuenta.n = 0; cuenta.desde = ahora; cuenta.tranquilo = tranquilo; }
  if (ahora - cuenta.desde >= 2000) {
    info.fps = Math.round(cuenta.n * 1000 / (ahora - cuenta.desde));
    cuenta.n = 0; cuenta.desde = ahora;
    if (calidadPedida === "auto" && info.fps < 0.8 * (1000 / intervalo) && ahora - ultimoCambio > 4000 && calidad !== "baja") {
      aplicarCalidad(calidad === "alta" ? "media" : "baja");
      ultimoCambio = ahora;
    }
  }

  if (simulando) simularAudio(dt);
  // Audio -> nivel y espectro suavizados (sube rápido, baja despacio: se ve vivo pero no nervioso)
  const fuente = nombreEstado === "hablando" ? espVoz : espMic;
  const nivelObjetivo = nombreEstado === "hablando" ? vozJarvis * 6 : nombreEstado === "escuchando" ? mic * 8 : 0;
  const k = nivelObjetivo > nivel ? 1 - Math.pow(0.0008, dt) : 1 - Math.pow(0.08, dt);
  nivel += (Math.min(nivelObjetivo, 1.0) - nivel) * k;
  const activo = nombreEstado === "hablando" || nombreEstado === "escuchando";
  for (let i = 0; i < 16; i++) {
    const o = activo ? fuente[i] : 0;
    espSuave[i] += (o - espSuave[i]) * (o > espSuave[i] ? 1 - Math.pow(0.002, dt) : 1 - Math.pow(0.05, dt));
    U.uEsp.value[i] = espSuave[i];
  }

  // Transición suave entre estados (constante de tiempo ~0,35 s)
  const s = 1 - Math.pow(0.004, dt);
  for (const c of ["energia", "frec", "remolino", "tam", "brillo", "vel"]) actual[c] += (objetivo[c] - actual[c]) * s;
  U.uColorA.value.lerp(objetivo.colA, s);
  U.uColorB.value.lerp(objetivo.colB, s);
  reloj.t += dt * (0.55 + actual.vel * 0.6);
  U.uTiempo.value = reloj.t;
  U.uEnergia.value = actual.energia;
  U.uFrec.value = actual.frec;
  U.uRemolino.value = actual.remolino;
  U.uBrillo.value = actual.brillo;
  U.uVelPart.value = actual.vel;
  U.uNivel.value = nivel;
  U.uHabla.value += ((nombreEstado === "hablando" ? 1 : 0) - U.uHabla.value) * s;
  // Amplitud de la deformación: casi quieta en reposo, viva al hablar
  U.uAmp.value = 0.028 + actual.energia * 0.05 + nivel * 0.035;
  // Aparición (despertar): < 200 ms
  tAparicion = Math.min(1, tAparicion + dt / 0.18);
  const ap = 1 - Math.pow(1 - tAparicion, 3);
  U.uAparicion.value = ap;
  matFinal.uniforms.uAparicion.value = ap;
  // Respiración en reposo: lenta y casi imperceptible
  const respira = 1 + Math.sin(reloj.t * 0.9) * 0.008 * (1 - Math.min(1, nivel * 4));
  grupo.scale.setScalar(actual.tam * respira * (0.92 + 0.08 * ap));
  grupo.rotation.y += dt * 0.05 * (0.4 + actual.vel);
  grupo.rotation.x = Math.sin(reloj.t * 0.13) * 0.12;
  // los carteles (núcleo) siempre de cara a la cámara aunque el grupo gire
  grupo.children.forEach((o) => { if (o.userData.cartel) o.quaternion.copy(grupo.quaternion).invert(); });
  matFinal.uniforms.uTiempo.value = reloj.t;
  renderizar();
  info.ms = Math.round((performance.now() - t0) * 10) / 10;
  if (avisarPrimero) { avisarPrimero = false; window.alPrimerFotograma?.(); }
}

let avisarPrimero = false;
function arrancar() {
  if (!renderer || corriendo || !visible) return;
  avisarPrimero = true;
  corriendo = true;
  info.corriendo = true;
  ultimo = performance.now();
  requestAnimationFrame(fotograma);
}
function parar() { corriendo = false; info.corriendo = false; }
document.addEventListener("visibilitychange", () => { visible = !document.hidden && visible; if (document.hidden) parar(); else if (visibleExterno) { visible = true; arrancar(); } });
let visibleExterno = true;

// Compila los shaders YA (aunque la página esté oculta, con Jarvis dormido): si no, el primer fotograma al
// despertar tardaba ~1,8 s compilando el ruido, el raymarching y el bloom (medido con /api/diag).
function precompilar() {
  if (!renderer) return;
  try {
    const t0 = performance.now();
    renderer.compile(escena, camara);
    renderizar();          // también las pasadas del postproceso
    info.compilado_ms = Math.round(performance.now() - t0);
  } catch (e) { console.warn("No pude precompilar el orbe:", e); }
}
construir(new URLSearchParams(location.search).get("estilo") || window.ESTILO_ORBE || "nucleo");
aplicarCalidad("alta");
precompilar();
try {
  const dbg = renderer?.getContext().getExtension("WEBGL_debug_renderer_info");
  info.gpu = dbg ? renderer.getContext().getParameter(dbg.UNMASKED_RENDERER_WEBGL) : "";
} catch { /* sin datos de GPU */ }
arrancar();

window.orbe = {
  estado(n) {
    if (!ESTADOS[n] || n === nombreEstado) return;
    if (n === "despertando") tAparicion = 0;
    nombreEstado = n; objetivo = ESTADOS[n]; cambioEstado = performance.now();
  },
  nivelMic(v) { if (!simulando) mic = v; },
  nivelVoz(v) { if (!simulando) vozJarvis = v; },
  espectro(fuente, bandas) {
    if (simulando || !bandas) return;
    const destino = fuente === "voz" ? espVoz : espMic;
    for (let i = 0; i < 16; i++) destino[i] = bandas[i] || 0;
  },
  visible(v) {
    visibleExterno = v;
    visible = v && !document.hidden;
    if (visible) { arrancar(); } else parar();
  },
  calidad(nombre) {
    calidadPedida = nombre || "auto";
    aplicarCalidad(calidadPedida === "auto" ? "alta" : calidadPedida);
    ultimoCambio = performance.now();
  },
  estilo(nombre) { if (["nucleo", "anillo", "malla"].includes(nombre) && nombre !== info.estilo) { construir(nombre); aplicarCalidad(calidad); precompilar(); } },
  simular(si) { simulando = !!si; if (!si) { mic = vozJarvis = 0; espVoz.fill(0); espMic.fill(0); } },
  aparecer() { tAparicion = 0; },
  sombra(v) { matFinal.uniforms.uSombra.value = v; },
  info,
  redimensionar,
};
