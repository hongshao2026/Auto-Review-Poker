"""Independent HRC4 nodedata codec and explicit float32/native conversion.

No original executable is loaded. Unknown stores can round-trip opaquely but
cannot resume training. Native RNG/sample/visit history is restarted explicitly.
"""
from __future__ import annotations

from array import array
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import struct
import sys

FORMATS = (23,25,27,31,63)
MAX_PAYLOAD = 268435424
F32_MAX = float.fromhex('0x1.fffffep127')
F32_MIN = 2.**-149


def _require(value,message):
    if not value: raise ValueError(message)


def _array(data,code):
    result=array(code);result.frombytes(data)
    if sys.byteorder!='little':result.byteswap()
    return result


def _bytes(values,code='f',finite=False):
    result=array(code,values)
    if finite and any(not math.isfinite(x) for x in result):
        raise ValueError('Storage overflows finite float32 representation')
    if sys.byteorder!='little':result.byteswap()
    return result.tobytes()


def raw_count(fmt,h,k):
    _require(fmt in FORMATS and type(h) is int and h>0 and type(k) is int and 2<=k<=16,'Unsupported storage shape')
    return 1+h*(2*k+1) if fmt==23 else 1+k+h*(k if fmt==25 else 2*k if fmt==27 else 2*k+1)


def raw_offset(fmt,h,k):
    return 1+h*(2*k+1) if fmt==23 else 1+k+h*(k if fmt==25 else 2*k if fmt==27 else 2*k+1)


def decode_payload(node_id,fmt,count,locks,payload,actions,*,reserved=(0,0)):
    """Decode one pY record. Numeric arrays preserve original float32 bits."""
    record={'id':node_id,'format_id':fmt,'bucket_or_vector_count':count,'action_count':actions,
            'reserved':tuple(reserved),'locks':{},'payload_sha256':hashlib.sha256(payload).hexdigest()}
    _require(type(count) is int and count>=0 and 0<=locks<=actions,'Invalid payload counts')
    if actions==0:
        _require(fmt==1024 and locks==0,'Leaf must use format1024 without action locks')
        _require((count>0 and len(payload)%(4*count)==0) or (count==0 and not payload),'Invalid terminal vector dimensions')
        width=len(payload)//(4*count) if count else 0
        record.update(vectors=[_array(payload[4*width*i:4*width*(i+1)],'f') for i in range(count)],vector_width=width)
        return record
    position=0
    for _ in range(locks):
        _require(position+4+4*count<=len(payload),'Truncated locked action')
        action=struct.unpack_from('<i',payload,position)[0];position+=4
        _require(0<=action<actions and action not in record['locks'],'Invalid/duplicate locked action')
        record['locks'][action]=_array(payload[position:position+4*count],'f');position+=4*count
    if fmt not in FORMATS:
        record['opaque_payload']=bytes(payload)
        return record
    if fmt==63:
        prefix=4*(2*actions+3)
        _require(position+prefix<=len(payload),'Truncated format63 prefix')
        metadata=_array(payload[position:position+prefix-4],'f')
        underlying=struct.unpack_from('<i',payload,position+prefix-4)[0]
        record['frequency']={'targets':metadata[:actions],'minimum':metadata[actions],'maximum':metadata[actions+1],
                             'edges':metadata[actions+2:],'underlying_format':underlying}
        position+=prefix
    _require(len(payload)-position==4*raw_count(fmt,count,actions),'Storage payload length differs from format/shape')
    record['raw']=_array(payload[position:],'f')
    return record


def encode_payload(record):
    if 'opaque_payload' in record:return bytes(record['opaque_payload'])
    fmt=record['format_id'];h=record['bucket_or_vector_count'];k=record['action_count']
    if not k:
        vectors=record['vectors'];_require(fmt==1024 and len(vectors)==h,'Invalid terminal record')
        width=len(vectors[0]) if vectors else 0
        _require(all(len(row)==width for row in vectors),'Terminal vectors have unequal widths')
        return b''.join(_bytes(row) for row in vectors)
    payload=bytearray()
    for action,row in sorted(record.get('locks',{}).items()):
        _require(type(action) is int and 0<=action<k and len(row)==h,'Invalid locked action')
        payload.extend(struct.pack('<i',action));payload.extend(_bytes(row))
    if fmt==63:
        meta=record['frequency']
        _require(len(meta['targets'])==k and len(meta['edges'])==k,'Invalid frequency metadata shape')
        payload.extend(_bytes([*meta['targets'],meta['minimum'],meta['maximum'],*meta['edges']]))
        payload.extend(struct.pack('<i',meta['underlying_format']))
    _require(len(record['raw'])==raw_count(fmt,h,k),'Invalid raw storage length')
    payload.extend(_bytes(record['raw']))
    return bytes(payload)


def decode_nodedata(data,action_counts,expected_nodes=None,*,allow_missing=False,max_bytes=1<<30):
    """Return (records_by_original_id, offsets_by_original_id)."""
    _require(len(data)<=max_bytes and len(data)>=4,'Nodedata size limit or truncated header')
    count=struct.unpack_from('<i',data)[0]
    expected=len(action_counts) if expected_nodes is None else expected_nodes
    _require(count==expected and set(action_counts)==set(range(count)),'Nodedata/tree mapping count differs')
    records={};offsets={};position=4
    while position<len(data):
        _require(position+32<=len(data),'Truncated node header')
        node,size,reserved,fmt,buckets,locks,tail=struct.unpack_from('<6iQ',data,position)
        _require(node in action_counts and node not in records,'Invalid/duplicate node ID')
        _require(0<=size<=MAX_PAYLOAD and position+32+size<=len(data),'Invalid/truncated node payload')
        records[node]=decode_payload(node,fmt,buckets,locks,data[position+32:position+32+size],action_counts[node],reserved=(reserved,tail))
        offsets[node]=(position,32+size);position+=32+size
    _require(allow_missing or len(records)==count,'Missing node payloads: viewer-only archive cannot fully resume')
    return records,offsets


def encode_nodedata(records,total_nodes=None):
    """Write pY-compatible records, retaining insertion order and reserved words."""
    count=len(records) if total_nodes is None else total_nodes
    _require(type(count) is int and count>0 and all(type(i) is int and 0<=i<count for i in records),'Invalid node mapping')
    output=bytearray(struct.pack('<i',count));offsets={}
    for node,record in records.items():
        payload=encode_payload(record);_require(len(payload)<=MAX_PAYLOAD,'Node payload exceeds original pY limit')
        reserved,tail=record.get('reserved',(0,0));offsets[node]=(len(output),32+len(payload))
        output.extend(struct.pack('<6iQ',node,len(payload),reserved,record['format_id'],record['bucket_or_vector_count'],len(record.get('locks',{})),tail))
        output.extend(payload)
    return bytes(output),offsets


def leaf_record(node_id,vectors):
    vectors=[array('d',row) for row in vectors]
    _require(vectors and vectors[0] and all(len(row)==len(vectors[0]) for row in vectors),'Leaf vectors must be nonempty and rectangular')
    _require(all(math.isfinite(x) for row in vectors for x in row),'Nonfinite terminal utility')
    return {'id':node_id,'format_id':1024,'action_count':0,'bucket_or_vector_count':len(vectors),
            'vector_width':len(vectors[0]),'vectors':vectors,'reserved':(0,0),'locks':{}}


def terminal_rank_patterns(terminal):
    """Yield original mh/me outcome-index rank representatives (higher wins).

    This enumerates rank relations only. Caller must perform actual settlement
    and equity evaluation for each vector, including side pots/rake/bounties.
    """
    players=len(terminal['folded']);live=[p for p in range(players) if not terminal['folded'][p]]
    _require(live,'Terminal has no live player')
    order=sorted(live,key=lambda p:(-terminal['contributions'][p],p))
    for index in range(3**(len(live)-1)):
        value=index;level=9;ranks=[0]*players
        for seat in reversed(order):
            digit=value%3-1;value//=3;ranks[seat]=0 if digit<0 else level
            if digit>0:level-=1
        ranks[order[0]]=level
        yield ranks


def _check_leaf(record,compact,node):
    term=compact['terminals'][node['terminal_id']]
    live=sum(not folded for folded in term['folded'])
    return record['format_id']==1024 and record.get('vector_width')==compact['players'] and record['bucket_or_vector_count']==3**max(0,live-1)


def _transform(scale,offsets,players):
    _require(type(scale) in (int,float) and math.isfinite(scale) and scale>0,'utility_scale must be finite and positive')
    offsets=[0.]*players if offsets is None else list(offsets)
    _require(len(offsets)==players and all(type(x) in (int,float) and math.isfinite(x) for x in offsets),'utility_offsets must be finite per-player values')
    return float(scale),offsets


def _scaled_raw(raw,fmt,h,k,factor):
    result=array('d',raw)
    for bucket in range(h):
        start=raw_offset(fmt,bucket,k)
        for action in range(k):result[start+action]*=factor
    _require(all(math.isfinite(x) for x in result),'Nonfinite learned storage cannot resume or export')
    return result


def _extrema(minimum,maximum,scale,offset,inverse=False):
    # Preserve the explicit unobserved sentinels, not an overflowing affine image.
    if minimum==F32_MAX and maximum==F32_MIN:return minimum,maximum
    if inverse:return (minimum-offset)/scale,(maximum-offset)/scale
    return minimum*scale+offset,maximum*scale+offset


def runtime_locks(record):
    """Replay original pY -> mf -> my ascending lock setters.

    Stored float32 values remain unchanged in record. Original my itself clamps
    a newly edited row and rescales prior locks when their sum exceeds one.
    """
    rows=[None]*record['action_count'];h=record['bucket_or_vector_count']
    for action,source in sorted(record.get('locks',{}).items()):
        row=list(source)
        if any(r is not None for r in rows):
            row=[min(max(x,0.),1.) for x in row]
        rows[action]=row
        for bucket in range(h):
            # All source values are binary32; later rescaled rows use Java's
            # compensated DoubleStream.sum order.
            total=compensation=0.
            for existing in rows:
                value=0. if existing is None else existing[bucket]
                adjusted=value-compensation;new=total+adjusted
                compensation=(new-total)-adjusted;total=new
            total-=compensation
            if total>1:
                factor=(1-row[bucket])/(total-row[bucket])
                for a,existing in enumerate(rows):
                    if a!=action and existing is not None:existing[bucket]*=factor
    return rows


def storage_configuration(records,compact,*,utility_scale=1.,utility_offsets=None,node_id_map=None):
    """Return required per-street stores/policies and explicit training blockers.

    node_id_map maps native node ID to original record ID. This does not mutate
    compact; callers attach compatible configuration before creating identity.
    """
    scale,offsets=_transform(utility_scale,utility_offsets,compact['players'])
    mapping=node_id_map or {n['id']:n['id'] for n in compact['nodes']}
    street_formats=[23,25,25,25];seen={};policies=[];reasons=[];counters=[]
    for node in compact['nodes']:
        record=records.get(mapping[node['id']]);k=len(node['children']);h=node['buckets']
        if record is None:reasons.append(f"Node {node['id']}: missing saved payload");counters.append(None);continue
        if not k:
            counters.append(None)
            if not _check_leaf(record,compact,node):reasons.append(f"Node {node['id']}: terminal vector count/width differs from mh outcome layout")
            continue
        fmt=record['format_id'];base=record.get('frequency',{}).get('underlying_format',fmt)
        if fmt not in FORMATS or base not in (23,25,27,31):
            reasons.append(f"Node {node['id']}: unsupported format {fmt}/{base}");counters.append(None);continue
        if record['action_count']!=k or record['bucket_or_vector_count']!=h:
            reasons.append(f"Node {node['id']}: action/bucket dimensions differ");counters.append(None);continue
        counter=record['raw'][0];counters.append(counter if math.isfinite(counter) and counter>=0 else None)
        if not math.isfinite(counter) or not 0<=counter<=2**52:reasons.append(f"Node {node['id']}: invalid/unsafe float32 update clock")
        if any(not math.isfinite(v) for v in record['raw']):reasons.append(f"Node {node['id']}: nonfinite raw storage")
        street=node['street']
        if (street==0 and base!=23) or (street>0 and base==23):reasons.append(f"Node {node['id']}: unsupported street/base format {street}/{base}")
        if street in seen and seen[street]!=base:reasons.append(f'Street {street}: mixed per-node storage formats require unsupported native per-node profile')
        seen[street]=base;street_formats[street]=base
        locks=record.get('locks',{})
        if locks:
            if fmt in (25,63):reasons.append(f"Node {node['id']}: locks on format {fmt} cannot preserve this store")
            if any(not math.isfinite(v) or not 0<=v<=1 for row in locks.values() for v in row):
                reasons.append(f"Node {node['id']}: invalid source lock probabilities");continue
            rows=runtime_locks(record)
            if any(not math.isfinite(v) or not 0<=v<=1 for row in rows if row is not None for v in row):reasons.append(f"Node {node['id']}: invalid lock probabilities")
            if len(locks)==k and any(abs(sum(row[b] for row in rows)-1)>k*2**-23 for b in range(h)):
                reasons.append(f"Node {node['id']}: full locks are not normalized within float32 roundoff")
            policies.append({'node_id':node['id'],'locks':rows})
        elif fmt==63:
            meta=record['frequency'];targets=[None if math.isnan(x) else x for x in meta['targets']]
            if any(x is not None and (not math.isfinite(x) or not 0<=x<=1) for x in targets) or sum(x for x in targets if x is not None)>1+1e-7:reasons.append(f"Node {node['id']}: invalid frequency targets")
            if any(not math.isfinite(x) for x in [meta['minimum'],meta['maximum'],*meta['edges']]):reasons.append(f"Node {node['id']}: nonfinite frequency metadata")
            policies.append({'node_id':node['id'],'frequency':{'targets':targets,'edges':[x/scale for x in meta['edges']]}})
    return {'trainable':not reasons,'reasons':reasons,'stores':{'version':1,'street_formats':street_formats},
            'policies':{'version':1,'nodes':policies},'saved_update_counters':counters,
            'utility_scale':scale,'utility_offsets':offsets}


def _read_node_state(stream,index,version):
    k,h=index['actions'],index['buckets'];fmt=index['format']
    stream.seek(index['visits_offset']-(12 if version!=1 else 8))
    updates=struct.unpack('<Q',stream.read(8))[0]
    if version!=1:_require(struct.unpack('<I',stream.read(4))[0]==fmt,'Checkpoint format/index mismatch')
    _require(updates==index['updates'],'Checkpoint clock/index mismatch')
    stream.seek(index['raw_offset']);raw=_array(stream.read(8*index['raw_count']),'d')
    _require(len(raw)==index['raw_count'],'Truncated checkpoint raw storage')
    state={'raw':raw,'updates':updates}
    if fmt==31:
        stream.seek(index['shared_state_offset']);state['shared']=_array(stream.read(8*k),'d')
    if fmt==63:
        stream.seek(index['frequency_state_offset']);extra=_array(stream.read(8*(2+3*k)),'d')
        state.update(minimum=extra[0],maximum=extra[1],edges=extra[2:2+k],edge_sums=extra[2+k:2+2*k],shared=extra[2+2*k:])
        state['targets']=_array(stream.read(8*k),'d') if version==3 else array('d',(math.nan if x is None else x for x in index['targets']))
    return state


def checkpoint_to_records(output_dir,*,utility_scale=1.,utility_offsets=None,leaf_records,node_id_map=None):
    """Export actual learned state; caller supplies independently correct leaves."""
    folder=Path(output_dir);compact=json.loads((folder/'tree.json').read_text());index=json.loads((folder/'index.json').read_text())
    scale,offsets=_transform(utility_scale,utility_offsets,compact['players'])
    mapping=node_id_map or {n['id']:n['id'] for n in compact['nodes']};records={};ambiguities=[]
    with (folder/'checkpoint.bin').open('rb') as stream:
        header=stream.read(68+compact['players']*8)
        _require(header[:8] in (b'HRSOLV01',b'HRSOLV02',b'HRSOLV03'),'Unsupported checkpoint version')
        from .hrc_checkpoint import _identity
        _require(struct.unpack_from('<Q',header,8)[0]==_identity(compact),'Checkpoint/tree identity differs')
        version=int(chr(header[7]))
        for node,meta in zip(compact['nodes'],index['nodes']):
            nid=node['id'];rid=mapping[nid];k=len(node['children']);h=node['buckets']
            if not k:
                _require(nid in leaf_records,f'Node {nid}: missing absolute terminal utility vectors')
                record=deepcopy(leaf_records[nid]);_require(record['format_id']==1024 and record['action_count']==0,'Expected format1024 leaf')
                _require(_check_leaf(record,compact,node),'Terminal vector count/width differs from original mh layout')
                record['id']=rid;records[rid]=record;continue
            fmt=meta['format'];_require(meta['raw_count']==raw_count(fmt,h,k),'Checkpoint raw shape differs')
            state=_read_node_state(stream,meta,version)
            raw=_scaled_raw(state['raw'],fmt,h,k,scale)
            if fmt!=25:raw[0]=float(state['updates'])
            if fmt in (31,63):raw[1:1+k]=state['shared']
            record={'id':rid,'format_id':fmt,'action_count':k,'bucket_or_vector_count':h,'reserved':(0,0),
                    'raw':_array(_bytes(raw,finite=True),'f'),'locks':{a:array('f',row) for a,row in enumerate(meta.get('locks',[])) if row is not None}}
            if fmt==63:
                minimum,maximum=_extrema(state['minimum'],state['maximum'],scale,offsets[node['actor']])
                if state['maximum']==F32_MIN and state['minimum']!=F32_MAX:ambiguities.append({'node_id':nid,'kind':'maximum_has_zero_sentinel_floor','detail':'Affine conversion preserves stored bound; discarded negative historical maximum cannot be reconstructed.'})
                base=compact.get('stores',{}).get('street_formats',[23,25,25,25])[node['street']]
                record['frequency']={'targets':array('f',state['targets']),'minimum':minimum,'maximum':maximum,
                                     'edges':array('d',(x*scale for x in state['edge_sums'])),'underlying_format':base}
                _bytes([minimum,maximum,*record['frequency']['edges']],finite=True)
            records[rid]=record
    report={'float32_quantization':True,'utility_scale':scale,'utility_offsets':offsets,
            'counter_flushed_before_encoding':True,'rng_or_visits_written_to_hrc':False,'ambiguities':ambiguities}
    return records,report


def _rng_seed(seed):
    _require(type(seed) is int and 0<=seed<2**64,'Seed must be uint64')
    mask=2**64-1;state=[];value=seed
    for _ in range(4):
        value=(value+0x9e3779b97f4a7c15)&mask;z=value
        z=((z^(z>>30))*0xbf58476d1ce4e5b9)&mask;z=((z^(z>>27))*0x94d049bb133111eb)&mask
        state.append(z^(z>>31))
    return state


def records_to_checkpoint(records,compact,output_dir,*,seed,utility_scale=1.,utility_offsets=None,node_id_map=None,mode='v4'):
    """Create HRSOLV03 with raw loaded clocks and explicitly restarted RNG/history."""
    cfg=storage_configuration(records,compact,utility_scale=utility_scale,utility_offsets=utility_offsets,node_id_map=node_id_map)
    _require(cfg['trainable'],'Read-only HRC storage: '+'; '.join(cfg['reasons']))
    _require(mode in ('v3','v4'),'Unknown solver mode')
    _require(compact.get('stores',{'version':1,'street_formats':[23,25,25,25]})==cfg['stores'],'Attach required stores configuration before importing checkpoint')
    _require(compact.get('policies',{'version':1,'nodes':[]})==cfg['policies'],'Attach required policies configuration before importing checkpoint')
    provenance=compact.get('import_provenance',{})
    _require(provenance.get('format')=='hrcz' and isinstance(provenance.get('source_sha256'),str) and len(provenance['source_sha256'])==64 and all(c in '0123456789abcdef' for c in provenance['source_sha256']),'Imported identity requires source SHA-256 provenance')
    _require(provenance.get('saved_update_counters')==cfg['saved_update_counters'],'Imported counter provenance differs from payloads')
    output=Path(output_dir);output.mkdir(parents=True,exist_ok=True)
    _require(not any((output/name).exists() for name in ('checkpoint.bin','index.json','tree.json')),'Import destination already contains native state')
    from .hrc_native import prepare
    from .hrc_checkpoint import _identity
    prepared=prepare(compact,output);players=compact['players'];scale=cfg['utility_scale'];offsets=cfg['utility_offsets']
    mapping=node_id_map or {n['id']:n['id'] for n in compact['nodes']}
    index={'version':3,'samples':0,'fresh_zero_origin':False,'source_history_unknown':True,'utility':'net_payout' if compact.get('equity') else 'net_bb',
           'algorithm':'audited_'+mode+'_single_thread','ci':None,'nodes':[]}
    with (output/'checkpoint.bin').open('wb') as stream:
        stream.write(b'HRSOLV03');stream.write(struct.pack('<QQIII4Q',_identity(compact),0,len(compact['nodes']),players,int(mode=='v4'),*_rng_seed(seed)));stream.write(bytes(players*8))
        for node in compact['nodes']:
            nid=node['id'];record=records[mapping[nid]];k=len(node['children']);h=node['buckets'] if k else 0
            fmt=record['format_id'] if k else 0;raw=_scaled_raw(record['raw'],fmt,h,k,1/scale) if k else array('d')
            updates=math.floor(raw[0]+.5) if k else 0
            stream.write(struct.pack('<QI',updates,fmt));visits_offset=stream.tell();stream.write(bytes(8*h));raw_offset=stream.tell();stream.write(_bytes(raw,'d'))
            meta={'id':nid,'actor':node['actor'],'street':node['street'],'buckets':h,'actions':k,'updates':updates,
                  'visits_offset':visits_offset,'raw_offset':raw_offset,'raw_count':len(raw),'format':fmt,'special':node.get('special',0)}
            if k:meta.update(history_unknown=True,saved_counter_float32=record['raw'][0],imported_updates_baseline=updates)
            if fmt==31:
                meta['shared_state_offset']=stream.tell();stream.write(_bytes(raw[1:1+k],'d'))
            if fmt==63:
                frequency=record['frequency'];minimum,maximum=_extrema(frequency['minimum'],frequency['maximum'],scale,offsets[node['actor']],True)
                edges=[x/scale for x in frequency['edges']];targets=frequency['targets']
                meta['frequency_state_offset']=stream.tell();stream.write(_bytes([minimum,maximum,*edges,*edges,*raw[1:1+k],*targets],'d'))
                meta['targets']=[None if math.isnan(x) else x for x in targets]
            if record.get('locks'):meta['locks']=runtime_locks(record)
            index['nodes'].append(meta)
    index['root_mean_net_payout' if compact.get('equity') else 'root_mean_net_bb']=[0.]*players
    (output/'index.json').write_text(json.dumps(index,indent=2),encoding='utf-8')
    report={'format':'hrcz-import-history-v1','source_sha256':provenance['source_sha256'],'source_iterations':None,
            'source_rng_state':None,'source_per_bucket_visits':None,'new_seed':seed,'samples_since_import':0,
            'saved_update_counters':cfg['saved_update_counters'],'clock_semantics':'Original float32 counter retained in raw[0]; true clock starts at Java Math.round(snapshot), not zero.',
            'utility_scale':scale,'utility_offsets':offsets,'original_leaf_values_used_for_native_training':False,
            'rng_restarted':True,'ci_history_restarted':True,'bit_exact_original_continuation':False}
    (output/'import-history.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
    return {'checkpoint_path':str(output/'checkpoint.bin'),'index_path':str(output/'index.json'),
            'manifest_path':prepared['manifest_path'],'report':report}
