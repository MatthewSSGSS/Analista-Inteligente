// Analítica (explorador). Todo lo calcula Python (ui/explorer.py: _elegir_lente,
// _en_js y los constructores de cada lente); aquí solo se dibuja. Usa parte.css.
// Modo "lentes":  { lentes: [{clave, icono, nombre, pregunta, activa}], botones }
// Modo "lectura": { base: [texto con **negritas**], titulo, subtitulo, badge,
//                   kpis?, grafico: {tipo: barras|lineas|calor|puntos|cajas, …}, hallazgos }

ICONOS_KPI.antes = "⏮️";
ICONOS_KPI.despues = "⏭️";
ICONOS_KPI.diferencia = "↕️";
ICONOS_KPI.ejecutado = "✅";
ICONOS_KPI.objetivo = "🏁";

const AN_N = 190;   // ancho de la columna de nombres en las barras y cajas (px)

function _cifraAn(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1).replace(/\.0$/, "")} mil M`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(a >= 1e8 ? 0 : 1).replace(/\.0$/, "")} M`;
  if (a >= 1e4) return `${Math.round(v / 1e3)} mil`;
  return v.toLocaleString("es-CO", { maximumFractionDigits: 1 });
}

function _guias(min, max, n = 4) {
  const paso = (max - min) / n || 1;
  const pot = Math.pow(10, Math.floor(Math.log10(Math.abs(paso))));
  const redondo = [1, 2, 2.5, 5, 10].map((m) => m * pot).find((m) => m >= paso) || paso;
  const out = [];
  for (let v = Math.ceil(min / redondo) * redondo; v <= max + 1e-9 && out.length < 7; v += redondo) out.push(v);
  return out;
}

function _rango(valores, extra = []) {
  let min = Math.min(...valores, ...extra), max = Math.max(...valores, ...extra);
  const margen = (max - min) * 0.08 || Math.abs(max) * 0.1 || 1;
  if (min >= 0 && min - margen < 0) min = 0; else min -= margen;
  return [min, max + margen];
}

// ── Barras horizontales (ranking, periodo vs. periodo, cumplimiento) ─────
function _barras(g) {
  const div = !!g.divergente;
  const filas = (g.filas || []).map((f, i) => {
    const a = Math.max(-100, Math.min(100, Number(f.a) || 0));
    let barra, cifra;
    if (div) {
      const w = (Math.abs(a) / 2) * 0.8;
      barra = `left:${a >= 0 ? 50 : 50 - w}%;width:${w}%`;
      cifra = a >= 0 ? `left:calc(${50 + w}% + 6px)` : `right:calc(${50 + w}% + 6px)`;
    } else {
      const w = Math.max(0, a) * 0.78;
      barra = `left:0;width:${w}%`;
      cifra = `left:calc(${w}% + 8px)`;
    }
    return `<div class="an-fila" style="--i:${i}">
      <span class="an-n" title="${texto(f.n)}">${texto(f.n)}</span>
      <div class="an-pista${div ? " div" : ""}"><i class="an-barra ${texto(f.tono)}" style="${barra}"></i>
        <b class="an-cifra" style="${cifra}">${texto(f.t)}</b></div>
    </div>`;
  }).join("");
  const ref = g.ref && !div
    ? `<div class="an-ref" style="left:calc(${AN_N}px + (100% - ${AN_N}px) * ${(g.ref.pos * 0.78) / 100})"><span>${texto(g.ref.t)}</span></div>`
    : "";
  return `<div class="an-barras" style="--n:${AN_N}px">${ref}${filas}</div>`;
}

// ── Líneas en el tiempo (evolución), con leyenda que oculta series ───────
function _lineas(g) {
  const x = g.x || [], series = g.series || [], prom = g.prom;
  const todas = [...series, ...(prom ? [prom] : [])];
  const vals = todas.flatMap((s) => (s.v || []).filter((v) => v != null));
  if (x.length < 2 || !vals.length) return "";
  const H = 280, pt = 12, pb = 8;
  const [min, max] = _rango(vals, g.base100 ? [100] : []);
  const yv = (v) => pt + (1 - (v - min) / (max - min || 1)) * (H - pt - pb);
  const xv = (i) => (i * 1000) / (x.length - 1);
  const trazo = (v) => {
    let d = "", abierto = false;
    v.forEach((y, i) => {
      if (y == null) { abierto = false; return; }
      d += `${abierto ? "L" : "M"}${xv(i).toFixed(1)},${yv(y).toFixed(1)} `;
      abierto = true;
    });
    return d;
  };
  const guias = _guias(min, max);
  const lineasGuia = guias.map((v) => `<line class="an-guia" x1="0" x2="1000" y1="${yv(v).toFixed(1)}" y2="${yv(v).toFixed(1)}"/>`).join("");
  const parcial = g.parcial
    ? `<rect class="an-parcial" x="${xv(Math.max(0, x.length - 1.5)).toFixed(1)}" y="0" width="${(1000 - xv(Math.max(0, x.length - 1.5))).toFixed(1)}" height="${H}"/>`
    : "";
  const cien = g.base100 ? `<line class="an-cien" x1="0" x2="1000" y1="${yv(100).toFixed(1)}" y2="${yv(100).toFixed(1)}"/>` : "";
  const caminos = series.map((s, i) => `<path class="an-linea" data-s="${i}" d="${trazo(s.v)}" style="stroke:${texto(s.color)}" pathLength="1"/>`).join("")
    + (prom ? `<path class="an-linea prom" data-s="p" d="${trazo(prom.v)}" pathLength="1"/>` : "");
  const salto = x.length > 14 ? Math.ceil(x.length / 12) : 1;
  const ejeX = x.map((m, i) => (i % salto === 0 || i === x.length - 1)
    ? `<span style="left:${(i / (x.length - 1)) * 100}%">${texto(m)}</span>` : "").join("");
  const ejeY = guias.map((v) => `<span style="top:${yv(v)}px">${texto(_cifraAn(v))}</span>`).join("");
  const leyenda = series.map((s, i) => `<button class="an-ley" data-s="${i}"><i style="background:${texto(s.color)}"></i>${texto(s.n)}</button>`).join("")
    + (prom ? `<button class="an-ley prom" data-s="p"><i></i>${texto(prom.n)}</button>` : "")
    + (g.parcial ? `<span class="an-ley-nota">▒ último periodo incompleto</span>` : "");
  return `<div class="an-lin">
      <div class="an-eje-y">${ejeY}</div>
      <div class="an-lin-area">
        <svg viewBox="0 0 1000 ${H}" preserveAspectRatio="none">${lineasGuia}${parcial}${cien}${caminos}</svg>
        <div class="an-guia-v" hidden></div><div class="an-tip" hidden></div>
      </div>
      <div class="an-eje-x">${ejeX}</div>
    </div>
    <div class="an-leyenda">${leyenda}</div>`;
}

function _interactuarLineas(raiz, g) {
  const area = raiz.querySelector(".an-lin-area");
  if (!area) return () => {};
  const ocultas = new Set();
  raiz.querySelectorAll(".an-ley[data-s]").forEach((b) => b.addEventListener("click", () => {
    const s = b.dataset.s;
    if (ocultas.has(s)) ocultas.delete(s); else ocultas.add(s);
    b.classList.toggle("oculta", ocultas.has(s));
    raiz.querySelectorAll(`.an-linea[data-s="${s}"]`).forEach((p) => p.classList.toggle("oculta", ocultas.has(s)));
  }));
  const tip = area.querySelector(".an-tip"), guia = area.querySelector(".an-guia-v");
  const n = (g.x || []).length;
  const mover = (ev) => {
    const r = area.getBoundingClientRect();
    const i = Math.max(0, Math.min(n - 1, Math.round(((ev.clientX - r.left) / r.width) * (n - 1))));
    const pct = (i / (n - 1)) * 100;
    const filas = (g.series || []).map((s, k) => ocultas.has(String(k)) || s.v[i] == null ? ""
      : `<div><i style="background:${texto(s.color)}"></i>${texto(s.n)}<b>${texto(s.t[i])}</b></div>`).join("")
      + (g.prom && !ocultas.has("p") && g.prom.v[i] != null ? `<div class="prom"><i></i>${texto(g.prom.n)}<b>${texto(g.prom.t[i])}</b></div>` : "");
    tip.innerHTML = `<small>${texto(g.x[i])}</small>${filas}`;
    tip.hidden = false; guia.hidden = false;
    guia.style.left = `${pct}%`;
    tip.style.left = `${pct}%`;
    tip.classList.toggle("izq", pct > 60);
  };
  const salir = () => { tip.hidden = true; guia.hidden = true; };
  area.addEventListener("pointermove", mover);
  area.addEventListener("pointerleave", salir);
  return () => { area.removeEventListener("pointermove", mover); area.removeEventListener("pointerleave", salir); };
}

// ── Mapa de calor (tabla cruzada) ────────────────────────────────────────
function _calor(g) {
  const cols = g.cols || [];
  const cab = `<div class="an-c-esq"></div>` + cols.map((c) => `<div class="an-c-col" title="${texto(c)}">${texto(c)}</div>`).join("");
  const cuerpo = (g.filas || []).map((f, r) => `<div class="an-c-fila" title="${texto(f.n)}">${texto(f.n)}</div>`
    + f.c.map((c, j) => c.i == null ? `<div class="an-c-celda vacia"></div>`
      : `<div class="an-c-celda${c.i > 0.55 ? " oscura" : ""}" style="--i:${c.i};--r:${r}" title="${texto(f.n)} × ${texto(cols[j])}: ${texto(c.t)}">${texto(c.t)}</div>`).join("")).join("");
  return `<div class="an-calor-envoltura"><div class="an-calor" style="--cols:${cols.length}">${cab}${cuerpo}</div></div>`;
}

// ── Dispersión (relación entre dos métricas) ─────────────────────────────
function _puntos(g) {
  const p = g.p || [];
  if (p.length < 2) return "";
  const H = 380, pt = 14, pb = 10;
  const [x0, x1] = _rango(p.map((q) => q.x));
  const [y0, y1] = _rango(p.map((q) => q.y));
  const fx = (v) => (v - x0) / (x1 - x0 || 1);
  const yv = (v) => pt + (1 - (v - y0) / (y1 - y0 || 1)) * (H - pt - pb);
  const recta = g.recta ? `<line class="an-recta" x1="${(fx(g.recta[0][0]) * 1000).toFixed(1)}" y1="${yv(g.recta[0][1]).toFixed(1)}"
      x2="${(fx(g.recta[1][0]) * 1000).toFixed(1)}" y2="${yv(g.recta[1][1]).toFixed(1)}"/>` : "";
  const medianas = `<line class="an-mediana" x1="${(fx(g.mx) * 1000).toFixed(1)}" x2="${(fx(g.mx) * 1000).toFixed(1)}" y1="0" y2="${H}"/>
    <line class="an-mediana" x1="0" x2="1000" y1="${yv(g.my).toFixed(1)}" y2="${yv(g.my).toFixed(1)}"/>`;
  const puntos = p.map((q, i) => `<span class="an-pt ${texto(q.tono)}${g.rotular ? " grande" : ""}" data-i="${i}"
      style="left:${fx(q.x) * 100}%;top:${yv(q.y)}px">${g.rotular && q.n ? `<em>${texto(q.n.slice(0, 22))}</em>` : ""}</span>`).join("");
  const ejeY = _guias(y0, y1).map((v) => `<span style="top:${yv(v)}px">${texto(_cifraAn(v))}</span>`).join("");
  const ejeX = _guias(x0, x1).map((v) => `<span style="left:${fx(v) * 100}%">${texto(_cifraAn(v))}</span>`).join("");
  return `<div class="an-pts">
      <div class="an-eje-y">${ejeY}</div>
      <div class="an-pts-area">
        <svg viewBox="0 0 1000 ${H}" preserveAspectRatio="none">${medianas}${recta}</svg>
        ${puntos}<div class="an-tip" hidden></div>
      </div>
      <div class="an-eje-x">${ejeX}</div>
      <div class="an-ejes-nombre"><span>↑ ${texto(g.ey)}</span><span>${texto(g.ex)} →</span></div>
    </div>
    <div class="an-leyenda"><span class="an-ley-nota"><i class="pos"></i>rinde más de lo esperado</span>
      <span class="an-ley-nota"><i class="neg"></i>rinde menos</span><span class="an-ley-nota">- - lo esperado · ⋯ medianas</span></div>`;
}

function _interactuarPuntos(raiz, g) {
  const area = raiz.querySelector(".an-pts-area");
  if (!area) return () => {};
  const tip = area.querySelector(".an-tip");
  const sobre = (ev) => {
    const el = ev.target.closest(".an-pt");
    if (!el) { tip.hidden = true; return; }
    const q = g.p[Number(el.dataset.i)];
    tip.innerHTML = `${q.n ? `<small>${texto(q.n)}</small>` : ""}<div>${texto(g.ex)}<b>${texto(q.tx)}</b></div>`
      + `<div>${texto(g.ey)}<b>${texto(q.ty)}</b></div>`;
    tip.style.left = el.style.left;
    tip.style.top = el.style.top;
    tip.classList.toggle("izq", parseFloat(el.style.left) > 60);
    tip.hidden = false;
  };
  const salir = () => { tip.hidden = true; };
  area.addEventListener("pointerover", sobre);
  area.addEventListener("pointerleave", salir);
  return () => { area.removeEventListener("pointerover", sobre); area.removeEventListener("pointerleave", salir); };
}

// ── Cajas (distribución) ─────────────────────────────────────────────────
function _cajas(g) {
  const filas = (g.g || []).map((c, i) => `<div class="an-caja-fila" style="--i:${i}">
      <span class="an-n" title="${texto(c.n)}">${texto(c.n)}<small>${texto(c.cuenta)} registros</small></span>
      <div class="an-caja-pista" title="${texto(c.t)}">
        <span class="bigote" style="left:${c.lo}%;width:${Math.max(0.5, c.hi - c.lo)}%"></span>
        <span class="caja" style="left:${c.q1}%;width:${Math.max(0.8, c.q3 - c.q1)}%"></span>
        <span class="mediana" style="left:${c.med}%"></span>
        ${(c.fuera || []).map((x) => `<i style="left:${x}%"></i>`).join("")}
      </div>
    </div>`).join("");
  if (!filas) return "";
  return `<div class="an-cajas" style="--n:${AN_N}px">${filas}
      <div class="an-cajas-eje"><span>${texto(g.min)}</span><span>${texto(g.max)}</span></div></div>
    <div class="an-leyenda"><span class="an-ley-nota"><i class="caja"></i>la mitad central de los registros</span>
      <span class="an-ley-nota"><i class="mediana"></i>mediana</span><span class="an-ley-nota"><i class="fuera"></i>fuera de lo habitual</span></div>`;
}

const _GRAFICOS = { barras: _barras, lineas: _lineas, calor: _calor, puntos: _puntos, cajas: _cajas };

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const d = data || {};
  acento(d.acento);

  if (d.modo === "lentes") {
    const raiz = montar(parentElement, "an an-sel", `
      <nav class="an-lentes">${(d.lentes || []).map((l, i) => `
        <button class="an-lente${l.activa ? " activa" : ""}" data-accion="${texto(l.clave)}" data-revelar="${i * 45}">
          <span class="an-ico">${texto(l.icono)}</span><b>${texto(l.nombre)}</b><small>${texto(l.pregunta)}</small>
        </button>`).join("")}</nav>`);
    acciones(raiz, setTriggerValue, d.botones || {});
    const limpiar = [revelar(raiz), ...[...raiz.querySelectorAll(".an-lente")].map((b) => foco(b, false))];
    return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
  }

  const g = d.grafico || {};
  const dibujar = _GRAFICOS[g.tipo];
  const kpis = d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : "";
  const raiz = montar(parentElement, "pd an", `
    ${d.base && d.base.length ? `<div class="an-base" data-revelar="0"><span>📐</span><p>${d.base.map(conNegritas).join(" · ")}</p></div>` : ""}
    ${kpis}
    <section class="an-tarjeta" data-revelar="120">
      <header class="an-cab">
        <div><h3>${texto(d.titulo)}</h3>${d.subtitulo ? `<p>${texto(d.subtitulo)}</p>` : ""}</div>
        ${d.badge ? `<span class="an-badge">${texto(d.badge)}</span>` : ""}
      </header>
      <div class="an-grafico an-${texto(g.tipo)}">${dibujar ? dibujar(g) : ""}</div>
    </section>
    ${d.hallazgos && d.hallazgos.length ? `<section class="an-dice" data-revelar="240"><h4>💡 Qué dice</h4>
      <ul>${d.hallazgos.map((h) => `<li>${conNegritas(h)}</li>`).join("")}</ul></section>` : ""}
  `);

  const grafico = raiz.querySelector(".an-grafico");
  const limpiar = [
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(raiz.querySelector(".pd-kpis"), () => raiz.querySelector(".pd-kpis").classList.add("dibujar")),
    alVerse(grafico, () => grafico.classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpi")].map((t) => foco(t, false)),
    g.tipo === "lineas" ? _interactuarLineas(raiz, g) : null,
    g.tipo === "puntos" ? _interactuarPuntos(raiz, g) : null,
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
