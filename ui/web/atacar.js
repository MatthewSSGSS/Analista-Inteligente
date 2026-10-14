// Qué atacar. Todo lo calcula Python (ui/planes._datos_atacar); aquí solo se
// dibuja y se anima. Usa parte.css (recuadro oscuro, tarjetas, cejas).
// Datos: { diag, oportunidades, nota_oportunidades, plan, tablero }

function _barrasCausa(c) {
  if (!c || !c.filas || !c.filas.length) return "";
  return `
    <div class="at-card" data-revelar="120">
      <small class="at-lbl">Dónde nació el cambio · por ${texto(c.etiqueta)}</small>
      ${c.filas.map((f, i) => `
        <div class="at-fila">
          <div class="at-fila-top"><b>${texto(f.nombre)}</b><span class="${f.tono}">${texto(f.delta)}</span></div>
          <div class="at-pista"><i class="${f.tono}" style="--ancho:${f.ancho}%;--d:${i * 90}ms"></i></div>
          <div class="at-fila-sub">${texto(f.de_a)}</div>
          ${f.sub ? `<div class="at-fila-sub">↳ ${conCifras(f.sub)}</div>` : ""}
        </div>`).join("")}
      ${c.nota ? `<div class="at-nota">${conCifras(c.nota)}</div>` : ""}
    </div>`;
}

function _palanca(p) {
  if (!p) return "";
  const barra = (b, i) => `
    <div class="at-palanca-fila"><b>${texto(b.nombre)}</b>
      <div class="at-pista"><i class="${b.tono}" style="--ancho:${b.ancho}%;--d:${300 + i * 120}ms"></i></div>
      <span class="${b.tono}">${texto(b.txt)}</span></div>`;
  return `
    <div class="at-card" data-revelar="200">
      <small class="at-lbl">La palanca · volumen o ticket</small>
      ${p.barras.map(barra).join("")}
      ${p.texto ? `<p class="at-palanca-txt">${conCifras(p.texto)}</p>` : ""}
      ${p.accion ? `<div class="at-palanca-acc">👉 ${texto(p.accion)}</div>` : ""}
    </div>`;
}

function _oportunidades(ops, nota) {
  if (!ops || !ops.length) return "";
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Prioridades</span><h2>Qué atacar primero</h2>
        <p>Cada oportunidad con lo que vale al mes, en orden de valor: empieza por la de arriba.</p></div>
      <div class="at-ops">${ops.map((o, i) => `
        <article class="at-op" data-revelar="${i * 90}">
          <div class="at-op-n">${i + 1}</div>
          <div class="at-op-cuerpo">
            <div class="at-op-tit">${texto(o.titulo)}</div>
            <p>${conCifras(o.texto)}</p>
            ${o.quienes.length ? `<div class="at-op-quienes">${o.quienes.map((q) => `<span>${texto(q.nombre)}<b>${texto(q.monto)}</b></span>`).join("")}</div>` : ""}
            ${o.accion ? `<div class="at-op-acc">👉 ${texto(o.accion)}</div>` : ""}
          </div>
          <div class="at-op-valor">
            <b data-contar="+${texto(o.monto)}">+${texto(o.monto)}</b><small>${texto(o.pct)}</small>
            <div class="at-op-medidor"><i style="--ancho:${o.ancho}%"></i></div>
          </div>
        </article>`).join("")}</div>
      ${nota ? `<p class="at-pie">${texto(nota)}</p>` : ""}
    </section>`;
}

function _plan(p) {
  if (!p) return "";
  const total = p.conteos.reduce((s, c) => s + c.n, 0) || 1;
  return `
    <section class="at-plan" data-revelar="0">
      <div class="at-plan-texto">
        <span class="ai-ceja">Plan del periodo</span>
        <h2>${texto(p.titulo)}</h2>
        <p>${conCifras(p.resumen)}</p>
        <div class="at-plan-barra">${p.conteos.filter((c) => c.n).map((c) => `<span style="--flex:${c.n};--c:${c.color}"></span>`).join("")}</div>
        <div class="at-plan-leyenda">${p.conteos.map((c) => `<span><i style="background:${c.color}"></i><b>${c.n}</b>${texto(c.etiqueta)}</span>`).join("")}</div>
        <div class="at-plan-chips">${p.chips.map((c) => `<span class="${c.n ? c.tono : ""}"><b>${c.n}</b>${texto(c.texto)}</span>`).join("")}</div>
      </div>
      <div class="at-anillo">
        <svg viewBox="0 0 120 120"><circle class="fondo" cx="60" cy="60" r="50"/>
          <circle class="avance" cx="60" cy="60" r="50" pathLength="100" style="--pct:${p.avance};--c:${p.color}"/></svg>
        <div><b data-contar="${p.avance}%">${p.avance}%</b><small>${p.hechos} de ${p.total} pasos</small></div>
      </div>
    </section>`;
}

function _tablero(cols) {
  if (!cols || !cols.length) return "";
  return `<section class="at-tablero">${cols.map((c, ci) => `
    <div class="at-col" style="--c:${c.color}" data-revelar="${ci * 100}">
      <div class="at-col-cab"><span>${c.icono} ${texto(c.etiqueta)}</span><b>${c.tarjetas.length}</b></div>
      <div class="at-col-sub">${texto(c.urgencia)}</div>
      ${c.tarjetas.length ? c.tarjetas.map((t) => `
        <article class="at-tarjeta">
          <div class="at-tarjeta-top"><span>#${t.num}</span>${t.alerta ? `<em class="${t.alerta_roja ? "rojo" : ""}">⚠️ ${texto(t.alerta)}</em>` : ""}</div>
          <div class="at-tarjeta-tit">${texto(t.titulo)}</div>
          ${t.valor ? `<div class="at-tarjeta-valor">💰 ${texto(t.valor)}</div>` : ""}
          ${t.casos.length ? `<div class="at-tarjeta-casos">${t.casos.map((x) => `<span>${texto(x)}</span>`).join("")}${t.mas ? `<span class="mas">+${t.mas}</span>` : ""}</div>` : ""}
          <div class="at-tarjeta-avance"><i style="--ancho:${t.avance}%"></i></div>
          <div class="at-tarjeta-pie"><span class="${t.hecho ? "hecho" : ""}">${texto(t.estado)}</span>${t.fecha ? `<span class="${t.vencida ? "rojo" : ""}">📅 ${texto(t.fecha)}</span>` : ""}</div>
          <div class="at-tarjeta-pie"><span class="at-persona ${t.responsable ? "" : "falta"}"><i>${texto(t.iniciales)}</i>${texto(t.responsable || "Sin responsable")}</span></div>
          ${t.medir ? `<div class="at-tarjeta-medir">🎯 ${texto(t.medir)}</div>` : ""}
        </article>`).join("") : `<div class="at-vacio">Nada en esta categoría</div>`}
    </div>`).join("")}</section>`;
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const g = d.diag;

  const raiz = montar(parentElement, "pd at", `
    ${g ? `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="at-hero">
        <div class="at-hero-cab">
          <div>
            <div class="pd-ceja" data-revelar="0"><span>Qué atacar · por qué se movió el número</span></div>
            <h1 class="pd-titular"></h1>
            <p class="at-hero-sub" data-revelar="200">${texto(g.sub)}</p>
          </div>
          ${g.delta ? `<div class="at-delta ${g.delta.tono}" data-revelar="150"><b data-contar="${texto(g.delta.txt)}">${texto(g.delta.txt)}</b><small>${texto(g.delta.etiqueta)}</small></div>` : ""}
        </div>
        ${g.causa || g.palanca ? `<div class="at-grid">${_barrasCausa(g.causa)}${_palanca(g.palanca)}</div>` : ""}
      </div>
    </section>` : ""}
    ${_oportunidades(d.oportunidades, d.nota_oportunidades)}
    ${_plan(d.plan)}
    ${_tablero(d.tablero)}
  `);

  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    g ? escribir(raiz.querySelector(".pd-titular"), String(g.titular || ""), null, 16) : () => {},
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    ...[...raiz.querySelectorAll(".at-grid, .at-ops, .at-plan, .at-tablero")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
    ...[...raiz.querySelectorAll(".at-op, .at-tarjeta")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
