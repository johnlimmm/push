"""Measure direct-start Hybrid execution separately from offline validation and I/O."""
import copy
import hashlib
import json
from pathlib import Path
import platform
import random
import sys
import time

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))
from run_hybrid import HybridManager, HybridParticipant, session_metrics
from hybrid_core import HybridExecutionCore, HybridFederation
from hybrid_adapters import SwapAdapter, TeleportAdapter
from hybrid_validation import validate_report, cross_validate
from p5b_workload import workload
from paper_timing import replay_production_trace


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, allow_nan=False).encode()).hexdigest()


class CountedParticipant(HybridParticipant):
    """Count actual application-framed IPC lines/bytes, not OS recv() calls."""
    def __init__(self, *args):
        self.tx_lines = self.rx_lines = self.tx_bytes = self.rx_bytes = 0
        super().__init__(*args)

    def send(self, line):
        super().send(line)
        self.tx_lines += 1
        self.tx_bytes += len((line+'\n').encode('ascii'))

    def read(self):
        line = self.stream.readline(4098)
        if not line or not line.endswith(b'\n') or len(line) > 4097:
            raise RuntimeError('invalid/disconnected IPC stream')
        self.rx_lines += 1
        self.rx_bytes += len(line)
        return line.decode('ascii').split()


def run_once(config, reference_cache):
    manager = HybridManager(config)
    config = manager.config
    t0 = time.perf_counter()
    core = HybridExecutionCore(config)
    for slot, session in enumerate(config['sessions']):
        adapter = (SwapAdapter if session['protocol'] == 'swap' else TeleportAdapter)(core, session, slot)
        core.adapters[session['session_id']] = adapter
    core.drain()
    t1 = time.perf_counter()
    participant = CountedParticipant(manager.binary, config, core.roots)
    federation = HybridFederation(core, participant)
    t2 = time.perf_counter()
    try:
        snapshot = federation.run()
        t3 = time.perf_counter()
        participant.finish()
    finally:
        participant.close()
    t4 = time.perf_counter()
    report = dict(schema_version=2, milestone='Hybrid-Direct-Start', architecture='direct-session-start-v2',
        model='Full-Sync',nodes=participant.nodes,config=config,
        execution_core='HybridExecutionCore', federation='HybridFederation', ns3_binary=str(manager.binary),
        ns3_time_ns=participant.now_ns, time_unit='ns', snapshot=snapshot, events=core.events,
        ns3_events=federation.rows, bridge_steps=federation.steps, q2ns_status=participant.q2ns_status)
    report['validation'] = validate_report(report)
    report['cross_validation'] = cross_validate(report, reference_cache)
    report['metrics'] = session_metrics(report)
    report['batch_completion_ns'] = max(r['completion_ns'] for r in report['metrics']['sessions'])
    t5 = time.perf_counter()
    requests = snapshot['requests']
    completed = sum(r['operation'] == 'CORRECTION' and r['state'] == 'COMPLETED' for r in requests)
    if completed != len(config['sessions']):
        raise RuntimeError('incomplete benchmark transactions')
    counters = dict(synchronization_rounds=len(federation.steps),
        distinct_boundary_timestamps=len({s['time_ns'] for s in federation.steps}),
        ipc_tx_lines=participant.tx_lines, ipc_rx_lines=participant.rx_lines,
        ipc_tx_bytes=participant.tx_bytes, ipc_rx_bytes=participant.rx_bytes,
        classical_trace_rows=len(federation.rows), completed_transactions=completed,
        final_transaction_ns=max(r['completion_ns'] for r in requests),
        final_federation_ns=participant.now_ns,
        background_packets=sum(f['count'] for f in config['background'].values()))
    measurement = dict(core_initialization_seconds=t1-t0, participant_startup_seconds=t2-t1,
        federation_seconds=t3-t2, participant_finish_seconds=t4-t3,
        simulation_seconds=t4-t0, offline_validation_seconds=t5-t4,
        simulation_seconds_per_transaction=(t4-t0)/completed,
        federation_seconds_per_transaction=(t3-t2)/completed, counters=counters,
        max_density_matrix_error=report['cross_validation']['max_density_matrix_error'],
        trace_sha256=digest(report))
    return report, measurement


def scenario(plan, count, load):
    # Constant per-session quantum model and background offered rate, with a
    # finite traffic window extended to cover the whole batch at every N.
    p = dict(sessions=count, correction_duration_ns=500000)
    cfg = workload(p, load, plan['request_interval_ns'], plan['traffic_seed'], plan['quantum_seed'])
    cfg['name'] = 'paper-scaling-n{}-load{}'.format(count, load)
    for index, session in enumerate(cfg['sessions']):
        session['protocol'] = 'teleport' if index % 2 else 'swap'
        if index % 2:
            session['input_state'] = '+i'
    return cfg


def statistics(values, samples):
    ordered = sorted(values)
    count = len(values)
    mean = sum(values)/count
    rng = random.Random(7301)
    boot = sorted(sum(rng.choice(values) for _ in values)/count for _ in range(samples))
    median = (ordered[(count-1)//2]+ordered[count//2])/2
    return dict(mean=mean, median=median, minimum=min(values), maximum=max(values),
        ci95_repetition_bootstrap=[boot[int(.025*(samples-1))], boot[int(.975*(samples-1))]])


def environment():
    import netsquid as ns
    import numpy as np
    cpu = next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines()
                if line.startswith('model name')), 'unknown')
    return dict(python=sys.version, netsquid=ns.__version__, numpy=np.__version__,
                platform=platform.platform(), cpu=cpu, cpu_affinity=sorted(__import__('os').sched_getaffinity(0)),
                python_executable=sys.executable, instrumentation='Two IPC line/byte counters per direction; normal production trace logging enabled.')


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
        save(destination/'traces'/(key+'.json'), report)
        save(destination/'warmups'/(key+'.json'), measurement)
        replays[key] = replay_production_trace(report)
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
    result = dict(passed=True, environment=environment(), plan=plan, groups=groups,
        measured_runs=len(rows), warmup_runs=len(cells), rows=rows,
        max_density_matrix_error=max(r['max_density_matrix_error'] for r in rows),
        all_repetition_trace_hashes_equal=True,
        native_timing_replay_requests=sum(len(p['jobs']) for r in replays.values() for p in r.values()),
        native_timing_replay_max_error_ns=max(max(p['max_absolute_error_ns'].values()) for r in replays.values() for p in r.values()),
        measurement_scope='Imported Python runtime: core initialization, ns-3 process startup/configuration, production federation including in-memory logging and final snapshot, status/teardown. Excludes build, Python imports, config normalization, offline validation and file writing. Full background drain included.',
        interpretation='Fixed topology, finite-batch scaling up to 64 sessions; repetition CI reflects host runtime variability, not workload uncertainty. Not isolated IPC overhead or network-node scaling.')
    save(destination/'summary.json', result)
    return result
