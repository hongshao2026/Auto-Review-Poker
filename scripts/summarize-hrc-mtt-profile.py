"""Analyze one bounded capture using identical ETW scheduling accounting."""
from __future__ import annotations
import argparse
import bisect
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('etw_symbols', ROOT / 'scripts/summarize-hrc-etw.py')
etw = importlib.util.module_from_spec(spec)
spec.loader.exec_module(etw)
NS, E = etw.NS, etw.E


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('folder', type=Path)
    p.add_argument('--scratch', type=Path, help='Temporary XML location; defaults to the capture folder')
    a = p.parse_args()
    out = a.folder.resolve()
    capture = json.loads((out / 'capture.json').read_text(encoding='utf8'))
    assert capture['status'] == 'completed' and capture['wpr_stop']['returncode'] == 0
    pid, workers = capture['pid'], set(capture['worker_tids'])
    assert len(workers) == 20
    scratch=(a.scratch or out/'decode-scratch').resolve();scratch.mkdir(parents=True,exist_ok=True)
    xml = scratch / (out.name+'-events.xml')
    samples, switches, ready, stacks, images, headers = [], [], [], [], [], []
    all_target_tids = set(workers)
    cached = out / 'parsed-events.json'
    identity = {'schema': 2, 'etl_sha256': sha(out / 'solver-cpu.etl'), 'pid': pid,
                'parser_sha256':sha(Path(__file__)), 'capture_sha256':sha(out/'capture.json')}
    if cached.exists():
        data = json.loads(cached.read_text(encoding='utf8'))
        # The decoded event schema is unchanged when only downstream accounting
        # changes. Retain the original decoding identity, rather than relabel it.
        assert all(data['identity'][k] == v for k,v in identity.items() if k != 'parser_sha256')
        identity={'decoded_events':data['identity'],'analysis_source_sha256':sha(Path(__file__))}
        samples, switches, ready, stacks, images, headers = [data[k] for k in ('samples','switches','ready','stacks','images','headers')]
        all_target_tids = set(data['all_target_tids'])
    else:
        assert not xml.exists(), 'Preserve or explicitly remove the previous reproducible scratch file'
        result = subprocess.run(['tracerpt.exe', str(out / 'solver-cpu.etl'), '-of', 'XML', '-o', str(xml), '-y'],
                                capture_output=True, text=True, timeout=300)
        (out / 'tracerpt.txt').write_text(result.stdout + result.stderr, encoding='utf8')
        result.check_returncode()
        dump_sha=sha(xml)
        iterator = ET.iterparse(xml, events=('start', 'end'))
        _, root = next(iterator)
        for event, node in iterator:
            if event != 'end' or node.tag != E + 'Event':
                continue
            system = node.find('e:System', NS)
            guid = node.findtext('t:ExtendedTracingInfo/t:EventGuid', '', NS).lower()
            opcode = int(system.findtext('e:Opcode', '0', NS))
            version = int(system.findtext('e:Version', '0', NS))
            when = etw.tick(system.find('e:TimeCreated', NS).get('SystemTime'))
            cpu = int(system.find('e:Execution', NS).get('ProcessorID'))
            fields = {x.get('Name'): x.text for x in node.findall('e:EventData/e:Data', NS)}
            if guid.startswith('{ce1dbfb4') and opcode == 46:
                samples.append((when, cpu, etw.number(fields['ThreadId']), etw.number(fields['InstructionPointer'])))
            elif guid.startswith('{3d6fa8d1'):
                if opcode == 36:
                    raw = bytes.fromhex(node.findtext('e:BinaryEventData', '', NS))
                    assert version >= 2 and len(raw) >= 24
                    new, old = struct.unpack_from('<II', raw)
                    switches.append((when, cpu, new, old, raw[14], raw[12]))
                elif opcode == 50 and 'TThreadId' in fields:
                    ready.append((when, etw.number(fields['TThreadId']), etw.number(fields.get('Flag', '0'))))
                elif opcode in (1,2,3,4):
                    payload = node.findtext('e:ProcessingErrorData/e:EventPayload', '', NS)
                    if payload:
                        thread_pid, tid = struct.unpack_from('<II', bytes.fromhex(payload))
                    else:
                        thread_pid = etw.number(fields.get('ProcessId', '-1'))
                        tid = etw.number(fields.get('TThreadId', fields.get('ThreadId', '-1')))
                    if thread_pid == pid:
                        all_target_tids.add(tid)
            elif guid.startswith('{2cb15d1d') and fields and etw.number(fields.get('ProcessId', '-1')) == pid and opcode in (10,3,4):
                image = {'base': etw.number(fields['ImageBase']), 'size': etw.number(fields['ImageSize']), 'path': fields['FileName']}
                if not any(x['base'] == image['base'] for x in images):
                    images.append(image)
            elif guid.startswith('{def2fe46') and opcode == 32:
                payload = node.findtext('e:ProcessingErrorData/e:EventPayload', '', NS)
                if payload:
                    raw = bytes.fromhex(payload)
                    if len(raw) >= 16 and struct.unpack_from('<I', raw, 8)[0] == pid:
                        assert (len(raw)-16) % 8 == 0
                        qpc, _, tid = struct.unpack_from('<QII', raw)
                        frames = struct.unpack_from('<' + 'Q'*((len(raw)-16)//8), raw, 16)
                        stacks.append((when, qpc, tid, frames))
            elif guid.startswith('{68fdd900') and opcode == 0:
                headers.append(fields)
            root.clear()
        cached.write_text(json.dumps({'identity': identity, 'samples': samples, 'switches': switches,
                                     'ready': ready, 'stacks': stacks, 'images': images, 'headers': headers,
                                     'all_target_tids': sorted(all_target_tids)}), encoding='utf8')
        (out/'xml-expansion.json').write_text(json.dumps({'sha256':dump_sha,'bytes':xml.stat().st_size,
            'scratch_path':str(xml),'retention':'Raw ETL retained; reproducible XML removed after streaming parse'},indent=2),encoding='utf8')
        assert xml.resolve().is_relative_to(scratch)
        xml.unlink()
    assert headers and all(etw.number(h['PerfFreq']) == 10000000 for h in headers)
    samples_by_key = defaultdict(list)
    for when, cpu, tid, ip in samples:
        if tid in workers:
            samples_by_key[tid, ip].append(when)
    for values in samples_by_key.values():
        values.sort()
    offsets = Counter()
    for when, qpc, tid, frames in stacks:
        if tid not in workers or not frames:
            continue
        values = samples_by_key.get((tid, frames[0]), [])
        at = bisect.bisect_right(values, when)
        for i in range(max(0, at-3), at):
            if when-values[i] <= 100000:
                offsets[values[i]-qpc] += 1
    assert offsets, 'No exact IP+TID clock calibration'
    offset, votes = offsets.most_common(1)[0]
    low, high = capture['capture_begin']['qpc'] + offset, capture['capture_end']['qpc'] + offset
    requested_low,requested_high=low,high
    cpu_bounds={}
    thread_first={}
    for when,cpu,new,old,state,reason in switches:
        if cpu not in cpu_bounds:cpu_bounds[cpu]=[when,when]
        cpu_bounds[cpu][0]=min(cpu_bounds[cpu][0],when);cpu_bounds[cpu][1]=max(cpu_bounds[cpu][1],when)
        for tid in (new,old):
            if tid in workers:thread_first[tid]=min(thread_first.get(tid,when),when)
    assert workers <= thread_first.keys()
    # Memory-mode ETW can overwrite the start of a CPU's circular buffer
    # without counting it as EventsLost. Use only the common recorded interior.
    low=max(low,max(b[0] for b in cpu_bounds.values())+1000000,max(thread_first.values())+1000000)
    high=min(high,min(b[1] for b in cpu_bounds.values()))
    assert high > low
    assert high-low > 50000000, 'Require at least five seconds of common recorded coverage'
    stack_at = defaultdict(list)
    for when, qpc, tid, frames in stacks:
        stack_at[qpc+offset, tid].extend(frames)
    switches.sort(key=lambda x: (x[0], x[1]))
    running, residency, in_times, out_times = Counter(), Counter(), defaultdict(list), defaultdict(list)
    last_cpu, mismatches = {}, 0
    process_running = Counter()
    for when, cpu, new, old, state, reason in switches:
        if cpu in last_cpu:
            before, before_tid = last_cpu[cpu]
            if before_tid != old and when >= low and before <= high:
                mismatches += 1
            span = max(0, min(when, high)-max(before, low))
            if before_tid in all_target_tids:
                process_running[before_tid] += span
            if before_tid in workers:
                running[before_tid] += span
                residency[cpu] += span
        last_cpu[cpu] = when, new
        if new == old:
            continue
        if old in workers:
            out_times[old].append((when, state, reason))
        if new in workers:
            in_times[new].append(when)
    ready_by_tid = defaultdict(list)
    for when, tid, flag in ready:
        if tid in workers and not flag & 6:
            ready_by_tid[tid].append(when)
    for values in ready_by_tid.values():
        values.sort()
    pdb_path=ROOT/'analysis/hrc-native/build/identities/c253acd92207f90ccc00f0ed771a27316841b54fb585a016e0d6a88ca5753c89'
    search_path = ';'.join((str(Path(capture['command'][0]).resolve().parent), str(pdb_path),
                           str(ROOT/'analysis/hrc-native/build'))) if capture['kind'] == 'native' else None
    symbols = etw.Symbols(images, search_path=search_path) if search_path else None
    own_image = next((image for image in images if image['path'].replace('\\','/').split('/')[-1].lower() == 'solver.exe'), None)
    def solver_frame(frames):
        if not own_image:
            return None
        return next((ip for ip in frames if own_image['base'] <= ip < own_image['base']+own_image['size']), None)
    off, off_by_tid, reasons, resume = Counter(), Counter(), Counter(), Counter()
    for tid in workers:
        ins = sorted(in_times[tid])
        for when, state, reason in out_times[tid]:
            at = bisect.bisect_right(ins, when)
            end = ins[at] if at < len(ins) else high
            span = max(0, min(end, high)-max(when, low))
            if not span:
                continue
            off_by_tid[tid] += span
            reasons[state, reason] += span
            if state in (1,3,7):
                off['ready_to_run'] += span
            elif state == 5:
                r = ready_by_tid[tid]
                i = bisect.bisect_left(r, when)
                if i < len(r) and r[i] <= end:
                    off['waiting'] += max(0, min(r[i], high)-max(when, low))
                    off['ready_after_wait'] += max(0, min(end, high)-max(r[i], low))
                else:
                    off['waiting_without_ready_event'] += span
            else:
                off['other_state_' + str(state)] += span
            if symbols:
                frame = solver_frame(stack_at.get((end, tid), []))
                resume[symbols.resolve(frame)['symbol'] if frame else 'no_exact_solver_frame'] += span
    own_samples = [(when,cpu,tid,ip) for when,cpu,tid,ip in samples if tid in workers and low <= when <= high]
    exclusive, inclusive, lines = Counter(), Counter(), Counter()
    matched = 0
    for when, cpu, tid, ip in own_samples:
        frames = stack_at.get((when, tid), [])
        matched += bool(frames)
        if symbols:
            item = symbols.resolve(ip)
            exclusive[item['symbol']] += 1
            if item['line']:
                lines[item['line']['file'],item['line']['line']] += 1
            own_names = {symbols.resolve(f)['symbol'] for f in frames if solver_frame([f]) is not None}
            inclusive.update(own_names)
    sec = lambda value: value / 10000000
    elapsed = sec(high-low)
    residuals = {tid: sec(high-low-running[tid]-off_by_tid[tid]) for tid in workers}
    validation = {'no_lost_events': all(etw.number(h['EventsLost']) == 0 and etw.number(h['BuffersLost']) == 0 for h in headers),
                  'cswitch_continuity_mismatches': mismatches,
                  'cpu_stack_coverage': matched / len(own_samples),
                  'max_abs_thread_residual_seconds': max(map(abs, residuals.values()))}
    assert validation['no_lost_events'] and mismatches == 0
    assert validation['max_abs_thread_residual_seconds'] < .0001, repr({'validation':validation,'residuals':residuals,'offsets':offsets.most_common(3)})
    # Java JIT frames need not unwind through ETW; JFR is the named Java source.
    if symbols:
        assert validation['cpu_stack_coverage'] > .99
    result = {'schema':'mtt-etw-diagnostic-v1', 'kind':capture['kind'], 'stage':capture['stage'], 'pid':pid,
              'validation':validation, 'identity':identity, 'worker_tids':sorted(workers),
              'window':{'wall_seconds':elapsed,'qpc_begin':low-offset,'qpc_end':high-offset,
                        'requested_wall_seconds':(requested_high-requested_low)/10000000,
                        'prefix_trim_seconds':(low-requested_low)/10000000,
                        'suffix_trim_seconds':(requested_high-high)/10000000,
                        'definition':'Requested training window intersected with common per-CPU/per-worker event coverage, plus 100ms boundary guard'},
              'clock_calibration':{'offset_ticks':offset,'same_ip_tid_votes':votes,'top_offsets':offsets.most_common(3)},
              'sample_count':len(own_samples), 'worker_running_cpu_seconds':sec(sum(running.values())),
              'worker_mean_logical_cpus':sec(sum(running.values()))/elapsed,
              'process_running_cpu_seconds':sec(sum(process_running.values())),
              'external_process_cpu_delta':capture['cpu_after']-capture['cpu_before'],
              'off_cpu_seconds':{k:sec(v) for k,v in off.items()},
              'off_cpu_state_reason':[{'state':k[0],'reason':k[1],'seconds':sec(v)} for k,v in reasons.most_common()],
              'thread_accounting':[{'tid':tid,'running_seconds':sec(running[tid]),'off_seconds':sec(off_by_tid[tid]),'residual_seconds':residuals[tid]} for tid in sorted(workers)],
              'running_per_logical_cpu':[{'cpu':cpu,'seconds':sec(value)} for cpu,value in sorted(residency.items())],
              'exclusive_native':[{'symbol':k,'samples':v,'percent':100*v/len(own_samples)} for k,v in exclusive.most_common(35)],
              'inclusive_native':[{'symbol':k,'samples':v,'percent':100*v/len(own_samples)} for k,v in inclusive.most_common(25)],
              'exclusive_lines':[{'file':k[0],'line':k[1],'samples':v,'percent':100*v/len(own_samples)} for k,v in lines.most_common(30)],
              'off_cpu_by_resume_native_frame':[{'symbol':k,'seconds':sec(v)} for k,v in resume.most_common(25)],
              'limitations':['Short instrumented window, not time-to-CI measurement.',
                             'Ready/yield time and sampled update functions are not exact recoverable lock costs.',
                             'Original Java hotspots are from JFR, native hotspots from ETW sampled IP; percentages are different sampling populations.',
                             'No hardware memory-bandwidth or cache-miss counters measured.']}
    (out/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf8')
    print(json.dumps({k:result[k] for k in ('kind','stage','validation','sample_count','worker_mean_logical_cpus','off_cpu_seconds','exclusive_native')},ensure_ascii=False))


if __name__ == '__main__':
    main()
