"""Public README animation using only original synthetic assets and real game code.

This script never reads desktop probes, screenshots, saved profiles, or native
windows. The decorative mock desktop exists only in these exported illustrations.
"""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
from types import SimpleNamespace

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import pygame

from desktop_world.game_view import GameView
from desktop_world.profile import _default_profile


WIDTH, HEIGHT = 960, 540
NAMES = (
    "Notes", "Sketch", "Terminal", "Music", "Star", "Browser", "Archive", "Ideas",
    "草稿", "灵感", "Build", "Melody", "Orbit", "Web", "Books", "Canvas",
    "Memo", "Palette", "Console", "Rhythm", "Pixel", "Globe", "Drafts", "Photos",
    "Plan", "Draw", "Run", "Song", "Spark", "Links", "Inbox", "Studio",
    "Readme", "Art", "Shell", "Tune", "Night", "Explore", "Folder", "Play",
)
COLORS = ((238, 241, 225), (255, 192, 103), (110, 229, 181),
          (232, 135, 207), (255, 218, 116), (135, 188, 253))


def original_icon(kind: int, size: int = 30) -> Image.Image:
    """Draw an original file, folder, terminal, note, pixel star, or browser."""
    factor = 4
    image = Image.new("RGBA", (size * factor, size * factor))
    draw = ImageDraw.Draw(image)
    color = COLORS[kind]

    def box(rect, fill, radius=0, outline=None, width=1):
        draw.rounded_rectangle(tuple(round(v * factor) for v in rect),
            radius=round(radius*factor), fill=fill, outline=outline, width=width*factor)

    def line(points, fill, width=1):
        draw.line([(round(x*factor),round(y*factor)) for x,y in points], fill=fill, width=width*factor)

    def polygon(points, fill):
        draw.polygon([(round(x*factor),round(y*factor)) for x,y in points], fill=fill)

    if kind == 0:
        polygon([(6,2),(19,2),(25,8),(25,28),(6,28)], (*color,255))
        polygon([(19,2),(19,9),(25,9)], (149,177,192,255))
        for y,width in ((14,12),(18,9),(22,11)):
            line([(10,y),(10+width,y)],(65,94,112,255),1)
    elif kind == 1:
        box((2,6,28,25),(*color,255),3)
        box((3,3,14,10),(240,167,76,255),2)
        polygon([(2,11),(29,9),(26,27),(4,27)],(255,209,132,255))
    elif kind == 2:
        box((2,3,28,27),(24,51,56,255),4,(*color,255))
        line([(7,10),(12,15),(7,20)],(*color,255),2)
        line([(16,20),(23,20)],(*color,255),2)
        for x in (7,11,15):
            box((x,5,x+1,6),(134,192,170,255),1)
    elif kind == 3:
        box((3,2,27,28),(75,43,87,255),6)
        line([(13,21),(13,8),(24,5),(24,18)],(*color,255),2)
        draw.ellipse((7*factor,18*factor,14*factor,24*factor),fill=(*color,255))
        draw.ellipse((18*factor,15*factor,25*factor,21*factor),fill=(*color,255))
    elif kind == 4:
        polygon([(12,2),(18,2),(18,8),(24,8),(24,12),(29,12),(29,18),(23,18),
                 (23,24),(18,24),(18,29),(12,29),(12,23),(6,23),(6,18),(1,18),
                 (1,12),(7,12),(7,7),(12,7)],(*color,255))
        box((11,11,13,15),(86,74,47,255),1)
        box((18,11,20,15),(86,74,47,255),1)
    else:
        draw.ellipse((2*factor,2*factor,28*factor,28*factor),fill=(*color,255))
        draw.ellipse((8*factor,3*factor,22*factor,27*factor),outline=(232,245,255,255),width=factor)
        line([(3,15),(27,15)],(232,245,255,255),1)
        line([(5,8),(25,8)],(232,245,255,255),1)
        line([(5,22),(25,22)],(232,245,255,255),1)
    return image.resize((size,size),Image.Resampling.LANCZOS)


def synthetic_snapshot():
    """Forty fictional desktop items; no user filenames or images are sampled."""
    icons = []
    for index,name in enumerate(NAMES):
        column,row = index//8,index%8
        x,y=36+column*60,112+row*48
        icons.append(SimpleNamespace(key=f"showcase-{index}",name=name,x=x,y=y,width=30,height=30,
            image=original_icon(index%6),label_rect=(x-12,y+32,x+42,y+46)))
    return SimpleNamespace(bounds=(0,0,WIDTH,HEIGHT),work_area=(16,96,944,514),icons=icons,
                           font_name="microsoftyaheiui,microsoftyahei,segoeui",font_size=10)


def font(size: int):
    path=pygame.font.match_font("microsoftyaheiui,microsoftyahei,segoeui")
    return ImageFont.truetype(path,size) if path else ImageFont.load_default()


def backdrop(title: str, subtitle: str):
    """An explicitly fictional desktop backdrop used only by this exporter."""
    image=Image.new("RGB",(WIDTH,HEIGHT))
    draw=ImageDraw.Draw(image)
    for y in range(HEIGHT):
        ratio=y/(HEIGHT-1)
        draw.line((0,y,WIDTH,y),fill=(round(18+8*ratio),round(34+8*ratio),round(44+10*ratio)))
    glow=Image.new("RGBA",image.size)
    gd=ImageDraw.Draw(glow)
    gd.ellipse((330,-180,1110,590),fill=(58,135,139,36))
    gd.ellipse((540,110,980,650),fill=(105,91,150,30))
    image=Image.alpha_composite(image.convert("RGBA"),glow.filter(ImageFilter.GaussianBlur(65)))
    draw=ImageDraw.Draw(image)
    draw.text((26,16),"DESKTOP KILLER",font=font(12),fill=(117,236,189,255))
    draw.text((26,36),title,font=font(28),fill=(239,244,241,255))
    draw.text((27,74),subtitle,font=font(11),fill=(154,178,180,255))
    draw.line((26,95,934,95),fill=(72,108,116,100))
    draw.rounded_rectangle((350,518,610,539),radius=10,fill=(13,26,34,225))
    for index,color in enumerate(COLORS):
        x=394+index*31
        draw.rounded_rectangle((x,524,x+12,535),radius=3,fill=(*color,220))
    draw.text((26,522),"演示桌面 · 原创虚构图标",font=font(10),fill=(127,153,162,255))
    draw.text((880,522),"09:41",font=font(10),fill=(127,153,162,255))
    return image


def composite(view, background):
    frame=view.render()
    layer=Image.frombytes("RGBA",frame.get_size(),pygame.image.tobytes(frame,"RGBA"))
    return Image.alpha_composite(background,layer).convert("RGB")


def choose_existing_rewards(view):
    session=view.session
    while session.state=="upgrade":
        order=["chain","multishot","blades","damage","fire_rate","pierce","shield",
               "vitality","pulse","speed","magnet","seal"]
        if session.player.hp<65:
            order=["vitality","shield"]+order
        index=min(range(len(session.upgrade_choices)),key=lambda i:order.index(session.upgrade_choices[i]["id"]))
        session.choose_upgrade(index)
    if session.state=="intermission":
        session.choose_stage(1)


def battle_step(view, dt):
    """Use only ordinary cursor movement, legal skills, and offered upgrades."""
    choose_existing_rewards(view)
    session=view.session
    p=session.player
    cursor=(565+math.cos(session.total_time*.55)*83,305+math.sin(session.total_time*.55)*105)
    nearby=[actor for actor in session.actors if actor.state=="active"]
    if nearby:
        closest=min(nearby,key=lambda actor:math.dist(actor.pos,p.pos))
        distance=math.dist(closest.pos,p.pos)
        if distance<session.pulse_radius*.78:
            session.pulse()
        if distance<p.radius+closest.radius+15:
            session.dash(cursor)
    view.update(dt,cursor)
    if session.state in ("won","lost"):
        raise RuntimeError("showcase bot finished before its capture window; choose a different legal route")


def battle_frames(fps):
    profile=_default_profile()
    profile["settings"]["show_hints"]=False
    view=GameView(synthetic_snapshot(),profile=profile,start_mode="campaign",seed=7)
    background=backdrop("当桌面开始追着你跑。","活下来，再去收拾那些准备重启的家伙。")
    warmup,duration=24.0,8.0
    for _ in range(round(warmup*60)):
        battle_step(view,1/60)
    frames=[]
    for _ in range(round(duration*fps)):
        frames.append(composite(view,background))
        for _ in range(60//fps):
            battle_step(view,1/60)
    return frames,{"fps":fps,"duration_s":duration,"simulation_start_s":warmup,
                   "simulation_end_s":round(view.session.total_time,2),"summary":view.session.summary()}


def heart_points():
    raw=[(16*math.sin(i*math.tau/240)**3,
          -(13*math.cos(i*math.tau/240)-5*math.cos(2*i*math.tau/240)
            -2*math.cos(3*i*math.tau/240)-math.cos(4*i*math.tau/240))) for i in range(241)]
    low,high=min(y for x,y in raw),max(y for x,y in raw)
    return [(535+x*13,303+(y-(low+high)/2)*13) for x,y in raw]


def drawing_frames(fps):
    view=GameView(synthetic_snapshot(),profile=_default_profile(),start_mode="drawing",seed=7)
    background=backdrop("让图标，画一颗心。","落笔 → 松手 → 图标沿着你的线条重新排阵")
    path=heart_points()
    duration=9.5
    started=finished=False
    all_arrived_at=None
    added=0
    frames=[]
    for frame_index in range(round(duration*fps)):
        # Session APIs receive the same point sequence as a user's held pen.
        for substep in range(60//fps):
            t=(frame_index*(60//fps)+substep)/60
            if t>=.5 and not started:
                view.session.begin_stroke(path[0])
                started=True
                added=1
            if started and not finished:
                upto=min(len(path),1+round(max(0,t-.5)/3.0*(len(path)-1)))
                while added<upto:
                    view.session.add_point(path[added])
                    added+=1
                if t>=3.5:
                    if not view.session.end_stroke():
                        raise RuntimeError("synthetic drawing failed to commit")
                    finished=True
            view.session.update(1/60)
            view.clock+=1/60
        frames.append(composite(view,background))
        if finished and all_arrived_at is None and all(math.dist(a.pos,a.target)<.2 for a in view.session.actors):
            all_arrived_at=(frame_index+1)/fps
    arrived=sum(math.dist(a.pos,a.target)<.2 for a in view.session.actors)
    if arrived!=len(view.session.actors):
        raise RuntimeError("drawing ended before every real simulated actor arrived")
    return frames,{"fps":fps,"duration_s":len(frames)/fps,"pen_down_s":.5,"pen_up_s":3.5,
                   "all_arrived_s":all_arrived_at,"final_hold_s":len(frames)/fps-all_arrived_at,
                   "arrived":arrived,"icons":len(view.session.actors),"stroke_count":view.session.stroke_count}


def save_gif(frames,path,fps):
    samples=frames[::max(1,len(frames)//12)][:12]
    palette_source=Image.new("RGB",(320*4,180*3))
    for index,frame in enumerate(samples):
        palette_source.paste(frame.resize((320,180),Image.Resampling.LANCZOS),((index%4)*320,(index//4)*180))
    palette=palette_source.quantize(colors=224,method=Image.Quantize.MEDIANCUT)
    indexed=[frame.quantize(palette=palette,dither=Image.Dither.NONE) for frame in frames]
    # GIF durations are in centiseconds; distribute rounding instead of speeding up.
    durations=[round((index+1)*100/fps)*10-round(index*100/fps)*10 for index in range(len(frames))]
    indexed[0].save(path,save_all=True,append_images=indexed[1:],duration=durations,
                    loop=0,optimize=True,disposal=1)
    if path.stat().st_size>4*1024*1024:
        raise RuntimeError(f"{path.name} exceeds the public 4 MiB budget")


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,default=ROOT/"docs"/"media")
    parser.add_argument("--fps",type=int,choices=(10,12),default=12)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=True)
    metadata={"source":"Forty script-generated original icons with fictional names; no desktop capture",
              "background":"Fictional demonstration backdrop, never used by the game",
              "size":[WIDTH,HEIGHT],"speed":"real-time"}
    for name,render in (("battle",battle_frames),("drawing",drawing_frames)):
        frames,info=render(args.fps)
        path=args.output/f"{name}.gif"
        save_gif(frames,path,args.fps)
        frames[0].save(args.output/f"{name}-first.png")
        key_index=(len(frames)-1 if name=="drawing" else len(frames)//2)
        frames[key_index].save(args.output/f"{name}-key.png")
        if name=="drawing":
            frames[round(2.5*args.fps)].save(args.output/"drawing-stroke.png")
        info["bytes"]=path.stat().st_size
        metadata[name]=info
        print(f"{name}: {len(frames)} frames, {path.stat().st_size/1024:.0f} KiB")
    (args.output/"showcase.json").write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding="utf-8")


if __name__=="__main__":
    main()
