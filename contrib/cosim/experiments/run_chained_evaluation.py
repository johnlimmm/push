#!/usr/bin/env python3
"""Finite end-to-end characterization with fixed native physics and real routing."""
import argparse
import csv
import hashlib
import itertools
import json
from pathlib import Path
import random
import sys
import time

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from run_chained import ChainedManager
from run_provisioned import save_report
from run_hybrid import HybridValidationFailure


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('plan',type=Path);parser.add_argument('--output-dir',type=Path,required=True)
    args=parser.parse_args();plan=json.loads(args.plan.read_text());out=args.output_dir
    if out.exists():raise ValueError('choose a new output directory; no result overwrites')
    out.mkdir(parents=True);(out/'plan.json').write_text(json.dumps(plan,indent=2,sort_keys=True)+'\n')
    rows=[];reports=[];maximum=0.;begin=time.monotonic()
    try:
        for access,interval,load,seed in itertools.product(plan['access_delays_ns'],plan['request_intervals_ns'],plan['result_loads'],plan['traffic_seeds']):
            period=round(824000/load) if load else 1000000
            phase=random.Random(seed).randrange(period)
            c=dict(name='chained-evaluation',seed=plan['quantum_seed'],access_link=dict(rate_bps=10000000,delay_ns=access),
                chains=[dict(chain_id=i+1,session_start_ns=plan['first_start_ns']+i*interval,input_state=plan['input_state'])
                        for i in range(plan['chains_per_run'])],
                background={'result':dict(start_ns=phase,interval_ns=period,count=60 if load else 0,payload_bytes=1000)})
            report=ChainedManager(c).run(enumerate_branches=True)
            name='a{}-i{}-load{}-phase{}.json.gz'.format(access,interval,load,seed)
            save_report(out/name,report)
            error=report['cross_validation']['max_density_matrix_error'];maximum=max(maximum,error)
            reports.append(dict(report=name,sha256=hashlib.sha256((out/name).read_bytes()).hexdigest(),passed=True,error=error))
            for m in report['metrics']['chains']:
                reference=report['cross_validation']['chains'][str(m['chain_id'])]['reference']
                rows.append(dict(access_delay_ns=access,request_interval_ns=interval,result_load=load,traffic_seed=seed,
                    chain_id=m['chain_id'],latency_ns=m['latency_ns'],completion_ns=m['completion_ns'],
                    output_fidelity=m['output_fidelity'],expected_output_fidelity=reference['expected_fidelity'],
                    swap_fidelity=m['swap_fidelity'],input_at_teleport_fidelity=m['input_at_teleport_fidelity'],**m['delays']))
            print('{} runs, max error {:.3g}, {:.1f}s'.format(len(reports),maximum,time.monotonic()-begin),flush=True)
    except Exception as error:
        if isinstance(error,HybridValidationFailure):save_report(out/'failure-report.json.gz',error.report)
        (out/'failure.json').write_text(json.dumps(dict(error=str(error),completed_runs=len(reports))))
        raise
    with (out/'chains.csv').open('w',newline='') as stream:
        writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    groups=[]
    for access,interval,load in itertools.product(plan['access_delays_ns'],plan['request_intervals_ns'],plan['result_loads']):
        own=[r for r in rows if (r['access_delay_ns'],r['request_interval_ns'],r['result_load'])==(access,interval,load)]
        fields=['latency_ns','expected_output_fidelity','swap_R_wait_ns','teleport_A_wait_ns','swap_B_wait_ns','teleport_B_wait_ns','ready_packet_ns']
        groups.append(dict(access_delay_ns=access,request_interval_ns=interval,result_load=load,transactions=len(own),
            means={k:sum(r[k] for r in own)/len(own) for k in fields},
            ranges={k:[min(r[k] for r in own),max(r[k] for r in own)] for k in fields}))
    summary=dict(architecture='swapping-assisted-teleportation-v5',passed=True,runs=len(reports),transactions=len(rows),
        plan=plan,groups=groups,reports=reports,max_density_matrix_error=maximum,
        interpretation='Finite characterization. Four periodic-traffic phases; branch-exact expectation at each timing, no population generalization.',
        elapsed_seconds=time.monotonic()-begin)
    (out/'summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')


if __name__=='__main__':main()
