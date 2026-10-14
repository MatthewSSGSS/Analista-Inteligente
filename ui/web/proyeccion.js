// Proyección. Todo lo calcula Python (ui/forecast._datos_proyeccion). Usa parte.css.
// Datos: { frase, tono, etiqueta, grande, delta, kpis, puntos, confianza }
// puntos: [{m, v, t, futuro, lo, hi, plo, phi, rango}]

ICONOS_KPI.real = "📍";
ICONOS_KPI.estimado = "🔮";
ICONOS_KPI.probable = "🎯";
ICONOS_KPI.confianza = "🛡️";

function _grafico(puntos) {
  if (!puntos || puntos.length < 2) return "";
  const W = 760, H = 240, pl = 8, pr = 8, pt = 14, pb = 26;
  const vals = puntos.flatMap((p) => [p.v, p.lo, p.hi].filter((x) => x != null));
  const min = Math.min(...vals, 0 < Math.min(...vals) ? Math.min(...vals) * 0.9 : Math.min(...vals));
  const max = Math.max(...vals);
  const rango = max - min || 1;
  const x = (i) => pl + (i * (W - pl - pr)) / (puntos.length - 1);
  const y = (v) => pt + (1 - (v - min) / rango) * (H - pt - pb);
  const reales = puntos.map((p, i) => ({ ...p, i })).filter((p) => !p.futuro);
  const futuros = puntos.map((p, i) => ({ ...p, i })).filter((p) => p.futuro);
  const ult = reales[reales.length - 1];
  const linea = (arr) => arr.map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const banda = (lo, hi) => futuros.length ? `M${x(ult.i).toFixed(1)},${y(ult.v).toFixed(1)} `
    + futuros.map((p) => `L${x(p.i).toFixed(1)},${y(p[hi]).toFixed(1)}`).join(" ")
    + " " + [...futuros].reverse().map((p) => `L${x(p.i).toFixed(1)},${y(p[lo]).toFixed(1)}`).join(" ") + " Z" : "";
  const area = `${linea(reales)} L${x(ult.i).toFixed(1)},${H - pb} L${x(reales[0].i).toFixed(1)},${H - pb} Z`;
  const puntosSvg = puntos.map((p, i) => `<circle class="py-pt ${p.futuro ? "fut" : ""}" cx="${x(i).toFixed(1)}" cy="${y(p.v).toFixed(1)}" r="3.4" data-i="${i}"/>`).join("");
  const etiquetas = puntos.map((p, i) => (i === 0 || i === reales.length - 1 || i === puntos.length - 1)
    ? `<span style="left:${(x(i) / W) * 100}%">${texto(p.m)}</span>` : "").join("");
  return `
    <div class="py-grafico">
      <svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="none">
        <defs><linearGradient id="pyArea" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0%" stop-color="#ff5b6c" stop-opacity=".32"/><stop offset="100%" stop-color="#ff5b6c" stop-opacity="0"/></linearGradient></defs>
        <path class="py-area" d="${area}" fill="url(#pyArea)"/>
        ${futuros.length ? `<path class="py-banda peor" d="${banda("lo", "hi")}"/>` : ""}
        ${futuros.length && futuros[0].plo != null ? `<path class="py-banda probable" d="${banda("plo", "phi")}"/>` : ""}
        <line class="py-hoy" x1="${x(ult.i).toFixed(1)}" x2="${x(ult.i).toFixed(1)}" y1="${pt}" y2="${H - pb}"/>
        <path class="py-real" d="${linea(reales)}"/>
        ${futuros.length ? `<path class="py-futuro" d="${linea([ult, ...futuros])}"/>` : ""}
        ${puntosSvg}
      </svg>
      <div class="py-hoy-lbl" style="left:${(x(ult.i) / W) * 100}%">hoy</div>
      <div class="py-ejes">${etiquetas}</div>
      <div class="py-tip" hidden></div>
    </div>
    <div class="py-leyenda"><span><i class="real"></i>Real</span><span><i class="fut"></i>Estimado</span>
      <span><i class="prob"></i>Lo más probable</span><span><i class="peor"></i>Peor y mejor caso</span></div>`;
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
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
  `);

  const svg = raiz.querySelector(".py-grafico svg");
  const tip = raiz.querySelector(".py-tip");
  const pts = d.puntos || [];
  const mover = (ev) => {
    const r = svg.getBoundingClientRect();
    const i = Math.max(0, Math.min(pts.length - 1, Math.round(((ev.clientX - r.left) / r.width) * (pts.length - 1))));
    raiz.querySelectorAll(".py-pt").forEach((c) => c.classList.toggle("activo", Number(c.dataset.i) === i));
    const p = pts[i];
    tip.hidden = false;
    tip.innerHTML = `<b>${texto(p.t)}</b>${texto(p.m)}${p.futuro ? ` · estimado${p.rango ? `<br><small>${texto(p.rango)}</small>` : ""}` : " · real"}`;
    tip.style.left = `${(i / (pts.length - 1)) * 100}%`;
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
