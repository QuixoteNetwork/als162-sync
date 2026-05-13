#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
download_tiles.py  —  ALS162 GPS Sync
======================================
Descarga tiles de OpenStreetMap en baja resolución (zoom 0-6) para
incluirlos como mapa offline dentro de la aplicación.

Ejecutar UNA SOLA VEZ antes de compilar con PyInstaller:
    python download_tiles.py

Los tiles se guardan en:  assets/tiles/z/x/y.png

Zoom 0-5 = 1365 tiles ≈ 15-22 MB
"""

import urllib.request
import os
import sys
import time

# ── Configuración ─────────────────────────────────────────────────────────────
ZOOM_MAX  = 6          # 0-6 ≈ 100 MB  | 0-5  ≈ 20 MB   |  0-4 ≈ 4 MB   |  0-3 ≈ 700 KB
TILE_URL  = "https://tile.openstreetmap.org/{z}/{x}/{y}.png"
OUT_DIR   = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "assets", "tiles")
HEADERS   = {"User-Agent": "ALS162GPSSync/0.3 (seed-download; +https://github.com)"}
DELAY_S   = 0.25       # pausa entre requests (respetar limite de OSM)

# ── Calcular lista de tiles ───────────────────────────────────────────────────
tiles = []
for z in range(ZOOM_MAX + 1):
    n = 2 ** z
    for x in range(n):
        for y in range(n):
            tiles.append((z, x, y))

total = len(tiles)
print(f"\nALS162 GPS Sync — Descarga de tiles bundleados")
print(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
print(f"Destino : {OUT_DIR}")
print(f"Zooms   : 0 – {ZOOM_MAX}")
print(f"Tiles   : {total}")
print()

os.makedirs(OUT_DIR, exist_ok=True)
ok = skip = fail = 0

for i, (z, x, y) in enumerate(tiles, 1):
    path = os.path.join(OUT_DIR, str(z), str(x), f"{y}.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)

    if os.path.isfile(path) and os.path.getsize(path) > 100:
        skip += 1
        continue

    pct = i / total * 100
    bar = "█" * int(pct / 2) + "░" * (50 - int(pct / 2))
    sys.stdout.write(f"\r[{bar}] {pct:5.1f}%  z={z} x={x} y={y}   ")
    sys.stdout.flush()

    try:
        req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                     headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as r:
            data = r.read()
        with open(path, "wb") as f:
            f.write(data)
        ok += 1
        time.sleep(DELAY_S)
    except Exception as e:
        fail += 1
        # Reintento simple
        time.sleep(1.0)
        try:
            req = urllib.request.Request(TILE_URL.format(z=z, x=x, y=y),
                                         headers=HEADERS)
            with urllib.request.urlopen(req, timeout=20) as r:
                data = r.read()
            with open(path, "wb") as f:
                f.write(data)
            ok += 1; fail -= 1
        except Exception:
            pass

# ── Resumen ───────────────────────────────────────────────────────────────────
total_bytes = sum(
    os.path.getsize(os.path.join(root, f))
    for root, _, files in os.walk(OUT_DIR)
    for f in files if f.endswith(".png")
)
print(f"\n\n✓ Descargados : {ok}")
print(f"  Omitidos    : {skip}  (ya existían)")
print(f"  Fallidos    : {fail}")
print(f"  Tamaño total: {total_bytes / 1_048_576:.1f} MB")
print(f"\nListo. Ahora compila con:  pyinstaller ALS162_GPS_Sync.spec\n")
