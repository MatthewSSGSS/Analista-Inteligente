// Cabecera del inicio de sesión: marca, frase y la red de datos animada.
// Solo dibuja: usuario y contraseña siguen siendo campos de Streamlit
// (ui/login.py), así la contraseña va directo a Python y no pasa por aquí.

export default function (component) {
  const { data, parentElement } = component;
  const d = data || {};
  const raiz = montar(parentElement, "ai-acceso", `
    <div class="ai-acceso-banda">
      <canvas class="ai-red"></canvas>
      <div class="ai-acceso-contenido">
        <span class="ai-orbe" data-revelar="0"></span>
        <h1 data-revelar="80">${texto(d.nombre || "Analista Inteligente")}</h1>
        <p data-revelar="160">De tu archivo a la decisión: qué pasó, por qué y qué hacer ahora.</p>
      </div>
    </div>
    <p class="ai-acceso-pide" data-revelar="220">Inicia sesión para continuar</p>
  `);
  const limpiar = [redDeDatos(raiz.querySelector(".ai-red")), revelar(raiz)];
  return () => limpiar.forEach((f) => { try { f(); } catch (e) { /* ya desmontado */ } });
}
