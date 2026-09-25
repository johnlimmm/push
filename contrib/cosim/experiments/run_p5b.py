#!/usr/bin/env python3
"""P5-B: frozen Q2NS Full Sync와 세 단순화 모델을 동일 workload에서 비교한다."""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import sys

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))

from run_hybrid import HybridManager
from hybrid_config import expected_timing, normalize_config
from p5b_nodq import NoDqManager
from p5b_fixed import run_fixed
from p5b_timing import no_dq_timing, fixed_timing, decoupled
from p5b_workload import validate_plan, workload, workload_digest, calibration_entry, digest
from p5b_analysis import model_rows, compare, summarize


def save(path, value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')


def verify_frozen():
    manifest=json.loads((MODULE/'baselines/q2ns-freeze.json').read_text())
    root=MODULE.parents[1]
    # 결과는 재실행으로 갱신 가능하다. 소스·설정·명세와 nested Q2NS 변경분은 고정한다.
    for name,h in manifest['file_sha256'].items():
        if '/results/' not in name and hashlib.sha256((root/name).read_bytes()).hexdigest()!=h:
            raise RuntimeError('frozen source changed: '+name)
    archive=MODULE/'baselines'/manifest['archive']
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=manifest['archive_sha256']:
        raise RuntimeError('frozen archive changed')
    return True


class ReferenceCache(dict):
    """Shared cache keyed by the complete independent reference specification.

    The hybrid validator includes protocol, noise, creation times and all actual
    operation/packet-arrival timestamps. No sampled state is cached.
    """
    pass


def run_model(config,model,cache,delays=None):
    if model not in ('Full-Sync','No-Dq-R','Fixed-Dc'):
        raise ValueError('unknown execution model: '+model)
    config=normalize_config(config)
    timing=(expected_timing(config)['sessions'] if model=='Full-Sync' else
            no_dq_timing(config)['sessions'] if model=='No-Dq-R' else fixed_timing(config,delays)['sessions'])
    if any(t['correction_wait_ns'] for t in timing.values()):
        raise ValueError(model+': workload violates B wait=0')
    refs=cache
    report=(HybridManager(config).run(refs) if model=='Full-Sync' else
            NoDqManager(config).run(refs) if model=='No-Dq-R' else run_fixed(config,delays,refs))
    return report


def evaluate(raw, destination):
    plan=validate_plan(raw); verify_frozen(); destination=Path(destination)
    if (destination/'summary.json').exists(): raise ValueError('choose a new output directory; evaluation already exists')
    save(destination/'plan.json',plan); cache=ReferenceCache(); calibration={}; max_error=0.0
    # 이 단계는 test workload를 실행하거나 읽기 전에 끝낸다.
    for load in plan['classical_loads']:
        records=[]; provenance=[]
        for seed in plan['calibration_traffic_seeds']:
            cfg=workload(plan,load,plan['calibration_request_interval_ns'],seed,plan['quantum_seeds'][0])
            report=run_model(cfg,'Full-Sync',cache)
            path='calibration/load-{}-traffic-{}.json'.format(load,seed);save(destination/path,report)
            records.append(report);provenance.append(dict(traffic_seed=seed,workload_sha256=workload_digest(cfg),report=path))
            max_error=max(max_error,report['cross_validation']['max_density_matrix_error'])
        entry=calibration_entry(load,records);entry['runs']=provenance;calibration[str(load)]=entry
    cal=dict(plan_sha256=digest(plan),by_classical_load=calibration,
        calibration_traffic_seeds=plan['calibration_traffic_seeds'],test_traffic_seeds=plan['test_traffic_seeds'])
    save(destination/'calibration.json',cal); cal_hash=digest(cal)
    errors=[]; cases=[]
    for load in plan['classical_loads']:
        delays=calibration[str(load)]['delays']
        for interval in plan['request_intervals_ns']:
            for traffic in plan['test_traffic_seeds']:
                for seed in plan['quantum_seeds']:
                    cfg=workload(plan,load,interval,traffic,seed)
                    key='load-{}_interval-{}_traffic-{}_quantum-{}'.format(load,interval,traffic,seed)
                    metadata=dict(classical_load=load,request_interval_ns=interval,traffic_seed=traffic,quantum_seed=seed,
                                  workload_sha256=workload_digest(cfg),calibration_sha256=cal_hash)
                    rows={};reports={};rates={}
                    for model in ('Full-Sync','No-Dq-R','Fixed-Dc'):
                        report=run_model(cfg,model,cache,delays)
                        report['experiment']=dict(metadata,model=model)
                        save(destination/'runs'/key/(model+'.json'),report)
                        max_error=max(max_error,report['cross_validation']['max_density_matrix_error'])
                        reports[model]=report
                        rows[model]=model_rows(report,plan['fidelity_min'],plan['deadline_ns'])
                        # 有限 batch 지표의 관측 창: local session start부터 마지막 correction 완료까지.
                        duration=report['batch_completion_ns']-min(s['session_start_ns'] for s in cfg['sessions'])
                        rates[model]=dict(observation_duration_ns=duration,
                            completed_throughput_per_second=len(rows[model])*1e9/duration,
                            expected_service_goodput_per_second=sum(r['success_probability'] for r in rows[model])*1e9/duration)
                    rows['Decoupled']=decoupled(cfg,reports['No-Dq-R'])
                    for model in ('No-Dq-R','Fixed-Dc','Decoupled'):
                        errors.extend(compare(rows['Full-Sync'],rows[model],dict(metadata,model=model),plan['deadline_ns']))
                    case=dict(metadata,models=rows,batch_rates=rates)
                    save(destination/'runs'/key/'comparison.json',case)
                    cases.append(dict(metadata,path='runs/'+key+'/comparison.json'))
                    print(key+' PASS',flush=True)
    verify_frozen()
    summary=dict(milestone='P5-B-Direct-Start',architecture='direct-session-start-v2',passed=True,scope='finite seeded evaluation; pilot, not a hardware truth or stationary performance claim',
        historical_q2ns_sources_unchanged=True,calibration_sha256=cal_hash,calibration_test_disjoint=True,
        calibration_runs=len(plan['classical_loads'])*len(plan['calibration_traffic_seeds']),
        test_workloads=len(plan['classical_loads'])*len(plan['request_intervals_ns'])*len(plan['test_traffic_seeds']),
        quantum_repetitions=len(plan['quantum_seeds']),paired_cases=len(cases),execution_runs=3*len(cases),
        transactions_per_model=len(cases)*plan['sessions'],max_density_matrix_error=max_error,
        plan=plan,groups=summarize(errors,plan['bootstrap_samples']),cases=cases,
        statistics='95% percentile bootstrap over traffic-seed clusters; sessions/quantum seeds averaged within cluster; paired sampled feasibility uses shared quantum seed, not guaranteed identical BSM branch')
    save(destination/'errors.json',errors)
    with (destination/'errors.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(errors[0]));writer.writeheader();writer.writerows(errors)
    save(destination/'summary.json',summary)
    return summary


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args()
    try: result=evaluate(json.loads(args.plan.read_text()),args.output_dir)
    except Exception as error:
        if hasattr(error,'report'):
            save(args.output_dir/'failed-run.json',error.report)
        save(args.output_dir/'failure.json',dict(passed=False,error=str(error)))
        raise
    print('P5-B: {} paired cases; max state error {:.3g}; PASS'.format(result['paired_cases'],result['max_density_matrix_error']))


if __name__=='__main__':main()
