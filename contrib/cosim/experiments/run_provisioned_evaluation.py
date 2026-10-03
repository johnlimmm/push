#!/usr/bin/env python3
"""Finite factorial causality evaluation; raw reports remain compressed."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import sys

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from run_provisioned import ProvisionedManager, save_report


def source_hashes():
    files=list((MODULE/'python').glob('provisioned_*.py'))+[
        MODULE/'python/run_provisioned.py',MODULE/'python/quantum_network_backend.py',
        MODULE/'python/netsquid_reference_provisioned.py',MODULE/'examples/cosim-provisioned.cc',Path(__file__).resolve()]
    files+=list((MODULE/'python').glob('native_*.py'))
    return {str(p.relative_to(MODULE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(files)}


def workload(plan,delays,traffic,kind,rate,seed):
    protocols={'swap':['swap'],'teleport':['teleport'],'mixed':['swap','teleport','swap','teleport']}[kind]
    result=dict(name='provisioned-'+kind,seed=seed,
        quantum_links={name:dict(delay_ns=value,depolar_rate_hz=rate) for name,value in zip(('RA','RB'),delays)},
        sessions=[dict(session_id=i+1,protocol=p,session_start_ns=plan['session_start_ns']+i*plan['session_interval_ns'],
            **({'input_state':'+i'} if p=='teleport' else {})) for i,p in enumerate(protocols)])
    if traffic:
        # Fixed burst train; it spans the latest configured delivery + R batch.
        result['background']=dict(result=dict(start_ns=2200000,interval_ns=850000,count=20,payload_bytes=1000))
    return result


def evaluate(plan,destination):
    destination=Path(destination)
    if destination.exists():raise ValueError('choose an unused output directory')
    destination.mkdir(parents=True);sources=source_hashes()
    save_report(destination/'plan.json',plan)
    cache={};rows=[];transactions=0
    cells=itertools.product(plan['channel_delays_ns'],plan['background_enabled'],plan['workloads'],
                            plan['depolar_rates_hz'],plan['quantum_seeds'])
    for index,(delays,traffic,kind,rate,seed) in enumerate(cells):
        raw=workload(plan,delays,traffic,kind,rate,seed)
        try:report=ProvisionedManager(raw).run(cache)
        except Exception as error:
            if hasattr(error,'report'):save_report(destination/'failure-report.json.gz',error.report)
            save_report(destination/'failure.json',dict(index=index,config=raw,error=str(error)));raise
        path='runs/{:03d}.json.gz'.format(index)
        save_report(destination/path,report)
        transactions+=len(raw['sessions'])
        rows.append(dict(report=path,quantum_delays_ns=delays,background_enabled=traffic,workload=kind,
            depolar_rate_hz=rate,seed=seed,max_density_matrix_error=report['cross_validation']['max_density_matrix_error'],
            batch_completion_ns=report['batch_completion_ns'],sessions=report['metrics']['sessions'],
            delivery_count=len(report['snapshot']['quantum_network']['deliveries'])))
        print('provisioned case {} {} {} background={} noise={} seed={} PASS'.format(index,kind,delays,traffic,rate,seed),flush=True)
    if sources!=source_hashes():raise RuntimeError('evaluation source changed during run')
    summary=dict(passed=True,architecture='provisioned-native-v4',plan=plan,runs=len(rows),transactions=transactions,
        max_density_matrix_error=max(r['max_density_matrix_error'] for r in rows),source_sha256=sources,rows=rows,
        scope='Finite deterministic channel-delay/noise x background x protocol workload validation; two quantum seeds, no population performance claim.',
        classical_packet_drop_count=0,quantum_loss_model='none',ready_notification='ideal_zero_delay')
    save_report(destination/'summary.json',summary)
    return summary


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();value=evaluate(json.loads(args.plan.read_text()),args.output_dir)
    print('{} provisioning runs / {} transactions PASS'.format(value['runs'],value['transactions']))
