// Anomalías: valores que no encajan con el resto de su columna.
// Todo lo calcula Python (ui/anomalies._datos_anomalias). Usa parte.css.
// Datos: { total, registros, columnas: [{n, cuantos, ancho, tipos}], casos: [{col, tipo, valor, contexto, x, lo, hi, fuera}] }

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const cols = (d.columnas || []).map((c, i) => `
    <div class="an-col" data-revelar="${i * 70}"><span title="${texto(c.n)}">${texto(c.n)}</span>
      <div class="ca-pista"><i style="--ancho:${c.ancho}%"></i></div><b>${c.cuantos}</b><small>${texto(c.tipos)}</small></div>`).join("");
  const casos = (d.casos || []).map((c, i) => `
    <article class="an-caso" data-revelar="${Math.min(i, 12) * 50}">
      <div class="an-caso-cab"><span class="an-tipo">${texto(c.tipo)}</span><small>${texto(c.col)}</small></div>
      <b class="an-valor">${texto(c.valor)}</b>
      <p>${texto(c.contexto)}</p>
      ${c.x != null ? `
      <div class="an-banda"><span class="normal" style="left:${c.lo}%;width:${Math.max(1, c.hi - c.lo)}%"></span>
        <em style="left:${c.x}%"></em></div>
      <div class="an-banda-lbl"><span>rango normal: ${texto(c.rango)}</span><span class="${c.fuera}">${c.fuera === "arriba" ? "por encima" : c.fuera === "abajo" ? "por debajo" : ""}</span></div>` : ""}
    </article>`).join("");
  const raiz = montar(parentElement, "pd an", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="an-hero">
        <div class="an-numero ${d.total_n ? "" : "cero"}" data-revelar="0"><b data-contar="${texto(d.total)}">${texto(d.total)}</b><small>posibles anomalías</small></div>
        <div class="ca-texto">
          <div class="pd-ceja" data-revelar="40"><span class="pd-estado ${d.total_n ? "negative" : "positive"}"><i></i>${d.total_n ? "Para revisar" : "Sin anomalías"}</span><span>Anomalías · ${texto(d.registros)} registros revisados</span></div>
          <h1 data-revelar="80">${texto(d.titular)}</h1>
          <p data-revelar="140">Se marca un valor cuando queda muy lejos del rango normal de su columna (más de 1.5 veces el rango entre cuartiles), cuando es negativo donde no debería, o cuando una fecha está vacía. La meta no se revisa: un objetivo alto es una decisión, no un error.</p>
        </div>
      </div>
    </section>
    ${cols ? `<section class="pd-bloque"><div class="pd-bloque-cab"><span class="ai-ceja">Dónde están</span><h2>Por columna</h2></div>
      <div class="ca-cols an-cols">${cols}</div></section>` : ""}
    ${casos ? `<section class="pd-bloque"><div class="pd-bloque-cab"><span class="ai-ceja">Casos</span><h2>Los más alejados de lo normal</h2>
      <p>Cada caso con su registro y dónde cae frente al rango normal de la columna (la franja verde).</p></div>
      <div class="an-casos">${casos}</div></section>` : ""}
  `);
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    ...[...raiz.querySelectorAll(".an-cols, .an-casos")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
