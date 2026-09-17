#!/usr/bin/env python3
"""P2: P1 UDP 참가자·federation 순서를 유지하고 native T1/T2 aging을 검증한다."""

import argparse
import json
from pathlib import Path
import subprocess
import sys

from p1_quantum import EventLog
from p2_quantum import P2Quantum
from p2_validation import normalize_config, validate_report
from p2_reference_validation import compare_reference
from run_p1 import P1Participant, find_worker


class P2FederationManager:
    def __init__(self, scenario, binary=None):
        self.config = normalize_config(scenario)
        self.binary = Path(binary) if binary else find_worker()

    def run(self, reference=None):
        """reference는 동일 설정·시각의 결정론적 분기 표를 반복 실험에서 재사용할 때만 전달한다."""
        log = EventLog(self.config['session_id'])
        root = log.add('SESSION_CREATED', 0, source='federation')
        quantum = P2Quantum(self.config, log, root)
        participant = P1Participant(self.binary, self.config, root)
        steps = []
        try:
            while True:
                horizon = quantum.next_safe_horizon()
                candidates = [t for t in (horizon, participant.next_time) if t is not None]
                if not candidates:
                    break
                if len(steps) >= 100000:
                    raise RuntimeError('P2 federation step limit exceeded')
                at = min(candidates)
                quantum.round = len(steps)
                quantum.phase = 'COMMIT'
                completed = quantum.advance_to_boundary(at)
                # P0와 동일하게 완료 → ns-3 현재 시각 배출 → 입력 → 배정 → 결과 주입 순서다.
                rows = participant.advance(at)
                inputs = []
                for row in rows:
                    if row['session_id'] != self.config['session_id']:
                        raise RuntimeError('trace session mismatch')
                    is_correction = row['event_type'] == 'CORRECTION_REQUEST'
                    input_pairs = [row['pair_a'], row['pair_b']]
                    details = dict(packet_bytes=row['packet_bytes'], bsm_request_id=row['request_id'])
                    if is_correction:
                        # 보정의 실제 입력은 AB다. 패킷이 운반한 AR/RB 생성 이력은 별도로 보존한다.
                        details['ancestor_pair_ids'] = input_pairs
                        input_pairs = [row['output_pair_id']]
                    log.add(row['event_type'], at,
                            {0: 'Controller', 1: 'A', 2: 'R', 3: 'B'}[row['node_id']],
                            row['cause'], row['event_id'], source='ns3',
                            source_sequence=row['source_sequence'], round=len(steps), phase='NS3',
                            request_id=2 if is_correction else row['request_id'],
                            message_id=row['message_id'] or None,
                            input_pair_ids=input_pairs, output_pair_id=row['output_pair_id'],
                            processor_id=row['node_id'] if row['node_id'] in (2, 3) else None,
                            measurement_bits=[row['m1'], row['m2']] if row['m1'] >= 0 else None,
                            details=details)
                    if row['event_type'] in ('BSM_REQUEST', 'CORRECTION_REQUEST'):
                        inputs.append(row)
                quantum.phase = 'INPUT'
                for row in inputs:
                    if row['event_type'] == 'BSM_REQUEST':
                        quantum.submit_bsm(row, row['event_id'])
                    else:
                        quantum.submit_correction(row, row['event_id'])
                quantum.phase = 'DISPATCH'
                quantum.schedule_queued()
                participant.inject_completions(at, completed, quantum.complete_causes)
                quantum.check_invariants()
                if quantum.now_ns != participant.now_ns:
                    raise RuntimeError('P2 federation clock mismatch')
                steps.append(dict(time_ns=at, quantum_horizon_ns=horizon, inputs=len(inputs),
                                  quantum_next_ns=quantum.next_safe_horizon(), ns3_next_ns=participant.next_time))
            snapshot = quantum.snapshot()
            if not quantum.ab or quantum.ab['state'] != 'USABLE':
                raise RuntimeError('P2 ended without a usable AB pair')
            participant.finish()
        finally:
            participant.close()
        report = dict(schema_version=1, milestone='P2', model='atomic-swapping-native-T1T2',
                      config=self.config, ns3_binary=str(self.binary), ns3_time_ns=participant.now_ns,
                      time_unit='ns', session_completion_ns=quantum.ab['usable_ns'],
                      nodes={'Controller': 0, 'A': 1, 'R': 2, 'B': 3},
                      snapshot=snapshot, events=log.events, bridge_steps=steps)
        report['validation'] = validate_report(report)
        report['cross_validation'] = compare_reference(report, reference)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ns3-binary', type=Path)
    args = parser.parse_args()
    report = P2FederationManager(json.loads(args.scenario.read_text()), args.ns3_binary).run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print('{}: USABLE at {} ns, fidelity={:.16g}, timing/reference PASS; report: {}'.format(
        report['config']['name'], report['session_completion_ns'], report['snapshot']['ab_pair']['fidelity'], args.output))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print('cosim-p2: {}'.format(error), file=sys.stderr)
        sys.exit(1)
