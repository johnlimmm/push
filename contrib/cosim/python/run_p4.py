#!/usr/bin/env python3
"""P4: 실제 device FIFO 지연과 NetSquid native memory aging의 연결 검증."""

import argparse
import json
import os
import socket
from pathlib import Path
import subprocess
import sys

from p1_quantum import EventLog
from p2_quantum import P2Quantum
from p4_config import normalize_config
from p4_validation import validate_report
from p2_reference_validation import compare_reference
from run_p0 import Participant, NS3_DIR


def find_worker():
    candidates = [p for p in (NS3_DIR / "build/contrib/cosim").rglob("*cosim-p4*")
                  if p.is_file() and os.access(str(p), os.X_OK)]
    if len(candidates) != 1:
        raise RuntimeError("Build ./ns3 build cosim-p4, or specify --ns3-binary")
    return candidates[0]


class P4Participant(Participant):
    """P0의 소켓 framing/종료 관리를 공유하고 P4의 설정·trace 프로토콜을 사용한다."""

    def __init__(self, binary, config, root_cause):
        self.process = None
        self.stream = None
        self.sock, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(15)
        try:
            self.process = subprocess.Popen([str(binary), '--bridgeFd={}'.format(peer.fileno())],
                                            pass_fds=(peer.fileno(),), stdout=subprocess.DEVNULL)
        except BaseException:
            self.sock.close()
            raise
        finally:
            peer.close()
        self.stream = self.sock.makefile('rwb', buffering=0)
        self.source_sequence = 0
        try:
            if self.read() != ['HELLO', 'COSIM_P4', '1']:
                raise RuntimeError('incompatible P4 participant')
            values = [config['session_id'], config['command_time_ns'],
                      config['command_link']['rate_bps'], config['command_link']['delay_ns'],
                      config['result_link']['rate_bps'], config['result_link']['delay_ns'],
                      config['command_payload_bytes'], config['result_payload_bytes'],
                      config['queue_packets'], root_cause]
            self.send('CONFIG ' + ' '.join(map(str, values)))
            for side in ('command', 'result'):
                flow = config['background'][side]
                self.send('FLOW {} {} {} {} {}'.format(side, flow['start_ns'], flow['interval_ns'],
                                                      flow['count'], flow['payload_bytes']))
            ready = self.read()
            if len(ready) != 3 or ready[:2] != ['READY', '0']:
                raise RuntimeError('invalid READY')
            self.now_ns = 0
            self.next_time = self._time(ready[2])
        except BaseException:
            self.close()
            raise

    def advance(self, at):
        self.send('ADVANCE {}'.format(at))
        header = self.read()
        if len(header) != 4 or header[:2] != ['BOUNDARY', str(at)]:
            raise RuntimeError('P4 boundary mismatch')
        count = int(header[3])
        if not 0 <= count <= 100000:
            raise RuntimeError('invalid P4 trace count')
        self.now_ns = at
        self.next_time = self._time(header[2])
        events = []
        for _ in range(count):
            row = self.read()
            if len(row) != 17 or row[0] != 'TRACE' or int(row[2]) != at or int(row[1]) != self.source_sequence:
                raise RuntimeError('malformed or out-of-order P4 trace')
            self.source_sequence += 1
            events.append(dict(event_id='n:' + row[1], source_sequence=int(row[1]),
                               time_ns=at, event_type=row[3], node_id=int(row[4]),
                               message_id=int(row[5]), cause=row[6], session_id=int(row[7]),
                               request_id=int(row[8]), pair_a=int(row[9]), pair_b=int(row[10]),
                               output_pair_id=int(row[11]), m1=int(row[12]), m2=int(row[13]),
                               packet_bytes=int(row[14]), kind=int(row[15]), queue_depth=int(row[16])))
        return events

    def inject_completions(self, at, results, causes):
        if not results:
            return
        self.send('INJECT {} {}'.format(at, len(results)))
        for result in results:
            self.send('RESULT {} {} {} {}'.format(result['request_id'], result['m1'],
                      result['m2'], causes[result['request_id']]))
        reply = self.read()
        if len(reply) != 2 or reply[0] != 'INJECTED':
            raise RuntimeError('invalid P4 INJECTED')
        self.next_time = self._time(reply[1])


class P4ValidationFailure(RuntimeError):
    """탈락 실행의 원본 trace를 호출자가 JSON으로 보존할 수 있게 한다."""
    def __init__(self, report, error):
        super().__init__(str(error))
        self.report = report


class P4FederationManager:
    def __init__(self, scenario, binary=None):
        self.config = normalize_config(scenario)
        self.binary = Path(binary) if binary else find_worker()

    def run(self, reference=None):
        """reference는 동일 설정·시각의 결정론적 분기 표를 반복 실험에서 재사용할 때만 전달한다."""
        log = EventLog(self.config['session_id'])
        root = log.add('SESSION_CREATED', 0, source='federation')
        quantum = P2Quantum(self.config, log, root)
        participant = P4Participant(self.binary, self.config, root)
        steps, raw_rows = [], []
        try:
            while True:
                horizon = quantum.next_safe_horizon()
                candidates = [t for t in (horizon, participant.next_time) if t is not None]
                if not candidates:
                    break
                if len(steps) >= 100000:
                    raise RuntimeError('P4 federation step limit exceeded')
                at = min(candidates)
                quantum.round = len(steps)
                quantum.phase = 'COMMIT'
                completed = quantum.advance_to_boundary(at)
                # P0와 동일하게 완료 → ns-3 현재 시각 배출 → 입력 → 배정 → 결과 주입 순서다.
                rows = participant.advance(at)
                raw_rows.extend(rows)
                inputs = []
                for row in rows:
                    # v1 quantum/control log는 유지하고 packet 계측은 별도 목록에 둔다.
                    if row['kind'] > 2 or row['event_type'].startswith('QUEUE_') or row['event_type'] in (
                            'PHY_TX_END', 'PHY_TX_DROP', 'PHY_RX_DROP', 'TC_DROP'):
                        continue
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
                    raise RuntimeError('P4 federation clock mismatch')
                steps.append(dict(time_ns=at, quantum_horizon_ns=horizon, inputs=len(inputs),
                                  quantum_next_ns=quantum.next_safe_horizon(), ns3_next_ns=participant.next_time))
            snapshot = quantum.snapshot()
            participant.finish()
        finally:
            participant.close()
        report = dict(schema_version=1, milestone='P4', model='atomic-swapping-native-T1T2',
                      config=self.config, ns3_binary=str(self.binary), ns3_time_ns=participant.now_ns,
                      time_unit='ns', session_completion_ns=quantum.ab.get('usable_ns') if quantum.ab else None,
                      nodes={'Controller': 0, 'A': 1, 'R': 2, 'B': 3},
                      snapshot=snapshot, events=log.events, bridge_steps=steps, ns3_events=raw_rows)
        report['packet_events'] = [dict(row, packet_id=row['message_id'],
            traffic_class='background' if row['kind'] > 2 else 'control',
            link='command' if row['kind'] in (1, 3) else 'result') for row in raw_rows
            if row['message_id'] and row['event_type'] not in ('BSM_REQUEST', 'CORRECTION_REQUEST')]
        report['traffic_drain_completion_ns'] = max((row['time_ns'] for row in raw_rows
            if row['event_type'] in ('COMMAND_RX', 'RESULT_RX', 'BACKGROUND_RX')), default=0)
        report['simulation_completion_ns'] = participant.now_ns
        try:
            report['validation'] = validate_report(report)
            report['cross_validation'] = compare_reference(report, reference)
        except (RuntimeError, ValueError, KeyError) as error:
            report['validation'] = dict(passed=False, error=str(error))
            raise P4ValidationFailure(report, error) from error
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ns3-binary', type=Path)
    args = parser.parse_args()
    failure = None
    try:
        report = P4FederationManager(json.loads(args.scenario.read_text()), args.ns3_binary).run()
    except P4ValidationFailure as error:
        report, failure = error.report, error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    if failure is not None:
        raise failure
    print('{}: USABLE at {} ns, fidelity={:.16g}, timing/reference PASS; report: {}'.format(
        report['config']['name'], report['session_completion_ns'], report['snapshot']['ab_pair']['fidelity'], args.output))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print('cosim-p4: {}'.format(error), file=sys.stderr)
        sys.exit(1)
