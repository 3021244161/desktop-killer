"""Player-facing hub, wardrobe, career and drawing-mode presentation."""
from __future__ import annotations

import copy
import math
import uuid

import pygame

INK, WHITE, DIM = (23, 30, 35), (239, 244, 241), (158, 176, 176)
MINT, GOLD, RED, BLUE = (117, 236, 189), (255, 192, 102), (255, 111, 111), (124, 192, 249)


class ProductViews:
    def _cached(self, name, factory):
        if name not in self._profile_cache:
            self._profile_cache[name] = factory()
        return self._profile_cache[name]

    def _persist(self):
        self._profile_cache.clear()
        if self.on_profile_change and self.on_profile_change() is False:
            self._say("保存失败，请检查存档目录是否可写", RED)
            return False
        return True

    def _say(self, text, color=MINT):
        self.toast, self.toast_color, self.toast_left = text, color, 4.0

    def _transaction(self, operation):
        previous = copy.deepcopy(self.profile)
        result = operation()
        if isinstance(result, dict) and result.get("ok") is False:
            reason = result.get("reason", "暂时无法完成")
            self._say({"insufficient_crystals":"数据晶片不足，完成战斗可继续积累。",
                       "max_level":"这项训练已达到最高等级。", "maxed":"这项训练已达到最高等级。",
                       "not_owned":"先解锁这套装扮再装备。"}.get(reason, str(reason)), GOLD)
            return result
        if not self._persist():
            self.profile.clear()
            self.profile.update(previous)
            self._profile_cache.clear()
            return {"ok": False, "reason": "save_failed"}
        return result

    def _product_action(self, action):
        from . import progression, wardrobe
        from .profile import set_setting
        if action == "retry_save":
            if self._persist():
                self.reward["saved"] = True
                self._say("档案已保存")
            return None
        if action in ("help", "open_data"):
            return action
        category, value = action.split(":", 1)
        if category == "page":
            self.page = value
        elif category == "outfit":
            def acquire():
                entry = next(item for item in wardrobe.outfit_catalog(self.profile) if item["id"] == value)
                if not entry["owned"]:
                    result = wardrobe.purchase_outfit(self.profile, value)
                    if not result.get("ok"):
                        return result
                return wardrobe.equip_outfit(self.profile, value)
            result = self._transaction(acquire)
            if result and result.get("ok"):
                self._say("换装完成 · 下一局将穿上这套装扮")
        elif category == "talent":
            result = self._transaction(lambda: progression.purchase_talent(self.profile, value))
            if result and result.get("ok"):
                self._say("训练完成 · 从下一局开始生效")
        elif category == "setting":
            current = self.profile.get("settings", {}).get(value, value in ("show_hints", "drawing_guides"))
            self._transaction(lambda: set_setting(self.profile, value, not current))
        elif category == "preset" and self.mode == "drawing":
            if self.session.preset(value):
                self._record_formation(sum(self._line_length(line) for line in self.session.strokes))
        elif category == "draw" and self.mode == "drawing":
            if value == "undo":
                self.session.undo()
            elif value == "reset":
                self.session.reset()
            elif value == "pause":
                self.drawing_paused = not self.drawing_paused
                self.session.cancel_stroke()
                self._drawing_started = False
                self._drawing_wait_release = True
        self.buttons.clear()
        return None

    def _draw_toast(self):
        if self.toast_left <= 0:
            return
        width = min(self.work.w - 32, round(470 * self.scale))
        rect = pygame.Rect(self.work.centerx - width // 2, self.work.bottom - round(100 * self.scale),
                           width, round(48 * self.scale))
        pygame.draw.rect(self.frame, (*INK, 245), rect, border_radius=8)
        self._wrap(self.toast, rect.x + 10, rect.y + 7, rect.w - 20,
                   getattr(self, "toast_color", MINT), 13, 2)

    def _page_frame(self, title, subtitle, height=650, width=500):
        rect = self._menu_rect(height=height, width=width)
        self._panel(rect)
        x, y = rect.x + round(24*self.scale), rect.y + round(22*self.scale)
        self._text(title, (x, y), WHITE, 28)
        self._wrap(subtitle, x, y + round(42*self.scale), rect.w - round(48*self.scale), DIM, 12, 2)
        self._button(pygame.Rect(x, rect.bottom - round(48*self.scale), round(110*self.scale), round(30*self.scale)),
                     "返回主菜单", "page:home")
        return rect, x, y + round(90*self.scale)

    def _draw_product_page(self):
        methods = {"home": self._draw_home, "wardrobe": self._draw_wardrobe,
                   "career": self._draw_career, "achievements": self._draw_achievements,
                   "settings": self._draw_settings, "guide": self._draw_guide}
        methods.get(self.page, self._draw_home)()

    def _draw_home(self):
        from .game_view import MODES
        from .progression import account_info
        from .wardrobe import draw_character, equipped_outfit
        info = self._cached("account",lambda:account_info(self.profile))
        sc = self.scale
        rect = self._menu_rect(height=670, width=500)
        self._panel(rect)
        x, y = rect.x+round(24*sc), rect.y+round(22*sc)
        width = rect.w-round(48*sc)
        self._text("DESKTOP KILLER  /  0.3", (x,y), MINT, 12)
        self._text("桌面叛乱", (x,y+round(24*sc)), WHITE, 36)
        draw_character(self.frame, (rect.right-round(50*sc), y+round(46*sc)),
                       outfit=self._cached("equipped",lambda:equipped_outfit(self.profile)), scale=1.7*sc,
                       clock=0 if self.profile.get("settings",{}).get("reduced_motion") else self.clock)
        self._text(f"档案 Lv.{info['level']}    数据晶片 {info['crystals']:,}", (x,y+round(76*sc)), GOLD, 13)
        y += round(110*sc)
        for mode, (title, description, number) in MODES.items():
            self._button(pygame.Rect(x,y,width,round(67*sc)), title, mode,
                         subtitle=description, number=number, accent=BLUE if mode=="drawing" else MINT)
            if mode != "drawing":
                best=self.profile.get("modes",{}).get(mode,{}).get("best_score",0)
                self._text(f"最高 {best:,}",(x+width-round(12*sc),y+round(10*sc)),DIM,11,right=True)
            y += round(76*sc)
        y += round(5*sc)
        for index,(title,page) in enumerate((("角色换装 · C","wardrobe"),("成长训练 · H","career"),
                                           ("成就档案","achievements"),("偏好设置","settings"))):
            column, row = index%2, index//2
            self._button(pygame.Rect(x+column*(width//2+4), y+round(row*45*sc), width//2-4, round(37*sc)),title,"page:"+page)
        y += round(101*sc)
        self._wrap("Ctrl + 左键画画。所有图标都能成为画笔。", x, y, width, DIM, 12, 2)
        bottom=rect.bottom-round(48*sc)
        self._button(pygame.Rect(x,bottom,round(140*sc),round(30*sc)),"玩法与 PDF 手册","page:guide")
        self._button(pygame.Rect(rect.right-round(134*sc),bottom,round(110*sc),round(30*sc)),"退出 · F5","quit",accent=RED)

    def _draw_wardrobe(self):
        from .wardrobe import outfit_catalog, draw_character
        from .progression import account_info
        balance = self._cached("account",lambda:account_info(self.profile))["crystals"]
        rect,x,y=self._page_frame("角色换装",f"数据晶片 {balance:,} · 外观不改变能力，可随时切换。")
        sc=self.scale
        tile_w=(rect.w-round(58*sc))//2
        for index,item in enumerate(self._cached("outfits",lambda:outfit_catalog(self.profile))):
            tile=pygame.Rect(x+(index%2)*(tile_w+round(10*sc)),y+round((index//2)*151*sc),tile_w,round(140*sc))
            pygame.draw.rect(self.frame,(32,43,47,250),tile,border_radius=8)
            draw_character(self.frame,(tile.centerx,tile.y+round(43*sc)),outfit=item["id"],scale=1.4*sc,
                           clock=0 if self.profile.get("settings",{}).get("reduced_motion") else self.clock)
            self._text(item["title"],(tile.centerx,tile.y+round(77*sc)),WHITE,14,center=True)
            label="已装备" if item["equipped"] else "装备" if item["owned"] else f"解锁 · {item['price']} 晶片"
            self._button(pygame.Rect(tile.x+round(8*sc),tile.bottom-round(38*sc),tile.w-round(16*sc),round(29*sc)),
                         label,"outfit:"+item["id"],accent=MINT if item["owned"] else GOLD)

    def _draw_career(self):
        from .progression import talent_catalog,account_info
        info=self._cached("account",lambda:account_info(self.profile))
        rect,x,y=self._page_frame("成长训练",f"档案 Lv.{info['level']} · {info['crystals']:,} 晶片 · 天赋下一局生效")
        sc=self.scale
        self._text(f"档案经验  {info['xp_into_level']}/{info['xp_for_next']}",(x,y),BLUE,12)
        y+=round(24*sc)
        for item in self._cached("talents",lambda:talent_catalog(self.profile)):
            row=pygame.Rect(x,y,rect.w-round(48*sc),round(65*sc))
            pygame.draw.rect(self.frame,(32,43,47,250),row,border_radius=6)
            self._text(f"{item['title']}  {item['level']}/{item['max_level']}",(x+9,y+round(7*sc)),WHITE,14)
            if self.scale>=.62:
                self._wrap(item["description"],x+9,y+round(32*sc),row.w-round(110*sc),DIM,11,1)
            label="已满级" if item["maxed"] else f"升级 {item['price']}"
            self._button(pygame.Rect(row.right-round(101*sc),y+round(16*sc),round(91*sc),round(32*sc)),
                         label,"talent:"+item["id"],accent=DIM if item["maxed"] else GOLD)
            y+=round(73*sc)

    def _draw_achievements(self):
        from .progression import achievement_catalog,account_info
        info=self._cached("account",lambda:account_info(self.profile))
        rect,x,y=self._page_frame("成就档案",f"{info['runs']} 局战斗 · {info['wins']} 次胜利 · 每项奖励只领取一次")
        sc=self.scale
        for item in self._cached("achievements",lambda:achievement_catalog(self.profile)):
            row=pygame.Rect(x,y,rect.w-round(48*sc),round(57*sc))
            color=MINT if item["unlocked"] else DIM
            self._text(("✓ " if item["unlocked"] else "○ ")+item["title"],(x,y),color,14)
            self._text("已达成" if item["unlocked"] else f"{item['progress']}/{item['target']}",
                       (row.right,y),color,11,right=True)
            if sc>=.62:
                self._wrap(item["description"],x,y+round(22*sc),row.w,DIM,11,1)
            self._bar(pygame.Rect(x,y+round(44*sc),row.w,2),item["progress_ratio"],color)
            y+=round(60*sc)

    def _draw_settings(self):
        rect,x,y=self._page_frame("偏好设置","设置与战绩保存在本机；旧版档案会自动升级。",height=510)
        sc=self.scale
        for title,key,default in (("操作提示","show_hints",True),("减少动态效果","reduced_motion",False),
                                  ("画画辅助线","drawing_guides",True)):
            enabled=self.profile.get("settings",{}).get(key,default)
            self._button(pygame.Rect(x,y,rect.w-round(48*sc),round(45*sc)),
                         f"{title}：{'开' if enabled else '关'}","setting:"+key)
            y+=round(55*sc)
        self._button(pygame.Rect(x,y,rect.w-round(48*sc),round(45*sc)),
                     "音效：关" if self.profile.get("muted") else "音效：开","mute")
        y+=round(60*sc)
        self._button(pygame.Rect(x,y,rect.w-round(48*sc),round(38*sc)),"打开存档目录","open_data")

    def _draw_guide(self):
        rect,x,y=self._page_frame("从桌面开始冒险","战斗与创作，共用你自己的真实桌面图标。",height=610)
        width=rect.w-round(48*self.scale)
        sections=(("战斗", "鼠标 / WASD 移动，自动开火。空格 / 左键脉冲，Shift / 右键冲刺。击碎后靠近原位并停留，赶在复活前断链。"),
                  ("画画", "按 4 进入画画模式。Ctrl + 按住左键画线，松开后图标均匀走成图案。支持多笔。Backspace 撤销，R 回原位，空格隐藏辅助线。"),
                  ("成长", "战斗结算获得经验和数据晶片。换装只有外观变化；训练提供有上限的永久提升。成就另有奖励。"),
                  ("随时离开", "P / Esc 暂停，切出应用自动暂停。F5 还原桌面并退出。游戏不改变真实桌面文件和排列。"))
        for title,description in sections:
            self._text(title,(x,y),MINT,16)
            y=self._wrap(description,x,y+round(27*self.scale),width,DIM,13,4)+round(20*self.scale)
        self._button(pygame.Rect(rect.right-round(190*self.scale),rect.bottom-round(48*self.scale),
                                     round(166*self.scale),round(30*self.scale)),"打开 PDF 手册 · F1","help",accent=BLUE)

    @staticmethod
    def _line_length(line):
        return sum(math.dist(a,b) for a,b in zip(line,line[1:]))

    def _record_formation(self, distance):
        from .progression import record_drawing
        result=self._transaction(lambda: record_drawing(self.profile,strokes=1,distance=distance,event_id=uuid.uuid4().hex))
        if isinstance(result,dict) and result.get("achievements"):
            self._say("成就达成 · 前往成就档案查看奖励")

    def _finish_stroke(self):
        distance=self._line_length(self.session.preview)
        if self.session.end_stroke():
            self._record_formation(distance)
        elif self.session.last_error:
            self._say(self.session.last_error,GOLD)
        self._drawing_started=False

    def _update_drawing(self,dt,cursor,keys,buttons,demo):
        s=self.session
        if self.drawing_paused:
            return
        chord=0x11 in keys and 1 in buttons
        if self._drawing_wait_release:
            if not chord:
                self._drawing_wait_release=False
            self._drawing_chord=chord
            s.update(dt)
            return
        point=self._point(cursor)
        canvas=self.work.collidepoint(point) and not self._drawing_ui_rect.collidepoint(point)
        if chord and not self._drawing_chord and canvas:
            s.begin_stroke(cursor)
            self._drawing_started=True
        elif chord and self._drawing_started:
            if canvas:
                s.add_point(cursor)
            else:
                self._finish_stroke()
        elif not chord and self._drawing_started:
            if canvas:
                s.add_point(cursor)
            self._finish_stroke()
        self._drawing_chord=chord
        if demo and not self._drawing_demo_done and s.total_time>1.2:
            s.preset("heart")
            self._drawing_demo_done=True
        s.update(dt)

    def _draw_drawing(self):
        s=self.session
        playing={a.key for a in s.actors}
        for actor in self.assets.actors:
            if actor.key not in playing:
                self.assets._draw_actor(actor)
        if self.profile.get("settings",{}).get("drawing_guides",True):
            for line in s.strokes:
                if len(line)>1:
                    pygame.draw.lines(self.frame,(*BLUE,95),False,[self._point(p) for p in line],2)
        if len(s.preview)>1:
            pygame.draw.lines(self.frame,(*MINT,220),False,[self._point(p) for p in s.preview],3)
        for actor in s.actors:
            visual=self._visual[actor.key]
            point=self._point(actor.pos)
            if actor.state=="home":
                self.frame.blit(visual.image,visual.home)
                self.frame.blit(visual.label,visual.home+visual.label_offset)
            else:
                moving=actor.state=="moving"
                bob=round(math.sin(s.total_time*10+actor.home[0]) * 1.5) if moving and not self.profile.get("settings",{}).get("reduced_motion") else 0
                self.frame.blit(visual.image,visual.image.get_rect(center=(point[0],point[1]+bob)))
        sc=self.scale
        rect=pygame.Rect(self.work.right-round(382*sc),self.work.top+round(18*sc),round(364*sc),round(283*sc))
        self._drawing_ui_rect=rect.inflate(12,12)
        self._panel(rect,accent=BLUE)
        x,y=rect.x+round(16*sc),rect.y+round(16*sc)
        self._text("画画模式"+(" · 已暂停" if self.drawing_paused else ""),(x,y),BLUE,22)
        y+=round(37*sc)
        self._wrap("Ctrl + 按住左键画线，松开后排列。",x,y,rect.w-round(32*sc),WHITE,12,2)
        y+=round(35*sc)
        arrived=sum(math.dist(a.pos,a.target)<2 for a in s.actors)
        self._text(f"{len(s.strokes)} 笔画  ·  {arrived}/{len(s.actors)} 图标已就位",(x,y),DIM,12)
        y+=round(31*sc)
        for i,(title,shape) in enumerate((("爱心","heart"),("星形","star"),("圆形","circle"))):
            self._button(pygame.Rect(x+round(i*112*sc),y,round(104*sc),round(32*sc)),title,"preset:"+shape,accent=BLUE)
        y+=round(43*sc)
        for i,(title,action) in enumerate((("撤销","draw:undo"),("回原位","draw:reset"),("辅助线","setting:drawing_guides"))):
            self._button(pygame.Rect(x+round(i*112*sc),y,round(104*sc),round(32*sc)),title,action)
        y+=round(43*sc)
        for i,(title,action) in enumerate((("继续" if self.drawing_paused else "暂停","draw:pause"),("主菜单","menu"),("退出 F5","quit"))):
            self._button(pygame.Rect(x+round(i*112*sc),y,round(104*sc),round(32*sc)),title,action)
        self._text("图案越大，图标之间的间距越舒展。",(x,rect.bottom-round(24*sc)),DIM,11)
