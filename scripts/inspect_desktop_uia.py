"""Read-only UI Automation probe of the 360 desktop provider."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop_world.shell_native import GUID,_method,_bind
import pythoncom

def check(hr, label):
 if hr<0:raise OSError(f"{label}: 0x{hr&0xffffffff:08x}")
def release(p):
 if p:_method(p,2,W.ULONG)(p)
ole=C.WinDLL("ole32")
create=_bind(ole,"CoCreateInstance",C.c_long,[C.POINTER(GUID),W.LPVOID,W.DWORD,C.POINTER(GUID),C.POINTER(W.LPVOID)])
auto=C.WinDLL("oleaut32")
free=_bind(auto,"SysFreeString",None,[W.LPVOID])
def name(p):
 s=W.LPVOID();check(_method(p,23,C.c_long,C.POINTER(W.LPVOID))(p,C.byref(s)),"name")
 try:return C.wstring_at(s) if s else ""
 finally:free(s)

uia=W.LPVOID();condition=W.LPVOID()
rows=[]
try:
 check(create(C.byref(GUID.parse("ff48dba4-60ef-4201-aa87-54103eef594e")),None,1,
              C.byref(GUID.parse("30cbe57d-d9d0-452a-ab13-7ac5ac4825ee")),C.byref(uia)),"create UIA")
 check(_method(uia,21,C.c_long,C.POINTER(W.LPVOID))(uia,C.byref(condition)),"true condition")
 report=json.loads((ROOT/"artifacts/icon-sources.json").read_text(encoding="utf-8"))
 targets=[r for r in report["all_windows"] if r.get("visible") and "desktoplite" in r.get("process", "").lower()]
 for target in targets:
  root=W.LPVOID();items=W.LPVOID();row={"hwnd":target["hwnd"]}
  try:
   check(_method(uia,6,C.c_long,W.HWND,C.POINTER(W.LPVOID))(uia,target["hwnd"],C.byref(root)),"ElementFromHandle")
   row["name"]=name(root)
   check(_method(root,6,C.c_long,C.c_int,W.LPVOID,C.POINTER(W.LPVOID))(root,4,condition,C.byref(items)),"FindAll descendants")
   n=C.c_int();check(_method(items,3,C.c_long,C.POINTER(C.c_int))(items,C.byref(n)),"length")
   row["descendant_count"]=n.value;row["descendants"]=[]
   for i in range(min(n.value,300)):
    item=W.LPVOID()
    try:
     check(_method(items,4,C.c_long,C.c_int,C.POINTER(W.LPVOID))(items,i,C.byref(item)),"GetElement")
     row["descendants"].append(name(item))
    finally:release(item)
  except Exception as exc:row["error"]=repr(exc)
  finally:release(items);release(root)
  rows.append(row)
finally:release(condition);release(uia)
(ROOT/"artifacts/desktop-uia.json").write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(rows,ensure_ascii=False,indent=2))
