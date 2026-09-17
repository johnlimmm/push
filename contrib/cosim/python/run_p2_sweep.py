#!/usr/bin/env python3
"""단일 P2 transaction의 command/result 지연을 각각 바꿔 noise on/off 결과를 저장한다."""

import argparse
import copy
import csv
import json
from pathlib import Path
import sys

from p2_validation import normalize_config
from quantum_scheduler import MAX_TIME_NS, integer
from run_p2 import P2FederationManager


def validate_sweep(rows, command_delays, result_delays):
    """단조성은 관찰값이다. T1/T2에서 고정 Phi+ fidelity의 감소를 보편 법칙으로 강제하지 않는다."""
    indexed = {(r['command_delay_ns'], r['result_delay_ns'], r['noise_on']): r for r in rows}
    if len(rows) != 2 * len(command_delays) * len(result_delays) or len(indexed) != len(rows):
        raise RuntimeError('incomplete or duplicate sweep rows')
    violations = []
    for command in command_delays:
        for result in result_delays:
            on, off = (indexed[(command, result, flag)] for flag in (True, False))
            if any(on[key] != off[key] for key in ('bsm_start_ns', 'bsm_completion_ns',
                    'correction_start_ns', 'session_completion_ns')) or abs(off['co_sim_conditional_fidelity'] - 1) > 1e-12:
                raise RuntimeError('noise off/on timing or noiseless baseline mismatch')
            if not on['reference_passed'] or not off['reference_passed']:
                raise RuntimeError('sweep reference failed')
    # 한 축씩 변화시켜 보관 구간과 정확한 시간 증가를 분리한다.
    for axis, values, fixed_values in (('command', command_delays, result_delays),
                                      ('result', result_delays, command_delays)):
        for fixed in fixed_values:
            for lower, upper in zip(values, values[1:]):
                key1 = (lower, fixed, True) if axis == 'command' else (fixed, lower, True)
                key2 = (upper, fixed, True) if axis == 'command' else (fixed, upper, True)
                a, b = indexed[key1], indexed[key2]
                if b['session_completion_ns'] - a['session_completion_ns'] != upper - lower:
                    raise RuntimeError('sweep completion delay mismatch')
                if axis == 'result':
                    for key in ('bsm_start_ns', 'bsm_completion_ns', 'input_AR_fidelity',
                                'input_RB_fidelity', 'frame_fidelity', 'measurement_bits'):
                        if a[key] != b[key]:
                            raise RuntimeError('result delay changed pre-result quantum state')
                elif b['bsm_start_ns'] - a['bsm_start_ns'] != upper - lower:
                    raise RuntimeError('command delay/input age mismatch')
                if b['reference_ensemble_fidelity'] > a['reference_ensemble_fidelity'] + 1e-12:
                    violations.append(dict(axis=axis, fixed_delay_ns=fixed, lower_delay_ns=lower,
                        upper_delay_ns=upper, lower_fidelity=a['reference_ensemble_fidelity'],
                        upper_fidelity=b['reference_ensemble_fidelity']))
    return dict(passed=True, conditions=len(command_delays) * len(result_delays), runs=len(rows),
                checks=['noise_off_P1_limit', 'noise_independent_timing', 'separate_delay_effects',
                        'conditional_reference_at_every_point'],
                monotonic_sanity=dict(quantity='reference_probability_weighted_usable_fidelity',
                    nonincreasing=not violations, increases=violations, required_for_acceptance=False,
                    reason='T1/T2 relaxation and branch weights do not guarantee monotonic fixed-Phi+ fidelity'))


def run_sweep(spec, directory, binary=None):
    if not isinstance(spec, dict) or set(spec) != {'scenario', 'command_delays_ns', 'result_delays_ns'}:
        raise ValueError('sweep requires scenario, command_delays_ns, result_delays_ns')
    base = normalize_config(spec['scenario'])
    axes = []
    for key in ('command_delays_ns', 'result_delays_ns'):
        values = spec[key]
        if not isinstance(values, list) or not values:
            raise ValueError('delay axis must be a nonempty list')
        for value in values:
            integer(value, key, maximum=MAX_TIME_NS)
        if values != sorted(set(values)):
            raise ValueError('delay axis must be sorted and unique')
        axes.append(values)
    # 모든 조건을 먼저 검증한다. 중간에 overflow가 발견되어 일부 결과만 남는 일을 피한다.
    configurations = []
    for command in axes[0]:
        for result in axes[1]:
            for on in (False, True):
                config = copy.deepcopy(base)
                config['command_link']['delay_ns'] = command
                config['result_link']['delay_ns'] = result
                if not on:
                    config['memory_noise'].update(T1_ns=0, T2_ns=0)
                config['name'] = 'p2-c{}-r{}-{}'.format(command, result, 'on' if on else 'off')
                configurations.append((normalize_config(config), on))
    directory = Path(directory)
    (directory / 'runs').mkdir(parents=True, exist_ok=True)
    rows = []
    for config, on in configurations:
        report = P2FederationManager(config, binary).run()
        path = Path('runs') / (config['name'] + '.json')
        (directory / path).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        snapshot, cross = report['snapshot'], report['cross_validation']
        points = snapshot['checkpoints']
        rows.append(dict(command_delay_ns=config['command_link']['delay_ns'],
                         result_delay_ns=config['result_link']['delay_ns'], noise_on=on,
                         bsm_start_ns=points['bsm_start']['AR']['sim_time_ns'],
                         bsm_completion_ns=points['frame']['sim_time_ns'],
                         correction_start_ns=points['correction_start']['sim_time_ns'],
                         session_completion_ns=report['session_completion_ns'],
                         input_AR_fidelity=points['bsm_start']['AR']['fidelity'],
                         input_RB_fidelity=points['bsm_start']['RB']['fidelity'],
                         frame_fidelity=points['frame']['fidelity'],
                         co_sim_conditional_fidelity=snapshot['ab_pair']['fidelity'],
                         reference_ensemble_fidelity=cross['reference']['ensemble']['fidelity'],
                         measurement_bits=cross['observed_branch'],
                         reference_max_density_matrix_error=cross['max_density_matrix_error'],
                         reference_passed=cross['passed'], report=str(path)))
        print('{}/{} {}'.format(len(rows), len(configurations), config['name']), flush=True)
    validation = validate_sweep(rows, *axes)
    summary = dict(milestone='P2', scenario=base, command_delays_ns=axes[0], result_delays_ns=axes[1],
                   rows=rows, validation=validation)
    (directory / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True, allow_nan=False) + '\n')
    with (directory / 'summary.csv').open('w', newline='') as stream:
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
    print('P2 sweep PASS: {} runs; {}'.format(summary['validation']['runs'], args.output_dir / 'summary.csv'))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print('cosim-p2-sweep: {}'.format(error), file=sys.stderr)
        sys.exit(1)
