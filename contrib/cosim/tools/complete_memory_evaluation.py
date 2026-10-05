#!/usr/bin/env python3
"""Complete missing independent cells with bounded worker lifetimes.

This is orchestration only: imports the registered runner, preserves its plan,
physics and report paths, and leaves final aggregation to its --resume audit.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor, as_completed
import hashlib
import itertools
import json
from pathlib import Path
import subprocess
import sys

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'experiments'),str(MODULE/'python')]


def run_cell(root,load,interval,traffic):
    from run_memory_evaluation import (read_report,workload,hashes,ChainedManager,
        run_model,save_report,timing_signature,close_workers)
    out=Path(root);plan=read_report(out/'plan.json')
    if hashes()!=read_report(out/'execution-source.json'):
        raise ValueError('source changed before parallel cell')
    key='load-{}-interval-{}-phase-{}'.format(load,interval,traffic)
    calibration=read_report(out/'calibration.json')['by_load'][str(load)]['delays']
    def obtain(path,create):
        if path.exists():
            report=read_report(path)
        else:
            report=create();save_report(path,report)
        if not report['validation']['passed'] or not report['cross_validation']['passed']:
            raise ValueError('invalid cell report '+str(path))
        return report
    try:
        signature=None
        for index,state in enumerate(plan['input_states']):
            cfg=workload(plan,interval,load,traffic,True)
            for c in cfg['chains']:c['input_state']=state
            r=obtain(out/'chains'/key/('input-{}.json.gz'.format(index)),
                     lambda:ChainedManager(cfg).run(enumerate_branches=True))
            if any(c['input_state']!=state for c in r['config']['chains']):raise ValueError('wrong input')
            current=timing_signature(r)
            if signature is not None and current!=signature:raise ValueError('input-dependent timing')
            signature=current
        cfg=workload(plan,interval,load,traffic)
        cache={}
        for model in ('Full-Sync','No-Dq-R','Fixed-Dc'):
            obtain(out/'ablations'/key/(model+'.json.gz'),
                   lambda:run_model(cfg,model,cache,calibration))
        if hashes()!=read_report(out/'execution-source.json'):raise ValueError('source changed after cell')
        return key
    finally:close_workers()


def subprocess_cell(args):
    # A fresh interpreter per cell bounds NetSquid component/cache lifetime.
    root,load,interval,traffic=args
    return subprocess.check_output([sys.executable,__file__,str(root),'--cell',
        str(load),str(interval),str(traffic)],universal_newlines=True).strip()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output',type=Path)
    parser.add_argument('--cell',nargs=3)
    parser.add_argument('--workers',type=int,default=2)
    parser.add_argument('--max-cells',type=int,default=24,
                        help='Bound each execution session; rerun for remaining cells')
    args=parser.parse_args()
    if args.cell:
        print(run_cell(args.output,float(args.cell[0]),int(args.cell[1]),int(args.cell[2])))
        return
    out=args.output.resolve();plan=json.loads((out/'plan.json').read_text())
    if (out/'summary.json').exists():raise ValueError('already complete')
    tasks=[];complete=0
    for load,interval in itertools.product(plan['classical_loads'],plan['request_intervals_ns']):
        for traffic in (plan['test_traffic_seeds'] if load else plan['test_traffic_seeds'][:1]):
            key='load-{}-interval-{}-phase-{}'.format(load,interval,traffic)
            paths=[out/'chains'/key/('input-{}.json.gz'.format(i)) for i in range(6)]
            paths += [out/'ablations'/key/(m+'.json.gz') for m in ('Full-Sync','No-Dq-R','Fixed-Dc')]
            if all(p.exists() for p in paths):complete+=1
            else:tasks.append((str(out),load,interval,traffic))
    remaining=len(tasks);tasks=tasks[:args.max_cells]
    entry=dict(workers=args.workers,complete_cells_before=complete,missing_cells=remaining,
        batch_cells=len(tasks),completed=False,
        orchestrator=str(Path(__file__).resolve().relative_to(MODULE)),
        orchestrator_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        note='Only missing new-profile reports generated; final runner --resume audits all cells. Fresh process per cell, identical physical code and plan.')
    manifest=out/'parallel-provenance.json'
    previous=json.loads(manifest.read_text()) if manifest.exists() else None
    history=[] if previous is None else previous.get('invocations',[previous])
    history.append(entry);metadata=dict(entry,invocations=history)
    manifest.write_text(json.dumps(metadata,indent=2)+'\n')
    print('Retained {} complete cells; completing {} of {} missing with {} workers'.format(complete,len(tasks),remaining,args.workers),flush=True)
    # These workers orchestrate independent simulations, not coding agents.
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures=[pool.submit(subprocess_cell,t) for t in tasks]
        for i,future in enumerate(as_completed(futures),1):
            print('{}/{} cells: {}'.format(i,len(tasks),future.result()),flush=True)
    entry['completed']=True;metadata.update(completed=True)
    manifest.write_text(json.dumps(metadata,indent=2)+'\n')


if __name__=='__main__':main()
