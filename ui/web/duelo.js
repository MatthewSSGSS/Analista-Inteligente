// Comparar personas: cara a cara. Todo lo calcula Python
// (ui/person_compare._datos_duelo). Usa parte.css.
// Datos: { a: {nombre, valor, puesto}, b: {...}, metrica, diferencia, pct, ganador, total_grupo,
//          duelos: [{n, a, b, at, bt, gana}], desglose: {dimension, filas: [{n, a, b, at, bt}]} }

function _ini(n) {
  const p = String(n || "?").trim().split(/\s+/);
  return ((p[0] || "?")[0] + (p.length > 1 ? p[p.length - 1][0] : "")).toUpperCase();
}

function _espejo(filas, a, b) {
  return filas.map((f, i) => `
    <div class="du-fila" data-revelar="${Math.min(i, 10) * 60}">
      <span class="du-v a ${f.gana === "a" ? "gana" : ""}">${texto(f.at)}</span>
      <div class="du-lado a"><i style="--ancho:${f.a}%"></i></div>
      <span class="du-n" title="${texto(f.n)}">${texto(f.n)}</span>
      <div class="du-lado b"><i style="--ancho:${f.b}%"></i></div>
      <span class="du-v b ${f.gana === "b" ? "gana" : ""}">${texto(f.bt)}</span>
    </div>`).join("");
}

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const a = d.a || {}, b = d.b || {};
  const lado = (p, cls) => `
    <div class="du-persona ${cls} ${d.ganador === cls ? "ganador" : ""}" data-revelar="${cls === "a" ? 0 : 120}">
      <div class="du-avatar">${d.ganador === cls ? `<span class="du-corona">👑</span>` : ""}<b>${texto(_ini(p.nombre))}</b></div>
      <h2 title="${texto(p.nombre)}">${texto(p.nombre)}</h2>
      <div class="du-valor" data-contar="${texto(p.valor)}">${texto(p.valor)}</div>
      <small>${texto(d.metrica)}${p.puesto ? ` · ${texto(p.puesto)}` : ""}</small>
    </div>`;
  const raiz = montar(parentElement, "pd du", `
    <section class="pd-hero">
      <canvas class="ai-red"></canvas>
      <div class="du-hero">
        ${lado(a, "a")}
        <div class="du-centro" data-revelar="60">
          <span class="du-vs">VS</span>
          <b data-contar="${texto(d.diferencia)}">${texto(d.diferencia)}</b>
          ${d.pct ? `<em>${texto(d.pct)}</em>` : ""}
          <small>${texto(d.lectura)}</small>
        </div>
        ${lado(b, "b")}
      </div>
    </section>
    ${d.duelos && d.duelos.length ? `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Indicador por indicador</span><h2>Quién gana en qué</h2>
        <p>Cada fila es un indicador: la barra roja es ${texto(a.nombre)} y la verde-azulada ${texto(b.nombre)}. El número resaltado es el que gana.</p></div>
      <div class="du-tabla">${_espejo(d.duelos, a, b)}</div>
    </section>` : ""}
    ${d.desglose && d.desglose.filas.length ? `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Qué explica la diferencia</span><h2>Por ${texto(d.desglose.dimension)}</h2>
        <p>${texto(d.metrica)} de cada uno en sus categorías principales.</p></div>
      <div class="du-tabla">${_espejo(d.desglose.filas, a, b)}</div>
    </section>` : ""}
  `);
  const limpiar = [
    redDeDatos(raiz.querySelector(".pd-hero .ai-red")),
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    ...[...raiz.querySelectorAll(".du-tabla")].map((el) => alVerse(el, () => el.classList.add("dibujar"))),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
