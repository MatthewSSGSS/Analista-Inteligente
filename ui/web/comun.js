// Utilidades compartidas de las pantallas en JavaScript
// (ui/components/escena.py las antepone al .js de cada pantalla).
// Cada función devuelve su limpieza, para que la pantalla la llame cuando
// Streamlit la desmonte (animaciones y observadores no quedan corriendo).

const MOVIMIENTO = !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

function texto(valor) {
  const d = document.createElement("div");
  d.textContent = valor == null ? "" : String(valor);
  return d.innerHTML;
}

// Red de puntos que derivan y se unen cuando están cerca: el fondo "de
// datos" de la portada y del acceso. Se pausa cuando no está a la vista.
function redDeDatos(canvas, opciones = {}) {
  if (!canvas) return () => {};
  const color = opciones.color || "255,91,108";
  const color2 = opciones.color2 || "94,234,212";
  const ctx = canvas.getContext("2d");
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  let w = 0, h = 0, nodos = [], raf = null, visible = true;

  function medir() {
    const r = canvas.getBoundingClientRect();
    w = Math.max(1, r.width); h = Math.max(1, r.height);
    canvas.width = w * dpr; canvas.height = h * dpr;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    const n = Math.max(22, Math.min(80, Math.round((w * h) / 11000)));
    nodos = Array.from({ length: n }, () => ({
      x: Math.random() * w, y: Math.random() * h,
      vx: (Math.random() - 0.5) * 0.28, vy: (Math.random() - 0.5) * 0.28,
      r: Math.random() * 1.7 + 0.7, frio: Math.random() < 0.3,
    }));
    if (!MOVIMIENTO) dibujar();
  }

  function dibujar() {
    ctx.clearRect(0, 0, w, h);
    const lejos = 130;
    for (let i = 0; i < nodos.length; i++) {
      const a = nodos[i];
      for (let j = i + 1; j < nodos.length; j++) {
        const b = nodos[j];
        const dx = a.x - b.x, dy = a.y - b.y, d = Math.hypot(dx, dy);
        if (d < lejos) {
          ctx.strokeStyle = `rgba(${a.frio && b.frio ? color2 : color},${(1 - d / lejos) * 0.28})`;
          ctx.lineWidth = 0.7;
          ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        }
      }
    }
    for (const n of nodos) {
      ctx.fillStyle = `rgba(${n.frio ? color2 : color},.85)`;
      ctx.beginPath(); ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2); ctx.fill();
    }
  }

  function cuadro() {
    for (const n of nodos) {
      n.x += n.vx; n.y += n.vy;
      if (n.x < 0 || n.x > w) n.vx *= -1;
      if (n.y < 0 || n.y > h) n.vy *= -1;
    }
    dibujar();
    raf = visible ? requestAnimationFrame(cuadro) : null;
  }

  const ro = new ResizeObserver(medir);
  ro.observe(canvas);
  const io = new IntersectionObserver(([e]) => {
    visible = e.isIntersecting;
    if (visible && !raf && MOVIMIENTO) raf = requestAnimationFrame(cuadro);
  });
  io.observe(canvas);
  medir();
  if (MOVIMIENTO) raf = requestAnimationFrame(cuadro);
  return () => { if (raf) cancelAnimationFrame(raf); ro.disconnect(); io.disconnect(); };
}

// Aparición escalonada de lo marcado con data-revelar al entrar en pantalla.
function revelar(raiz) {
  const elementos = [...raiz.querySelectorAll("[data-revelar]")];
  if (!MOVIMIENTO || !("IntersectionObserver" in window)) {
    elementos.forEach((e) => e.classList.add("visible"));
    return () => {};
  }
  const io = new IntersectionObserver((entradas) => {
    entradas.forEach((e) => {
      if (!e.isIntersecting) return;
      const retraso = Number(e.target.dataset.revelar || 0);
      setTimeout(() => e.target.classList.add("visible"), retraso);
      io.unobserve(e.target);
    });
  }, { threshold: 0.12 });
  elementos.forEach((e) => io.observe(e));
  return () => io.disconnect();
}

// Luz que sigue al cursor y una inclinación leve de la tarjeta.
function foco(tarjeta, inclinar = true) {
  if (!tarjeta) return () => {};
  tarjeta.classList.add("ai-foco");
  const mover = (ev) => {
    const r = tarjeta.getBoundingClientRect();
    const x = ev.clientX - r.left, y = ev.clientY - r.top;
    tarjeta.style.setProperty("--mx", `${x}px`);
    tarjeta.style.setProperty("--my", `${y}px`);
    if (inclinar && MOVIMIENTO) {
      const rx = ((y / r.height) - 0.5) * -4, ry = ((x / r.width) - 0.5) * 5;
      tarjeta.style.transform = `perspective(900px) rotateX(${rx}deg) rotateY(${ry}deg) translateY(-4px)`;
    }
  };
  const salir = () => { tarjeta.style.transform = ""; };
  tarjeta.addEventListener("pointermove", mover);
  tarjeta.addEventListener("pointerleave", salir);
  return () => { tarjeta.removeEventListener("pointermove", mover); tarjeta.removeEventListener("pointerleave", salir); };
}

// Cuenta un número hasta su valor (cifras con punto decimal, como el panel).
function contar(el, hasta, { decimales = 0, prefijo = "", sufijo = "", ms = 1300, signo = false } = {}) {
  if (!el) return;
  const fmt = (v) => {
    const s = Math.abs(v).toFixed(decimales);
    const pre = v < 0 ? "−" : (signo && v > 0 ? "+" : "");
    return `${pre}${prefijo}${s}${sufijo}`;
  };
  if (!MOVIMIENTO) { el.textContent = fmt(hasta); return; }
  const t0 = performance.now();
  const paso = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    const suave = 1 - Math.pow(1 - p, 3);
    el.textContent = fmt(hasta * suave);
    if (p < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

// Escribe un texto letra por letra; llama a `listo` al terminar.
function escribir(el, frase, listo, ms = 26) {
  if (!el) return () => {};
  if (!MOVIMIENTO) { el.textContent = frase; if (listo) listo(); return () => {}; }
  let i = 0, vivo = true;
  el.textContent = "";
  el.classList.add("escribiendo");
  const tic = () => {
    if (!vivo) return;
    el.textContent = frase.slice(0, ++i);
    if (i < frase.length) setTimeout(tic, ms);
    else { el.classList.remove("escribiendo"); if (listo) listo(); }
  };
  setTimeout(tic, 350);
  return () => { vivo = false; };
}

// Cada botón con data-accion avisa a Python qué se eligió. Camino principal:
// pulsar el botón de Streamlit escondido de esa acción (`botones`, desde
// ui/components/escena.botones_ocultos); si no está, el aviso del componente.
function acciones(raiz, setTriggerValue, botones = {}) {
  raiz.querySelectorAll("[data-accion]").forEach((b) => {
    b.addEventListener("click", () => {
      raiz.querySelectorAll("[data-accion]").forEach((x) => x.classList.remove("cargando"));
      b.classList.add("cargando");
      const clave = botones[b.dataset.accion];
      const nativo = clave ? document.querySelector(`.st-key-${clave} button`) : null;
      if (nativo) nativo.click();
      else setTriggerValue("accion", b.dataset.accion);
    });
  });
}

// Quita lo montado en un rerun anterior (Streamlit vuelve a llamar a la
// función de la pantalla con los datos nuevos).
function montar(parentElement, clase, html) {
  parentElement.querySelectorAll(".ai-raiz").forEach((n) => n.remove());
  const raiz = document.createElement("div");
  raiz.className = `ai ai-raiz ${clase}`;
  raiz.innerHTML = html;
  parentElement.appendChild(raiz);
  return raiz;
}

// Cuenta hasta la cifra de un texto ya formateado por Python («685.1M»,
// «+20.2%», «4.7 mil M», «5,032»): anima solo el número y conserva el resto.
function contarTexto(el, valor, ms = 1300) {
  if (!el) return;
  const txt = String(valor == null ? "" : valor);
  const m = txt.match(/^(.*?)([+\-−]?)(\d[\d,]*(?:\.\d+)?)(.*)$/);
  if (!m || !MOVIMIENTO) { el.textContent = txt; return; }
  const [, pre, signo, num, post] = m;
  const miles = num.includes(",");
  const dec = (num.split(".")[1] || "").length;
  const fin = parseFloat(num.replace(/,/g, ""));
  const fmt = (v) => {
    let s = v.toFixed(dec);
    if (miles) { const [e, d] = s.split("."); s = e.replace(/\B(?=(\d{3})+(?!\d))/g, ",") + (d ? "." + d : ""); }
    return pre + signo + s + post;
  };
  const t0 = performance.now();
  const paso = (t) => {
    const p = Math.min(1, (t - t0) / ms);
    el.textContent = fmt(fin * (1 - Math.pow(1 - p, 3)));
    if (p < 1) requestAnimationFrame(paso); else el.textContent = txt;
  };
  requestAnimationFrame(paso);
}

// Texto seguro con los porcentajes y variaciones resaltados por su signo.
function conCifras(valor) {
  // Solo una cifra con signo que empieza palabra: «R-4» o «2025-26» no se tocan.
  return texto(valor).replace(/(^|[\s(])([+\-−]\s?\d[\d,]*(?:\.\d+)?\s?(?:%|pts)?)/g, (_, antes, s) =>
    `${antes}<b class="${/^[\-−]/.test(s) ? "neg" : "pos"}">${s}</b>`);
}

// Activa la animación de entrada de un elemento cuando aparece en pantalla.
function alVerse(el, fn) {
  if (!el) return () => {};
  if (!MOVIMIENTO || !("IntersectionObserver" in window)) { fn(); return () => {}; }
  const io = new IntersectionObserver(([e]) => { if (e.isIntersecting) { fn(); io.disconnect(); } }, { threshold: 0.2 });
  io.observe(el);
  return () => io.disconnect();
}

// ── Piezas del tablero (parte del día y resumen) ──────────────────────
const ICONOS_KPI = { mes: "📅", meta: "🎯", anual: "🔁", acumulado: "📈", margen: "💰", ticket: "🧾", primero: "🥇", ultimo: "🔻", movio: "📉", grupo: "👥", distancia: "↔️" };

function areaSvg(serie, id = "pdGrad") {
  // Área de los últimos meses: línea que se dibuja sola y el último punto que late.
  if (!serie || serie.length < 2) return "";
  const W = 320, H = 120, pad = 6;
  const vals = serie.map((p) => p.v);
  const min = Math.min(...vals), max = Math.max(...vals);
  const rango = max - min || 1;
  const xs = serie.map((_, i) => pad + (i * (W - 2 * pad)) / (serie.length - 1));
  const ys = vals.map((v) => H - 14 - ((v - min) / rango) * (H - 34));
  const linea = xs.map((x, i) => `${i ? "L" : "M"}${x.toFixed(1)},${ys[i].toFixed(1)}`).join(" ");
  const area = `${linea} L${xs[xs.length - 1].toFixed(1)},${H} L${xs[0].toFixed(1)},${H} Z`;
  const ult = xs.length - 1;
  const puntos = xs.map((x, i) => `<circle class="pd-pt" cx="${x.toFixed(1)}" cy="${ys[i].toFixed(1)}" r="3" data-i="${i}"/>`).join("");
  return `
    <svg class="pd-area" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="${id}" x1="0" x2="0" y1="0" y2="1">
        <stop offset="0%" stop-color="#ff5b6c" stop-opacity=".45"/><stop offset="100%" stop-color="#ff5b6c" stop-opacity="0"/>
      </linearGradient></defs>
      <path class="pd-area-relleno" d="${area}" fill="url(#${id})"/>
      <path class="pd-area-linea" d="${linea}" pathLength="1"/>
      ${puntos}
      <circle class="pd-pt-ult" cx="${xs[ult].toFixed(1)}" cy="${ys[ult].toFixed(1)}" r="4.5"/>
      <circle class="pd-pt-onda" cx="${xs[ult].toFixed(1)}" cy="${ys[ult].toFixed(1)}" r="4.5"/>
    </svg>`;
}

function tarjetaKpi(k, i) {
  const anillo = k.clave === "meta" && k.pct != null ? `
      <svg class="pd-anillo" viewBox="0 0 44 44"><circle class="fondo" cx="22" cy="22" r="18"/>
        <circle class="avance ${k.tono}" cx="22" cy="22" r="18" pathLength="100" style="--pct:${Math.max(0, Math.min(100, k.pct))}"/></svg>` : "";
  return `
    <article class="pd-kpi pd-${k.tono}${k.chico ? " chico" : ""}" data-revelar="${i * 80}">
      <div class="pd-kpi-cab"><span class="pd-kpi-ico">${ICONOS_KPI[k.clave] || "•"}</span><small>${texto(k.etiqueta)}</small></div>
      <div class="pd-kpi-cuerpo"><b${k.chico ? "" : ` data-contar="${texto(k.valor)}"`}>${texto(k.valor)}</b>${anillo}</div>
      ${k.detalle ? `<em>${conCifras(k.detalle)}</em>` : ""}
    </article>`;
}


// Texto con **negritas** (las frases de lectura vienen así de core/).
function conNegritas(valor) {
  return conCifras(valor).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>");
}

// Mini gráfico de línea (sin ejes) para una fila.
function chispa(valores, clase = "") {
  if (!valores || valores.length < 2) return "";
  const W = 90, H = 26, min = Math.min(...valores), max = Math.max(...valores), r = max - min || 1;
  const pts = valores.map((v, i) => `${((i * W) / (valores.length - 1)).toFixed(1)},${(H - 3 - ((v - min) / r) * (H - 6)).toFixed(1)}`);
  const sube = valores[valores.length - 1] >= valores[valores.length - 2];
  return `<svg class="chispa ${clase} ${sube ? "sube" : "baja"}" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
    <polyline points="${pts.join(" ")}"/><circle cx="${pts[pts.length - 1].split(",")[0]}" cy="${pts[pts.length - 1].split(",")[1]}" r="2.6"/></svg>`;
}
