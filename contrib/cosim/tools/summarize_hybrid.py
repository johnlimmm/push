#!/usr/bin/env python3
"""저장된 suite 로그와 실제 report/원본 해시를 검사하여 milestone 요약을 생성한다."""
import hashlib
import json
from pathlib import Path
import re

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
RESULTS=MODULE/'results'

def read(name):return json.loads((RESULTS/name).read_text())
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def suite(name,expected):
    text=(RESULTS/name).read_text()
    match=re.search(r'Ran (\d+) tests in ([\d.]+)s\s+OK\s*$',text)
    if not match or int(match.group(1))!=expected:raise RuntimeError('suite did not pass: '+name)
    return dict(passed=True,tests=int(match.group(1)),elapsed_seconds=float(match.group(2)),log=name)


def main():
    python_suites=dict(hybrid=suite('hybrid-test-suite.log',14),
                       p0_p5b_q2ns=suite('hybrid-regression-suite.log',122))
    native=read('hybrid-native-test-summary.json')
    if not native['passed'] or native['test_cases']!=83:raise RuntimeError('native regression failed')
    freeze=json.loads((MODULE/'baselines/p5b-freeze.json').read_text())
    if digest(MODULE/'baselines'/freeze['archive'])!=freeze['archive_sha256']:raise RuntimeError('archive changed')
    for name,value in freeze['file_sha256'].items():
        if '/results/' not in name and digest(ROOT/name)!=value:raise RuntimeError('frozen source changed: '+name)
    patch=json.loads((MODULE/'integrations/q2ns-teleport-external.json').read_text())
    if digest(MODULE/'integrations'/patch['patch'])!=patch['patch_sha256']:raise RuntimeError('patch changed')
    for name,value in patch['source_sha256'].items():
        if digest(ROOT/'contrib/q2ns'/name)!=value:raise RuntimeError('Q2NS patch source changed: '+name)
    coverage=read('hybrid-branch-coverage.json');equivalence=read('hybrid-swap-equivalence.json')
    if not coverage['passed'] or not all(v['passed'] for v in equivalence.values()):raise RuntimeError('coverage/equivalence failed')
    scenarios={};maximum=coverage['max_density_matrix_error']
    for name in ['teleport','mixed','mixed-fast-bsm','swap-quantum-only','swap-joint-result','swap-joint-both']:
        filename='hybrid-'+name+'.json';report=read(filename)
        if not report['validation']['passed'] or not report['cross_validation']['passed']:raise RuntimeError(filename)
        maximum=max(maximum,report['cross_validation']['max_density_matrix_error'])
        requests=report['snapshot']['requests']
        scenarios[name]=dict(passed=True,report=filename,
            max_density_matrix_error=report['cross_validation']['max_density_matrix_error'],
            q2ns_status=report['q2ns_status'],sessions=[dict(session_id=int(sid),protocol=s['protocol'],
                usable_fidelity=s['checkpoints']['usable']['fidelity'],
                completion_ns=s['checkpoints']['usable']['sim_time_ns'],
                waiting_ns={r['operation']:r['start_ns']-r['arrival_ns'] for r in requests if str(r['session_id'])==sid})
                for sid,s in report['snapshot']['sessions'].items()])
    negative=read('hybrid-overflow-rejected.json')
    if negative['validation']['passed'] or 'packet drop' not in negative['validation']['error']:raise RuntimeError('overflow test')
    sources=[MODULE/'README-HYBRID.md',MODULE/'SPEC-HYBRID.md',MODULE/'examples/cosim-hybrid.cc',
             MODULE/'python/run_hybrid.py',MODULE/'python/netsquid_reference_hybrid.py',
             MODULE/'tests/test_hybrid.py',Path(__file__),ROOT/'scratch/cosim-hybrid/CMakeLists.txt']
    sources+=sorted((MODULE/'python').glob('hybrid_*.py'))
    sources+=sorted((MODULE/'scenarios').glob('hybrid-*.json'))
    summary=dict(date='2026-09-16',milestone='Multi-Protocol Hybrid Execution: Teleportation Integration',
        passed=True,scope='Fixed C/A/R/B placement, IPv4/UDP, pre-created input/EPR, atomic BSM/correction; shared R/B FIFO; native T1/T2 aging.',
        common_core='HybridExecutionCore',common_federation='HybridFederation',
        python_tests=136,native_test_cases=83,total_test_cases=219,
        test_suites=python_suites,native_summary='hybrid-native-test-summary.json',
        max_density_matrix_error=maximum,branch_coverage=coverage,swap_equivalence=equivalence,
        scenarios=scenarios,frozen_sources_unchanged=True,freeze='baselines/p5b-freeze.json',
        q2ns_patch=patch,overflow_negative_test=dict(expected_failure=True,report='hybrid-overflow-rejected.json'),
        source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sources})
    (RESULTS/'hybrid-validation-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    print('Hybrid: 219 tests, 160 branch transactions, max state error {:.3g}; PASS'.format(maximum))

if __name__=='__main__':main()
