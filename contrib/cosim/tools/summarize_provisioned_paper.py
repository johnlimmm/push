#!/usr/bin/env python3
"""Audit fresh v4 P5-B/cost evidence and join it with the full regression result."""
import gzip
import hashlib
import json
from pathlib import Path
import sys

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
sys.path[:0]=[str(MODULE/'experiments'),str(MODULE/'python')]
from run_provisioned_p5b import verify_frozen


def read(path):
    with (gzip.open(str(path),'rt') if path.suffix=='.gz' else path.open()) as stream:
        return json.load(stream)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    verify_frozen()
    paths=dict(p5b=MODULE/'results/provisioned-p5b-expanded/summary.json',
        scaling=MODULE/'results/provisioned-paper-scaling/summary.json',
        regression=MODULE/'results/provisioned-paper-regression/summary.json',
        paper=MODULE/'paper/provisioned-v4/results-summary.json')
    evidence={name:read(path) for name,path in paths.items()}
    if not all(v['passed'] and v['architecture']=='provisioned-native-v4' for v in evidence.values()):
        raise RuntimeError('incomplete v4 evidence')
    p5b=evidence['p5b'];cost=evidence['scaling'];reg=evidence['regression']
    assert (p5b['paired_cases'],p5b['execution_runs'],p5b['calibration_runs'],p5b['transactions_per_model'])==(384,1152,6,1536)
    assert cost['measured_runs']==120 and cost['warmup_runs']==12 and cost['fifo_timing_requests']==500
    assert cost['fifo_timing_max_error_ns']==0 and cost['all_repetition_trace_hashes_equal']
    assert reg['total_test_cases']==291 and reg['published_evidence_preserved']
    for summary in (p5b,cost):
        for path,want in summary['source_sha256'].items():
            assert sha(MODULE/path)==want,path
    plan=p5b['plan'];assert not set(plan['calibration_traffic_seeds']) & set(plan['test_traffic_seeds'])
    assert len(plan['test_traffic_seeds'])==32 and len(plan['quantum_seeds'])==2
    assert plan['fidelity_min']==.5 and plan['deadline_ns']==5000000

    # Read original reports, not only aggregate booleans. Ensure all variants kept
    # the same input/noise/quantum channels and resource waiting, with real UDP
    # only in Full-Sync/No-Dq-R and no B-wait in the P5-B study.
    raw_hashes={};checks=0
    directory=paths['p5b'].parent
    for case in p5b['cases']:
        folder=(directory/case['path']).parent
        reports={name:read(folder/(name+'.json.gz')) for name in ('Full-Sync','No-Dq-R','Fixed-Dc')}
        base=reports['Full-Sync']
        base_resources=[r for r in base['snapshot']['resources'] if r['handle']!='output']
        for name,report in reports.items():
            assert report['architecture']=='provisioned-native-v4'
            assert report['config']==base['config']
            assert report['config']['quantum_links']==plan['quantum_links']
            assert report['validation']['passed'] and report['cross_validation']['passed']
            assert [r for r in report['snapshot']['resources'] if r['handle']!='output']==base_resources
            assert all(m['correction_wait_ns']==0 for m in report['metrics']['sessions'])
            assert [m['resource_wait_ns'] for m in report['metrics']['sessions']]==[200000,0,0,0]
            for metric in report['metrics']['sessions']:
                assert metric['transaction_latency_ns']==(metric['resource_wait_ns']+metric['quantum_wait_ns']+
                    report['config']['bsm_duration_ns']+metric['result_delay_ns']+
                    metric['correction_wait_ns']+report['config']['correction_duration_ns'])
            if name=='No-Dq-R':assert all(m['quantum_wait_ns']==0 for m in report['metrics']['sessions'])
            if name=='Fixed-Dc':assert 'ns3_events' not in report
            else:
                assert report['q2ns_status']['native_qubit_count']==report['q2ns_status']['native_state_count']==0
                assert not any('DROP' in row['event_type'] for row in report['ns3_events'])
            file=folder/(name+'.json.gz');raw_hashes[str(file.relative_to(MODULE))]=sha(file);checks+=1
    assert checks==1152
    calibration=read(directory/'calibration.json')
    calibration_runs=0
    for entry in calibration['by_classical_load'].values():
        for run in entry['runs']:
            file=directory/run['report'];report=read(file)
            assert report['architecture']=='provisioned-native-v4'
            assert report['config']['quantum_links']==plan['quantum_links']
            assert report['validation']['passed'] and report['cross_validation']['passed']
            assert run['traffic_seed'] in plan['calibration_traffic_seeds']
            raw_hashes[str(file.relative_to(MODULE))]=sha(file);calibration_runs+=1
    assert calibration_runs==6
    for path in (MODULE/'results/provisioned-paper-scaling/traces').glob('*.json.gz'):
        report=read(path);assert report['cross_validation']['passed']
        raw_hashes[str(path.relative_to(MODULE))]=sha(path)
    maximum=max(p5b['max_density_matrix_error'],cost['max_density_matrix_error'])
    assert maximum<=1e-12
    sources=list((MODULE/'experiments').glob('*provisioned*.py'))
    sources+=list((MODULE/'tools').glob('*provisioned*paper*.py'))
    sources += [MODULE/'experiments/tests/test_provisioned_evaluation.py',
        MODULE/'README-PROVISIONED-EVALUATION.md',MODULE/'scenarios/provisioned-p5b-expanded.json',
        MODULE/'scenarios/provisioned-paper-validation.json']
    result=dict(passed=True,architecture='provisioned-native-v4',milestone='v4-P5B-and-cost',
        total_test_cases=291,new_evaluation_tests=13,paired_cases=384,execution_runs=1152,
        calibration_runs=6,transactions_per_model=1536,scaling_measured_runs=120,scaling_warmup_runs=12,
        max_density_matrix_error=maximum,ready_gated_fifo_requests=500,max_timing_error_ns=0,
        v3_and_v4_correctness_sources_unchanged=True,all_models_preserve_provisioning=True,
        no_dq_keeps_resource_wait=True,p5b_no_b_wait=True,p5b_no_classical_drop=True,
        raw_reports_audited=checks,quantum_links=plan['quantum_links'],
        evidence={name:dict(path=str(path.relative_to(ROOT)),sha256=sha(path)) for name,path in paths.items()},
        raw_report_sha256=raw_hashes,
        source_sha256={str(path.relative_to(ROOT)):sha(path) for path in sorted(set(sources))},
        interpretation='Fixed quantum links, t=0 pre-generated EPRs, lossless and ideal readiness. Finite traffic-phase workload with fixed two-seed calibration. Cost repetitions measure host variability, not isolated IPC overhead.',
        prior_evidence='v3 paper/RESULTS.md and prior v4 provisioning results remain unchanged; fresh v4 paper in paper/provisioned-v4.')
    (MODULE/'results/provisioned-paper-validation-summary.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('v4 paper: 291 tests; 384 paired cases; 120 cost repetitions; max state error {:.3g}; PASS'.format(maximum))


if __name__=='__main__':main()
