#!/usr/bin/env python3
"""결정론적 correctness 이후의 유한 background offered-load characterization."""

import argparse
import csv
import json
from pathlib import Path

from p4_config import normalize_config
from run_p4 import P4FederationManager, P4ValidationFailure


def save(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n')


def run_sweep(output, loads=(0, 250000, 500000, 750000, 900000, 950000), packet_count=32):
    """rho는 wire bits 기준이며 ppm 단위 정수로 입력한다. 혼잡 발생/단조성은 가정하지 않는다."""
    output = Path(output)
    loads = list(loads)
    if (not loads or len(set(loads)) != len(loads) or
            any(type(v) is not int or not 0 <= v <= 1000000 for v in loads) or
            type(packet_count) is not int or not 1 <= packet_count <= 2000):
        raise ValueError('loads must be distinct integer ppm values in [0, 1000000]; count in [1, 2000]')
    records, maximum = [], 0.0
    for mode, sides in (('command-only', ('command',)), ('result-only', ('result',)), ('both', ('command', 'result'))):
        for load in loads:
            off_timing = None
            for noise in (False, True):
                name = 'p4-{}-{}ppm-{}'.format(mode, load, 'on' if noise else 'off')
                raw = dict(name=name, background={})
                if not noise:
                    raw['memory_noise'] = dict(model='T1T2NoiseModel', T1_ns=0, T2_ns=0)
                for side in sides:
                    rate = 100000000 if side == 'command' else 10000000
                    # 시작 위상과 패킷 크기/개수는 고정하고 주기만 바꾼다.
                    interval = ((1030*8*10**9*10**6 + rate*load//2)//(rate*load)) if load else 1000000
                    raw['background'][side] = dict(start_ns=0, interval_ns=interval,
                                                   count=packet_count if load else 0, payload_bytes=1000)
                config = normalize_config(raw)
                path = output/'runs'/(name+'.json')
                try:
                    report = P4FederationManager(config).run()
                    timing = [report['metrics']['classical'][s] for s in ('command', 'result')]
                    if not noise:
                        off_timing = timing
                        if abs(report['snapshot']['ab_pair']['fidelity']-1) > 1e-12:
                            raise P4ValidationFailure(report, 'noise-off Bell state mismatch')
                    elif timing != off_timing:
                        raise P4ValidationFailure(report, 'noise changed classical timing')
                except P4ValidationFailure as error:
                    report = error.report
                    report['validation'] = dict(passed=False, error=str(error))
                save(path, report)
                row = dict(name=name, mode=mode, requested_load_ppm=load, noise_enabled=noise,
                           report=str(path.relative_to(output)), passed=report['validation']['passed'])
                if row['passed']:
                    error = report['cross_validation']['max_density_matrix_error']
                    maximum = max(maximum, error)
                    row.update(session_completion_ns=report['session_completion_ns'],
                        traffic_drain_completion_ns=report['traffic_drain_completion_ns'],
                        sampled_usable_fidelity=report['snapshot']['ab_pair']['fidelity'],
                        reference_ensemble_fidelity=report['cross_validation']['reference']['ensemble']['fidelity'],
                        max_density_matrix_error=error, quantum_wait_ns=0, drops=0)
                    for side in ('command', 'result'):
                        classical, link = report['metrics']['classical'][side], report['metrics']['links'][side]
                        for key in ('queue_wait_ns', 'total_delay_ns'):
                            row[side+'_'+key] = classical[key]
                        for key in ('utilization', 'queue_peak_packets', 'queue_mean_packets', 'offered_background_load'):
                            row[side+'_'+key] = link[key]
                else:
                    row['error'] = report['validation']['error']
                records.append(row)
                # 중간 실패도 누락되지 않도록 각 실행마다 결과를 저장한다.
                save(output/'progress.json', records)
    summary = dict(milestone='P4', purpose='finite deterministic characterization; not statistical performance evidence',
                   seed=7, packet_count_per_flow=packet_count, runs=len(records),
                   passed=all(r['passed'] for r in records), max_density_matrix_error=maximum, records=records)
    save(output/'summary.json', summary)
    keys = sorted(set().union(*(row.keys() for row in records)))
    with (output/'summary.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        writer.writerows(records)
    return summary


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    summary = run_sweep(args.output)
    print('P4 sweep: {} runs, passed={}, max state error={:.3g}'.format(
        summary['runs'], summary['passed'], summary['max_density_matrix_error']))
    raise SystemExit(0 if summary['passed'] else 1)
