"""Build the Chinese gameplay manual from the reviewed release content JSON.

Fonts are subset-embedded in the PDF, not distributed as standalone font files.
After building, render every page with Poppler and visually review before shipping.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Paragraph

ROOT = Path(__file__).resolve().parents[1]
PAGE_W, PAGE_H = A4
MARGIN = 46
INK = colors.HexColor("#17333B")
MUTED = colors.HexColor("#536C70")
ACCENT = colors.HexColor("#167A74")
PAPER = colors.HexColor("#FCFBF7")
LINE = colors.HexColor("#D9E3E1")


def register_fonts(font_dir: Path) -> None:
    pdfmetrics.registerFont(TTFont("ManualRegular", str(font_dir / "msyh.ttc"), subfontIndex=0))
    pdfmetrics.registerFont(TTFont("ManualBold", str(font_dir / "msyhbd.ttc"), subfontIndex=0))
    pdfmetrics.registerFontFamily("ManualRegular", normal="ManualRegular", bold="ManualBold")


def paragraph(canvas: Canvas, text: str, x: float, top: float, width: float,
              size: float = 10.7, bold: bool = False, color=INK,
              leading: float | None = None) -> float:
    style = ParagraphStyle("manual", fontName="ManualBold" if bold else "ManualRegular",
                           fontSize=size, leading=leading or size * 1.65, textColor=color,
                           alignment=TA_LEFT, wordWrap="CJK", splitLongWords=True)
    block = Paragraph(escape(text).replace("\n", "<br/>"), style)
    _, height = block.wrap(width, PAGE_H)
    if top - height < 58:
        raise ValueError(f"Page overflow: {text[:60]!r}")
    block.drawOn(canvas, x, top - height)
    return top - height


def furniture(canvas: Canvas, index: int, total: int, title: str, version: str) -> None:
    canvas.setFillColor(PAPER)
    canvas.rect(0, 0, PAGE_W, PAGE_H, fill=1, stroke=0)
    canvas.setFillColor(ACCENT)
    canvas.rect(MARGIN, PAGE_H - 43, 20, 3, fill=1, stroke=0)
    canvas.setFont("ManualBold", 8.2)
    canvas.drawString(MARGIN + 29, PAGE_H - 43, "DESKTOP KILLER / 桌面叛乱")
    canvas.setFillColor(MUTED)
    canvas.setFont("ManualRegular", 8)
    canvas.drawRightString(PAGE_W - MARGIN, PAGE_H - 43, version)
    canvas.setStrokeColor(LINE)
    canvas.line(MARGIN, 45, PAGE_W - MARGIN, 45)
    canvas.setFont("ManualRegular", 8)
    canvas.drawString(MARGIN, 28, title)
    canvas.drawRightString(PAGE_W - MARGIN, 28, f"{index:02d} / {total:02d}")


def section(canvas: Canvas, block: dict, top: float) -> float:
    width = PAGE_W - MARGIN * 2
    if block.get("outfit_strip"):
        os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
        import pygame
        from PIL import Image
        sys.path.insert(0, str(ROOT))
        from desktop_world.wardrobe import OUTFITS, draw_character
        slot = width / len(OUTFITS)
        for index, (key, outfit) in enumerate(OUTFITS.items()):
            image = pygame.Surface((120, 120), pygame.SRCALPHA, 32)
            draw_character(image, (60, 60), outfit=key, scale=2.0)
            rgba = Image.frombytes("RGBA", image.get_size(), pygame.image.tobytes(image, "RGBA"))
            x = MARGIN + slot * index
            canvas.drawImage(ImageReader(rgba), x + (slot-62)/2, top - 62, 62, 62, mask="auto")
            paragraph(canvas, outfit["title"], x + 4, top - 67, slot - 8, 8.5, color=MUTED)
        return top - 102
    if block.get("title"):
        top = paragraph(canvas, block["title"], MARGIN, top, width, 14, True) - 9
    for text in block.get("paragraphs", []):
        top = paragraph(canvas, text, MARGIN, top, width) - 11
    for row in block.get("rows", []):
        key, text = row
        key_width = 130
        bottom_key = paragraph(canvas, key, MARGIN + 12, top - 10, key_width - 20, 10.2, True, ACCENT)
        bottom_text = paragraph(canvas, text, MARGIN + key_width, top - 10, width - key_width - 12, 10.2)
        bottom = min(bottom_key, bottom_text) - 10
        canvas.setStrokeColor(LINE)
        canvas.line(MARGIN, bottom, PAGE_W - MARGIN, bottom)
        top = bottom
    if block.get("note"):
        top -= 7
        top = paragraph(canvas, block["note"], MARGIN + 12, top, width - 24, 9.4, color=MUTED) - 6
    return top - 17


def build(content: dict, output: Path, font_dir: Path) -> None:
    register_fonts(font_dir)
    pages = content["pages"]
    if not 1 <= len(pages) <= 12:
        raise ValueError("Manual requires 1 to 12 explicitly reviewed pages")
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas = Canvas(str(output), pagesize=A4, pageCompression=1)
    canvas.setTitle(content["title"])
    canvas.setAuthor("Desktop Killer")
    canvas.setSubject("桌面叛乱中文玩法指南")
    for index, page in enumerate(pages, 1):
        furniture(canvas, index, len(pages), content["title"], content["version"])
        canvas.bookmarkPage(f"page-{index}")
        canvas.addOutlineEntry(page["title"], f"page-{index}", level=0)
        top = PAGE_H - 78
        top = paragraph(canvas, page.get("eyebrow", f"{index:02d}"), MARGIN, top,
                        PAGE_W - MARGIN * 2, 9.5, True, ACCENT) - 12
        top = paragraph(canvas, page["title"], MARGIN, top, PAGE_W - MARGIN * 2, 25, True, leading=35) - 13
        if page.get("intro"):
            top = paragraph(canvas, page["intro"], MARGIN, top, PAGE_W - MARGIN * 2,
                            11.5, color=MUTED, leading=19) - 23
        for block in page.get("sections", []):
            top = section(canvas, block, top)
        canvas.showPage()
    canvas.save()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--content", type=Path, default=ROOT / "packaging" / "manual_content.json")
    parser.add_argument("--output", type=Path, default=ROOT / "output" / "pdf" / "玩法指南.pdf")
    parser.add_argument("--font-dir", type=Path, default=Path(r"C:\Windows\Fonts"))
    args = parser.parse_args()
    build(json.loads(args.content.read_text(encoding="utf-8")), args.output, args.font_dir)
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
