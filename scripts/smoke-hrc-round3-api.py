"""Verify the running app executes the measured round-three kernel."""
import importlib.util
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[1]


def main():
    formal=json.loads((ROOT/'reports/hrc-three40bb-ci10-round3-current8-20261108.json').read_text(encoding='utf-8'))
    assert formal['status']=='ci_target_reached'
    fastest=ROOT/'reports/hrc-three40bb-ci10-round3-current20-20261108.json'
    if fastest.is_file():assert json.loads(fastest.read_text())['status']=='ci_target_reached'
    spec=importlib.util.spec_from_file_location('local_api_smoke',ROOT/'scripts/smoke-hrc-node-lock-api.py')
    helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper)
    old_job=ROOT/'.runs/1d898413dc2e416ea087fc2f30202f5d.json';old_sha=helper.sha(old_job)
    previous=json.loads((ROOT/'.runs/2b9cb5ede0554d21a2b5213145c80fcc.json').read_text(encoding='utf-8'))
    config=previous['config'];config.update(iterations=1003,threads=2,stopping_mode='samples',sampling_stage='calculation')
    config.pop('target_ci',None)
    created=helper.request('/api/jobs',{'config':config});job_id=created['id'];started=time.monotonic()
    while True:
        state=helper.request('/api/jobs/'+job_id)
        if state['status'] in ('completed','failed','cancelled'):break
        if time.monotonic()-started>120:raise RuntimeError('API smoke exceeded 120s: '+job_id)
        time.sleep(.25)
    assert state['status']=='completed',state
    summary=helper.request('/api/jobs/'+job_id+'/export')['summary']
    assert summary['iterations_completed']==1003 and summary['training_threads']==2
    assert summary['terminal_tables'] and summary['terminal_pointer_cache'] and summary['unlocked_strategy_reads']
    assert summary['terminal_settlements']==0
    stamp=json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text(encoding='utf-8'))
    benchmark=json.loads((ROOT/'reports/hrc-throughput-round3-final-20261108.json').read_text(encoding='utf-8'))
    sections={'api':helper.pe_section_hashes(stamp['executable_path']),
              'measured':helper.pe_section_hashes(benchmark['cases']['current8'])}
    equal_code=sections['api']['.text']==sections['measured']['.text']
    result={'status':'completed','job_id':job_id,'summary':summary,'build':stamp,
            'previous_ui_job_unchanged':helper.sha(old_job)==old_sha,
            'native_text_section_equal_to_measured':equal_code,'pe_section_hashes':sections,
            'limitations':['Running service retains older imported Python build helper; changed CPP triggers compilation.',
                           'A future header-only change requires refreshing that Python process; no service restart was performed.']}
    assert result['previous_ui_job_unchanged'] and equal_code
    output=ROOT/'reports/hrc-round3-api-smoke-20261108.json'
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'status':'completed','job_id':job_id,'report':str(output)},ensure_ascii=False),flush=True)


if __name__=='__main__':main()
