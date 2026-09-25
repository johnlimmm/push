#!/usr/bin/env python3
"""Audit saved v2 run artifacts against their CSVs, aggregates and provenance."""
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
RESULTS=MODULE/'results'
PAPER=MODULE/'paper'
ARCH='direct-session-start-v2'


def read(path):return json.loads(path.read_text())
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def close(a,b):assert abs(a-b)<=1e-9*max(1,abs(a),abs(b)),(a,b)


def main():
    summary=read(RESULTS/'direct-start-validation-summary.json')
    assert summary['passed'] and summary['architecture']==ARCH and summary['total_test_cases']==230
    for name,value in summary['source_sha256'].items():assert sha(ROOT/name)==value,name
    for name,value in summary['evidence_sha256'].items():assert sha(RESULTS/name)==value,name
    paper=read(PAPER/'results-summary.json')
    assert paper['architecture']==ARCH
    for name,value in paper['evidence'].items():assert sha(ROOT/name)==value,name
    counts={}
    for name,expected_cases in [('pilot',48),('expanded',384)]:
        folder=RESULTS/('direct-start-p5b-'+name);evaluation=read(folder/'summary.json')
        rows=list(csv.DictReader((folder/'errors.csv').open()))
        assert len(evaluation['cases'])==expected_cases and len(rows)==12*expected_cases
        rows_by_case={}
        for r in rows:
            key=(float(r['classical_load']),int(r['request_interval_ns']),int(r['traffic_seed']),int(r['quantum_seed']),r['model'],int(r['session_id']))
            assert key not in rows_by_case
            rows_by_case[key]=r
        for case in evaluation['cases']:
            comparison=read(folder/case['path'])
            full={m['session_id']:m for m in comparison['models']['Full-Sync']}
            for model,metrics in comparison['models'].items():
                if model!='Decoupled':
                    report=read((folder/case['path']).parent/(model+'.json'))
                    assert report['architecture']==ARCH and report['validation']['passed'] and report['cross_validation']['passed']
                    assert set(report['config']['background'])=={'result'}
                    assert not any('command' in k for k in report['config'])
                    assert not any('command' in k for s in report['config']['sessions'] for k in s)
                    requests={(r['session_id'],r['operation']):r for r in report['snapshot']['requests']}
                    for m in metrics:
                        b=requests[m['session_id'],'BSM'];c=requests[m['session_id'],'CORRECTION']
                        assert b['arrival_ns']==m['session_start_ns']
                        assert m['transaction_latency_ns']==c['completion_ns']-b['arrival_ns']
                        assert m['transaction_latency_ns']==m['quantum_wait_ns']+report['config']['bsm_duration_ns']+m['result_delay_ns']+report['config']['correction_duration_ns']
                        assert m['correction_wait_ns']==0
                        assert m['deadline_ok']==(m['transaction_latency_ns']<=evaluation['plan']['deadline_ns'])
                        assert m['feasible']==(m['deadline_ok'] and m['usable_fidelity']>=evaluation['plan']['fidelity_min'])
                    if model=='Fixed-Dc':assert set(report['fixed_delays'])=={'result_ns'}
                    else:
                        assert report['nodes']==dict(A=0,R=1,B=2)
                        assert not any(r['event_type'].startswith('COMMAND_') or 'DROP' in r['event_type'] for r in report['ns3_events'])
                        assert report['q2ns_status']['native_qubit_count']==report['q2ns_status']['native_state_count']==0
                if model=='Full-Sync':continue
                for m in metrics:
                    f=full[m['session_id']]
                    key=(case['classical_load'],case['request_interval_ns'],case['traffic_seed'],case['quantum_seed'],model,m['session_id'])
                    r=rows_by_case[key]
                    assert int(r['delta_latency_ns'])==m['transaction_latency_ns']-f['transaction_latency_ns']
                    if model=='Decoupled':assert r['delta_fidelity']==r['false_feasible']==''
                    else:
                        close(float(r['delta_fidelity']),m['usable_fidelity']-f['usable_fidelity'])
                        close(float(r['delta_expected_fidelity']),m['expected_fidelity']-f['expected_fidelity'])
                        assert int(r['false_feasible'])==int(m['feasible'] and not f['feasible'])
                        assert int(r['false_infeasible'])==int(not m['feasible'] and f['feasible'])
        for g in evaluation['groups']:
            group=[r for r in rows if r['model']==g['model'] and float(r['classical_load'])==g['classical_load'] and int(r['request_interval_ns'])==g['request_interval_ns']]
            for field,metric,absolute in [('delta_latency_ns','latency_mae_ns',True),('delta_latency_ns','latency_bias_ns',False),
                ('delta_expected_fidelity','expected_fidelity_bias',False),('false_feasible','false_feasible_rate',False),
                ('false_infeasible','false_infeasible_rate',False),('false_deadline_feasible','false_deadline_feasible_rate',False)]:
                clusters=defaultdict(list)
                for r in group:
                    if r[field]!='':clusters[int(r['traffic_seed'])].append(abs(float(r[field])) if absolute else float(r[field]))
                if not clusters:assert g[metric] is None
                else:
                    close(g[metric]['mean'],sum(sum(v)/len(v) for v in clusters.values())/len(clusters))
                    assert g[metric]['traffic_clusters']==len(clusters)
        counts[name]=dict(paired_cases=expected_cases,csv_rows=len(rows),raw_execution_reports=3*expected_cases)
    timing=read(RESULTS/'direct-start-timing/summary.json')
    timing_rows=list(csv.DictReader((PAPER/'timing.csv').open()))
    assert len(timing_rows)==timing['requests']==2500
    assert all(r['qucl_'+k]==r['native_'+k] for r in timing_rows for k in ('start_ns','completion_ns','waiting_ns'))
    scaling=read(RESULTS/'direct-start-scaling/summary.json')
    assert len(list(csv.DictReader((PAPER/'scaling.csv').open())))==len(scaling['rows'])==120
    for g in scaling['groups']:
        rows=[r for r in scaling['rows'] if r['sessions']==g['sessions'] and r['classical_load']==g['classical_load']]
        assert len(rows)==10 and len({r['trace_sha256'] for r in rows})==1
        assert all(r['counters']==g['counters'] for r in rows)
        close(g['simulation_seconds']['mean'],sum(r['simulation_seconds'] for r in rows)/10)
    original=Path('/home/ns3/QuCl.pdf')
    result=dict(passed=True,architecture=ARCH,full_regression_rerun=True,total_test_cases=230,
        artifact_counts=counts,synthetic_timing_rows=2500,scaling_measurements=120,
        source_and_evidence_hashes_match=True,raw_comparison_csv_aggregates_match=True,
        no_command_path_in_evaluation=True,latency_decomposition_matches=True,
        manuscript_rebuilt=False,original_manuscript_sha256=sha(original) if original.exists() else None,
        evidence_sha256={'results/direct-start-validation-summary.json':sha(RESULTS/'direct-start-validation-summary.json')},
        artifact_sha256={str(p.relative_to(MODULE)):sha(p) for p in sorted(PAPER.rglob('*'))
                         if p.is_file() and p.name!='validation-checks.json'})
    (PAPER/'validation-checks.json').write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('Direct-start audit: raw model traces, paired CSVs, aggregates, clocks and provenance PASS')

if __name__=='__main__':main()
