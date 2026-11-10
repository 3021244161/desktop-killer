"""Offline visual QA using already-exported independent icon assets; no desktop takeover."""
import argparse
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
import pygame


def load_snapshot(path):
    data = json.loads((path / "desktop.json").read_text(encoding="utf-8"))
    icons = []
    for index, record in enumerate(data["icons"]):
        image = Image.open(path / record["asset"]).convert("RGBA")
        label = path / f"label-{index:03d}.png"
        icons.append(SimpleNamespace(**{k: record[k] for k in ("key","name","x","y","width","height","label_rect")},
                                     image=image, label_image=Image.open(label).convert("RGBA") if label.exists() else None))
    return SimpleNamespace(bounds=data["bounds"],work_area=data["work_area"],icons=icons,
                           font_name=data["font"][0],font_size=data["font"][1])


def render(probe, output):
    from desktop_world.game_view import GameView
    from desktop_world.profile import load_profile
    view = GameView(load_snapshot(probe), seed=14)
    output.mkdir(parents=True, exist_ok=True)
    def save(name):
        frame = view.render()
        pygame.image.save(frame,str(output / f"{name}-alpha.png"))
        # Neutral QA ground makes transparent text legible; never used by the game.
        bg = Image.new("RGBA",frame.get_size(),(50,62,66,255))
        overlay=Image.frombytes("RGBA",frame.get_size(),pygame.image.tobytes(frame,"RGBA"))
        bg.alpha_composite(overlay)
        bg.convert("RGB").save(output / f"{name}.png")
    save("menu")
    for page in ("wardrobe", "career", "achievements", "settings", "guide"):
        view.page = page
        save(page)
    view.page = "home"
    view.start("drawing")
    view.session.preset("heart")
    for _ in range(10*60):
        view.update(1/60, (1000,600))
    save("drawing-heart")
    view.start("campaign")
    for _ in range(20*60):
        view.update(1/60, (1000,600), demo=True)
        if view.session.state == "upgrade":
            save("upgrade")
            view.session.choose_upgrade(0)
    save("combat")
    if view.session.state == "playing":
        view.session.toggle_pause()
    save("pause")
    view.session.retire()
    view.update(0,(1000,600))
    save("result")
    print(json.dumps({"output":str(output),"frames":sorted(p.name for p in output.glob('*.png'))}))


if __name__ == "__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("--probe",type=Path,default=ROOT/"artifacts"/"fixed-provider"/"probe")
    parser.add_argument("--output",type=Path,default=ROOT/"artifacts"/"product-ui")
    args=parser.parse_args()
    render(args.probe,args.output)
