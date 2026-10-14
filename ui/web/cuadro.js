// Cómo va cada uno: tarjetas + ranking vivo (semáforo, barra, variación del
// mes y mini gráfico por fila; al tocar una fila se despliega su detalle).
// Todo lo calcula Python (ui/cuadro_comparativo._datos_cuadro). Usa parte.css.
// Datos: { kpis, titulo, subtitulo, filas, lectura, aviso }

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const filas = (d.filas || []).map((f, i) => `
    <article class="cu-fila ${texto(f.tono)}" data-revelar="${Math.min(i, 12) * 50}">
      <button class="cu-fila-cab" type="button" aria-expanded="false">
        <span class="cu-pos">${f.posicion}</span>
        <span class="cu-nombre" title="${texto(f.nombre)}">${texto(f.nombre)}</span>
        <span class="cu-barra"><i style="--ancho:${f.barra}%"></i>${f.marca != null ? `<em style="left:${f.marca}%"></em>` : ""}</span>
        <span class="cu-valor"><b>${texto(f.principal)}</b><small>${texto(f.secundario)}</small></span>
        <span class="cu-estado">${texto(f.estado)}</span>
        <span class="cu-var ${f.var_tono}">${texto(f.variacion)}</span>
        ${chispa(f.serie, "cu-chispa")}
        <span class="cu-flecha">⌄</span>
      </button>
      <div class="cu-detalle"><div>${f.detalle.map(([k, v]) => `<span><small>${texto(k)}</small><b>${texto(v)}</b></span>`).join("")}</div></div>
    </article>`).join("");

  const raiz = montar(parentElement, "pd cu", `
    ${d.kpis && d.kpis.length ? `<section class="pd-kpis n${d.kpis.length}">${d.kpis.map(tarjetaKpi).join("")}</section>` : ""}
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Ranking</span><h2>${texto(d.titulo)}</h2><p>${texto(d.subtitulo)}</p></div>
      <div class="cu-leyenda"><span class="bueno">● Bien</span><span class="medio">● Cerca</span><span class="malo">● Por debajo</span>
        ${d.marca_txt ? `<span class="cu-leyenda-marca"><em></em>${texto(d.marca_txt)}</span>` : ""}<span class="cu-leyenda-nota">Toca una fila para ver su detalle</span></div>
      <div class="cu-lista">${filas}</div>
    </section>
    ${d.lectura && d.lectura.length ? `
    <section class="pd-bloque">
      <div class="pd-bloque-cab"><span class="ai-ceja">Lectura</span><h2>Lo que dice el cuadro</h2></div>
      <div class="cu-lectura">${d.lectura.map((t, i) => `<p data-revelar="${i * 80}">${conNegritas(t)}</p>`).join("")}</div>
      ${d.aviso ? `<div class="cu-aviso">⚠️ ${texto(d.aviso)}</div>` : ""}
    </section>` : ""}
  `);

  raiz.querySelectorAll(".cu-fila-cab").forEach((cab) => cab.addEventListener("click", () => {
    const abierta = cab.closest(".cu-fila").classList.toggle("abierta");
    cab.setAttribute("aria-expanded", String(abierta));
  }));
  const lista = raiz.querySelector(".cu-lista");
  const limpiar = [
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
    alVerse(raiz.querySelector(".pd-kpis"), () => raiz.querySelector(".pd-kpis") && raiz.querySelector(".pd-kpis").classList.add("dibujar")),
    alVerse(lista, () => lista && lista.classList.add("dibujar")),
    ...[...raiz.querySelectorAll(".pd-kpi")].map((t) => foco(t, false)),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
