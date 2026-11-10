"""Reclaim only generated round-four timing indexes whose checkpoints were discarded."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
BASE=(ROOT/'.research-cache/cpu-round4-20261108').resolve()

def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    removed=[]
    for report in BASE.glob('*/report.json'):
        data=json.loads(report.read_text(encoding='utf-8'))
        if data.get('status')!='completed':continue
        for row in [*data.get('serial',[]),*data.get('trials',[])]:
            if not row.get('generated_checkpoint_removed_after_hash'):continue
            folder=Path(row['output']).resolve();index=folder/'index.json'
            if not folder.is_relative_to(BASE) or folder.parent!=report.parent:
                raise ValueError('Refusing to remove an index outside its new timing trial')
            if (folder/'checkpoint.bin').exists():raise ValueError('Checkpoint still retained; preserve its index')
            if not index.is_file():continue
            removed.append({'path':str(index),'bytes':index.stat().st_size,'sha256':sha(index),
                            'report':str(report),'checkpoint_sha256':row['checkpoint_sha256']})
            index.unlink()
    receipt=BASE/'discarded-timing-indexes.json'
    prior=json.loads(receipt.read_text()) if receipt.exists() else []
    receipt.write_text(json.dumps([*prior,*removed],indent=2)+'\n')
    print(json.dumps({'removed_generated_indexes':len(removed),'bytes_reclaimed':sum(x['bytes'] for x in removed)}))

if __name__=='__main__':main()
