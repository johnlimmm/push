#!/usr/bin/env python3
"""Full regression with atomic published evidence preserved byte-for-byte."""
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from validate_hybrid_v1 import NATIVE_SUITES

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
OUT=MODULE/'results/native-timed'


def run(command, name):
    start=time.monotonic()
    with (OUT/name).open('w') as stream:
        proc=subprocess.run(command,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
    return dict(command=command,log=name,returncode=proc.returncode,elapsed_seconds=time.monotonic()-start)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    tracked=subprocess.check_output(['git','ls-files','-z','contrib/cosim/results'],cwd=str(ROOT)).decode().split('\0')
    original={name:(ROOT/name).read_bytes() for name in tracked if name and (ROOT/name).is_file()}
    suites={};native={}
    try:
        for name,folder,count in [('python','tests',159),('paper','experiments/tests',16)]:
            result=run([sys.executable,'-m','unittest','discover','-s','contrib/cosim/'+folder,'-v'],name+'-regression.log')
            text=(OUT/result['log']).read_text()
            match=re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',text)
            result['tests']=int(match.group(1)) if match else 0
            result['passed']=result['returncode']==0 and result['tests']==count
            suites[name]=result;print(name+': '+str(result['passed']),flush=True)
        for name,count in NATIVE_SUITES.items():
            result=run(['build/utils/ns3.47-test-runner-default','--suite='+name,'--verbose'],name+'.log')
            text=(OUT/result['log']).read_text();result['tests']=len(re.findall(r'^  PASS ',text,re.MULTILINE))
            result['passed']=result['returncode']==0 and result['tests']==count and text.startswith('PASS '+name+' ') and 'FAIL' not in text
            native[name]=result;print(name+': '+str(result['passed']),flush=True)
    finally:
        # Old regression suites write into their historical output locations.
        # Keep this rerun's copies, then restore the published atomic artifacts.
        for name,previous in original.items():
            current=ROOT/name
            if current.exists() and current.read_bytes()!=previous:
                copy=OUT/'atomic-regression'/current.relative_to(MODULE/'results')
                copy.parent.mkdir(parents=True,exist_ok=True);copy.write_bytes(current.read_bytes())
            current.write_bytes(previous)
    result=dict(architecture='native-timed-v3',date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        suites=suites,native_suites=native,atomic_published_evidence_preserved=True,
        total_test_cases=sum(v['tests'] for v in list(suites.values())+list(native.values())),
        passed=all(v['passed'] for v in list(suites.values())+list(native.values())))
    (OUT/'regression-summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    if not result['passed']:raise SystemExit('Regression failed: inspect native-timed logs')
    print('Native timed: {} tests PASS'.format(result['total_test_cases']),flush=True)


if __name__=='__main__':main()
