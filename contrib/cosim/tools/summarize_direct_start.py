#!/usr/bin/env python3
"""Summarize rerun v2 evidence; refuse old-architecture reports or failed suites."""
import datetime
import hashlib
import json
from pathlib import Path
from verify_hybrid_v1 import verify, DEFAULT

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
RESULTS=MODULE/'results'
ARCH='direct-session-start-v2'


def load(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verify(DEFAULT,archive_only=True)
    base=RESULTS/'direct-start';reg=load(base/'regression-summary.json')
    assert reg['passed'] and reg['total_test_cases']==230 and reg['architecture']==ARCH
    coverage=load(base/'hybrid-branch-coverage.json')
    assert coverage['passed'] and coverage['transactions']==160
    assert all(set(v)=={'00','01','10','11'} for v in coverage['branches'].values())
    scenarios={};maximum=coverage['max_density_matrix_error']
    evidence=[base/'regression-summary.json',base/'hybrid-branch-coverage.json']
    for name in ('teleport','mixed','mixed-fast-bsm','swap-quantum-only','swap-joint-result',
                 'swap-matched-quantum-only','swap-matched-joint-result'):
        path=base/('hybrid-'+name+'.json');r=load(path);evidence.append(path)
        assert r['architecture']==ARCH and r['validation']['passed'] and r['cross_validation']['passed']
        assert r['nodes']==dict(A=0,R=1,B=2)
        assert not any(e['event_type'].startswith('COMMAND_') for e in r['ns3_events'])
        scenarios[name]=dict(report=str(path.relative_to(RESULTS)),nodes=r['nodes'],passed=True,
            q2ns_status=r['q2ns_status'],metrics=r['metrics'],batch_completion_ns=r['batch_completion_ns'],
            max_density_matrix_error=r['cross_validation']['max_density_matrix_error'])
        maximum=max(maximum,r['cross_validation']['max_density_matrix_error'])
    negative=load(base/'hybrid-overflow-rejected.json')
    assert not negative['validation']['passed'] and 'packet drop' in negative['validation']['error']
    evaluations={}
    for name in ('p5b-pilot','p5b-expanded','timing','scaling'):
        path=RESULTS/('direct-start-'+name)/'summary.json';r=load(path);evidence.append(path)
        assert r['passed'] and r['architecture']==ARCH
        evaluations[name]=dict(summary=str(path.relative_to(RESULTS)),sha256=sha(path),passed=True)
        for key in ('paired_cases','execution_runs','calibration_runs','transactions_per_model',
                    'max_density_matrix_error','case_count','requests','max_absolute_error_ns',
                    'measured_runs','warmup_runs','native_timing_replay_requests','native_timing_replay_max_error_ns'):
            if key in r:evaluations[name][key]=r[key]
        maximum=max(maximum,r.get('max_density_matrix_error',0))
    # The experiment tools live with active v2 sources. Historical stages and the
    # immutable v1 archive remain separate, rather than claiming byte equivalence.
    paths=[MODULE/'examples/cosim-hybrid.cc',MODULE/'python/run_hybrid.py',MODULE/'python/netsquid_reference_hybrid.py',
           MODULE/'tests/test_hybrid.py',MODULE/'tests/test_p5b.py',Path(__file__).resolve(),MODULE/'tools/validate_direct_start.py',
           MODULE/'tools/audit_direct_start.py',ROOT/'scratch/cosim-hybrid/CMakeLists.txt']
    paths+=list((MODULE/'python').glob('hybrid_*.py'))
    paths+=list((MODULE/'experiments').glob('*.py'))+list((MODULE/'experiments/tests').glob('*.py'))
    paths+=list((MODULE/'scenarios').glob('hybrid-*.json'))+list((MODULE/'scenarios').glob('p5b-*.json'))
    patches={}
    for name in ('swap','teleport'):
        manifest=MODULE/'integrations'/('q2ns-'+name+'-external.json');p=load(manifest)
        assert sha(manifest.parent/p['patch'])==p['patch_sha256']
        assert all(sha(ROOT/'contrib/q2ns'/n)==v for n,v in p['source_sha256'].items())
        patches[name]=p
    result=dict(architecture=ARCH,milestone='Hybrid v2: direct R session activation',passed=True,
        date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        scope='A/R/B, local Q2NS start at R, shared R/B FIFO, native R-to-B UDP result, NetSquid sole state ownership and T1/T2 aging',
        latency_definition='correction completion - local session_start_ns',
        total_test_cases=reg['total_test_cases'],regression=reg,branch_coverage=coverage,
        scenarios=scenarios,evaluations=evaluations,max_density_matrix_error=maximum,
        historical_v1_archive_unchanged=True,current_sources_equal_v1=False,q2ns_patches_unchanged=patches,
        overflow_negative_test=dict(expected_failure=True,report='direct-start/hybrid-overflow-rejected.json'),
        source_sha256={str(p.relative_to(ROOT)):sha(p) for p in sorted(set(paths))},
        evidence_sha256={str(p.relative_to(RESULTS)):sha(p) for p in evidence})
    destination=RESULTS/'direct-start-validation-summary.json'
    destination.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('{}: {} tests; max state error {:.3g}; PASS'.format(ARCH,result['total_test_cases'],maximum))

if __name__=='__main__':main()
