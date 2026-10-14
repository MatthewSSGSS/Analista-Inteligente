// Resumen ejecutivo. Todo lo calcula Python (ui/executive._datos_resumen);
// aquí solo se dibuja y se anima. Usa las tarjetas y el recuadro oscuro del
// parte del día (escena.py le suma parte.css).
// Datos: { veredicto, porque, kpis, senales, proyeccion, lectura, seguimiento, botones }

ICONOS_KPI.lider = "🏆";

function _proyeccionSvg(p) {
  // Lo real en línea continua y lo proyectado en discontinua hasta un punto hueco que late.
  if (!p || !p.serie || p.serie.length < 2 || !p.meta) return "";
  const W = 320, H = 130, padX = 10;
  const todos = [...p.serie.map((s) => s.v), p.meta.v];
  const min = Math.min(...todos), max = Math.max(...todos), rango = max - min || 1;
  const n = p.serie.length;
  const x = (i) => padX + (i * (W - 2 * padX)) / n;
  const y = (v) => H - 18 - ((v - min) / rango) * (H - 40);
  const real = p.serie.map((s, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(s.v).toFixed(1)}`).join(" ");
  const ux = x(n - 1), uy = y(p.serie[n - 1].v), px = x(n), py = y(p.meta.v);
  return `
    <svg class="rs-proy-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <path class="rs-real" d="${real}" pathLength="1"/>
      <path class="rs-futuro" d="M${ux.toFixed(1)},${uy.toFixed(1)} L${px.toFixed(1)},${py.toFixed(1)}"/>
      <circle class="rs-ult" cx="${ux.toFixed(1)}" cy="${uy.toFixed(1)}" r="4"/>
      <circle class="rs-meta" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="5"/>
      <circle class="rs-meta-onda" cx="${px.toFixed(1)}" cy="${py.toFixed(1)}" r="5"/>
    </svg>
    <div class="rs-proy-ejes"><span>${texto(p.serie[0].m)}</span><span>${texto(p.serie[n - 1].m)}</span>
      <span class="rs-proy-fin">≈ ${texto(p.meta.t)} · ${texto(p.meta.m)}</span></div>`;
}

function _senales(s) {
  if (!s || (!s.positivas.length && !s.vigilar.length)) return "";
  const lista = (items, clase, icono, vacio) => items.length
    ? items.map((t, i) => `<li class="${clase}" data-revelar="${i * 90}"><span>${icono}</span><div>${conCifras(t)}</div></li>`).join("")
    : `<li class="rs-vacio">${vacio}</li>`;
  return `
    <section class="rs-panel">
      <div class="pd-bloque-cab"><span class="ai-ceja">Señales</span><h2>Quién empujó y quién frenó</h2></div>
      <div class="rs-senales">
        <div><b class="rs-sub pos">A favor</b><ul>${lista(s.positivas, "pos", "▲", "Sin mejoras destacadas.")}</ul></div>
        <div><b class="rs-sub neg">A vigilar</b><ul>${lista(s.vigilar, "neg", "!", "Sin alertas prioritarias.")}</ul></div>
      </div>
    </section>`;
}

function _proyeccion(p) {
  if (!p) return "";
  return `
    <section class="rs-panel rs-proy">
      <div class="pd-bloque-cab"><span class="ai-ceja">Proyección</span><h2>A este ritmo…</h2></div>
      <div class="rs-proy-grafico">${_proyeccionSvg(p)}</div>
      <p class="rs-proy-texto">${conCifras(p.texto)}</p>
      <span class="rs-confianza ${texto(p.confianza)}">Confianza ${texto(p.confianza)}</span>
    </section>`;
}

function _lectura(items) {
  if (!items || !items.length) return "";
  const icono = { warning: "⚠️", positive: "✅" };
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Lectura analítica</span><h2>Lo que conviene revisar</h2></div>
      <div class="rs-lectura">${items.map((x, i) => `
        <article class="rs-hallazgo ${texto(x.tipo)}" data-revelar="${i * 90}">
          <div class="rs-hallazgo-cab"><span>${icono[x.tipo] || "💡"}</span><b>${texto(x.titulo)}</b></div>
          <p>${conCifras(x.texto)}</p>
          ${x.accion ? `<div class="rs-hallazgo-accion"><b>Qué revisar</b>${texto(x.accion)}</div>` : ""}
        </article>`).join("")}</div>
    </section>`;
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const v = d.veredicto || {};
  const pq = d.porque || {};

  const raiz = montar(parentElement, "pd rs", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="pd-hero-grid">
        <div class="pd-hero-texto">
          <div class="pd-ceja" data-revelar="0">
            <span class="pd-estado ${texto(v.tono)}"><i></i>${texto(v.estado)}</span>
            <span>Resumen ejecutivo${v.periodo ? ` · ${texto(v.periodo)}` : ""}</span>
          </div>
          <h1 class="pd-titular"></h1>
          ${v.detalle ? `<p class="pd-perspectiva" data-revelar="300">${conCifras(v.detalle)}</p>` : ""}
        </div>
        ${pq.frases && pq.frases.length ? `
        <div class="rs-porque" data-revelar="150">
          <small>Por qué y qué atacar</small>
          <ol>${pq.frases.map((f, i) => `<li data-revelar="${250 + i * 120}"><span>${i + 1}</span><p>${conCifras(f)}</p></li>`).join("")}</ol>
          <div class="rs-porque-botones">
            <button class="ai-cta" data-accion="atacar">🎯 Qué atacar y el plan <span class="flecha">→</span></button>
            ${d.seguimiento ? `<button class="rs-sec" data-accion="seguimiento">🔎 Ver un caso concreto</button>` : ""}
          </div>
        </div>` : ""}
      </div>
    </section>
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    ${d.senales || d.proyeccion ? `<div class="rs-dos">${_senales(d.senales)}${_proyeccion(d.proyeccion)}</div>` : ""}
    ${_lectura(d.lectura)}
  `);

  acciones(raiz, setTriggerValue, d.botones || {});
  const proy = raiz.querySelector(".rs-proy");
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    escribir(raiz.querySelector(".pd-titular"), String(v.titular || ""), null, 16),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(raiz.querySelector(".pd-kpis"), () => raiz.querySelector(".pd-kpis").classList.add("dibujar")),
    alVerse(proy, () => proy && proy.classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpi, .rs-hallazgo, .rs-panel")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
