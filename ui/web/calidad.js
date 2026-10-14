// Calidad del dato. Todo lo calcula Python (ui/quality._datos_calidad). Usa parte.css.
// Datos: { puntaje, tono, veredicto, medidas: [{n, v}], duplicados, columnas: [{n, tipo, completo, faltan, unicos}], cambios }

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const medidas = (d.medidas || []).map((m, i) => `
    <div class="ca-medida" data-revelar="${200 + i * 80}"><div><span>${texto(m.n)}</span><b data-contar="${m.v.toFixed(0)}%">${m.v.toFixed(0)}%</b></div>
      <div class="ca-pista"><i style="--ancho:${m.v}%"></i></div></div>`).join("");
  const columnas = (d.columnas || []).map((c, i) => `
    <div class="ca-col ${c.completo < 80 ? "malo" : c.completo < 98 ? "medio" : "bueno"}" data-revelar="${Math.min(i, 14) * 40}">
      <span class="ca-col-n" title="${texto(c.n)}">${texto(c.n)}</span><span class="ca-tipo">${texto(c.tipo)}</span>
      <div class="ca-pista"><i style="--ancho:${c.completo}%"></i></div>
      <b>${c.completo.toFixed(0)}%</b><small>${c.faltan ? `${texto(c.faltan)} vacíos` : "completa"} · ${texto(c.unicos)} distintos</small>
    </div>`).join("");
  const raiz = montar(parentElement, "pd ca", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="ca-hero">
        <div class="ca-medidor ${texto(d.tono)}" data-revelar="0">
          <svg viewBox="0 0 120 120"><circle class="fondo" cx="60" cy="60" r="50"/>
            <circle class="avance" cx="60" cy="60" r="50" pathLength="100" style="--pct:${d.puntaje}"/></svg>
          <div><b data-contar="${d.puntaje.toFixed(0)}%">${d.puntaje.toFixed(0)}%</b><small>calidad general</small></div>
        </div>
        <div class="ca-texto">
          <div class="pd-ceja" data-revelar="40"><span class="pd-estado ${texto(d.tono)}"><i></i>${texto(d.estado)}</span><span>Calidad del dato</span></div>
          <h1 data-revelar="80">${texto(d.veredicto)}</h1>
          <p data-revelar="140">${texto(d.nota)}</p>
          <div class="ca-medidas">${medidas}
            <div class="ca-medida dup" data-revelar="480"><div><span>Filas repetidas</span><b data-contar="${texto(d.duplicados)}">${texto(d.duplicados)}</b></div></div>
          </div>
        </div>
      </div>
    </section>
    ${columnas ? `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Columna por columna</span><h2>Qué tan completa está cada una</h2>
        <p>De la más incompleta a la más completa. Verde = completa · ámbar = le falta poco · rojo = le falta mucho.</p></div>
      <div class="ca-cols">${columnas}</div>
    </section>` : ""}
    ${d.cambios && d.cambios.length ? `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Limpieza automática</span><h2>Lo que se arregló solo</h2>
        <p>Cambios de formato que el panel hizo al leer el archivo. Ningún valor del negocio se inventa.</p></div>
      <ol class="ca-cambios">${d.cambios.map((c, i) => `<li data-revelar="${Math.min(i, 10) * 50}"><span>${i + 1}</span><p>${conCifras(c)}</p></li>`).join("")}</ol>
    </section>` : ""}
  `);
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    ...[...raiz.querySelectorAll(".pd-hero, .ca-cols")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
