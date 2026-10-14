// Canales. Todo lo calcula Python (ui/comercial._datos_canales). Usa parte.css.
// Datos: { titular, en_riesgo, periodo, kpis, dona, escala, grupos, jugadas }

ICONOS_KPI.crecen = "🚀";
ICONOS_KPI.caen = "📉";
ICONOS_KPI.riesgo = "⚠️";

function _dona(partes) {
  // Dona de participación: cada canal es un arco que se dibuja al aparecer.
  if (!partes || !partes.length) return "";
  let acum = 0;
  const arcos = partes.map((p, i) => {
    const a = `<circle class="cn-arco" cx="60" cy="60" r="44" pathLength="100"
      style="--largo:${Math.max(0, p.pct - 0.6).toFixed(2)};--inicio:${(-acum).toFixed(2)};--c:${p.color};--d:${i * 110}ms"/>`;
    acum += p.pct;
    return a;
  }).join("");
  const leyenda = partes.map((p) => `<li><i style="background:${p.color}"></i><span>${texto(p.nombre)}</span><b>${p.pct.toFixed(1)}%</b></li>`).join("");
  return `
    <div class="cn-dona" data-revelar="150">
      <svg viewBox="0 0 120 120">${arcos}</svg>
      <ul>${leyenda}</ul>
    </div>`;
}

function _grupos(d) {
  if (!d.grupos || !d.grupos.length) return "";
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">A simple vista</span><h2>Semáforo de canales</h2>
        <p>Cada canal agrupado por lo que hay que hacer con él. Arriba lo urgente; abajo lo que está estable.</p></div>
      <div class="cn-escala"><span>Color de cada tarjeta:</span><span>${texto(d.escala[0])}</span><i></i><span>${texto(d.escala[1])}</span></div>
      ${d.grupos.map((g, gi) => `
        <div class="cn-grupo" data-revelar="${gi * 80}">
          <div class="cn-grupo-cab"><span class="cn-chip" style="background:${g.color}">${texto(g.etiqueta)} · ${g.tarjetas.length}</span>
            <span>${texto(g.accion)}</span></div>
          <div class="cn-grid">${g.tarjetas.map((t) => `
            <article class="cn-card" style="--c:${t.color}" title="${texto(t.nombre)}">
              <div class="cn-card-cab"><b>${texto(t.nombre)}</b><span>${texto(t.estado)}</span></div>
              <div class="cn-card-valor" data-contar="${texto(t.valor)}">${texto(t.valor)}</div>
              <div class="cn-card-fila"><span>Participación</span><b>${t.part}</b></div>
              <div class="cn-card-fila"><span>vs. ${texto(d.periodo_anterior)}</span><b style="color:${t.crec_color}">${t.flecha} ${texto(t.crec)}</b></div>
              ${t.meta ? `<div class="cn-card-fila"><span>Meta</span><b style="color:${t.meta_color}">${texto(t.meta)}</b></div>` : ""}
              <div class="cn-card-barra"><i style="--ancho:${t.ancho}%"></i></div>
            </article>`).join("")}</div>
        </div>`).join("")}
    </section>`;
}

function _jugadas(lista) {
  if (!lista || !lista.length) return "";
  const color = { malo: "var(--red)", bueno: "var(--green-strong)" };
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Dónde poner el esfuerzo</span><h2>Las jugadas, por impacto</h2>
        <p>Cada una con su cifra, para poder compararlas y elegir en vez de discutirlas. Rojo va mal · verde va bien.</p></div>
      <div class="cn-jugadas">${lista.map((j, i) => `
        <article class="cn-jugada ${texto(j.tono)}" data-revelar="${i * 80}">
          <div class="cn-jugada-cuerpo">
            <small>${texto(j.tipo)}</small>
            <p>${j.partes.map(([t, tono]) => tono === "info" ? texto(t)
              : `<b style="color:${color[tono] || "var(--text)"}">${texto(t)}</b>`).join("")}</p>
            ${j.palanca ? `<em>Palanca: <b style="color:${color[j.palanca_tono] || "var(--text)"}">${texto(j.palanca)}</b></em>` : ""}
          </div>
          <div class="cn-jugada-impacto"><small>Impacto</small><b data-contar="${texto(j.impacto)}">${texto(j.impacto)}</b>
            <div class="cn-medidor"><i style="--ancho:${j.ancho}%"></i></div></div>
        </article>`).join("")}</div>
    </section>`;
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const raiz = montar(parentElement, "pd cn", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="pd-hero-grid">
        <div class="pd-hero-texto">
          <div class="pd-ceja" data-revelar="0">
            <span class="pd-estado ${d.en_riesgo ? "negative" : "positive"}"><i></i>${d.en_riesgo ? "Hay negocio en riesgo" : "Sin canales grandes en riesgo"}</span>
            <span>Estrategia por canal · ${texto(d.periodo)}</span>
          </div>
          <h1 class="pd-titular"></h1>
        </div>
        ${_dona(d.dona)}
      </div>
    </section>
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    ${_grupos(d)}
    ${_jugadas(d.jugadas)}
  `);
  const dona = raiz.querySelector(".cn-dona");
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    escribir(raiz.querySelector(".pd-titular"), String(d.titular || ""), null, 14),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(dona, () => dona && dona.classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpis, .cn-grupo, .cn-jugadas")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
    ...[...raiz.querySelectorAll(".cn-card, .cn-jugada, .pd-kpi")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
