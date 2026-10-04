#!/usr/bin/env python3
"""Run preserved baseline regression and assemble new chain evidence without overwriting archives."""
import datetime
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from validate_hybrid_v1 import NATIVE_SUITES

MODULE=Path(__file__).resolve().parents[1];ROOT=MODULE.parents[1]
OUT=MODULE/'results/chained-regression'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh-chained-only',action='store_true',
        help='Update the chained suite from a fresh log; retain dated frozen baseline evidence')
    parser.add_argument('--chained-log',type=Path,default=Path('/tmp/chained-tests.log'))
    args=parser.parse_args()
    if args.refresh_chained_only:
        result=json.loads((OUT/'summary.json').read_text())
        assert result['passed']
        match=re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK\s*$',args.chained_log.read_text())
        if not match or int(match.group(1))!=17:raise ValueError('requires a fresh passing 17-case chained log')
        frozen=json.loads((MODULE/'baselines/provisioned-v4-freeze.json').read_text())
        assert all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen['source_sha256'].items())
        result.setdefault('baseline_evidence_date',result['date'])
        result['date']=datetime.datetime.now(datetime.timezone.utc).isoformat()
        result['rerun_scope']='chained only; unchanged frozen baseline suite results retained'
        dest=OUT/args.chained_log.name
        if args.chained_log.resolve()!=dest.resolve():shutil.copyfile(str(args.chained_log),str(dest))
        result['suites']['chained']=dict(tests=int(match.group(1)),passed=True,
            elapsed_seconds=float(match.group(2)),log=dest.name,date=result['date'])
        result['total_test_cases']=sum(v['tests'] for v in result['suites'].values())
        (OUT/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
        print('Refreshed chained suite; frozen baseline evidence retained from '+result['baseline_evidence_date'])
        return
    if OUT.exists():raise ValueError('choose a clean regression output directory')
    OUT.mkdir(parents=True)
    names=subprocess.check_output(['git','ls-files','-z','contrib/cosim/results'],cwd=str(ROOT)).decode().split('\0')
    original={n:(ROOT/n).read_bytes() for n in names if n and (ROOT/n).is_file()}
    suites={}
    def run(command,name,count,native=False):
        start=time.monotonic()
        path=OUT/(name+'.log')
        with path.open('w') as stream:p=subprocess.run(command,cwd=str(ROOT),stdout=stream,stderr=subprocess.STDOUT)
        log=path.read_text()
        match=re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',log)
        tests=len(re.findall(r'^  PASS ',log,re.MULTILINE)) if native else int(match.group(1)) if match else 0
        suites[name]=dict(command=command,tests=tests,passed=p.returncode==0 and tests==count,
            elapsed_seconds=time.monotonic()-start,log=path.name)
        print(name+': '+str(suites[name]['passed']),flush=True)
    try:
        # New tests already ran once; do not repeat the same 96 branch runs.
        code='''import unittest
suite=unittest.defaultTestLoader.discover('contrib/cosim/tests')
def flatten(s):
 for t in s:
  if isinstance(t,unittest.TestSuite):
   yield from flatten(t)
  elif t.__class__.__module__!='test_chained':yield t
result=unittest.TextTestRunner(verbosity=2).run(unittest.TestSuite(flatten(suite)))
raise SystemExit(not result.wasSuccessful())
'''
        run([sys.executable,'-c',code],'existing-python',179)
        run([sys.executable,'-m','unittest','discover','-s','contrib/cosim/experiments/tests','-v'],'existing-evaluation',29)
        for name,count in NATIVE_SUITES.items():
            run(['build/utils/ns3.47-test-runner-default','--suite='+name,'--verbose'],name,count,True)
    finally:
        for name,previous in original.items():
            current=ROOT/name
            if current.exists() and current.read_bytes()!=previous:
                dest=OUT/'replayed-published'/current.relative_to(MODULE/'results')
                dest=dest.with_name(dest.name+'.gz');dest.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(str(dest),'wb') as stream:stream.write(current.read_bytes())
            current.write_bytes(previous)
    shutil.copyfile(str(args.chained_log),OUT/'chained-tests.log')
    text=(OUT/'chained-tests.log').read_text();match=re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',text)
    suites['chained']=dict(tests=int(match.group(1)) if match else 0,passed=bool(match) and int(match.group(1))==17,log='chained-tests.log')
    frozen=json.loads((MODULE/'baselines/provisioned-v4-freeze.json').read_text())
    unchanged=all(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==h for p,h in frozen['source_sha256'].items())
    result=dict(date=datetime.datetime.now(datetime.timezone.utc).isoformat(),suites=suites,
        total_test_cases=sum(v['tests'] for v in suites.values()),frozen_sources_unchanged=unchanged,
        published_evidence_preserved=True,passed=unchanged and all(v['passed'] for v in suites.values()))
    (OUT/'summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    if not result['passed']:raise SystemExit('chained regression failed')


if __name__=='__main__':main()
