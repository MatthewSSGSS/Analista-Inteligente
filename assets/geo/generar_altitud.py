"""Genera `altitud_colombia.png`: la altitud del terreno de Colombia y alrededores.

La usa `core/territorio.altitudes()` para saber a qué altura poner cada dato
cuando el mapa está en «🏔️ Montañas 3D» (una columna de Bogotá tiene que
nacer a 2.600 m, no en el nivel del mar, o queda enterrada en la cordillera).
El relieve que se VE en el mapa no sale de aquí: lo baja el navegador por
cuadros, más nítido a cada zoom (ver `visualization/mapa_territorial.py`).

Fuente: Terrain Tiles de AWS (formato «terrarium», derivado de SRTM, GMTED,
ETOPO1 y otros; uso libre con atribución). Se unen los cuadros de zoom 7
(≈1,2 km por píxel) de la caja de Colombia y se guardan en gris de 8 bits:
cada nivel = 25 m (0–6.375 m), el mar en 0. Los límites (oeste, sur, este,
norte) van dentro del PNG, en el campo de texto «bounds».

Se corre una sola vez (necesita internet):  python assets/geo/generar_altitud.py
"""
from __future__ import annotations

import concurrent.futures as cf
import io
import json
import math
import urllib.request
from pathlib import Path

import numpy as np
from PIL import Image
from PIL.PngImagePlugin import PngInfo

URL = "https://elevation-tiles-prod.s3.amazonaws.com/terrarium/{z}/{x}/{y}.png"
ZOOM = 7
CAJA = (-4.5, 13.6, -82.0, -66.7)   # lat mín, lat máx, lon mín, lon máx (la de core/territorio)
PASO_M = 25
SALIDA = Path(__file__).with_name("altitud_colombia.png")


def _cuadro(lat, lon, z):
    n = 2 ** z
    x = int((lon + 180) / 360 * n)
    y = int((1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * n)
    return x, y


def _esquina(x, y, z):
    n = 2 ** z
    return x / n * 360 - 180, math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y / n))))


def _bajar(url):
    error = None
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as r:
                return np.asarray(Image.open(io.BytesIO(r.read())).convert("RGB")).astype(np.float64)
        except Exception as e:  # reintenta: el servidor a veces corta
            error = e
    raise error


def main():
    lat0, lat1, lon0, lon1 = CAJA
    x0, y0 = _cuadro(lat1, lon0, ZOOM)
    x1, y1 = _cuadro(lat0, lon1, ZOOM)
    alto = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256))
    pedidos = {(x, y): URL.format(z=ZOOM, x=x, y=y) for x in range(x0, x1 + 1) for y in range(y0, y1 + 1)}
    with cf.ThreadPoolExecutor(16) as ex:
        for (x, y), px in zip(pedidos, ex.map(_bajar, pedidos.values())):
            metros = px[..., 0] * 256 + px[..., 1] + px[..., 2] / 256 - 32768
            alto[(y - y0) * 256:(y - y0 + 1) * 256, (x - x0) * 256:(x - x0 + 1) * 256] = metros
    gris = np.clip(np.round(alto / PASO_M), 0, 255).astype(np.uint8)
    oeste, norte = _esquina(x0, y0, ZOOM)
    este, sur = _esquina(x1 + 1, y1 + 1, ZOOM)
    info = PngInfo()
    info.add_text("bounds", json.dumps([oeste, sur, este, norte]))
    info.add_text("paso_m", str(PASO_M))
    Image.fromarray(gris, "L").save(SALIDA, pnginfo=info, optimize=True)
    print(f"{SALIDA.name}: {gris.shape[1]}×{gris.shape[0]} px, {SALIDA.stat().st_size / 1024:.0f} KB, "
          f"límites {[round(v, 3) for v in (oeste, sur, este, norte)]}")


if __name__ == "__main__":
    main()
