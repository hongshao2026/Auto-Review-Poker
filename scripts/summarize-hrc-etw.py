"""Stream local tracerpt XML; emit only the explicitly recorded solver process.

Kernel event field offsets follow Microsoft's TraceEvent parser. Version-five
CSwitch keeps the version-two prefix; consistency/CPU-time checks are reported.
This is a diagnostic, never a replacement for unprofiled CI10 timing.
"""
import bisect
import argparse
from collections import Counter, defaultdict
import ctypes as c
from ctypes import wintypes as w
import hashlib
import json
from pathlib import Path
import struct
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT/'.research-cache/architecture-review-20261108/etw-cpu'
NS = {'e': 'http://schemas.microsoft.com/win/2004/08/events/event',
      't': 'http://schemas.microsoft.com/win/2004/08/events/trace'}
E = '{'+NS['e']+'}'


def number(value):
    return int(value.strip(), 16 if value.strip().lower().startswith('0x') else 10)


def tick(value):
    # All timestamps in this short trace share a date and offset. Keep 100ns
    # precision without tracerpt's unusual printed timezone or float epochs.
    clock = value[11:27]
    return (int(clock[:2])*3600+int(clock[3:5])*60+int(clock[6:8]))*10_000_000+int(clock[9:].ljust(7, '0'))


class Symbols:
    class Info(c.Structure):
        _fields_ = [('SizeOfStruct', w.ULONG), ('TypeIndex', w.ULONG),
                    ('Reserved', c.c_ulonglong*2), ('Index', w.ULONG),
                    ('Size', w.ULONG), ('ModBase', c.c_ulonglong),
                    ('Flags', w.ULONG), ('Value', c.c_ulonglong),
                    ('Address', c.c_ulonglong), ('Register', w.ULONG),
                    ('Scope', w.ULONG), ('Tag', w.ULONG),
                    ('NameLen', w.ULONG), ('MaxNameLen', w.ULONG), ('Name', c.c_char*1)]

    class Line(c.Structure):
        _fields_ = [('SizeOfStruct', w.DWORD), ('Key', c.c_void_p),
                    ('LineNumber', w.DWORD), ('FileName', c.c_char_p), ('Address', c.c_ulonglong)]

    def __init__(self, images, search_path=None):
        self.dll = c.WinDLL('dbghelp', use_last_error=True)
        self.handle = c.c_void_p(-1)
        d = self.dll
        d.SymSetOptions.argtypes = [w.DWORD]
        d.SymSetOptions(0x2 | 0x4 | 0x10 | 0x200 | 0x80000)
        d.SymInitializeW.argtypes = [w.HANDLE, w.LPCWSTR, w.BOOL]
        d.SymInitializeW.restype = w.BOOL
        if not d.SymInitializeW(self.handle, search_path or str(ROOT/'analysis/hrc-native/build'), False):
            raise c.WinError(c.get_last_error())
        d.SymLoadModuleExW.argtypes = [w.HANDLE, w.HANDLE, w.LPCWSTR, w.LPCWSTR,
                                      c.c_ulonglong, w.DWORD, c.c_void_p, w.DWORD]
        d.SymLoadModuleExW.restype = c.c_ulonglong
        d.SymFromAddr.argtypes = [w.HANDLE, c.c_ulonglong, c.POINTER(c.c_ulonglong), c.POINTER(self.Info)]
        d.SymFromAddr.restype = w.BOOL
        d.SymGetLineFromAddr64.argtypes = [w.HANDLE, c.c_ulonglong, c.POINTER(w.DWORD), c.POINTER(self.Line)]
        d.SymGetLineFromAddr64.restype = w.BOOL
        self.images, self.cache, self.loaded = images, {}, []
        kernel = c.WinDLL('kernel32', use_last_error=True)
        kernel.QueryDosDeviceW.argtypes = [w.LPCWSTR, w.LPWSTR, w.DWORD]
        devices = []
        for drive in ['C:', 'D:']:
            buf = c.create_unicode_buffer(4096)
            if kernel.QueryDosDeviceW(drive, buf, len(buf)):
                devices.append((buf.value, drive))
        for image in images:
            path = image['path']
            for device, drive in devices:
                if path.lower().startswith(device.lower()):
                    path = drive+path[len(device):]
                    break
            if path.startswith('\\SystemRoot\\'):
                path = 'C:\\Windows\\'+path[len('\\SystemRoot\\'):]
            if Path(path).is_file():
                loaded = d.SymLoadModuleExW(self.handle, None, path, None, image['base'], image['size'], None, 0)
                self.loaded.append(dict(name=Path(path).name, loaded=bool(loaded)))

    def resolve(self, address):
        if address in self.cache:
            return self.cache[address]
        module = next((x for x in self.images if x['base'] <= address < x['base']+x['size']), None)
        name = Path(module['path']).name if module else 'kernel_or_unmapped' if address >= 1 << 63 else 'unmapped_user'
        symbol, line = name, None
        buffer = c.create_string_buffer(c.sizeof(self.Info)+4096)
        info = c.cast(buffer, c.POINTER(self.Info))
        info.contents.SizeOfStruct = c.sizeof(self.Info)
        info.contents.MaxNameLen = 4096
        displacement = c.c_ulonglong()
        if module and self.dll.SymFromAddr(self.handle, address, c.byref(displacement), info):
            symbol = c.string_at(c.addressof(info.contents)+self.Info.Name.offset, info.contents.NameLen).decode('utf-8', 'replace')
            record = self.Line()
            record.SizeOfStruct = c.sizeof(record)
            line_displacement = w.DWORD()
            if self.dll.SymGetLineFromAddr64(self.handle, address, c.byref(line_displacement), c.byref(record)):
                line = {'file': record.FileName.decode('utf-8', 'replace'), 'line': record.LineNumber}
        result = dict(module=name, symbol=symbol, line=line)
        self.cache[address] = result
        return result


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--report',type=Path,default=ROOT/'reports/hrc-etw-cpu-diagnostic-20261108.json')
    args=parser.parse_args();OUT=args.output.resolve()
    run = json.loads((OUT/'report.json').read_text(encoding='utf-8'))
    pid = run['native']['pid']
    samples, switches, ready, stacks, images = [], [], [], [], []
    threads, headers, event_counts = {}, [], Counter()
    cached = OUT/'parsed-solver-events.json'
    def file_sha(path):
        with path.open('rb') as stream:
            return hashlib.file_digest(stream, 'sha256').hexdigest()
    source_identity = dict(parser_schema=2, etl_sha256=file_sha(OUT/'solver-cpu.etl'),
                           xml_sha256=file_sha(OUT/'events.xml'))
    parsed = json.loads(cached.read_text(encoding='utf-8')) if cached.exists() else {}
    cached_valid = parsed.get('source_identity') == source_identity
    if cached_valid:
        samples, switches, ready, stacks, images = [parsed[key] for key in ['samples', 'switches', 'ready', 'stacks', 'images']]
        threads = {int(k): v for k, v in parsed['threads'].items()}
        headers = parsed['headers']
        iterator = []
    else:
        iterator = ET.iterparse(OUT/'events.xml', events=['start', 'end'])
        _, root = next(iterator)
    for event, node in iterator:
        if event != 'end' or node.tag != E+'Event':
            continue
        system = node.find('e:System', NS)
        guid = node.findtext('t:ExtendedTracingInfo/t:EventGuid', '', NS)
        opcode = int(system.findtext('e:Opcode', '0', NS))
        version = int(system.findtext('e:Version', '0', NS))
        when = tick(system.find('e:TimeCreated', NS).get('SystemTime'))
        cpu = int(system.find('e:Execution', NS).get('ProcessorID'))
        data = {x.get('Name'): x.text for x in node.findall('e:EventData/e:Data', NS)}
        event_counts[guid+'/'+str(opcode)+'v'+str(version)] += 1
        if guid.startswith('{ce1dbfb4') and opcode == 46:
            samples.append((when, cpu, number(data['ThreadId']), number(data['InstructionPointer'])))
        elif guid.startswith('{3d6fa8d1'):
            if opcode in (1, 2, 3, 4):
                payload = node.findtext('e:ProcessingErrorData/e:EventPayload', '', NS)
                if payload:
                    raw = bytes.fromhex(payload)
                    thread_pid, tid = struct.unpack_from('<II', raw)
                elif data:
                    thread_pid = number(data.get('ProcessId', '-1'))
                    tid = number(data['TThreadId']) if 'TThreadId' in data else number(data['ThreadId'])
                else:
                    raise ValueError('Missing thread lifecycle payload')
                if thread_pid == pid:
                    row = threads.setdefault(tid, {})
                    row['start' if opcode in (1, 3) else 'end'] = when
                    if payload and opcode in (1, 3) and version >= 2 and len(raw) >= 56:
                        row['win32_start_address'] = struct.unpack_from('<Q', raw, 48)[0]
            elif opcode == 36:
                raw = bytes.fromhex(node.findtext('e:BinaryEventData', '', NS))
                if raw:
                    if version < 2 or len(raw) < 24:
                        raise ValueError('Unsupported CSwitch prefix')
                    new, old = struct.unpack_from('<II', raw)
                    reason, state = raw[12], raw[14]
                    switches.append((when, cpu, new, old, state, reason))
            elif opcode == 50 and 'TThreadId' in data:
                ready.append((when, number(data['TThreadId']), number(data.get('Flag', '0'))))
        elif guid.startswith('{2cb15d1d') and data and number(data.get('ProcessId', '-1')) == pid:
            if opcode in (10, 3, 4):
                image = dict(base=number(data['ImageBase']), size=number(data['ImageSize']), path=data['FileName'])
                if not any(x['base'] == image['base'] for x in images):
                    images.append(image)
        elif guid.startswith('{def2fe46') and opcode == 32:
            payload = node.findtext('e:ProcessingErrorData/e:EventPayload', '', NS)
            if payload:
                raw = bytes.fromhex(payload)
                if len(raw) >= 16 and struct.unpack_from('<I', raw, 8)[0] == pid:
                    if (len(raw)-16) % 8:
                        raise ValueError('Unexpected x64 StackWalk size')
                    qpc, _, tid = struct.unpack_from('<QII', raw)
                    frames = struct.unpack_from('<'+'Q'*((len(raw)-16)//8), raw, 16)
                    stacks.append((when, qpc, tid, frames))
        elif guid.startswith('{68fdd900') and opcode == 0:
            headers.append(data)
        root.clear()
    if not cached_valid:
        cached.write_text(json.dumps(dict(samples=samples, switches=switches, ready=ready, stacks=stacks,
                                         images=images, threads=threads, headers=headers,
                                         source_identity=source_identity)), encoding='utf-8')
    if len(threads) < 20:
        raise ValueError('Expected at least main+19 worker threads: '+repr(threads))
    if not headers or any(number(x['PerfFreq']) != 10_000_000 for x in headers):
        raise ValueError('Clock-offset calibration requires 10MHz QPC')
    all_threads = threads
    tids_by_start = sorted(threads, key=lambda tid: threads[tid].get('start', 0))
    main_tid, workers = tids_by_start[0], tids_by_start[-19:]
    if max(threads[tid]['start'] for tid in workers)-min(threads[tid]['start'] for tid in workers) > 1_000_000:
        raise ValueError('Persistent worker creation is not a distinct short cluster')
    if len({threads[tid].get('win32_start_address') for tid in workers}) != 1:
        raise ValueError('Persistent workers do not share a thread start address')
    threads = {tid: all_threads[tid] for tid in [main_tid, *workers]}
    excluded_threads = {tid: row for tid, row in all_threads.items() if tid not in threads}
    own_samples = [x for x in samples if x[2] in threads]
    samples_by_key = defaultdict(list)
    for when, cpu, tid, ip in own_samples:
        samples_by_key[tid, ip].append(when)
    for values in samples_by_key.values():
        values.sort()
    offsets = Counter()
    for when, qpc, tid, frames in stacks:
        if not frames:
            continue
        values = samples_by_key.get((tid, frames[0]), [])
        at = bisect.bisect_right(values, when)
        for i in range(max(0, at-3), at):
            if when-values[i] <= 100_000:
                offsets[values[i]-qpc] += 1
    if not offsets:
        raise ValueError('No exact sampled IP/StackWalk clock calibration')
    offset, votes = offsets.most_common(1)[0]
    stack_at = defaultdict(list)
    for when, qpc, tid, frames in stacks:
        stack_at[qpc+offset, tid].extend(frames)
    # Every worker exists throughout this interior interval. It excludes loading
    # and most shutdown work. Main thread plus the 19 persistent worker threads.
    low = max(threads[tid]['start'] for tid in workers)
    high = min(threads[tid]['end'] for tid in workers)
    if high <= low:
        raise ValueError('No shared 20-worker lifetime')
    switches.sort(key=lambda x: (x[0], x[1]))
    last_cpu, running_ticks, residency, mismatch = {}, Counter(), Counter(), 0
    own_out, own_in = defaultdict(list), defaultdict(list)
    same_thread_switches = 0
    for when, cpu, new, old, state, reason in switches:
        if cpu in last_cpu:
            previous, previous_tid = last_cpu[cpu]
            if previous_tid != old:
                mismatch += 1
            if previous_tid in threads:
                span = max(0, min(when, high)-max(previous, low))
                running_ticks[previous_tid] += span
                residency[cpu] += span
        last_cpu[cpu] = when, new
        if new == old:
            same_thread_switches += 1
            continue
        if old in threads:
            own_out[old].append((when, state, reason))
        if new in threads:
            own_in[new].append(when)
    ready_by_tid = defaultdict(list)
    ready_flags = Counter(flag for _, _, flag in ready)
    for when, tid, flag in ready:
        if not flag & 6:
            ready_by_tid[tid].append(when)
    for values in ready_by_tid.values():
        values.sort()
    off_ticks, off_reasons, off_stacks, off_by_tid = Counter(), Counter(), Counter(), Counter()
    resumed_with_exact_user_stack = 0
    symbols = Symbols(images)
    exe_name=Path(run['plan']['build']['executable_path']).name.lower()
    own_image = next(x for x in images if x['path'].replace('\\','/').split('/')[-1].lower()==exe_name)
    def first_own(frames):
        return next((x for x in frames if own_image['base'] <= x < own_image['base']+own_image['size']), None)
    for tid, events in own_out.items():
        ins = sorted(own_in[tid])
        for when, state, reason in events:
            i = bisect.bisect_right(ins, when)
            if i == len(ins):
                continue
            end = ins[i]
            span = max(0, min(end, high)-max(when, low))
            if not span:
                continue
            off_by_tid[tid] += span
            off_reasons[state, reason] += span
            if state in (1, 3, 7):
                off_ticks['ready'] += span
            elif state == 5:
                values = ready_by_tid[tid]
                j = bisect.bisect_left(values, when)
                if j < len(values) and values[j] <= end:
                    at = values[j]
                    off_ticks['waiting'] += max(0, min(at, high)-max(when, low))
                    off_ticks['ready_after_wait'] += max(0, min(end, high)-max(at, low))
                else:
                    off_ticks['waiting_without_ready_event'] += span
            else:
                off_ticks['other_state_'+str(state)] += span
            # WPR attaches CSwitch StackWalk to the incoming thread in this
            # trace. Inspect its saved resume chain at switch-in, not the new
            # thread's stack as though it belonged to the outgoing thread.
            frame = first_own(stack_at.get((end, tid), []))
            if frame:
                resumed_with_exact_user_stack += 1
            name = symbols.resolve(frame)['symbol'] if frame else 'no_exact_user_stack'
            off_stacks[name] += span
    exclusive, exclusive_lines, inclusive, sample_cpu = Counter(), Counter(), Counter(), Counter()
    matched, stack_own_samples, profiled_samples = 0, 0, 0
    for when, cpu, tid, ip in own_samples:
        if not low <= when <= high:
            continue
        profiled_samples += 1
        resolved = symbols.resolve(ip)
        exclusive[resolved['symbol']] += 1
        if resolved['line']:
            exclusive_lines[resolved['line']['file'], resolved['line']['line']] += 1
        frames = stack_at.get((when, tid), [])
        if frames:
            matched += 1
        own_frames = {symbols.resolve(x)['symbol'] for x in frames
                      if own_image['base'] <= x < own_image['base']+own_image['size']}
        if own_frames:
            stack_own_samples += 1
        inclusive.update(own_frames)
        sample_cpu[cpu] += 1
    seconds = lambda ticks: ticks/10_000_000
    residual = (high-low)*len(threads)-sum(running_ticks.values())-sum(off_by_tid.values())
    validation = dict(no_lost_events=all(number(x['EventsLost']) == 0 and number(x['BuffersLost']) == 0 for x in headers),
                      cswitch_continuity=mismatch == 0, exact_cpu_stack_coverage=matched/profiled_samples,
                      thread_accounting_residual_seconds=seconds(residual),
                      thread_accounting_within_100us=abs(residual) <= 1000,
                      running_cpu_below_process_total=seconds(sum(running_ticks.values())) <= run['native']['process_cpu_seconds']+0.01)
    if not (validation['no_lost_events'] and validation['cswitch_continuity'] and
            validation['exact_cpu_stack_coverage'] > .99 and validation['thread_accounting_within_100us'] and
            validation['running_cpu_below_process_total']):
        raise ValueError('ETW accounting validation failed: '+repr(validation))
    result = dict(schema='solver-etw-cpu-diagnostic-v1', pid=pid, main_tid=main_tid,
                  validation=validation, trace_identity=source_identity,
                  thread_count=len(threads), worker_tids=workers, trace_headers=headers,
                  all_thread_lifetimes=all_threads, excluded_helper_threads=excluded_threads,
                  worker_start_symbol=symbols.resolve(threads[workers[0]]['win32_start_address']),
                  ready_flags_counts=dict(ready_flags),
                  executable_sha256=run['executable_sha256'], native_cpu_seconds=run['native']['process_cpu_seconds'],
                  native_training_seconds=run['native']['summary']['elapsed_seconds'],
                  interval_definition='All 19 extra workers simultaneously alive; includes control and final save',
                  interior_wall_seconds=seconds(high-low), sampled_events=profiled_samples,
                  cpu_stack_exact_matches=matched, cpu_stack_own_module_matches=stack_own_samples,
                  clock_calibration=dict(offset_ticks=offset, exact_same_ip_votes=votes, other_candidates=offsets.most_common(5)),
                  cswitch_continuity_mismatches=mismatch,
                  same_thread_cswitch_events_excluded_from_off_cpu=same_thread_switches,
                  interior_running_cpu_seconds=seconds(sum(running_ticks.values())),
                  interior_off_cpu_seconds={k: seconds(v) for k, v in off_ticks.items()},
                  off_cpu_by_state_reason=[dict(state=k[0], reason=k[1], seconds=seconds(v)) for k, v in off_reasons.most_common()],
                  off_cpu_by_resume_solver_frame=[dict(symbol=k, seconds=seconds(v)) for k, v in off_stacks.most_common(30)],
                  off_cpu_resume_frame_definition='First own-module user frame on incoming CSwitch saved stack; association, not proof of cause',
                  off_cpu_intervals_with_exact_resume_user_stack=resumed_with_exact_user_stack,
                  thread_time_accounting=[dict(tid=tid, running_seconds=seconds(running_ticks[tid]),
                    off_seconds=seconds(off_by_tid[tid]), interval_seconds=seconds(high-low),
                    residual_seconds=seconds(high-low-running_ticks[tid]-off_by_tid[tid])) for tid in threads],
                  total_thread_time_residual_seconds=seconds(residual),
                  running_per_thread=[dict(tid=k, cpu_seconds=seconds(v)) for k, v in running_ticks.items()],
                  running_per_logical_cpu=[dict(cpu=k, seconds=seconds(v)) for k, v in sorted(residency.items())],
                  samples_per_logical_cpu=dict(sample_cpu),
                  exclusive=[dict(symbol=k, samples=v, percent=100*v/profiled_samples) for k, v in exclusive.most_common(40)],
                  exclusive_lines=[dict(file=k[0], line=k[1], samples=v, percent=100*v/profiled_samples) for k, v in exclusive_lines.most_common(40)],
                  inclusive_own_symbols=[dict(symbol=k, samples=v, percent=100*v/profiled_samples) for k, v in inclusive.most_common(30)],
                  symbol_modules=symbols.loaded,
                  parser_source_sha256=hashlib.sha256((OUT/'KernelTraceEventParser.cs').read_bytes()).hexdigest(),
                  limitations=['Short observed run with profiling enabled; not unprofiled CI10 performance.',
                               'Exclusive sampled IP counts are CPU samples, not exact instruction costs or cache-miss counts.',
                               'StackWalk clock offset fitted by exact sampled IP+thread and validated by exact matches.',
                               'Version5 CSwitch uses the documented TraceEvent prefix; inspect continuity and duration validation.',
                               'No priority/affinity/power/user application settings changed.'])
    path = args.report
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n', encoding='utf-8')
    print(json.dumps({k: result[k] for k in ['thread_count', 'interior_wall_seconds', 'sampled_events',
          'cpu_stack_exact_matches', 'cswitch_continuity_mismatches', 'interior_running_cpu_seconds',
          'interior_off_cpu_seconds', 'exclusive', 'inclusive_own_symbols']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
