"""Read-only MSAA enumeration of the third-party desktop window."""
import ctypes as C
from ctypes import wintypes as W
import json
from pathlib import Path
import sys
C.windll.user32.SetProcessDpiAwarenessContext(C.c_void_p(-4))
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from desktop_world.shell_native import GUID, _method
import pythoncom
import win32com.client

root_report=json.loads((ROOT/"artifacts/icon-sources.json").read_text(encoding="utf-8"))
targets=[r for r in root_report["all_windows"] if r.get("visible") and "desktoplite" in r.get("process", "").lower()]
oleacc=C.WinDLL("oleacc")
accessible=oleacc.AccessibleObjectFromWindow
accessible.argtypes=[W.HWND,W.DWORD,C.POINTER(GUID),C.POINTER(W.LPVOID)]
accessible.restype=C.c_long
rows=[]
for target in targets:
 for object_id in (0xFFFFFFFC,0):
  row={"hwnd":target["hwnd"],"class":target["class"],"object_id":object_id}
  pointer=W.LPVOID()
  hr=accessible(target["hwnd"],object_id,C.byref(GUID.parse("618736e0-3c3d-11cf-810c-00aa00389b71")),C.byref(pointer))
  row["hresult"]=f"0x{hr & 0xffffffff:08x}"
  if hr>=0 and pointer:
   try:
    unknown=pythoncom.ObjectFromAddress(pointer.value,pythoncom.IID_IDispatch)
    obj=win32com.client.Dispatch(unknown)
    row["child_count"]=obj.accChildCount
    def value(key,child):
     try:
      if key=="accLocation":
       return obj._oleobj_.InvokeTypes(-5015,0,1,(24,0),((16387,2),(16387,2),(16387,2),(16387,2),(12,1)),child)
      return obj._oleobj_.Invoke(obj._oleobj_.GetIDsOfNames(key),0,2,True,child)
     except Exception as exc:return {"error":str(exc)}
    row["self"]={k:value(k,0) for k in ("accName","accRole","accState","accLocation","accValue","accDescription")}
    row["children"]=[{"child_id":i,**{k:value(k,i) for k in ("accName","accRole","accState","accLocation","accValue","accDescription")}} for i in range(1,min(int(obj.accChildCount),200)+1)]
   except Exception as exc:
    row["error"]=repr(exc)
   finally:
    _method(pointer,2,W.ULONG)(pointer)
  rows.append(row)
out=ROOT/"artifacts/desktop-accessibility.json"
out.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding="utf-8")
print(json.dumps(rows,ensure_ascii=False,indent=2))
