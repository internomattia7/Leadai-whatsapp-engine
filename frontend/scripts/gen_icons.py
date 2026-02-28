"""
Generate PNG icons from logo.svg.

Usage:
    pip install cairosvg
    python scripts/gen_icons.py
"""
import os
import sys

try:
    import cairosvg
except ImportError:
    print("cairosvg not installed. Run: pip install cairosvg")
    sys.exit(1)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ICONS_DIR = os.path.join(SCRIPT_DIR, "..", "public", "icons")
SVG_PATH = os.path.join(ICONS_DIR, "logo.svg")

for size in (192, 512):
    out = os.path.join(ICONS_DIR, f"icon-{size}.png")
    cairosvg.svg2png(url=SVG_PATH, write_to=out, output_width=size, output_height=size)
    print(f"Generated {out}")
