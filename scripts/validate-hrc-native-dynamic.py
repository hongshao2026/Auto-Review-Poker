"""Retain bounded production integration evidence for fixed-board mode1."""
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def main():
    directory=ROOT/'analysis/hrc-deep/native-dynamic';directory.mkdir(parents=True,exist_ok=True)
    xml=directory/'pytest.xml'
    command=[sys.executable,'-m','pytest','tests/test_hrc_native_dynamic.py','-q','--junitxml='+str(xml)]
    started=time.monotonic();completed=subprocess.run(command,cwd=ROOT,capture_output=True,text=True)
    (directory/'pytest.txt').write_text(completed.stdout+completed.stderr,encoding='utf-8')
    suites=ET.parse(xml).getroot();results=[]
    for suite in suites.findall('testsuite'):
        for case in suite.findall('testcase'):
            results.append({'name':case.attrib['name'],'seconds':float(case.attrib.get('time','0')),
                            'passed':case.find('failure') is None and case.find('error') is None and case.find('skipped') is None})
    files=['native/hrc_research_solver.cpp','native/hrc_dynamic.hpp','native/hrc_chance.hpp','native/hrc_digest.hpp',
           'preflop_lab/hrc_native.py','scripts/native/dynamic_kernel_probe.cpp','tests/test_hrc_native_dynamic.py']
    upstream=['reports/hrc-original-chance-validation.json','reports/hrc-original-nested-traversal-validation.json']
    report={'passed':completed.returncode==0,'cases':len(results),'elapsed_seconds':time.monotonic()-started,
            'command':command,'results':results,'sources':{file:sha(ROOT/file) for file in files},
            'upstream_evidence':{file:sha(ROOT/file) for file in upstream},
            'build':json.loads((ROOT/'analysis/hrc-native/build/build.json').read_text()),
            'scope':{'production_deal_lookup_terminal_traversal_storage':True,'fresh_zero':True,
                     'synthetic_addressing_maps':True,'independent_strict_maps':True,
                     'formats':[25,27,31],'continuous_vs_resumed_checkpoint_byte_exact':True,
                     'original_solver_called_by_integration_tests':False,'mode2_supported':False,
                     'not_proven':['original full worker random stream equivalence','multithreaded schedule','equilibrium convergence','full product equivalence']}}
    destination=ROOT/'reports/hrc-native-dynamic-validation.json';destination.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({'passed':report['passed'],'cases':report['cases'],'report':str(destination)}))
    raise SystemExit(completed.returncode)

if __name__=='__main__':main()
