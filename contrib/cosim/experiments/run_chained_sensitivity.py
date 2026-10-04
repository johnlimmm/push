#!/usr/bin/env python3
"""Paired quantum-delivery timescale sensitivity of the unchanged v5 core."""
import argparse
import csv
import datetime
import gzip
import hashlib
import itertools
import json
from pathlib import Path
import random
import subprocess
import sys
import time

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]
sys.path.insert(0,str(MODULE/'python'))
from run_chained import ChainedManager
from run_provisioned import save_report
from run_hybrid import HybridValidationFailure
from p1_validation import tx_duration_ns


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def packet(report,kind,sid):
    found=[e for e in report['ns3_events'] if e['event_type']==kind and e['session_id']==sid]
    if len(found)!=1:raise ValueError('missing or duplicate '+kind)
    return found[0]


def packet_queue(report,pid):
    rows=[e for e in report['ns3_events'] if e['message_id']==pid]
    en={e['node_id']:e['time_ns'] for e in rows if e['event_type']=='QUEUE_ENQUEUE'}
    de={e['node_id']:e['time_ns'] for e in rows if e['event_type']=='QUEUE_DEQUEUE'}
    if not en or en.keys()!=de.keys():raise ValueError('queue trace mismatch')
    return sum(de[n]-en[n] for n in en)


def configuration(plan,quantum,load,seed):
    serialization=tx_duration_ns(plan['background_payload_bytes'],plan['classical_rate_bps'])
    period=round(serialization/load) if load else 1000000
    phase=random.Random(seed).randrange(period)
    return dict(name=plan['name'],seed=plan['quantum_seed'],
        memory_noise=plan['memory_noise'],native_instructions=plan['native_instructions'],
        quantum_links={name:dict(delay_ns=quantum[name+'_ns'],depolar_rate_hz=0) for name in ('RA','RB')},
        access_link=dict(rate_bps=plan['classical_rate_bps'],delay_ns=plan['access_delay_ns']),
        result_link=dict(rate_bps=plan['classical_rate_bps'],delay_ns=plan['result_delay_ns']),
        result_payload_bytes=plan['result_payload_bytes'],queue_packets=plan['queue_packets'],
        chains=[dict(chain_id=i+1,session_start_ns=plan['first_start_ns']+i*plan['request_interval_ns'],
            input_state=plan['input_state']) for i in range(plan['chains_per_run'])],
        background={'result':dict(start_ns=phase,interval_ns=period,
            count=plan['background_packet_count'] if load else 0,payload_bytes=plan['background_payload_bytes'])})


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path)
    parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();plan=json.loads(args.plan.read_text());out=args.output_dir
    if out.exists():raise ValueError('choose a new output directory')
    out.mkdir(parents=True)
    (out/'plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
    manifest=json.loads((MODULE/'results/chained-validation-summary.json').read_text())
    sources=dict(manifest['source_sha256'])
    for path in (Path(__file__).resolve(),args.plan.resolve()):sources[str(path.relative_to(ROOT))]=sha(path)
    for name,digest in sources.items():
        if sha(ROOT/name)!=digest:raise ValueError('source mismatch before execution: '+name)
    provenance=dict(started_at=datetime.datetime.now(datetime.timezone.utc).isoformat(),source_sha256=sources,
        base_commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=str(ROOT)).decode().strip(),
        python=sys.executable,existing_1x_evidence='results/chained-evaluation')
    (out/'provenance.json').write_text(json.dumps(provenance,indent=2,sort_keys=True)+'\n')
    reports=[];rows=[];maximum=0.;begin=time.monotonic();equivalent=0
    try:
        for quantum,load,seed in itertools.product(plan['quantum_delays'],plan['result_loads'],plan['traffic_seeds']):
            report=ChainedManager(configuration(plan,quantum,load,seed)).run(enumerate_branches=True)
            name='q{}-load{}-phase{}.json.gz'.format(quantum['scale'],load,seed)
            save_report(out/name,report)
            # The 1x cells must reproduce the previously published workload.
            if quantum['scale']==1:
                old_name='a{}-i{}-load{}-phase{}.json.gz'.format(plan['access_delay_ns'],plan['request_interval_ns'],load,seed)
                with gzip.open(str(MODULE/'results/chained-evaluation'/old_name),'rt') as stream:old=json.load(stream)
                # Compare the same serialized representation: in-memory
                # resource locations are tuples, whereas JSON stores lists.
                with gzip.open(str(out/name),'rt') as stream:current=json.load(stream)
                for field in ('metrics','snapshot','ns3_events','native_instructions','cross_validation'):
                    if current[field]!=old[field]:raise ValueError('1x reproduction mismatch: '+field)
                equivalent+=1
            maximum=max(maximum,report['cross_validation']['max_density_matrix_error'])
            reports.append(dict(report=name,sha256=sha(out/name),scale=quantum['scale'],load=load,phase_seed=seed,
                max_density_matrix_error=report['cross_validation']['max_density_matrix_error']))
            for m in report['metrics']['chains']:
                sid,tid=m['swap_session_id'],m['teleport_session_id']
                swap=packet(report,'RESULT_TX',sid);ready=packet(report,'PAIR_READY_TX',tid);tele=packet(report,'RESULT_TX',tid)
                ref=report['cross_validation']['chains'][str(m['chain_id'])]['reference']
                row=dict(scale=quantum['scale'],quantum_RA_ns=quantum['RA_ns'],quantum_RB_ns=quantum['RB_ns'],
                    result_load=load,traffic_seed=seed,chain_id=m['chain_id'],
                    session_start_ns=m['session_start_ns'],completion_ns=m['completion_ns'],latency_ns=m['latency_ns'],
                    expected_output_fidelity=ref['expected_fidelity'],output_fidelity=m['output_fidelity'],
                    swap_result_tx_ns=swap['time_ns'],swap_result_rx_ns=packet(report,'RESULT_RX',sid)['time_ns'],
                    ready_tx_ns=ready['time_ns'],ready_rx_ns=m['ready_received_ns'],
                    teleport_result_tx_ns=tele['time_ns'],teleport_result_rx_ns=packet(report,'RESULT_RX',tid)['time_ns'],
                    swap_packet_queue_ns=packet_queue(report,swap['message_id']),
                    ready_packet_queue_ns=packet_queue(report,ready['message_id']),
                    teleport_packet_queue_ns=packet_queue(report,tele['message_id']),**m['delays'])
                row['total_control_queue_ns']=sum(row[k] for k in ('swap_packet_queue_ns','ready_packet_queue_ns','teleport_packet_queue_ns'))
                rows.append(row)
            print('{} / 24 runs, scale {}, load {}, phase {}, max error {:.3g}, {:.1f}s'.format(
                len(reports),quantum['scale'],load,seed,maximum,time.monotonic()-begin),flush=True)
    except Exception as error:
        if isinstance(error,HybridValidationFailure):save_report(out/'failure-report.json.gz',error.report)
        (out/'failure.json').write_text(json.dumps(dict(error=str(error),completed_runs=len(reports)),indent=2)+'\n')
        raise
    groups=[]
    fields=['latency_ns','expected_output_fidelity','resource_wait_ns','swap_R_wait_ns','teleport_A_wait_ns',
        'swap_B_wait_ns','teleport_B_wait_ns','swap_packet_queue_ns','ready_packet_queue_ns','teleport_packet_queue_ns','total_control_queue_ns']
    for quantum,load in itertools.product(plan['quantum_delays'],plan['result_loads']):
        own=[r for r in rows if r['scale']==quantum['scale'] and r['result_load']==load]
        groups.append(dict(scale=quantum['scale'],result_load=load,transactions=len(own),
            means={k:sum(r[k] for r in own)/len(own) for k in fields},
            ranges={k:[min(r[k] for r in own),max(r[k] for r in own)] for k in fields}))
    lookup={(r['scale'],r['result_load'],r['traffic_seed'],r['chain_id']):r for r in rows}
    paired=[]
    for r in rows:
        base=lookup[1,r['result_load'],r['traffic_seed'],r['chain_id']]
        delta={k:r[k]-base[k] for k in fields}
        # Native durations and propagation/serialization are fixed across scales.
        accounted=sum(delta[k] for k in ('resource_wait_ns','swap_R_wait_ns','teleport_A_wait_ns',
            'swap_B_wait_ns','teleport_B_wait_ns','total_control_queue_ns'))
        if accounted!=delta['latency_ns']:raise ValueError('paired latency decomposition failed')
        paired.append(dict(scale=r['scale'],result_load=r['result_load'],traffic_seed=r['traffic_seed'],chain_id=r['chain_id'],
            delta_swap_result_tx_ns=r['swap_result_tx_ns']-base['swap_result_tx_ns'],**{'delta_'+k:v for k,v in delta.items()}))
    for name,data in [('chains.csv',rows),('paired-vs-1x.csv',paired)]:
        with (out/name).open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(data[0]));writer.writeheader();writer.writerows(data)
    if any(sha(ROOT/p)!=h for p,h in sources.items()):raise ValueError('source changed during experiment')
    summary=dict(passed=True,architecture='swapping-assisted-teleportation-v5',runs=len(reports),transactions=len(rows),
        plan=plan,provenance=provenance,groups=groups,reports=reports,max_density_matrix_error=maximum,
        baseline_1x_reproduced_runs=equivalent,paired_latency_decomposition_passed=True,
        unique_phase_conditions=15,zero_load_phase_repetitions='same workload; no additional independent samples',
        interpretation=plan['scope'],elapsed_seconds=time.monotonic()-begin)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
