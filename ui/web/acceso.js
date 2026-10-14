// Inicio de sesión: la red de datos animada cubre TODA la pantalla (un
// canvas fijo detrás de la app) y aquí arriba va la marca. Solo dibuja:
// usuario y contraseña siguen siendo campos de Streamlit (ui/login.py), así
// la contraseña va directo a Python y no pasa por aquí.

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const raiz = montar(parentElement, "ai-acceso", `
    <span class="ai-orbe" data-revelar="0"></span>
    <h1 data-revelar="80">${texto(d.nombre || "Analista Inteligente")}</h1>
    <p data-revelar="160">De tu archivo a la decisión: qué pasó, por qué y qué hacer ahora.</p>
  `);

  // El fondo vive fuera del componente (en el contenedor de la app) para
  // ocupar toda la ventana; se quita al salir del acceso.
  const app = document.querySelector('[data-testid="stApp"]') || document.body;
  app.querySelectorAll(":scope > canvas.ai-fondo-acceso").forEach((c) => c.remove());
  const fondo = document.createElement("canvas");
  fondo.className = "ai-fondo-acceso";
  fondo.setAttribute("aria-hidden", "true");
  Object.assign(fondo.style, { position: "fixed", inset: "0", width: "100vw", height: "100vh", zIndex: "0", pointerEvents: "none" });
  app.prepend(fondo);

  const limpiar = [redDeDatos(fondo), revelar(raiz), () => fondo.remove()];
  return () => limpiar.forEach((f) => { try { f(); } catch (e) { /* ya desmontado */ } });
}
