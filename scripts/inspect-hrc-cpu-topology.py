"""Read-only Windows CPU-set/core/cache topology. Never sets scheduling policy."""
from __future__ import annotations

import argparse
import collections
import ctypes as c
from ctypes import wintypes as w
import datetime
import json
import os
from pathlib import Path
import re
import struct
import subprocess

ROOT=Path(__file__).resolve().parents[1]

def inspect(pid=None):
    if os.name!='nt' or c.sizeof(c.c_void_p)!=8:
        raise RuntimeError('This reader requires 64-bit Windows')
    k=c.WinDLL('kernel32',use_last_error=True)
    k.GetCurrentProcess.restype=w.HANDLE
    k.OpenProcess.argtypes=[w.DWORD,w.BOOL,w.DWORD];k.OpenProcess.restype=w.HANDLE
    k.CloseHandle.argtypes=[w.HANDLE];k.CloseHandle.restype=w.BOOL
    k.GetSystemCpuSetInformation.argtypes=[c.c_void_p,w.ULONG,c.POINTER(w.ULONG),w.HANDLE,w.ULONG]
    k.GetSystemCpuSetInformation.restype=w.BOOL
    k.GetLogicalProcessorInformationEx.argtypes=[c.c_int,c.c_void_p,c.POINTER(w.DWORD)]
    k.GetLogicalProcessorInformationEx.restype=w.BOOL
    k.GetProcessAffinityMask.argtypes=[w.HANDLE,c.POINTER(c.c_size_t),c.POINTER(c.c_size_t)]
    k.GetProcessAffinityMask.restype=w.BOOL
    k.GetPriorityClass.argtypes=[w.HANDLE];k.GetPriorityClass.restype=w.DWORD
    k.GetProcessDefaultCpuSets.argtypes=[w.HANDLE,c.POINTER(w.ULONG),w.ULONG,c.POINTER(w.ULONG)]
    k.GetProcessDefaultCpuSets.restype=w.BOOL
    handle=k.GetCurrentProcess() if pid is None else k.OpenProcess(0x1400,False,pid)
    if not handle:raise c.WinError(c.get_last_error())
    try:
        length=w.ULONG()
        ok=k.GetSystemCpuSetInformation(None,0,c.byref(length),handle,0)
        if not ok and c.get_last_error()!=122:raise c.WinError(c.get_last_error())
        buffer=c.create_string_buffer(length.value)
        if not k.GetSystemCpuSetInformation(buffer,len(buffer),c.byref(length),handle,0):raise c.WinError(c.get_last_error())
        raw=buffer.raw[:length.value];sets=[];offset=0
        while offset<len(raw):
            size,kind=struct.unpack_from('<II',raw,offset)
            if size<8 or offset+size>len(raw):raise RuntimeError('Invalid CPU-set record')
            if kind==0:
                if size<32:raise RuntimeError('Truncated CPU-set record')
                ident,group,logical,core,llc,numa,eff,flags=struct.unpack_from('<IHBBBBBB',raw,offset+8)
                sets.append(dict(id=ident,group=group,logical_processor=logical,core_index=core,last_level_cache_index=llc,numa_node=numa,efficiency_class=eff,scheduling_class=raw[offset+20],parked=bool(flags&1),allocated=bool(flags&2),allocated_to_target_process=bool(flags&4),realtime=bool(flags&8),record_bytes=size))
            offset+=size
        length2=w.DWORD()
        ok=k.GetLogicalProcessorInformationEx(0xffff,None,c.byref(length2))
        if not ok and c.get_last_error()!=122:raise c.WinError(c.get_last_error())
        buffer2=c.create_string_buffer(length2.value)
        if not k.GetLogicalProcessorInformationEx(0xffff,buffer2,c.byref(length2)):raise c.WinError(c.get_last_error())
        raw2=buffer2.raw[:length2.value];cores=[];caches=[];offset=0
        def masks(start,count):
            result=[]
            for j in range(count):
                mask,group=struct.unpack_from('<QH',raw2,start+16*j)
                result.append(dict(group=group,mask_hex=hex(mask),logical_processors=[i for i in range(64)if mask&(1<<i)]))
            return result
        while offset<len(raw2):
            relation,size=struct.unpack_from('<II',raw2,offset)
            if size<8 or offset+size>len(raw2):raise RuntimeError('Invalid topology record')
            if relation==0:
                flags,eff=struct.unpack_from('<BB',raw2,offset+8)
                groups=struct.unpack_from('<H',raw2,offset+30)[0]
                cores.append(dict(smt=bool(flags&1),efficiency_class=eff,groups=masks(offset+32,groups)))
            elif relation==2:
                level,assoc,line_bytes,bytes_,kind=struct.unpack_from('<BBHII',raw2,offset+8)
                groups=struct.unpack_from('<H',raw2,offset+38)[0] or 1
                caches.append(dict(level=level,associativity=assoc,line_bytes=line_bytes,bytes=bytes_,kind=kind,groups=masks(offset+40,groups)))
            offset+=size
        cpu_cores=collections.defaultdict(list)
        for row in sets:cpu_cores[(row['group'],row['core_index'])].append(row['logical_processor'])
        observed={tuple((g['group'],tuple(g['logical_processors']))for g in x['groups'])for x in cores}
        expected={((g,tuple(sorted(cpus))),)for(g,_),cpus in cpu_cores.items()}
        if observed!=expected:raise RuntimeError('Independent core API and CPU-set mappings differ')
        for core in cores:
            for group in core['groups']:
                for logical in group['logical_processors']:
                    match=next(x for x in sets if x['group']==group['group'] and x['logical_processor']==logical)
                    if match['efficiency_class']!=core['efficiency_class']:raise RuntimeError('Efficiency class APIs disagree')
        ownmask=c.c_size_t();systemmask=c.c_size_t()
        affinity_ok=k.GetProcessAffinityMask(handle,c.byref(ownmask),c.byref(systemmask))
        default_count=w.ULONG()
        ok=k.GetProcessDefaultCpuSets(handle,None,0,c.byref(default_count))
        if not ok and c.get_last_error()!=122:raise c.WinError(c.get_last_error())
        default_sets=(w.ULONG*default_count.value)()
        if default_count.value and not k.GetProcessDefaultCpuSets(handle,default_sets,default_count.value,c.byref(default_count)):raise c.WinError(c.get_last_error())
        efficiencies=collections.defaultdict(lambda:dict(logical_processors=[],physical_cores=[]))
        for row in sets:
            item=efficiencies[row['efficiency_class']];item['logical_processors'].append(row['logical_processor'])
            key=[row['group'],row['core_index']]
            if key not in item['physical_cores']:item['physical_cores'].append(key)
        return dict(captured_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),inspected_process_pid=pid or os.getpid(),process_is_inspector=pid is None,cpu_sets=sets,cores=cores,caches=caches,core_count=len(cores),logical_processor_count=len(sets),efficiency_classes=dict(efficiencies),numa_nodes=sorted(set((x['group'],x['numa_node'])for x in sets)),core_mapping_crosscheck=True,process_default_cpu_sets=list(default_sets),process_affinity_mask_hex=hex(ownmask.value)if affinity_ok else None,system_affinity_mask_hex=hex(systemmask.value)if affinity_ok else None,process_priority_class=int(k.GetPriorityClass(handle)),read_only=True,thread_residency_observed=False,interpretation='Higher EfficiencyClass denotes intrinsically higher performance/lower efficiency; actual past solver thread residency is unknown.')
    finally:
        if pid is not None:k.CloseHandle(handle)

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--pid',type=int);parser.add_argument('--output',type=Path,default=ROOT/'reports/hrc-cpu-topology-20261108.json');args=parser.parse_args()
    result=inspect(args.pid)
    script="[pscustomobject]@{ processors=@(Get-CimInstance Win32_Processor | Select-Object Name,Manufacturer,NumberOfCores,NumberOfLogicalProcessors,MaxClockSpeed); os=(Get-CimInstance Win32_OperatingSystem | Select-Object Version,BuildNumber) } | ConvertTo-Json -Depth 4"
    shell=subprocess.run(['powershell','-NoProfile','-Command',script],check=True,capture_output=True,text=True,encoding='utf-8',errors='replace')
    result['system']=json.loads(shell.stdout)
    power=subprocess.run(['powercfg','/getactivescheme'],check=True,capture_output=True)
    guid=re.search(rb'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',power.stdout).group().decode('ascii').lower()
    result['active_power_scheme']={'guid':guid,'known_windows_scheme':'High performance' if guid=='8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c' else None}
    result['sources']=['https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-system_cpu_set_information','https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-processor_relationship','https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-cache_relationship','https://www.intel.com/content/www/us/en/products/sku/230494/intel-core-i513600kf-processor-24m-cache-up-to-5-10-ghz/specifications.html']
    args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n',encoding='utf-8')
    print(json.dumps({k:result[k]for k in ('core_count','logical_processor_count','efficiency_classes','numa_nodes','process_affinity_mask_hex','process_default_cpu_sets','active_power_scheme')}))

if __name__=='__main__':main()
