#!/usr/bin/env python3
"""Run all 291 tests while preserving every published v3 result byte-for-byte."""
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time
from validate_hybrid_v1 import NATIVE_SUITES

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
OUT=MODULE/'results/provisioned-paper-regression'


def run(command,name):
    start=time.monotonic()
    with (OUT/name).open('w') as stream:
        proc=subprocess.run(command,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
    return dict(command=command,log=name,returncode=proc.returncode,elapsed_seconds=time.monotonic()-start)


def main():
    if OUT.exists():raise ValueError('completed or partial provisioning regression already exists')
    OUT.mkdir(parents=True)
    names=subprocess.check_output(['git','ls-files','-z','contrib/cosim/results'],cwd=str(ROOT)).decode().split('\0')
    original={name:(ROOT/name).read_bytes() for name in names if name and (ROOT/name).is_file()}
    suites={};native={}
    try:
        for name,folder,count in [('python','tests',179),('paper','experiments/tests',29)]:
            result=run([sys.executable,'-m','unittest','discover','-s','contrib/cosim/'+folder,'-v'],name+'.log')
            match=re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',(OUT/result['log']).read_text())
            result['tests']=int(match.group(1)) if match else 0
            result['passed']=result['returncode']==0 and result['tests']==count
            suites[name]=result;print(name+': '+str(result['passed']),flush=True)
        for name,count in NATIVE_SUITES.items():
            result=run(['build/utils/ns3.47-test-runner-default','--suite='+name,'--verbose'],name+'.log')
            text=(OUT/result['log']).read_text();result['tests']=len(re.findall(r'^  PASS ',text,re.MULTILINE))
            result['passed']=result['returncode']==0 and result['tests']==count and text.startswith('PASS '+name+' ') and 'FAIL' not in text
            native[name]=result;print(name+': '+str(result['passed']),flush=True)
    finally:
        for name,previous in original.items():
            current=ROOT/name
            if current.exists() and current.read_bytes()!=previous:
                dest=OUT/'replayed-published'/current.relative_to(MODULE/'results')
                dest=dest.with_name(dest.name+'.gz');dest.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(str(dest),'wb') as stream:stream.write(current.read_bytes())
            current.write_bytes(previous)
    manifest=json.loads((MODULE/'baselines/native-v3-freeze.json').read_text())
    unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in manifest['source_sha256'].items())
    result=dict(architecture='provisioned-native-v4',date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        suites=suites,native_suites=native,published_evidence_preserved=True,v3_sources_unchanged=unchanged,
        total_test_cases=sum(v['tests'] for v in list(suites.values())+list(native.values())),
        passed=unchanged and all(v['passed'] for v in list(suites.values())+list(native.values())))
    (OUT/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    if not result['passed']:raise SystemExit('Regression failed: inspect provisioning logs')
    print('{} regression test cases PASS'.format(result['total_test_cases']),flush=True)


if __name__=='__main__':main()
