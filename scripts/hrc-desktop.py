"""Explicit, logged Windows UI actions scoped to one HRC process and observed handles."""
import argparse
import ctypes
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import win32gui
import win32process
import win32ui
from PIL import Image
from pywinauto import Application
from pywinauto.keyboard import send_keys

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'analysis/hrc-desktop'
(OUT/'screens').mkdir(parents=True,exist_ok=True)
p=argparse.ArgumentParser()
p.add_argument('action',choices=['windows','inspect','capture','click','press','keys','set','combo','menu','menus','cell'])
p.add_argument('--pid',type=int,default=3088)
p.add_argument('--hwnd',type=int)
p.add_argument('--control',type=int)
p.add_argument('--x',type=int);p.add_argument('--y',type=int)
p.add_argument('--text');p.add_argument('--label',default='capture')
p.add_argument('--double',action='store_true')
a=p.parse_args()
app=Application(backend='win32').connect(process=a.pid)

def scoped(handle):
    if win32process.GetWindowThreadProcessId(handle)[1]!=a.pid: raise RuntimeError('Handle does not belong to selected HRC process')
    return app.window(handle=handle).wrapper_object()

def record(result):
    row={'utc':datetime.now(timezone.utc).isoformat(),'request':vars(a),'result':result}
    with (OUT/'actions.jsonl').open('a',encoding='utf-8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))

def focus(window):
    window.set_focus()
    time.sleep(.12)
    foreground=win32gui.GetForegroundWindow()
    if win32process.GetWindowThreadProcessId(foreground)[1]!=a.pid: raise RuntimeError('HRC lost foreground; no input sent')

def info(window):
    r=window.rectangle()
    return {'handle':window.handle,'class':window.class_name(),'title':window.window_text(),'rect':[r.left,r.top,r.right,r.bottom], 'enabled':window.is_enabled()}

if a.action=='windows':
    record([info(w) for w in app.windows(visible_only=True)])
    raise SystemExit()
if a.hwnd is None: raise RuntimeError('Select an observed HRC window handle')
w=scoped(a.hwnd)
if a.action=='inspect':
    rows=[info(c) for c in w.descendants() if c.is_visible()]
    path=OUT/f'{a.label}-controls.json'
    path.write_text(json.dumps(rows,ensure_ascii=False,indent=2),encoding='utf-8')
    record({'window':info(w),'controls':rows})
elif a.action=='capture':
    # PrintWindow captures the selected window, including when an unrelated app overlaps it.
    rect=w.rectangle(); width,height=rect.width(),rect.height()
    source=win32gui.GetWindowDC(w.handle)
    source_dc=win32ui.CreateDCFromHandle(source); memory_dc=source_dc.CreateCompatibleDC()
    bitmap=win32ui.CreateBitmap();bitmap.CreateCompatibleBitmap(source_dc,width,height)
    memory_dc.SelectObject(bitmap)
    ok=ctypes.windll.user32.PrintWindow(w.handle,memory_dc.GetSafeHdc(),2)
    if not ok: raise RuntimeError('PrintWindow failed; no whole-desktop capture fallback')
    im=Image.frombuffer('RGB',(width,height),bitmap.GetBitmapBits(True),'raw','BGRX',0,1)
    path=OUT/'screens'/f'{a.label}.png';im.save(path)
    win32gui.DeleteObject(bitmap.GetHandle());memory_dc.DeleteDC();source_dc.DeleteDC();win32gui.ReleaseDC(w.handle,source)
    record({'window':info(w),'path':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
elif a.action=='menus':record(w.menu().get_properties())
elif a.action=='menu':
    focus(w);w.menu_select(a.text);record({'selected':a.text})
else:
    target=scoped(a.control) if a.control else w
    if not target.is_visible() or not target.is_enabled():raise RuntimeError('Target is hidden or disabled')
    if a.action=='set':
        if target.class_name()!='Edit':raise RuntimeError('Text setter requires an observed Edit control')
        target.set_edit_text(a.text);record({'target':info(target)})
    elif a.action=='combo':
        target.select(a.text);record({'target':info(target)})
    elif a.action=='keys':
        focus(w);send_keys(a.text,pause=.06,with_spaces=True);record({'keys':a.text})
    elif a.action=='cell':
        focus(w)
        rect=w.rectangle();sx,sy=rect.left+a.x,rect.top+a.y
        if not (0<=a.x<rect.width() and 0<=a.y<rect.height()):raise RuntimeError('Cell outside window')
        w.click_input(coords=(a.x,a.y),double=True)
        time.sleep(.08)
        edits=[c for c in w.descendants(class_name='Edit') if c.is_visible() and c.rectangle().left<=sx<c.rectangle().right and c.rectangle().top<=sy<c.rectangle().bottom]
        if len(edits)!=1:raise RuntimeError(f'Expected one visible cell editor, found {len(edits)}; no text entered')
        before=info(edits[0]);edits[0].set_edit_text(a.text)
        if win32process.GetWindowThreadProcessId(win32gui.GetForegroundWindow())[1]!=a.pid:raise RuntimeError('HRC lost foreground before commit')
        send_keys('{ENTER}');record({'cell':[a.x,a.y],'editor_before':before,'value':a.text})
    elif a.action=='click':
        focus(w)
        coords=(None,None)
        if a.x is not None:
            rect=target.rectangle()
            if not (0<=a.x<rect.width() and 0<=a.y<rect.height()):raise RuntimeError('Click outside selected window')
            coords=(a.x,a.y)
        before=info(target)
        target.click_input(coords=coords,double=a.double);record({'target_before':before,'coords':coords,'double':a.double})
    elif a.action=='press':
        if target.class_name()!='Button':raise RuntimeError('Press requires an observed native Button control')
        before=info(target)
        win32gui.PostMessage(target.handle,0x00F5,0,0)  # BM_CLICK; process-scoped native button only.
        record({'button_before':before,'method':'BM_CLICK'})
