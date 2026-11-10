"""Reproducible settings/topology archive audit; no original GUI or solver."""
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from preflop_lab.hrc_hrcz_tree import load_archive_tree
from preflop_lab.hrc_hrcz_settings import settings_to_config,config_to_settings,config_to_state,expand_prizes


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    output=ROOT/'analysis/hrc-deep/hrcz-settings';output.mkdir(parents=True,exist_ok=True)
    cases=[{}, {'1':0}, {'1':100}, {'1':100,'2':60,'5':30,'8':0},
           {'1':10,'4':10}, {'1':20,'2':0,'5':0}, {'1':100,'2':80,'3':60,'4':40,'5':20,'6':0},
           {'1':1e12,'3':.0001,'10':0}, {'1':.1,'5':0}, {'1':25,'1000':0}]
    inputs=output/'cases.tsv'
    inputs.write_text(''.join(str(i)+'\t'+','.join(k+':'+str(v) for k,v in prizes.items())+'\n' for i,prizes in enumerate(cases)))
    source=ROOT/'scripts/java/OriginalArchiveSettingsProbe.java'
    java=Path(r'D:\Tools\REA-Research\jdk-21.0.13+9\bin\java.exe')
    jar=Path(r'D:\Program Files\HRC\plugins\net.holdemresources.calculator_4.1.0.202603231401.jar')
    classes=output/'classes';classes.mkdir(exist_ok=True)
    built=subprocess.run([str(java.with_name('javac.exe')),'-d',str(classes),str(source)],capture_output=True,text=True)
    if built.returncode:raise RuntimeError(built.stderr)
    command=[str(java),'-Xmx256m','-cp',str(classes),'OriginalArchiveSettingsProbe',str(jar),str(inputs)]
    executed=subprocess.run(command,capture_output=True,text=True,timeout=30)
    (output/'original.jsonl').write_text(executed.stdout)
    if executed.returncode:raise RuntimeError(executed.stderr)
    records=[json.loads(line) for line in executed.stdout.splitlines()]
    payouts=[]
    for record in records:
        if record['kind']=='prizes':
            actual=expand_prizes({'prizes':cases[int(record['id'])]})
            payouts.append({**record,'independent':actual,'passed':actual==record['values']})
        elif record['kind']=='units':
            units={**record,'independent':[.01*v for v in record['internal']]}
            units['passed']=units['values']==units['independent']
    archives=[]
    for path in sorted((ROOT/'analysis/hrc-desktop').glob('*.hrcz')):
        tree=load_archive_tree(path)
        cfg=settings_to_config(tree.settings,tree.archive_state)
        unchanged=config_to_settings(cfg)==tree.settings and config_to_state(cfg)==tree.archive_state
        archives.append(dict(name=path.name,sha256=sha(path),**tree.validation,
                             physical_record_order_is_id_order=tree.record_order==tuple(range(len(tree.nodes))),
                             settings_state_roundtrip_exact=unchanged,
                             snapshot_sha256=hashlib.sha256(json.dumps(asdict(tree),sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                             passed=unchanged and tree.validation['all_actions_rule_checked']))
    report=dict(format='hrcz-settings-replay-validation-v1',jar_sha256=sha(jar),command=command,
        execution_scope='Original oL/oM/kF only plus hash-pinned Gson verifier dependency, platform parent loader, resources denied; no application/GUI/solver/network code',
        original_classes=[r for r in records if r['kind']=='class'],prize_cases=payouts,units=units,
        archives=archives,archive_count=len(archives),nodes=sum(r['nodes'] for r in archives),
        replayed_actions=sum(r['replayed_actions'] for r in archives),
        module_hashes={str(p.relative_to(ROOT)):sha(p) for p in [ROOT/'preflop_lab/hrc_hrcz_settings.py',ROOT/'preflop_lab/hrc_hrcz_tree.py',source]},
        limitations=['Archive state and leaf values do not prove convergence or solver equivalence.',
                     'Ante/straddle/skip/moving roundtrip tests use generated topology and previously audited rule primitives.',
                     'Unknown profiles and postflop subtree imports remain explicitly unsupported for training.'],
        passed=all(r['passed'] for r in payouts+archives) and units['passed'])
    destination=ROOT/'reports/hrc-original-hrcz-settings-validation.json'
    destination.write_text(json.dumps(report,indent=2)+'\n')
    print(json.dumps(dict(passed=report['passed'],archive_count=len(archives),nodes=report['nodes'],
                          replayed_actions=report['replayed_actions'],prize_cases=len(payouts),unit_values=len(units['values']),report=str(destination))))
    if not report['passed']:raise SystemExit(1)


if __name__=='__main__':main()
