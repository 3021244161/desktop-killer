"""Read-only PrintWindow diagnostic, never used as gameplay sprite assets."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop_world import shell_native as n
from PIL import Image
import win32gui
report=json.loads((ROOT/"artifacts/icon-sources.json").read_text(encoding="utf-8"))
target=next(r for r in report["all_windows"] if r.get("visible") and r.get("class")=="360DirectUICls" and r.get("text")=="360DTFenceLite")
hwnd=target["hwnd"]
l,t,w,h=win32gui.GetClientRect(hwnd)
dc=n.gdi32.CreateCompatibleDC(None)
data=W.LPVOID()
bmp=n.gdi32.CreateDIBSection(dc,C.byref(n._bmi(w,h)),0,C.byref(data),None,0)
old=n.gdi32.SelectObject(dc,bmp)
try:
 fn=n._bind(n.user32,"PrintWindow",W.BOOL,[W.HWND,W.HDC,W.UINT])
 ok=fn(hwnd,dc,2)
 image=Image.frombytes("RGBA",(w,h),C.string_at(data,w*h*4),"raw","BGRA").convert("RGB")
 out=ROOT/"artifacts/desklite-reference.png"
 image.save(out)
 print(json.dumps({"ok":bool(ok),"size":image.size,"path":str(out)}))
finally:
 n.gdi32.SelectObject(dc,old);n.gdi32.DeleteObject(bmp);n.gdi32.DeleteDC(dc)
