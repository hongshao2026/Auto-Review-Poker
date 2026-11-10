"""Short read-only CPU delta snapshot; records names, never command lines."""
import argparse
import ctypes as c
from ctypes import wintypes as w
import datetime
import importlib.util
import json
import os
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--seconds',type=float,default=2);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    if not .5<=args.seconds<=5:raise ValueError('Snapshot duration requires 0.5..5 seconds')
    k=c.WinDLL('kernel32',use_last_error=True);p=c.WinDLL('psapi',use_last_error=True)
    p.EnumProcesses.argtypes=[c.POINTER(w.DWORD),w.DWORD,c.POINTER(w.DWORD)];p.EnumProcesses.restype=w.BOOL
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    k.GetProcessTimes.argtypes=[w.HANDLE,*([c.POINTER(w.FILETIME)]*4)];k.GetProcessTimes.restype=w.BOOL
    k.QueryFullProcessImageNameW.argtypes=[w.HANDLE,w.DWORD,w.LPWSTR,c.POINTER(w.DWORD)];k.QueryFullProcessImageNameW.restype=w.BOOL
    k.GetSystemTimes.argtypes=[c.POINTER(w.FILETIME)]*3;k.GetSystemTimes.restype=w.BOOL
    def seconds(t):return ((int(t.dwHighDateTime)<<32)|int(t.dwLowDateTime))/1e7
    def proc_times(h):
        v=[w.FILETIME()for _ in range(4)]
        return (seconds(v[0])-11644473600,seconds(v[2])+seconds(v[3]))if k.GetProcessTimes(h,*map(c.byref,v))else None
    def total():
        v=[w.FILETIME()for _ in range(3)]
        if not k.GetSystemTimes(*map(c.byref,v)):raise c.WinError(c.get_last_error())
        return list(map(seconds,v))
    def enumerate_pids():
        a=(w.DWORD*32768)();n=w.DWORD()
        if not p.EnumProcesses(a,c.sizeof(a),c.byref(n)):raise c.WinError(c.get_last_error())
        return a[:n.value//4]
    observed={};window_start=time.time()
    def discover(initial=False):
        for pid in enumerate_pids():
            if pid in observed:continue
            h=k.OpenProcess(0x1000,False,pid)
            if not h:continue
            data=proc_times(h)
            if data is None:k.CloseHandle(h);continue
            buf=c.create_unicode_buffer(32768);n=w.DWORD(len(buf));ok=k.QueryFullProcessImageNameW(h,0,buf,c.byref(n))
            name=Path(buf.value).name if ok else '<unavailable>'
            baseline=data[1] if initial or data[0]<window_start else 0.
            observed[pid]=dict(handle=h,name=name,start_cpu=baseline,created_unix=data[0],new_during_window=not initial and data[0]>=window_start)
    discover(True);window_start=time.time();sys0=total();t0=time.perf_counter()
    for _ in range(4):time.sleep(args.seconds/4);discover()
    rows=[]
    for pid,entry in observed.items():
        data=proc_times(entry['handle'])
        if data:
            rows.append(dict(pid=pid,name=entry['name'],cpu_seconds=max(0,data[1]-entry['start_cpu']),new_during_window=entry['new_during_window']))
        k.CloseHandle(entry['handle'])
    elapsed=time.perf_counter()-t0;sys1=total();d=[b-a for a,b in zip(sys0,sys1)]
    for row in rows:row['average_logical_cpus']=row['cpu_seconds']/elapsed
    rows.sort(key=lambda x:x['cpu_seconds'],reverse=True)
    solver_topology=[]
    spec=importlib.util.spec_from_file_location('cpu_topology',ROOT/'scripts/inspect-hrc-cpu-topology.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for row in rows:
        if row['name'].startswith('hrc_research_solver'):
            try:
                x=module.inspect(row['pid']);solver_topology.append({key:x[key]for key in ['inspected_process_pid','process_affinity_mask_hex','process_default_cpu_sets','process_priority_class','thread_residency_observed']})
            except OSError:solver_topology.append({'pid':row['pid'],'status':'exited_before_topology_read'})
    result={'started_utc':datetime.datetime.fromtimestamp(window_start,datetime.timezone.utc).isoformat(),'elapsed_seconds':elapsed,'observer_pid':os.getpid(),'system_cpu_percent':100*(d[1]+d[2]-d[0])/(d[1]+d[2]),'system_average_busy_logical_cpus':(d[1]+d[2]-d[0])/elapsed,'processes':rows[:25],'solver_topology':solver_topology,'read_only':True,'sensitive_command_lines_read':False,'new_process_poll_seconds':args.seconds/4,'limitations':['Sub-poll processes that both start and exit between enumerations can be missed.','Small measurement skew from process enumeration; this is a short observational snapshot.','Process CPU seconds count scheduled time; no actual worker core residency or effective clocks measured.','Do not attribute earlier benchmark variability from this snapshot.']}
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))

if __name__=='__main__':main()
