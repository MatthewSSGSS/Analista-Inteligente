// Inicio · parte del día del gerente. Todo lo calcula Python
// (ui/home._datos_parte); aquí solo se dibuja y se anima.
// Datos: { encabezado, titular, perspectiva, causa, nota, cifra, serie,
//          kpis, movio, acciones, alertas, botones }

function _movio(m) {
  if (!m || !m.filas || !m.filas.length) return "";
  const tope = Math.max(...m.filas.map((f) => Math.abs(f.delta))) || 1;
  const filas = m.filas.map((f, i) => {
    const ancho = (Math.abs(f.delta) / tope) * 50;
    const lado = f.delta >= 0 ? "der" : "izq";
    return `
      <div class="pd-mov-fila" data-revelar="${i * 70}">
        <span class="pd-mov-nombre" title="${texto(f.nombre)}">${texto(f.nombre)}</span>
        <div class="pd-mov-pista"><span class="pd-mov-cero"></span>
          <span class="pd-mov-barra ${lado}" style="--ancho:${ancho.toFixed(1)}%"></span></div>
        <span class="pd-mov-cifra ${lado}">${texto(f.delta_txt)}<small>${texto(f.pct_txt)}</small></span>
      </div>`;
  }).join("");
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Por qué cambió</span><h2>¿Qué lo movió?</h2>
        <p>${texto(m.subtitulo)}</p></div>
      <div class="pd-mov">${filas}</div>
    </section>`;
}

function _acciones(acciones) {
  if (!acciones || !acciones.length) return "";
  const tarjetas = acciones.map((a, i) => `
    <article class="pd-acc ${i === 0 ? "abierta" : ""}" data-revelar="${i * 90}">
      <button class="pd-acc-cab" type="button" aria-expanded="${i === 0}">
        <span class="pd-acc-n">${i + 1}</span>
        <span class="pd-acc-tit">${texto(a.titulo)}</span>
        ${a.valor ? `<span class="pd-acc-valor"><b data-contar="+${texto(a.valor)}">+${texto(a.valor)}</b><small>al mes${a.pct ? ` · ${texto(a.pct)}` : ""}</small></span>` : ""}
        <span class="pd-acc-flecha">⌄</span>
      </button>
      <div class="pd-acc-cuerpo"><div>
        ${a.texto ? `<p>${conCifras(a.texto)}</p>` : ""}
        ${a.hacer ? `<div class="pd-acc-linea"><span>👉</span><div><b>Qué hacer</b>${texto(a.hacer)}</div></div>` : ""}
        ${a.medir ? `<div class="pd-acc-linea"><span>🎯</span><div><b>Cómo saber que funcionó</b>${texto(a.medir)}</div></div>` : ""}
        ${a.quienes && a.quienes.length ? `<div class="pd-acc-quienes">${a.quienes.map((q) => `<span>${texto(q)}</span>`).join("")}</div>` : ""}
      </div></div>
    </article>`).join("");
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Prioridades</span><h2>Qué hacer ahora</h2>
        <p>Ordenadas por lo que valen al mes. Toca cada una para ver qué hacer y cómo medirlo.</p></div>
      <div class="pd-accs">${tarjetas}</div>
    </section>`;
}

function _alertas(alertas) {
  if (!alertas || !alertas.length) return "";
  return `<section class="pd-alertas">${alertas.map((a, i) => `
    <div class="pd-alerta" data-revelar="${i * 90}"><span class="pd-alerta-ico">⚠️</span>
      <div><b>${texto(a.titulo)}</b><p>${conCifras(a.texto)}</p></div></div>`).join("")}</section>`;
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const e = d.encabezado || {};
  const c = d.cifra || {};

  const raiz = montar(parentElement, "pd", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="pd-hero-grid">
        <div class="pd-hero-texto">
          <div class="pd-ceja" data-revelar="0">
            <span class="pd-estado ${texto(e.tono)}"><i></i>${texto(e.estado)}</span>
            <span>Parte del día · ${texto(e.periodo)}</span>
          </div>
          <h1 class="pd-titular"></h1>
          ${d.perspectiva ? `<p class="pd-perspectiva" data-revelar="300">${conCifras(d.perspectiva)}</p>` : ""}
          ${d.causa ? `<p class="pd-causa" data-revelar="420">${conCifras(d.causa)}</p>` : ""}
          ${d.nota ? `<p class="pd-nota" data-revelar="480">${texto(d.nota)}</p>` : ""}
        </div>
        <div class="pd-hero-cifra" data-revelar="150">
          <small>${texto(c.etiqueta)}</small>
          <div class="pd-grande" data-contar="${texto(c.valor)}">${texto(c.valor)}</div>
          ${c.detalle ? `<span class="pd-delta ${texto(c.tono)}">${texto(c.detalle)}</span>` : ""}
          <div class="pd-grafico">${areaSvg(d.serie)}<div class="pd-tip" hidden></div></div>
          ${d.serie && d.serie.length > 1 ? `<div class="pd-ejes"><span>${texto(d.serie[0].m)}</span><span>${texto(d.serie[d.serie.length - 1].m)}</span></div>` : ""}
        </div>
      </div>
    </section>
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    ${_movio(d.movio)}
    ${_acciones(d.acciones)}
    ${_alertas(d.alertas)}
    <div class="pd-botones" data-revelar="0">
      <button class="ai-cta" data-accion="atacar">🎯 Ver el plan completo <span class="flecha">→</span></button>
      <button class="pd-sec" data-accion="resumen">📋 Ver el resumen</button>
    </div>
  `);

  acciones(raiz, setTriggerValue, d.botones || {});

  // Acordeón de acciones: se abre sin volver a Python.
  raiz.querySelectorAll(".pd-acc-cab").forEach((cab) => cab.addEventListener("click", () => {
    const art = cab.closest(".pd-acc");
    const abierta = art.classList.toggle("abierta");
    cab.setAttribute("aria-expanded", String(abierta));
  }));

  // Valor de cada mes al pasar el cursor por el gráfico.
  const svg = raiz.querySelector(".pd-area");
  const tip = raiz.querySelector(".pd-tip");
  const serie = d.serie || [];
  const enGrafico = (ev) => {
    if (!svg || !serie.length) return;
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(serie.length - 1, Math.round(((ev.clientX - r.left) / r.width) * (serie.length - 1))));
    raiz.querySelectorAll(".pd-pt").forEach((p) => p.classList.toggle("activo", Number(p.dataset.i) === i));
    tip.hidden = false;
    tip.innerHTML = `<b>${texto(serie[i].t)}</b>${texto(serie[i].m)}`;
    tip.style.left = `${(i / (serie.length - 1)) * 100}%`;
  };
  const fuera = () => { if (tip) tip.hidden = true; raiz.querySelectorAll(".pd-pt").forEach((p) => p.classList.remove("activo")); };
  if (svg) { svg.addEventListener("pointermove", enGrafico); svg.addEventListener("pointerleave", fuera); }

  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    escribir(raiz.querySelector(".pd-titular"), String(d.titular || ""), null, 18),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(raiz.querySelector(".pd-hero"), () => raiz.querySelector(".pd-hero").classList.add("dibujar")),
    alVerse(raiz.querySelector(".pd-kpis"), () => raiz.querySelector(".pd-kpis").classList.add("dibujar")),
    alVerse(raiz.querySelector(".pd-mov"), () => raiz.querySelector(".pd-mov").classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpi, .pd-acc")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
