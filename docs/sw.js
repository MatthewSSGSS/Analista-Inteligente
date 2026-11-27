/* Analista Inteligente · trabajador de la app instalable.
   Guarda la "cáscara" (esta página, el manifiesto y los íconos) para que la app
   abra al instante y, sin internet, muestre un aviso en vez de una pantalla en
   blanco. El panel en sí (Streamlit) siempre se carga en vivo: nunca se guardan
   datos ni archivos del usuario. */
const VERSION = "analista-v1";
const CASCARA = ["./", "./index.html", "./manifest.webmanifest", "./iconos/icono-192.png",
                 "./iconos/icono-512.png", "./iconos/apple-touch-icon.png", "./iconos/favicon-64.png"];

self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(VERSION).then((c) => c.addAll(CASCARA)).then(() => self.skipWaiting()));
});

self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys()
    .then((ks) => Promise.all(ks.filter((k) => k !== VERSION).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET" || url.origin !== self.location.origin) return;   // el panel va directo
  // Red primero (siempre la versión más nueva); si no hay internet, lo guardado.
  e.respondWith(
    fetch(e.request)
      .then((r) => { const copia = r.clone(); caches.open(VERSION).then((c) => c.put(e.request, copia)); return r; })
      .catch(() => caches.match(e.request).then((r) => r || caches.match("./index.html")))
  );
});
