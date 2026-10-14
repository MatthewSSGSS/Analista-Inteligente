// Finanzas / lectura estadística: una tarjeta por métrica con su rango dibujado
// (mínimo, cuartiles, mediana y máximo) y el promedio marcado.
// Todo lo calcula Python (app._datos_finanzas vía ui/anomalies). Usa parte.css.
// Datos: { metricas: [{n, media, mediana, min, max, q1, q3, std, cuenta, x: {q1, med, q3, media}, lectura}] }

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const tarjetas = (d.metricas || []).map((m, i) => `
    <article class="fi-tarjeta" data-revelar="${i * 80}">
      <div class="fi-cab"><b>${texto(m.n)}</b><small>${texto(m.cuenta)} valores</small></div>
      <div class="fi-cifras">
        <div><small>Promedio</small><b data-contar="${texto(m.media)}">${texto(m.media)}</b></div>
        <div><small>Mediana</small><b>${texto(m.mediana)}</b></div>
        <div><small>Dispersión</small><b>${texto(m.std)}</b></div>
      </div>
      <div class="fi-caja">
        <span class="bigote" style="left:0;width:100%"></span>
        <span class="caja" style="left:${m.x.q1}%;width:${Math.max(1, m.x.q3 - m.x.q1)}%"></span>
        <span class="mediana" style="left:${m.x.med}%"></span>
        <em style="left:${m.x.media}%" title="promedio"></em>
      </div>
      <div class="fi-ejes"><span>mín ${texto(m.min)}</span><span>la mitad central: ${texto(m.q1)} – ${texto(m.q3)}</span><span>máx ${texto(m.max)}</span></div>
      ${m.lectura ? `<p>${conCifras(m.lectura)}</p>` : ""}
    </article>`).join("");
  const raiz = montar(parentElement, "pd fi", `
    <div class="fi-leyenda"><span><i class="caja"></i>La mitad central de los valores</span><span><i class="mediana"></i>Mediana</span>
      <span><i class="media"></i>Promedio</span></div>
    <section class="fi-grid">${tarjetas}</section>
  `);
  const grid = raiz.querySelector(".fi-grid");
  const limpiar = [
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(grid, () => grid && grid.classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".fi-tarjeta")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
