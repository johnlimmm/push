#!/usr/bin/env python3
"""P3 유한 batch 도착 간격 sweep. 통계적 정상상태 성능 실험이 아닌 correctness 검사다."""

import argparse
import copy
import csv
import json
from pathlib import Path

from p3_config import normalize_config
from quantum_scheduler import MAX_TIME_NS, integer
from run_p3 import P3FederationManager


def run_sweep(spec, output_dir, binary=None):
    if not isinstance(spec, dict) or set(spec) != {'scenario', 'session_count', 'arrival_intervals_ns'}:
        raise ValueError('sweep requires scenario, session_count, arrival_intervals_ns')
    count = integer(spec['session_count'], 'session_count', 2, 64)
    intervals = spec['arrival_intervals_ns']
    if not isinstance(intervals, list) or not intervals:
        raise ValueError('arrival intervals must be nonempty')
    for interval in intervals:
        integer(interval, 'arrival_interval_ns', 1, MAX_TIME_NS)
    if intervals != sorted(set(intervals)):
        raise ValueError('arrival intervals must be sorted and unique')
    if not isinstance(spec['scenario'], dict) or 'sessions' in spec['scenario']:
        raise ValueError('sweep generates session commands starting at 1 ms')
    cases = []
    for interval in intervals:
        for noise_on in (False, True):
            config = copy.deepcopy(spec['scenario'])
            config['name'] = 'p3-interval-{}-{}'.format(interval, 'on' if noise_on else 'off')
            config['sessions'] = [dict(session_id=i+1, command_time_ns=1000000+i*interval) for i in range(count)]
            if not noise_on:
                config['memory_noise'] = dict(model='T1T2NoiseModel', T1_ns=0, T2_ns=0)
            cases.append((interval, noise_on, normalize_config(config)))
    directory = Path(output_dir)
    (directory/'runs').mkdir(parents=True, exist_ok=True)
    rows, configurations, errors = [], {}, []
    for interval, noise_on, config in cases:
        report = P3FederationManager(config, binary).run()
        relative = 'runs/' + config['name'] + '.json'
        (directory/relative).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')
        errors.append(report['cross_validation']['max_density_matrix_error'])
        timing = [(r['session_id'], r['bsm_start_ns'], r['completion_ns']) for r in report['metrics']['sessions']]
        if not noise_on:
            configurations[interval] = timing
        elif configurations[interval] != timing:
            raise RuntimeError('P3 noise on/off changed operation timing')
        for metric in report['metrics']['sessions']:
            sid = str(metric['session_id'])
            ref = report['cross_validation']['sessions'][sid]
            baseline = report['cross_validation']['no_wait_baselines'][sid]
            if not noise_on and abs(metric['usable_fidelity']-1) > 1e-12:
                raise RuntimeError('P3 noise-off Bell fidelity mismatch')
            rows.append(dict(arrival_interval_ns=interval, noise_on=noise_on,
                session_id=metric['session_id'], age_on_arrival_ns=metric['age_on_arrival_ns'],
                quantum_wait_ns=metric['quantum_wait_ns'], age_at_bsm_start_ns=metric['age_at_bsm_start_ns'],
                bsm_start_ns=metric['bsm_start_ns'], completion_ns=metric['completion_ns'],
                input_AR_fidelity=metric['input_fidelity']['AR'], input_RB_fidelity=metric['input_fidelity']['RB'],
                conditional_usable_fidelity=metric['usable_fidelity'],
                ensemble_usable_fidelity=ref['reference']['ensemble']['fidelity'],
                no_wait_ensemble_fidelity=baseline['reference']['ensemble']['fidelity'],
                ensemble_fidelity_delta=baseline['ensemble_fidelity_delta'],
                utilization=report['metrics']['processor']['utilization'],
                max_queue_length=report['metrics']['processor']['max_queue_length'],
                time_average_queue_length=report['metrics']['processor']['time_average_queue_length'],
                reference_error=ref['max_density_matrix_error'], report=relative))
        print('{}: {} sessions PASS'.format(config['name'], count), flush=True)
    summary = dict(milestone='P3', experiment='finite-batch-quantum-contention-validation',
        spec=spec, rows=rows, validation=dict(passed=True, batches=len(cases), transactions=len(rows),
        maximum_density_matrix_error=max(errors), checks=['per-session-state-reference', 'FIFO-timing',
        'noise-on-off-timing', 'noise-off-Bell', 'classical-no-queue', 'correction-no-queue']))
    (directory/'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False)+'\n')
    with (directory/'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    parser.add_argument('--ns3-binary', type=Path)
    args = parser.parse_args()
    summary = run_sweep(json.loads(args.scenario.read_text()), args.output_dir, args.ns3_binary)
    print('P3 sweep: {} batches / {} transactions PASS'.format(
        summary['validation']['batches'], summary['validation']['transactions']))


if __name__ == '__main__':
    main()
