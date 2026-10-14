// Cabecera animada de las vistas (ui/components/escena.cabecera).
// Datos: { titulo, subtitulo, ceja, icono, cifras: [{v, l}] }

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  acento(d.acento);
  const cifras = (d.cifras || []).map((c, i) => `
    <div class="cb-cifra" data-revelar="${200 + i * 90}"><b data-contar="${texto(c.v)}">${texto(c.v)}</b><small>${texto(c.l)}</small></div>`).join("");
  const raiz = montar(parentElement, "cb", `
    <canvas class="ai-red"></canvas>
    <div class="cb-cuerpo">
      <div class="cb-icono" data-revelar="0">${texto(d.icono || "📊")}</div>
      <div class="cb-texto">
        ${d.ceja ? `<span class="cb-ceja" data-revelar="40">${texto(d.ceja)}</span>` : ""}
        <h1 data-revelar="80">${texto(d.titulo)}</h1>
        ${d.subtitulo ? `<p data-revelar="140">${texto(d.subtitulo)}</p>` : ""}
      </div>
      ${cifras ? `<div class="cb-cifras">${cifras}</div>` : ""}
    </div>
  `);
  const limpiar = [
    redDeDatos(raiz.querySelector(".ai-red")),
    revelar(raiz),
    ...[...raiz.querySelectorAll("[data-contar]")].map((el) => alVerse(el, () => contarTexto(el, el.dataset.contar))),
  ];
  return () => limpiar.forEach((f) => { try { f && f(); } catch (err) { /* ya desmontado */ } });
}
