"""Genera los recursos de marca de Lazarus desde una sola geometría (zorro facetado).

Salida:
- lazarus/assets/logo.svg       logo negro con nariz naranja (fondo transparente)
- lazarus/assets/logo_white.svg logo blanco para fondos oscuros
- lazarus/assets/icon.png       ícono de app (fondo negro, zorro blanco), 256 px
- lazarus/assets/icon.svg       ícono de app en SVG
- installer/lazarus.ico         ícono del instalador y de los accesos directos
Uso: python installer/make_icon.py
"""
from pathlib import Path

from PIL import Image, ImageDraw

INK, ACCENT, APP_BG = "#111111", "#D4502A", "#111111"
W, H = 102.2, 108.0
POLYS = [
    ([(9.8, 1.7), (3.3, 48.3), (35.9, 31.5)], "ink"),                                   # oreja izquierda
    ([(92.4, 1.7), (98.9, 48.3), (66.3, 31.5)], "ink"),                                 # oreja derecha
    ([(1.7, 55.4), (37.6, 36.5), (48.9, 36.5), (48.9, 87.0), (37.6, 87.0)], "ink"),     # cara izquierda
    ([(100.5, 55.4), (64.6, 36.5), (53.3, 36.5), (53.3, 87.0), (64.6, 87.0)], "ink"),   # cara derecha
    ([(38.0, 91.7), (64.2, 91.7), (51.1, 106.5)], "accent"),                            # nariz
]
ROOT = Path(__file__).resolve().parent.parent


def svg(ink=INK, accent=ACCENT, bg=None, pad=0.0, radius=0.22) -> str:
    side = max(W, H) + 2 * pad
    ox, oy = (side - W) / 2, (side - H) / 2
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {side:.1f} {side:.1f}">']
    if bg:
        out.append(f'<rect width="{side:.1f}" height="{side:.1f}" rx="{side * radius:.1f}" fill="{bg}"/>')
    for pts, kind in POLYS:
        p = " ".join(f"{x + ox:.1f},{y + oy:.1f}" for x, y in pts)
        out.append(f'<polygon points="{p}" fill="{ink if kind == "ink" else accent}"/>')
    out.append("</svg>")
    return "".join(out)


def png(size, ink=INK, accent=ACCENT, bg=None, pad=0.0, radius=0.22) -> Image.Image:
    k = 4  # supermuestreo para bordes suaves
    s = size * k
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    side = max(W, H) + 2 * pad
    f = s / side
    ox, oy = (side - W) / 2, (side - H) / 2
    if bg:
        d.rounded_rectangle((0, 0, s - 1, s - 1), radius=int(s * radius), fill=bg)
    for pts, kind in POLYS:
        d.polygon([((x + ox) * f, (y + oy) * f) for x, y in pts], fill=ink if kind == "ink" else accent)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    assets = ROOT / "lazarus" / "assets"
    assets.mkdir(parents=True, exist_ok=True)
    (assets / "logo.svg").write_text(svg(), encoding="utf-8")
    (assets / "logo_white.svg").write_text(svg(ink="#FFFFFF"), encoding="utf-8")
    (assets / "icon.svg").write_text(svg(ink="#FFFFFF", bg=APP_BG, pad=22), encoding="utf-8")
    png(256, ink="#FFFFFF", bg=APP_BG, pad=22).save(assets / "icon.png")
    big = png(256, ink="#FFFFFF", bg=APP_BG, pad=22)
    big.save(ROOT / "installer" / "lazarus.ico",
             sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("ok:", ", ".join(p.name for p in assets.iterdir()))
