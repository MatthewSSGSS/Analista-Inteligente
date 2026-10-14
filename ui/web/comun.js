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
