"""Measure native timed Hybrid execution, including all gate state probes."""
import hashlib
import gzip
import json
from pathlib import Path
import random
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))
from provisioned_p5b_models import execute, CountedProvisionedParticipant
from provisioned_p5b_workload import workload
from paper_scaling import statistics, environment


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix=='.gz':
        with gzip.open(str(path),'wt') as stream: json.dump(value,stream,sort_keys=True,allow_nan=False)
    else: path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


def run_once(config, reference_cache):
    report, measurement, participant = execute(config, references=reference_cache,
        participant_class=CountedProvisionedParticipant, require_no_b_wait=False)
    cfg=report['config'];steps=report['bridge_steps']
    measurement.update(counters=dict(synchronization_rounds=len(steps),
        distinct_boundary_timestamps=len({s['time_ns'] for s in steps}),
        ipc_tx_lines=participant.tx_lines,ipc_rx_lines=participant.rx_lines,
        ipc_tx_bytes=participant.tx_bytes,ipc_rx_bytes=participant.rx_bytes,
        classical_trace_rows=len(report['ns3_events']),completed_transactions=len(cfg['sessions']),
        final_transaction_ns=report['batch_completion_ns'],final_federation_ns=participant.now_ns,
        background_packets=sum(f['count'] for f in cfg['background'].values()),
        native_instruction_completions=len(report['native_instructions']),
        quantum_deliveries=len(report['snapshot']['quantum_network']['deliveries']),
        resource_ready_notifications=sum(step['resources_ready'] for step in steps),
        resource_wait_total_ns=sum(row['resource_wait_ns'] for row in report['metrics']['sessions'])),
        max_density_matrix_error=report['cross_validation']['max_density_matrix_error'],trace_sha256=digest(report))
    return report,measurement


def timing_rows(report):
    cases=[]
    for operation in ('BSM','CORRECTION'):
        actual=[];oracle=[]
        for r in report['snapshot']['requests']:
            if r['operation']!=operation:continue
            t=report['validation']['expected_timing']['sessions'][str(r['session_id'])]
            expected={k:t[operation.lower()+'_'+k] for k in ('arrival_ns','start_ns','completion_ns')}
            observed={k:r[k] for k in ('arrival_ns','start_ns','completion_ns')}
            if expected!=observed:raise RuntimeError('native/FIFO timing mismatch')
            for values,rows in ((expected,oracle),(observed,actual)):
                rows.append(dict(values,session_id=r['session_id'],waiting_ns=values['start_ns']-values['arrival_ns']))
        cases.append(dict(operation=operation,sessions=len(actual),oracle=oracle,native=actual))
    return cases


def scenario(plan, count, load):
    # Constant per-session quantum model and background offered rate, with a
    # finite traffic window extended to cover the whole batch at every N.
    p = dict(sessions=count, correction_duration_ns=500000,native_instructions=plan['native_instructions'],
             quantum_links=plan['quantum_links'])
    cfg = workload(p, load, plan['request_interval_ns'], plan['traffic_seed'], plan['quantum_seed'])
    cfg['name'] = 'paper-scaling-n{}-load{}'.format(count, load)
    for index, session in enumerate(cfg['sessions']):
        session['protocol'] = 'teleport' if index % 2 else 'swap'
        if index % 2:
            session['input_state'] = '+i'
    return cfg


def evaluate(plan, destination):
    destination = Path(destination)
    if destination.exists():
        raise ValueError('choose an unused scaling output directory')
    save(destination/'plan.json', plan)
    cache, expected, rows, replays = {}, {}, [], {}
    cells = [(n, load) for n in plan['session_counts'] for load in plan['scaling_loads']]
    for n, load in cells:
        report, measurement = run_once(scenario(plan, n, load), cache)
        key = 'n{}-load{}'.format(n, load)
        expected[key] = measurement['trace_sha256']
        save(destination/'traces'/(key+'.json.gz'), report)
        save(destination/'warmups'/(key+'.json'), measurement)
        replays[key] = timing_rows(report)
        save(destination/'traces'/(key+'-native-timing.json'), replays[key])
        print('scaling warmup '+key+' PASS', flush=True)
    # Only wall-clock repetitions vary; each cell has exactly the same workload.
    # No other experiment is launched concurrently with this benchmark.
    schedule = [(n, load, rep) for rep in range(plan['scaling_repetitions']) for n, load in cells]
    random.Random(plan['order_seed']).shuffle(schedule)
    for n, load, rep in schedule:
        report, measurement = run_once(scenario(plan, n, load), cache)
        key = 'n{}-load{}'.format(n, load)
        if measurement['trace_sha256'] != expected[key]:
            raise RuntimeError('fixed-workload trace changed across repetitions: '+key)
        row = dict(measurement, sessions=n, classical_load=load, repetition=rep)
        rows.append(row)
        save(destination/'measurements'/(key+'-rep'+str(rep)+'.json'), row)
        print('scaling {} repetition {} PASS'.format(key, rep), flush=True)
    groups = []
    for n, load in cells:
        group = [r for r in rows if r['sessions'] == n and r['classical_load'] == load]
        names = [key for key in group[0] if key.endswith('_seconds') or key.endswith('_per_transaction')]
        groups.append(dict(sessions=n, classical_load=load, repetitions=len(group),
            counters=group[0]['counters'],
            **{name: statistics([r[name] for r in group], plan['bootstrap_samples']) for name in names}))
    result = dict(passed=True, architecture='provisioned-native-v4', environment=dict(environment(),native_instruction_state_probes=True,actual_quantum_channel_provisioning=True), plan=plan, groups=groups,
        measured_runs=len(rows), warmup_runs=len(cells), rows=rows,
        max_density_matrix_error=max(r['max_density_matrix_error'] for r in rows),
        all_repetition_trace_hashes_equal=True,
        fifo_timing_requests=sum(len(p['native']) for r in replays.values() for p in r),
        fifo_timing_max_error_ns=0,
        measurement_scope='Imported Python runtime: core initialization, ns-3 process startup/configuration, native federation including instruction state probes, in-memory logging and final snapshot, status/teardown. Excludes build, Python imports, config normalization, offline validation and file writing. Full background drain included.',
        interpretation='Fixed topology, finite-batch scaling up to 64 sessions; repetition CI reflects host runtime variability, not workload uncertainty. Not isolated IPC overhead or network-node scaling.')
    save(destination/'timing.json',dict(passed=True,architecture='provisioned-native-v4',source='independent resource-ready/FIFO oracle vs actual native circuit completion',case_count=len(cells),requests=result['fifo_timing_requests'],max_absolute_completion_error_ns=0,cases=[dict(case,cell=key) for key,rs in replays.items() for case in rs]))
    save(destination/'summary.json', result)
    return result
