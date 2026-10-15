// Proyección. Todo lo calcula Python (ui/forecast._datos_proyeccion). Usa parte.css.
// Datos: { frase, tono, etiqueta, grande, delta, kpis, puntos, confianza }
// puntos: [{m, v, t, futuro, lo, hi, plo, phi, rango}]

ICONOS_KPI.real = "📍";
ICONOS_KPI.estimado = "🔮";
ICONOS_KPI.probable = "🎯";
ICONOS_KPI.confianza = "🛡️";

function _escala(min, max) {
  // 4 o 5 guías horizontales en cifras redondas.
  const paso = (max - min) / 4 || 1;
  const pot = Math.pow(10, Math.floor(Math.log10(Math.abs(paso))));
  const redondo = [1, 2, 2.5, 5, 10].map((m) => m * pot).find((m) => m >= paso) || paso;
  const out = [];
  for (let v = Math.ceil(min / redondo) * redondo; v <= max + 1e-9 && out.length < 6; v += redondo) out.push(v);
  return out;
}

function _cifra(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return `${(v / 1e9).toFixed(1).replace(/\.0$/, "")} mil M`;
  if (a >= 1e6) return `${(v / 1e6).toFixed(a >= 1e8 ? 0 : 1).replace(/\.0$/, "")} M`;
  if (a >= 1e4) return `${Math.round(v / 1e3)} mil`;
  return v.toLocaleString("es-CO", { maximumFractionDigits: 1 });
}

function _mesEje(m, i, puntos) {
  // «ago» en el eje; el año solo en el primer mes y cuando cambia (enero).
  const [mes, anio] = String(m).split(" ");
  const previo = i > 0 ? String(puntos[i - 1].m).split(" ")[1] : null;
  return i === 0 || anio !== previo ? `${mes} ${anio}` : mes;
}

function _grafico(puntos) {
  if (!puntos || puntos.length < 2) return "";
  const W = 760, H = 300, pl = 54, pr = 34, pt = 40, pb = 26;
  const vals = puntos.flatMap((p) => [p.v, p.lo, p.hi].filter((x) => x != null));
  let min = Math.min(...vals), max = Math.max(...vals);
  const margen = (max - min) * 0.08 || Math.abs(max) * 0.1 || 1;
  min -= margen; max += margen;
  const rango = max - min || 1;
  const x = (i) => pl + (i * (W - pl - pr)) / (puntos.length - 1);
  const y = (v) => pt + (1 - (v - min) / rango) * (H - pt - pb);
  const pctX = (i) => (x(i) / W) * 100;
  const reales = puntos.map((p, i) => ({ ...p, i })).filter((p) => !p.futuro);
  const futuros = puntos.map((p, i) => ({ ...p, i })).filter((p) => p.futuro);
  const ult = reales[reales.length - 1];
  const linea = (arr) => arr.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const banda = (lo, hi) => futuros.length ? `M${x(ult.i).toFixed(1)},${y(ult.v).toFixed(1)} `
    + futuros.map((p) => `L${x(p.i).toFixed(1)},${y(p[hi]).toFixed(1)}`).join(" ")
    + " " + [...futuros].reverse().map((p) => `L${x(p.i).toFixed(1)},${y(p[lo]).toFixed(1)}`).join(" ") + " Z" : "";
  const area = `${linea(reales)} L${x(ult.i).toFixed(1)},${H - pb} L${x(reales[0].i).toFixed(1)},${H - pb} Z`;
  const guias = _escala(min, max);
  const lineasGuia = guias.map((v) => `<line class="py-guia" x1="${pl}" x2="${W - pr}" y1="${y(v).toFixed(1)}" y2="${y(v).toFixed(1)}"/>`).join("");
  const puntosSvg = puntos.map((p, i) => `<circle class="py-pt ${p.futuro ? "fut" : ""}" cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="3.4" data-i="${i}"/>`).join("");
  // Mejor y peor mes real, marcados.
  const iMax = reales.reduce((a, b) => (b.v > a.v ? b : a)).i;
  const iMin = reales.reduce((a, b) => (b.v < a.v ? b : a)).i;
  // Cada cifra escrita sobre su punto, en HTML encima del SVG (el texto dentro
  // de un SVG estirado se deforma). Con muchos meses va uno sí y uno no, pero
  // siempre el último real, los estimados, el mejor y el peor.
  const ancho = window.innerWidth || 1200;
  const salto = ancho < 700 ? 3 : (puntos.length > 16 ? 2 : 1);
  const cifras = puntos.map((p, i) => {
    const clave = p.futuro || i === ult.i || i === iMax || i === iMin || (ult.i - i) % salto === 0;
    if (!clave) return "";
    const marca = !p.futuro && i === iMax ? '<em class="max">máx</em>' : (!p.futuro && i === iMin ? '<em class="min">mín</em>' : "");
    // Estimados alternados arriba/abajo de la línea para que no se monten.
    const kFut = futuros.findIndex((f) => f.i === i);
    const abajo = (!p.futuro && i === iMin && i !== iMax) || (p.futuro && kFut % 2 === 1);
    const signo = /^-/.test(p.vs || "") ? "neg" : "pos";
    return `<span class="py-cifra ${p.futuro ? "fut" : ""} ${i === ult.i ? "ult" : ""} ${abajo ? "abajo" : ""}" `
      + `style="left:${pctX(i)}%;top:${y(p.v)}px">${marca}<b>${texto(p.t)}</b>`
      + `${p.vs ? `<small class="${signo}">${texto(p.vs)}</small>` : ""}</span>`;
  }).join("");
  const rotulos = guias.map((v) => `<span style="top:${y(v)}px">${texto(_cifra(v))}</span>`).join("");
  const etiquetas = puntos.map((p, i) => (puntos.length <= 16 || i % 2 === 0 || i === ult.i || i === puntos.length - 1)
    ? `<span class="${p.futuro ? "fut" : ""}" style="left:${pctX(i)}%">${texto(_mesEje(p.m, i, puntos))}</span>` : "").join("");
  return `
    <div class="py-grafico">
      <div class="py-lienzo" style="height:${H}px">
        <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" style="height:${H}px">
          <defs><linearGradient id="pyArea" x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" style="stop-color:var(--acc-l)" stop-opacity=".32"/><stop offset="100%" style="stop-color:var(--acc-l)" stop-opacity="0"/></linearGradient></defs>
          ${lineasGuia}
          <path class="py-area" d="${area}" fill="url(#pyArea)"/>
          ${futuros.length ? `<path class="py-banda peor" d="${banda("lo", "hi")}"/>` : ""}
          ${futuros.length && futuros[0].plo != null ? `<path class="py-banda probable" d="${banda("plo", "phi")}"/>` : ""}
          <line class="py-hoy" x1="${x(ult.i).toFixed(1)}" x2="${x(ult.i).toFixed(1)}" y1="${pt - 14}" y2="${H - pb}"/>
          <path class="py-real" d="${linea(reales)}"/>
          ${futuros.length ? `<path class="py-futuro" d="${linea([ult, ...futuros])}"/>` : ""}
          ${puntosSvg}
        </svg>
        <div class="py-rotulos">${rotulos}</div>
        <div class="py-cifras">${cifras}</div>
        <div class="py-hoy-lbl" style="left:${pctX(ult.i)}%">hoy</div>
      </div>
      <div class="py-ejes">${etiquetas}</div>
      <div class="py-tip" hidden></div>
    </div>
    <div class="py-leyenda"><span><i class="real"></i>Real</span><span><i class="fut"></i>Estimado</span>
      <span><i class="prob"></i>Lo más probable</span><span><i class="peor"></i>Peor y mejor caso</span>
      <span class="py-leyenda-nota">Debajo de cada cifra: cambio frente al mes anterior</span></div>`;
}

function _meses(lista) {
  if (!lista || !lista.length) return "";
  const chip = (v, txt) => (v ? `<span class="${/^-/.test(v) ? "neg" : "pos"}">${texto(v)} ${txt}</span>` : "");
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Mes a mes</span><h2>Lo que se espera en cada mes</h2>
        <p>La cifra estimada, entre qué valores es más probable que quede, el peor y el mejor caso, y cómo se compara con hoy y con el año pasado.</p></div>
      <div class="py-meses">${lista.map((m, i) => `
        <article class="py-mes" data-revelar="${i * 90}">
          <small>${texto(m.mes)}</small>
          <b data-contar="${texto(m.estimado)}">${texto(m.estimado)}</b>
          <div class="py-mes-chips">${chip(m.vs_hoy, "vs hoy")}${chip(m.vs_anio, "vs hace un año")}</div>
          ${m.probable ? `<div class="py-mes-fila"><span>Lo más probable</span><b>${texto(m.probable)}</b></div>` : ""}
          <div class="py-mes-fila"><span>Peor y mejor caso</span><b>${texto(m.extremos)}</b></div>
          ${m.anio_t ? `<div class="py-mes-fila"><span>Mismo mes del año pasado</span><b>${texto(m.anio_t)}</b></div>` : ""}
        </article>`).join("")}</div>
    </section>`;
}

function _contexto(lista) {
  if (!lista || !lista.length) return "";
  return `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Contexto</span><h2>Lo que dice la historia</h2></div>
      <div class="py-contexto">${lista.map((c, i) => `
        <div class="py-ctx" data-revelar="${i * 70}"><small>${texto(c.n)}</small><b>${conCifras(c.v)}</b>${c.d ? `<em>${texto(c.d)}</em>` : ""}</div>`).join("")}</div>
    </section>`;
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const raiz = montar(parentElement, "pd py", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="py-hero">
        <div class="py-hero-cab">
          <div class="pd-hero-texto">
            <div class="pd-ceja" data-revelar="0">
              <span class="pd-estado ${texto(d.tono)}"><i></i>Confianza ${texto(d.confianza)}</span>
              <span>Hacia dónde va · ${texto(d.etiqueta)}</span>
            </div>
            <h1 class="pd-titular"></h1>
          </div>
          <div class="py-grande" data-revelar="150">
            <small>${texto(d.grande_lbl)}</small>
            <b data-contar="${texto(d.grande)}">${texto(d.grande)}</b>
            ${d.delta ? `<span class="pd-delta ${texto(d.tono)}">${texto(d.delta)}</span>` : ""}
          </div>
        </div>
        ${_grafico(d.puntos)}
      </div>
    </section>
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    ${_meses(d.meses)}
    ${_contexto(d.contexto)}
  `);

  const svg = raiz.querySelector(".py-lienzo");
  const tip = raiz.querySelector(".py-tip");
  const pts = d.puntos || [];
  const mover = (ev) => {
    const r = svg.getBoundingClientRect();
    const u = ((ev.clientX - r.left) / r.width * 760 - 54) / (760 - 88);  // mismos márgenes que _grafico
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(u * (pts.length - 1))));
    raiz.querySelectorAll(".py-pt").forEach((c) => c.classList.toggle("activo", Number(c.dataset.i) === i));
    const p = pts[i];
    tip.hidden = false;
    tip.innerHTML = `<b>${texto(p.t)}</b>${texto(p.m)}${p.futuro ? ` · estimado${p.rango ? `<br><small>${texto(p.rango)}</small>` : ""}` : " · real"}`;
    tip.style.left = `${((54 + i * (760 - 88) / (pts.length - 1)) / 760) * 100}%`;
  };
  const salir = () => { tip.hidden = true; raiz.querySelectorAll(".py-pt").forEach((c) => c.classList.remove("activo")); };
  if (svg) { svg.addEventListener("pointermove", mover); svg.addEventListener("pointerleave", salir); }

  const graf = raiz.querySelector(".py-grafico");
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    escribir(raiz.querySelector(".pd-titular"), String(d.frase || ""), null, 13),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(graf, () => graf && graf.classList.add("dibujar")),
    alVerse(raiz.querySelector(".pd-kpis"), () => raiz.querySelector(".pd-kpis") && raiz.querySelector(".pd-kpis").classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpi")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
