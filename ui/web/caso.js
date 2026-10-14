// Seguimiento de un caso: la ficha completa de una persona / punto / código.
// Todo lo calcula Python (ui/person_profile._datos_caso). Usa parte.css.
// Datos: { nombre, sustantivo, registros, estado, tono, por_que, etiquetas, cifra, serie,
//          puesto, kpis, alertas, desglose, ficha }

ICONOS_KPI.total = "Σ";
ICONOS_KPI.vs = "⚖️";
ICONOS_KPI.mejor = "🏔️";
ICONOS_KPI.peor = "🕳️";
ICONOS_KPI.peso = "🥧";
ICONOS_KPI.registros = "🧾";

function _iniciales(nombre) {
  const partes = String(nombre || "?").trim().split(/\s+/).filter(Boolean);
  return ((partes[0] || "?")[0] + (partes.length > 1 ? partes[partes.length - 1][0] : (partes[0] || "")[1] || "")).toUpperCase();
}

function _lineas(serie) {
  // El caso (línea roja) contra el promedio del grupo (discontinua), mes a mes.
  if (!serie || serie.length < 2) return "";
  const W = 420, H = 150, pt = 10, pb = 8;
  const vals = serie.flatMap((p) => [p.v, p.g].filter((x) => x != null));
  const min = Math.min(...vals), max = Math.max(...vals), r = max - min || 1;
  const x = (i) => (i * W) / (serie.length - 1);
  const y = (v) => pt + (1 - (v - min) / r) * (H - pt - pb);
  const ruta = (k) => serie.map((p, i) => (p[k] == null ? "" : `${i && serie[i - 1][k] != null ? "L" : "M"}${x(i).toFixed(1)},${y(p[k]).toFixed(1)}`)).join(" ");
  const area = `${ruta("v")} L${x(serie.length - 1).toFixed(1)},${H} L0,${H} Z`;
  return `
    <svg class="cs-svg" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
      <defs><linearGradient id="csGrad" x1="0" x2="0" y1="0" y2="1"><stop offset="0%" stop-color="#ff5b6c" stop-opacity=".35"/>
        <stop offset="100%" stop-color="#ff5b6c" stop-opacity="0"/></linearGradient></defs>
      <path d="${area}" fill="url(#csGrad)"/>
      <path class="cs-grupo" d="${ruta("g")}"/>
      <path class="cs-caso" d="${ruta("v")}"/>
      ${serie.map((p, i) => `<circle class="cs-pt" cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="3.5" data-i="${i}"/>`).join("")}
    </svg>`;
}

function _puesto(p) {
  if (!p) return "";
  const puntos = p.puntos.map((v) => `<i style="left:${v}%"></i>`).join("");
  return `
    <section class="cs-puesto" data-revelar="0">
      <div class="cs-puesto-cab">
        <div><span class="ai-ceja">Su lugar en el grupo</span>
          <h2>${p.posicion}.º de ${p.total} <span class="cs-medida">${texto(p.medida || "")}</span></h2><p>${texto(p.texto)}</p></div>
        <div class="cs-percentil"><b data-contar="${texto(p.percentil)}">${texto(p.percentil)}</b><small>${texto(p.percentil_lbl)}</small></div>
      </div>
      <div class="cs-pista">
        <span class="cs-pista-lbl izq">${texto(p.min_lbl)}</span>
        <div class="cs-pista-barra">${puntos}<em style="--x:${p.x}%"><span>${texto(p.nombre)}</span></em>
          ${p.prom_x != null ? `<u style="left:${p.prom_x}%"><span>promedio</span></u>` : ""}</div>
        <span class="cs-pista-lbl der">${texto(p.max_lbl)}</span>
      </div>
    </section>`;
}

function _alertas(lista) {
  if (!lista || !lista.length) return "";
  const icono = { positive: "▲", warning: "!", info: "i" };
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Alertas y observaciones</span><h2>Lo que hay que saber de este caso</h2>
        <p>Cada lectura está comparada contra el resto del grupo, contra la meta o contra su propio pasado.</p></div>
      <div class="cs-alertas">${lista.map((a, i) => `
        <article class="cs-alerta ${texto(a.tipo)}" data-revelar="${i * 80}">
          <div class="cs-alerta-cab"><span>${icono[a.tipo] || "i"}</span><b>${texto(a.titulo)}</b></div>
          <p>${conCifras(a.texto)}</p>
          ${a.evidencia.length ? `<div class="cs-evidencia">${a.evidencia.map((e) => `<span><small>${texto(e.n)}</small><b>${texto(e.v)}</b>${e.d ? `<em>${texto(e.d)}</em>` : ""}</span>`).join("")}</div>` : ""}
          ${a.accion ? `<div class="cs-accion">👉 ${texto(a.accion)}</div>` : ""}
        </article>`).join("")}</div>
    </section>`;
}

function _desglose(d) {
  if (!d || !d.filas.length) return "";
  return `
    <section class="pd-bloque cs-desglose-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Qué explica su resultado</span><h2>Desglose por ${texto(d.dimension)}</h2>
        <p>${texto(d.texto)}</p></div>
      <div class="cs-desglose">${d.filas.map((f, i) => `
        <div class="cs-barra-fila" data-revelar="${i * 60}"><span title="${texto(f.n)}">${texto(f.n)}</span>
          <div><i style="--ancho:${f.ancho}%"></i></div><b>${texto(f.t)}</b><small>${texto(f.p)}</small></div>`).join("")}</div>
    </section>`;
}

function _ficha(f) {
  if (!f || !f.length) return "";
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Contexto completo</span><h2>Todo lo que el archivo sabe</h2></div>
      <div class="cs-ficha">${f.map((c, i) => `<div class="cs-dato" data-revelar="${Math.min(i, 16) * 30}"><small>${texto(c.campo)}</small><b>${texto(c.valor)}</b></div>`).join("")}</div>
    </section>`;
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const c = d.cifra || {};
  const raiz = montar(parentElement, "pd cs", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="pd-hero-grid">
        <div class="cs-quien">
          <div class="cs-avatar ${texto(d.tono)}" data-revelar="0"><span>${texto(_iniciales(d.nombre))}</span></div>
          <div>
            <div class="pd-ceja" data-revelar="40"><span class="pd-estado ${texto(d.tono)}"><i></i>${texto(d.estado)}</span>
              <span>${texto(d.sustantivo)} · ${texto(d.registros)} registros</span></div>
            <h1 class="cs-nombre" data-revelar="80">${texto(d.nombre)}</h1>
            ${d.etiquetas && d.etiquetas.length ? `<div class="cs-etiquetas" data-revelar="140">${d.etiquetas.map((e) => `<span><small>${texto(e.k)}</small>${texto(e.v)}</span>`).join("")}</div>` : ""}
            ${d.por_que ? `<p class="cs-porque" data-revelar="200">🔎 ${conCifras(d.por_que)}</p>` : ""}
          </div>
        </div>
        <div class="pd-hero-cifra" data-revelar="150">
          <small>${texto(c.etiqueta)}</small>
          <div class="pd-grande" data-contar="${texto(c.valor)}">${texto(c.valor)}</div>
          ${c.detalle ? `<span class="pd-delta ${texto(c.tono)}">${texto(c.detalle)}</span>` : ""}
          ${d.serie && d.serie.length > 1 ? `
          <div class="cs-grafico">${_lineas(d.serie)}<div class="pd-tip" hidden></div></div>
          <div class="cs-leyenda"><span><i class="caso"></i>${texto(d.nombre)}</span><span><i class="grupo"></i>${texto(d.grupo_lbl)}</span></div>
          <div class="pd-ejes"><span>${texto(d.serie[0].m)}</span><span>${texto(d.serie[d.serie.length - 1].m)}</span></div>` : ""}
        </div>
      </div>
    </section>
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    ${_puesto(d.puesto)}
    ${_alertas(d.alertas)}
    ${_desglose(d.desglose)}
    ${_ficha(d.ficha)}
  `);

  const svg = raiz.querySelector(".cs-svg");
  const tip = raiz.querySelector(".cs-grafico .pd-tip");
  const serie = d.serie || [];
  if (svg && tip) {
    svg.addEventListener("pointermove", (ev) => {
      const r = svg.getBoundingClientRect();
      const i = Math.max(0, Math.min(serie.length - 1, Math.round(((ev.clientX - r.left) / r.width) * (serie.length - 1))));
      raiz.querySelectorAll(".cs-pt").forEach((p) => p.classList.toggle("activo", Number(p.dataset.i) === i));
      tip.hidden = false;
      tip.innerHTML = `<b>${texto(serie[i].t)}</b>${texto(serie[i].m)}${serie[i].gt ? `<br><small>grupo: ${texto(serie[i].gt)}</small>` : ""}`;
      tip.style.left = `${(i / (serie.length - 1)) * 100}%`;
    });
    svg.addEventListener("pointerleave", () => { tip.hidden = true; raiz.querySelectorAll(".cs-pt").forEach((p) => p.classList.remove("activo")); });
  }
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    ...[...raiz.querySelectorAll(".pd-hero, .pd-kpis, .cs-puesto, .cs-desglose")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
    ...[...raiz.querySelectorAll(".pd-kpi, .cs-alerta")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
