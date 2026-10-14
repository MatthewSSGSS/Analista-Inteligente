// Portada (antes de elegir el modo). Datos desde ui/landing.py:
// { nombre, imagenes: {circuito, datos1, barras, mapa} } (data: URIs propias).

const _PALABRAS = ["ventas", "metas", "zonas", "equipos", "inventarios", "clientes"];

const _CAPACIDADES = [
  ["01", "Detecta", "Reconoce solo qué tipo de archivo es — ventas, personas, inventario, metas, catálogos — y adapta la lectura sin plantillas.", "circuito"],
  ["02", "Explica", "Dice qué cambió, por qué cambió y dónde está la diferencia, con la causa en palabras y en cifras.", "datos1"],
  ["03", "Propone", "Convierte el diagnóstico en acciones valoradas: qué hacer primero, con quién y cuánto vale al mes.", "barras"],
  ["04", "Comparte", "Informes en Excel, HTML e interactivos listos para enviar a dirección, sin entregar toda la base.", "mapa"],
];

const _PASOS = [
  ["Sube el archivo", "Excel o CSV, desde la barra lateral. Lee todas las hojas."],
  ["Lee el parte del día", "Qué pasó este mes, contra el año, y qué conviene hacer ahora."],
  ["Profundiza", "Filtros, ranking, cada persona, el mapa y la proyección."],
  ["Comparte", "Descarga el informe y envíalo tal cual."],
];

function _demoBarras() {
  const valores = [63, 58, 66, 71, 69, 75, 73, 70, 64, 68, 60, 70];
  return valores.map((v, i) => {
    const clase = i === valores.length - 1 ? "actual" : (i === valores.length - 2 ? "previo" : "");
    return `<span class="${clase}" style="--alto:${v}%;--i:${i}"></span>`;
  }).join("");
}

function _animarDemo(demo) {
  if (!demo) return () => {};
  let cancelado = false;
  const parar = escribir(demo.querySelector(".ai-demo-titular"),
    "Ingresos subió 17.1% en julio, pero el año va 4% por debajo.", () => {
      if (cancelado) return;
      demo.classList.add("fase-cifras");
      contar(demo.querySelector("[data-n=mes]"), 1.24, { decimales: 2, sufijo: " mil M" });
      contar(demo.querySelector("[data-n=anual]"), 0.6, { decimales: 1, sufijo: "%", signo: true });
      contar(demo.querySelector("[data-n=acum]"), -4.0, { decimales: 1, sufijo: "%" });
      setTimeout(() => { if (!cancelado) demo.classList.add("fase-barras"); }, 350);
      setTimeout(() => { if (!cancelado) demo.classList.add("fase-accion"); }, 1300);
    });
  return () => { cancelado = true; parar(); };
}

function _rotar(el) {
  if (!el || !MOVIMIENTO) return () => {};
  let i = 0;
  const id = setInterval(() => {
    el.classList.add("sale");
    setTimeout(() => {
      i = (i + 1) % _PALABRAS.length;
      el.textContent = _PALABRAS[i];
      el.classList.remove("sale");
    }, 280);
  }, 2400);
  return () => clearInterval(id);
}

export default function (component) {
  const { data, setTriggerValue, parentElement } = component;
  const d = data || {};
  const img = d.imagenes || {};
  const nombre = texto(d.nombre || "Analista Inteligente");

  const tarjetas = _CAPACIDADES.map(([n, t, p, foto], i) => `
    <article class="ai-cap" data-revelar="${i * 90}">
      <div class="ai-cap-foto" style="background-image:url('${img[foto] || ""}')"></div>
      <div class="ai-cap-cuerpo">
        <span class="ai-cap-n">${n}</span>
        <h3>${t}</h3>
        <p>${p}</p>
      </div>
    </article>`).join("");

  const pasos = _PASOS.map(([t, p], i) => `
    <li data-revelar="${i * 120}">
      <span class="ai-paso-n">${i + 1}</span>
      <b>${t}</b>
      <p>${p}</p>
    </li>`).join("");

  const raiz = montar(parentElement, "ai-portada", `
    <section class="ai-escenario">
      <canvas class="ai-red"></canvas>
      <div class="ai-halo"></div>
      <div class="ai-escenario-grid">
        <div class="ai-copy">
          <div class="ai-marca" data-revelar="0"><span class="ai-orbe"></span>${nombre}</div>
          <h1 data-revelar="80">Entiende tus <span class="ai-rota">${_PALABRAS[0]}</span><br>y decide qué hacer.</h1>
          <p class="ai-sub" data-revelar="160">Sube cualquier Excel o CSV. En segundos tienes qué pasó, por qué pasó
            y qué conviene hacer ahora — sin plantillas ni estructuras fijas.</p>
          <div class="ai-cta-fila" data-revelar="240">
            <button class="ai-cta" data-accion="comenzar">Comenzar <span class="flecha">→</span></button>
            <span class="ai-nota">Sin instalar nada · funciona con cualquier archivo</span>
          </div>
          <ul class="ai-chips" data-revelar="320">
            <li>Ventas</li><li>Personas</li><li>Inventario</li><li>Metas</li><li>Territorio</li><li>Logística</li>
          </ul>
        </div>
        <div class="ai-demo" data-revelar="200" aria-hidden="true">
          <div class="ai-demo-top"><span class="ai-vivo"></span>Así se ve · ejemplo de parte del día</div>
          <div class="ai-demo-titular"></div>
          <div class="ai-demo-kpis">
            <div><small>Julio</small><b data-n="mes">0</b><em class="sube">▲ 17.1% vs junio</em></div>
            <div><small>vs julio del año pasado</small><b data-n="anual">0</b><em>casi igual</em></div>
            <div><small>Acumulado del año</small><b data-n="acum">0</b><em class="baja">▼ por debajo</em></div>
          </div>
          <div class="ai-demo-barras">${_demoBarras()}</div>
          <div class="ai-demo-meses"><span>ago</span><span>jul</span></div>
          <div class="ai-demo-accion">
            <span class="ai-demo-ico">🎯</span>
            <div><b>Qué hacer ahora</b><p>Recuperar la región Sur: vale ≈ 47 M al mes.</p></div>
            <span class="ai-demo-chip">Ver plan</span>
          </div>
        </div>
      </div>
    </section>

    <section class="ai-seccion">
      <div class="ai-titulo" data-revelar="0"><span class="ai-ceja">Qué hace</span>
        <h2>Un analista que lee cualquier archivo</h2></div>
      <div class="ai-caps">${tarjetas}</div>
    </section>

    <section class="ai-seccion ai-como">
      <div class="ai-titulo" data-revelar="0"><span class="ai-ceja">Cómo usarlo</span>
        <h2>De un archivo a una decisión, en cuatro pasos</h2></div>
      <ol class="ai-pasos">${pasos}</ol>
    </section>

    <section class="ai-final" data-revelar="0">
      <div><h2>¿Listo para ver tu información de otra forma?</h2>
        <p>Empieza ahora: eliges el tipo de análisis y subes el archivo.</p></div>
      <button class="ai-cta" data-accion="comenzar">Comenzar <span class="flecha">→</span></button>
    </section>
  `);

  acciones(raiz, setTriggerValue);
  const limpiar = [
    redDeDatos(raiz.querySelector(".ai-red")),
    revelar(raiz),
    _rotar(raiz.querySelector(".ai-rota")),
    _animarDemo(raiz.querySelector(".ai-demo")),
    ...[...raiz.querySelectorAll(".ai-cap")].map((t) => foco(t)),
    foco(raiz.querySelector(".ai-demo"), false),
  ];
  return () => limpiar.forEach((f) => { try { f(); } catch (e) { /* ya desmontado */ } });
}
