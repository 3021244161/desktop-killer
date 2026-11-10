"""Reuse the game's original vector ghost as a transparent multi-size Windows icon."""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image
import pygame

from desktop_world.wardrobe import draw_character

SIZES = (16, 24, 32, 48, 64, 128, 256)


def ghost_icon() -> Image.Image:
    surface = pygame.Surface((320, 320), pygame.SRCALPHA, 32)
    draw_character(surface, (160, 144), outfit="ghost", scale=9.0, clock=0.0)
    rgba = Image.frombytes("RGBA", surface.get_size(), pygame.image.tobytes(surface, "RGBA"))
    box = rgba.getchannel("A").getbbox()
    if box is None:
        raise RuntimeError("The original ghost did not render")
    source = rgba.crop(box)
    edge = max(source.size) + 28
    padded = Image.new("RGBA", (edge, edge), (0, 0, 0, 0))
    padded.alpha_composite(source, ((edge-source.width)//2, (edge-source.height)//2))
    return padded.resize((256, 256), Image.Resampling.LANCZOS)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "packaging" / "icon.ico")
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    image = ghost_icon()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    image.save(args.output, format="ICO", sizes=[(edge, edge) for edge in SIZES])
    if args.preview:
        args.preview.parent.mkdir(parents=True, exist_ok=True)
        image.save(args.preview)
    with Image.open(args.output) as check:
        if check.ico.sizes() != {(edge, edge) for edge in SIZES}:
            raise RuntimeError("The ICO is missing a requested size")
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
