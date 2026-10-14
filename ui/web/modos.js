// Elegir el tipo de análisis. Datos desde ui/mode_choice.py:
// { nombre, imagenes: {completo, territorial, logistica} }.
// Cada tarjeta es un botón: el clic avisa a Python "completo",
// "territorial" o "logistica".

const _MODOS = [
  {
    clave: "completo", icono: "🧭", titulo: "Análisis Completo", acento: "var(--purple)",
    texto: "Todo el panel: qué pasó, por qué y qué atacar, cómo va cada uno, proyección, comparaciones y seguimiento, con informes listos para enviar.",
    puntos: ["Parte del día y plan de acción desde el primer momento", "Pregúntale al archivo y asistente IA", "Excel ejecutivo, informes HTML e interactivo"],
    figura: `<svg viewBox="0 0 120 60" class="fig-barras">${[22, 34, 28, 42, 38, 52].map((h, i) =>
      `<rect x="${8 + i * 18}" y="${58 - h}" width="11" height="${h}" rx="2" style="--i:${i}"/>`).join("")}
      <polyline points="13,40 31,30 49,34 67,22 85,26 103,10" class="linea"/></svg>`,
  },
  {
    clave: "territorial", icono: "🗺️", titulo: "Análisis Territorial", acento: "var(--teal)",
    texto: "Tu red sobre el mapa: dónde se concentra, dónde falta cobertura y dónde crecer, con semáforo por zona y plan de acción.",
    puntos: ["Cada zona en el mapa, con su detalle", "Dónde crecer con datos de población DANE", "El panel completo, entrando por el territorio"],
    figura: `<svg viewBox="0 0 120 60" class="fig-mapa">${[[24, 18], [46, 34], [70, 20], [92, 40], [58, 48], [36, 44], [84, 14]].map(([x, y], i) =>
      `<circle cx="${x}" cy="${y}" r="3" style="--i:${i}"/><circle cx="${x}" cy="${y}" r="3" class="onda" style="--i:${i}"/>`).join("")}</svg>`,
  },
  {
    clave: "logistica", icono: "🚚", titulo: "Seguimiento de Logística", acento: "var(--amber)",
    texto: "Haz seguimiento a tu operación logística: carga el archivo de seguimiento y revisa cómo va, en una sección propia.",
    puntos: ["Tu propio archivo, sin mezclarlo con el panel", "Seguimiento de la operación", "En construcción: se irá ampliando"],
    figura: `<svg viewBox="0 0 120 60" class="fig-ruta"><path d="M8 48 C 30 48, 30 14, 58 18 S 92 46, 112 12" class="camino"/>
      <path d="M8 48 C 30 48, 30 14, 58 18 S 92 46, 112 12" class="avance"/>
      <circle cx="8" cy="48" r="3.5"/><circle cx="112" cy="12" r="3.5"/></svg>`,
  },
];

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const d = data || {};
  const img = d.imagenes || {};

  const tarjetas = _MODOS.map((m, i) => `
    <button class="ai-modo" data-accion="${m.clave}" data-revelar="${120 + i * 110}" style="--acento:${m.acento}">
      <div class="ai-modo-portada" style="background-image:url('${img[m.clave] || ""}')">
        <div class="ai-modo-figura">${m.figura}</div>
      </div>
      <div class="ai-modo-cuerpo">
        <span class="ai-modo-ico">${m.icono}</span>
        <h3>${m.titulo}</h3>
        <p>${m.texto}</p>
        <ul>${m.puntos.map((p) => `<li>${p}</li>`).join("")}</ul>
        <span class="ai-modo-ir">Entrar <span class="flecha">→</span></span>
      </div>
    </button>`).join("");

  const raiz = montar(parentElement, "ai-modos", `
    <header class="ai-modos-cabeza">
      <div class="ai-marca-chica" data-revelar="0"><span class="ai-orbe"></span>${texto(d.nombre || "Analista Inteligente")}</div>
      <h1 data-revelar="60">¿Cómo quieres analizar tu información hoy?</h1>
      <p data-revelar="100">Elige según lo que necesites — puedes cambiar de modo cuando quieras desde la barra lateral.</p>
    </header>
    <div class="ai-modos-grid">${tarjetas}</div>
  `);

  acciones(raiz, setTriggerValue, d.botones || {});
  const limpiar = [revelar(raiz), ...[...raiz.querySelectorAll(".ai-modo")].map((t) => foco(t))];
  return () => limpiar.forEach((f) => { try { f(); } catch (e) { /* ya desmontado */ } });
}
