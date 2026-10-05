#!/usr/bin/env python3
"""Fresh six-input evaluation: literature gates with 20/10 ms memory.

Runs actual Q2NS/ns-3 packets for each input, followed by independent native
reference circuits. The preceding one-second T2 evaluation is left intact.
"""
import argparse
from collections import OrderedDict
import copy
import csv
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys
import time

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from literature_chained import ChainedManager
from literature_models import run_model, model_rows
from literature_validation import cross_validate_chained
from literature_physics import BSM_NS
from run_provisioned import save_report
from p1_validation import tx_duration_ns
from p5b_workload import calibration_entry
from provisioned_p5b_timing import decoupled
from p5b_analysis import compare, summarize
from literature_reference_client import close_workers


class Cache(OrderedDict):
    def __setitem__(self,key,value):
        if key not in self and len(self)>=128:self.popitem(last=False)
        super().__setitem__(key,value)


def hashes():
    paths=list((MODULE/'python').glob('*.py'))+list((MODULE/'experiments').glob('*.py'))
    paths += [MODULE/'examples/cosim-chained.cc',MODULE/'examples/cosim-provisioned.cc']
    return {str(p.relative_to(MODULE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


def workload(plan,interval,load,traffic,chain=False):
    cfg={k:copy.deepcopy(plan[k]) for k in ('native_instructions','memory_noise','quantum_links','gate_depolar_probability')}
    cfg.update(name='literature-chained' if chain else 'literature-swapping',seed=plan['quantum_seed'],
               result_link=copy.deepcopy(plan['classical_link']))
    serial=tx_duration_ns(plan['background_payload_bytes'],cfg['result_link']['rate_bps'])
    period=round(serial/load) if load else 1000000
    phase=random.Random(traffic).randrange(period)
    count=max(0,(plan['background_end_ns']-phase)//period+1) if load else 0
    cfg['background']=dict(result=dict(start_ns=phase,interval_ns=period,count=count,
                                       payload_bytes=plan['background_payload_bytes']))
    if chain:
        cfg['access_link']=copy.deepcopy(plan['classical_link'])
        cfg['chains']=[dict(chain_id=i+1,session_start_ns=plan['first_start_ns']+i*interval,input_state='+i')
                       for i in range(plan['sessions'])]
    else:
        cfg['sessions']=[dict(session_id=i+1,protocol='swap',session_start_ns=plan['first_start_ns']+i*interval)
                         for i in range(plan['sessions'])]
    return cfg


def csv_file(path,rows):
    with path.open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)


def validation(plan,out):
    states=['0','1','+','-','+i','-i'];coverage={s:set() for s in states}
    maximum=0.;minimum=1.;runs=0;checked=0;records=[]
    base=workload(plan,BSM_NS*2,0,1000,True)
    base['memory_noise'].update(T1_ns=0,T2_ns=0);base['gate_depolar_probability']=0
    base['chains']=[dict(chain_id=i+1,session_start_ns=plan['first_start_ns']+i*1000000,input_state=s)
                    for i,s in enumerate(states)]
    for seed in range(256):
        base['seed']=seed
        report=ChainedManager(base).run(reference=False);runs+=1
        new=[]
        for chain in report['config']['chains']:
            stage=report['snapshot']['sessions'];state=chain['input_state']
            bits=''.join(str(b) for sid in (chain['swap_session_id'],chain['teleport_session_id'])
                         for b in stage[str(sid)]['measurement_bits'])
            fidelity=stage[str(chain['teleport_session_id'])]['checkpoints']['usable']['fidelity']
            minimum=min(minimum,fidelity)
            if abs(fidelity-1)>1e-12:raise RuntimeError('noiseless fidelity')
            if bits not in coverage[state]:new.append(chain);coverage[state].add(bits)
        if new:
            view=dict(report,config=dict(report['config'],chains=new))
            report['cross_validation']=cross_validate_chained(view)
            maximum=max(maximum,report['cross_validation']['max_density_matrix_error']);checked+=len(new)
        save_report(out/('coverage/seed-{}.json.gz'.format(seed)),report)
        if all(len(v)==16 for v in coverage.values()):break
    if not all(len(v)==16 for v in coverage.values()):raise RuntimeError('incomplete joint branch coverage')
    for state,delay in itertools.product(states,[100000,500000]):
        cfg=workload(plan,2*BSM_NS,0,1000,True)
        cfg['chains']=[dict(chain_id=1,session_start_ns=plan['first_start_ns'],input_state=state)]
        cfg['access_link']['delay_ns']=delay
        report=ChainedManager(cfg).run(enumerate_branches=True)
        ref=report['cross_validation'];maximum=max(maximum,ref['max_density_matrix_error'])
        path='noise/{}-{}.json.gz'.format(states.index(state),delay);save_report(out/path,report)
        records.append(dict(input_state=state,access_delay_ns=delay,report=path,
            expected_fidelity=ref['chains']['1']['reference']['expected_fidelity'],
            latency_ns=report['metrics']['chains'][0]['latency_ns']))
    result=dict(passed=True,noiseless_runs=runs,noiseless_transactions=runs*6,
        distinct_input_branches_checked=checked,branches={s:sorted(v) for s,v in coverage.items()},
        minimum_noiseless_fidelity=minimum,noisy_runs=len(records),noisy_cases=records,
        max_density_matrix_error=maximum)
    save_report(out/'summary.json',result);return result


def read_report(path):
    with (gzip.open(path,'rt') if path.suffix=='.gz' else path.open()) as stream:
        return json.load(stream)


def validate_plan(plan):
    if plan['input_states'] != ['0','1','+','-','+i','-i']:
        raise ValueError('six distinct, equally weighted input states required')
    if plan['memory_noise'] != dict(model='T1T2NoiseModel',T1_ns=20000000,T2_ns=10000000):
        raise ValueError('registered memory profile is T1=20 ms, T2=10 ms')
    if set(plan['test_traffic_seeds']) & set(plan['calibration_traffic_seeds']):
        raise ValueError('seed overlap')


def timing_signature(report):
    # Quantum branches may differ by input, but fixed service slots and packet
    # sizes make timing input-independent. Check before averaging six states.
    return [(m['chain_id'],m['latency_ns'],sorted(m['delays'].items()))
            for m in report['metrics']['chains']]


def evaluate(plan,out,resume=False):
    validate_plan(plan)
    old_sources=None;reused=0
    if out.exists():
        if not resume or (out/'summary.json').exists():raise ValueError('choose a new result directory')
        if read_report(out/'plan.json')!=plan:raise ValueError('resume plan mismatch')
        old_sources=read_report(out/'execution-source.json')
        current=hashes()
        if current!=old_sources:
            raise ValueError('execution source changed; cannot resume')
    elif resume:raise ValueError('no run to resume')
    if set(plan['test_traffic_seeds'])&set(plan['calibration_traffic_seeds']):raise ValueError('seed overlap')
    out.mkdir(parents=True,exist_ok=resume);start=time.monotonic();sources=hashes();save_report(out/'plan.json',plan)
    save_report(out/'execution-source.json',sources)
    val=(read_report(out/'validation/summary.json') if resume and (out/'validation/summary.json').exists()
         else validation(plan,out/'validation'))
    if not val['passed']:raise ValueError('failed validation')
    print('Six-state validation PASS'+(' (retained validated run)' if resume else ''),flush=True)
    maximum=val['max_density_matrix_error'];cache=Cache();calibration={};cal_runs=0
    for load in plan['classical_loads']:
        records=[]
        for seed in (plan['calibration_traffic_seeds'] if load else plan['calibration_traffic_seeds'][:1]):
            cfg=workload(plan,plan['calibration_interval_ns'],load,seed)
            path=out/('calibration/load-{}-{}.json.gz'.format(load,seed))
            report=read_report(path) if resume and path.exists() else run_model(cfg,'Full-Sync',cache)
            if not report['validation']['passed'] or not report['cross_validation']['passed']:raise ValueError('failed calibration')
            records.append(report);cal_runs+=1
            if load:
                traffic=cfg['background']['result']
                last_background=traffic['start_ns']+(traffic['count']-1)*traffic['interval_ns']
                if report['batch_completion_ns'] >= last_background:
                    raise RuntimeError('calibration must complete while background traffic is active')
            if not path.exists():save_report(path,report)
            maximum=max(maximum,report['cross_validation']['max_density_matrix_error'])
        calibration[str(load)]=calibration_entry(load,records)
    save_report(out/'calibration.json',dict(seeds=plan['calibration_traffic_seeds'],by_load=calibration))
    errors=[];chains=[];cases=[];run_count=0
    for load,interval in itertools.product(plan['classical_loads'],plan['request_intervals_ns']):
        for traffic in (plan['test_traffic_seeds'] if load else plan['test_traffic_seeds'][:1]):
            key='load-{}-interval-{}-phase-{}'.format(load,interval,traffic)
            metadata=dict(classical_load=load,request_interval_ns=interval,traffic_seed=traffic,
                          quantum_seed=plan['quantum_seed'])
            signature=None
            for state_index,state in enumerate(plan['input_states']):
                cfg=workload(plan,interval,load,traffic,True)
                for chain in cfg['chains']:chain['input_state']=state
                path=out/'chains'/key/('input-{}.json.gz'.format(state_index))
                if resume and path.exists():report=read_report(path);reused+=1
                else:report=ChainedManager(cfg).run(enumerate_branches=True);save_report(path,report)
                if not report['validation']['passed'] or not report['cross_validation']['passed']:raise ValueError('failed chain')
                if any(c['input_state']!=state for c in report['config']['chains']):
                    raise ValueError('wrong input-state report')
                current_signature=timing_signature(report)
                if signature is not None and current_signature!=signature:
                    raise ValueError('input-dependent timing; cannot pool six states')
                signature=current_signature
                run_count+=1
                maximum=max(maximum,report['cross_validation']['max_density_matrix_error'])
                for m in report['metrics']['chains']:
                    ref=report['cross_validation']['chains'][str(m['chain_id'])]['reference']
                    chains.append(dict(metadata,input_state=state,chain_id=m['chain_id'],latency_ns=m['latency_ns'],
                        expected_fidelity=ref['expected_fidelity'],observed_fidelity=m['output_fidelity'],**m['delays']))
            rows={};reports={};cfg=workload(plan,interval,load,traffic)
            for model in ('Full-Sync','No-Dq-R','Fixed-Dc'):
                path=out/'ablations'/key/(model+'.json.gz')
                if resume and path.exists():r=read_report(path);reused+=1
                else:r=run_model(cfg,model,cache,calibration[str(load)]['delays']);save_report(path,r)
                if not r['validation']['passed'] or not r['cross_validation']['passed']:raise ValueError('failed model')
                run_count+=1
                maximum=max(maximum,r['cross_validation']['max_density_matrix_error'])
                reports[model]=r;rows[model]=model_rows(r,plan['fidelity_min'],plan['deadline_ns'])
            rows['Decoupled']=decoupled(reports['Full-Sync']['config'],reports['No-Dq-R'])
            for model in ('No-Dq-R','Fixed-Dc','Decoupled'):
                errors.extend(compare(rows['Full-Sync'],rows[model],dict(metadata,model=model),plan['deadline_ns']))
            case=dict(metadata,models=rows);save_report(out/'ablations'/key/'comparison.json',case);cases.append(case)
            print('{} cells / {} runs / {:.1f}s / error {:.2g}'.format(len(cases),run_count,time.monotonic()-start,maximum),flush=True)
    csv_file(out/'chains.csv',chains);csv_file(out/'errors.csv',errors)
    if hashes()!=sources:raise RuntimeError('execution source changed during experiment')
    summary=dict(passed=True,profile=plan['profile'],plan=plan,source_sha256=sources,
        validation=val,calibration_runs=cal_runs,paired_cases=len(cases),chain_runs=len(cases)*len(plan['input_states']),
        evaluation_runs=run_count,chain_transactions=len(chains),transactions_per_ablation_model=len(cases)*plan['sessions'],
        max_density_matrix_error=maximum,ablation_groups=summarize(errors,plan['bootstrap_samples']),
        elapsed_seconds=time.monotonic()-start,
        elapsed_scope='current invocation only; includes retained-report audits on resume',
        input_timing_equivalence_passed=True,
        statistics='Exact branch-weighted quantum expectation, equally averaged over six input states and four sessions inside each traffic phase; traffic-phase cluster bootstrap conditional on fixed calibration; zero-load phase not repeated.',
        scope='Literature-informed composite abstract processor: Liao/Iqbal gates, Bugalho 20/10 ms memory applied uniformly; fixed topology, ideal source/readout, lossless delivery, finite four-session batches.')
    summary['resumption']=dict(resumed=resume,reused_evaluation_runs=reused,new_evaluation_runs=run_count-reused,
        source_changes={} if old_sources is None else {k:dict(before=v,after=sources[k]) for k,v in old_sources.items() if sources[k]!=v},
        reason='Resume only byte-identical plan and execution sources.' if resume else None)
    summary['report_sha256']={str(p.relative_to(out)):hashlib.sha256(p.read_bytes()).hexdigest() for p in out.rglob('*.json.gz')}
    save_report(out/'summary.json',summary);return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--output-dir',type=Path,required=True)
    parser.add_argument('--resume',action='store_true',help='retain validated reports; require identical physics/circuit sources')
    args=parser.parse_args()
    try:result=evaluate(json.loads(args.plan.read_text()),args.output_dir,args.resume)
    except Exception as error:
        if hasattr(error,'report'):save_report(args.output_dir/'failure-report.json.gz',error.report)
        save_report(args.output_dir/'failure.json',dict(passed=False,error=str(error)));raise
    finally:close_workers()
    print('PASS: {} evaluation runs; maximum state error {:.3g}'.format(result['evaluation_runs'],result['max_density_matrix_error']))
