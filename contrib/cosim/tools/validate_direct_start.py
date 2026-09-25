#!/usr/bin/env python3
"""Run all historical and current regression suites for direct-start Hybrid v2."""
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from validate_hybrid_v1 import NATIVE_SUITES
from verify_hybrid_v1 import verify, DEFAULT

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
OUT=MODULE/'results/direct-start'


def run(command,name):
    at=time.monotonic()
    with (OUT/name).open('w') as stream:
        p=subprocess.run(command,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
    return dict(command=command,log=name,returncode=p.returncode,elapsed_seconds=time.monotonic()-at)


def main():
    OUT.mkdir(exist_ok=True);verify(DEFAULT,archive_only=True)
    suites={}
    for name,path,count in [('python','tests',140),('paper','experiments/tests',7)]:
        r=run([sys.executable,'-m','unittest','discover','-s','contrib/cosim/'+path,'-v'],name+'-regression.log')
        match=re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',(OUT/r['log']).read_text())
        r['tests']=int(match.group(1)) if match else 0
        r['passed']=r['returncode']==0 and r['tests']==count
        suites[name]=r;print(name+': '+str(r['passed']),flush=True)
    native={}
    for name,count in NATIVE_SUITES.items():
        r=run(['build/utils/ns3.47-test-runner-default','--suite='+name,'--verbose'],name+'.log')
        text=(OUT/r['log']).read_text();r['tests']=len(re.findall(r'^  PASS ',text,re.MULTILINE))
        r['passed']=r['returncode']==0 and r['tests']==count and text.startswith('PASS '+name+' ') and 'FAIL' not in text
        native[name]=r;print(name+': '+str(r['passed']),flush=True)
    result=dict(architecture='direct-session-start-v2',date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        test_suites=suites,native=native,historical_v1_archive_unchanged=True,
        total_test_cases=sum(r['tests'] for r in list(suites.values())+list(native.values())),
        passed=all(r['passed'] for r in list(suites.values())+list(native.values())))
    (OUT/'regression-summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    if not result['passed']:raise SystemExit('Regression failure: inspect results/direct-start logs')
    print('Direct-start: {} tests PASS'.format(result['total_test_cases']))

if __name__=='__main__':main()
