"""One explicitly selected HRC GUI run with nonblocking scoped Win32 polling.

Requires the independently audited mr-constructor observation hook installed
before the timed interval. No JDK attach, GC, pywinauto, or compilation occurs
during sampling. Screen frames are captured only while the selected HRC owns
the foreground, and only from its visible progress-dialog rectangle.
"""
from __future__ import annotations
import argparse,json,time,ctypes
from datetime import datetime,timezone
from pathlib import Path
import win32api,win32con,win32gui,win32process
from PIL import ImageGrab

# Keep screen pixels and Win32 window rectangles in the same DPI coordinate space.
ctypes.windll.user32.SetProcessDPIAware()

p=argparse.ArgumentParser()
p.add_argument('--pid',required=True,type=int);p.add_argument('--main',required=True,type=int)
p.add_argument('--ok',required=True,type=int);p.add_argument('--output',required=True)
p.add_argument('--seconds',default=3600,type=float)
a=p.parse_args();out=Path(a.output).resolve();out.mkdir(parents=True,exist_ok=True)
log=out/'win32-observations.jsonl';result=out/'observation-result.json'
assert not log.exists(), 'Use a new output directory; preserve previous evidence'
assert win32process.GetWindowThreadProcessId(a.ok)[1]==a.pid
assert win32gui.GetWindowText(a.ok)=='OK' and win32gui.IsWindowEnabled(a.ok)
proc=win32api.OpenProcess(win32con.PROCESS_QUERY_INFORMATION|win32con.PROCESS_VM_READ,False,a.pid)

def read():
    roots=[];rows=[]
    def root(h,_):
        if win32process.GetWindowThreadProcessId(h)[1]==a.pid and win32gui.IsWindowVisible(h):roots.append(h)
    win32gui.EnumWindows(root,None)
    for h in roots:
        rows.append({'hwnd':h,'class':win32gui.GetClassName(h),'text':win32gui.GetWindowText(h),'root':True,
                     'rect':list(win32gui.GetWindowRect(h)),'enabled':bool(win32gui.IsWindowEnabled(h))})
        def child(c,_):
            if win32gui.IsWindowVisible(c):
                text=win32gui.GetWindowText(c)
                if text:rows.append({'hwnd':c,'class':win32gui.GetClassName(c),'text':text,'root':False})
        win32gui.EnumChildWindows(h,child,None)
    times=win32process.GetProcessTimes(proc)
    return {'utc':datetime.now(timezone.utc).isoformat(),'epoch_millis':time.time_ns()//1000000,
            'elapsed_seconds':time.perf_counter()-start,'rows':rows,
            'process_cpu_seconds':(times['KernelTime']+times['UserTime'])/1e7,
            'process_memory':win32process.GetProcessMemoryInfo(proc)}

def emit(row):
    with log.open('a',encoding='utf8') as f:f.write(json.dumps(row,ensure_ascii=False)+'\n')

def ci_rows():
    path=out/'original-ci.jsonl'
    if not path.exists():return []
    values=[]
    for line in path.read_text(encoding='utf8').splitlines():
        try:row=json.loads(line)
        except json.JSONDecodeError:continue
        if row['original_epoch_millis']>=start_epoch:values.append(row)
    return values

start=time.perf_counter();start_epoch=time.time_ns()//1000000
before=read();emit({'event':'before_ok',**before})
win32gui.PostMessage(a.ok,win32con.BM_CLICK,0,0)
emit({'event':'ok_posted','elapsed_seconds':time.perf_counter()-start,'epoch_millis':time.time_ns()//1000000})
seen=False;idle=0;cancelled=False;frames=0;terminal_frame=False;last_print=-15;reason='observer_wall_bound'
while time.perf_counter()-start<a.seconds+20:
    row=read();emit(row)
    active=[x for x in row['rows'] if 'MC-CFR' in x['text'] or ': Monte Carlo Sampling' in x['text'] or x['text']=='Sampling...']
    seen|=bool(active)
    no_operations=any('No operations to display' in x['text'] for x in row['rows'])
    idle=idle+1 if seen and not active and no_operations else 0
    records=ci_rows();last_ci=records[-1]['ci'] if records else None
    if row['elapsed_seconds']-last_print>=15:
        print(json.dumps({'elapsed_seconds':row['elapsed_seconds'],'ci':last_ci,
          'ci_samples':records[-1]['original_samples'] if records else None,
          'active':bool(active),'visible_text':[x['text'] for x in row['rows'] if 'CI' in x['text'] or 'h/s' in x['text']]}),flush=True)
        last_print=row['elapsed_seconds']
    dialogs=[x for x in row['rows'] if x['root'] and ': Monte Carlo Sampling' in x['text']]
    if dialogs and (frames==0 or (last_ci is not None and last_ci<10 and not terminal_frame)):
        fg=win32gui.GetForegroundWindow()
        if fg and win32process.GetWindowThreadProcessId(fg)[1]==a.pid:
            filename=f'progress-{row["elapsed_seconds"]:09.3f}.png'
            ImageGrab.grab(bbox=tuple(dialogs[0]['rect']),all_screens=True).save(out/filename)
            emit({'event':'visible_progress_frame','elapsed_seconds':row['elapsed_seconds'],'file':filename,'rect':dialogs[0]['rect'],'foreground_hwnd':fg})
            frames+=1
            terminal_frame=last_ci is not None and last_ci<10
    if idle>=2:
        reason='observed_idle_with_ci_below_target' if last_ci is not None and last_ci<10 else 'observed_idle_without_verified_target'
        break
    if row['elapsed_seconds']>=a.seconds and not cancelled:
        buttons=[x['hwnd'] for x in row['rows'] if x['class']=='Button' and x['text']=='Cancel']
        if len(buttons)==1:
            win32gui.PostMessage(buttons[0],win32con.BM_CLICK,0,0);cancelled=True
            emit({'event':'declared_wall_bound_cancel_posted','hwnd':buttons[0],'elapsed_seconds':row['elapsed_seconds']})
        else:reason='wall_bound_cancel_unresolved';break
    time.sleep(1)
records=ci_rows()
summary={'reason':reason,'pid':a.pid,'start_epoch_millis':start_epoch,'start_utc':before['utc'],
         'observer_elapsed_seconds':time.perf_counter()-start,'last_observation':row,
         'before':before,'ci_records':records,'cancel_sent':cancelled,
         'ci_target_reached':bool(records and records[-1]['ci'] is not None and records[-1]['ci']<10),
         'numeric_ci_source':'original mr.<init>(IJJD)V argument observation; not independently recomputed',
         'native_solver_elapsed_seconds':None,
         'process_cpu_seconds_delta':row['process_cpu_seconds']-before['process_cpu_seconds']}
result.write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf8')
emit({'event':'observer_finished','reason':reason,'elapsed_seconds':summary['observer_elapsed_seconds']})
print(json.dumps({'reason':reason,'elapsed_seconds':summary['observer_elapsed_seconds'],
                  'ci':records[-1]['ci'] if records else None,'report':str(result)}),flush=True)
