"""Build README illustrations: add the shared style, symbols and subset fonts to each SVG source.

SVGs shown through <img> (as GitHub does) cannot load external fonts, so each
font is cut down to the characters the drawing uses and inlined as base64.

    python code/docs/images/src/build.py      # needs: pip install fonttools brotli
"""

from __future__ import annotations

import base64
import html
import io
import re
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont

SRC_DIR = Path(__file__).resolve().parent
OUT_DIR = SRC_DIR.parent
FONT_DIR = SRC_DIR / "fonts"
PLACEHOLDER = "/*FONTS*/"
STYLE_SLOT, DEFS_SLOT = "/*STYLE*/", "<!--DEFS-->"
FONTS = (  # (css family, weight, file)
    ("Fraunces", 700, "fraunces-latin-700-normal.woff2"),
    ("Atkinson", 400, "atkinson-hyperlegible-latin-400-normal.woff2"),
    ("Atkinson", 700, "atkinson-hyperlegible-latin-700-normal.woff2"),
    ("Caveat", 600, "caveat-latin-600-normal.woff2"),
)


def used_characters(svg: str) -> str:
    """Every character inside <text>/<tspan> content, plus a space."""
    text = "".join(re.findall(r">([^<>]+)<", svg))
    return "".join(sorted(set(html.unescape(text)) | {" "}))


def subset_font(path: Path, chars: str) -> str:
    font = TTFont(path)
    options = subset.Options()
    options.flavor = "woff2"
    options.layout_features = ["*"]
    subsetter = subset.Subsetter(options)
    subsetter.populate(text=chars)
    subsetter.subset(font)
    buffer = io.BytesIO()
    font.flavor = "woff2"
    font.save(buffer)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def font_faces(chars: str) -> str:
    faces = []
    for family, weight, file in FONTS:
        data = subset_font(FONT_DIR / file, chars)
        faces.append(f"@font-face{{font-family:'{family}';font-weight:{weight};"
                     f"src:url(data:font/woff2;base64,{data}) format('woff2');}}")
    return "\n    ".join(faces)


def build(source: Path) -> Path:
    svg = source.read_text(encoding="utf-8")
    for slot in (PLACEHOLDER, STYLE_SLOT, DEFS_SLOT):
        if slot not in svg:
            raise ValueError(f"{source.name}: missing {slot}")
    svg = (svg.replace(STYLE_SLOT, (SRC_DIR / "_style.css").read_text(encoding="utf-8").strip())
              .replace(DEFS_SLOT, (SRC_DIR / "_defs.svg").read_text(encoding="utf-8").strip()))
    out = OUT_DIR / source.name
    out.write_text(svg.replace(PLACEHOLDER, font_faces(used_characters(svg))), encoding="utf-8")
    return out


def main() -> None:
    for source in sorted(p for p in SRC_DIR.glob("*.svg") if not p.name.startswith("_")):
        out = build(source)
        print(f"{out.relative_to(OUT_DIR)}  {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
