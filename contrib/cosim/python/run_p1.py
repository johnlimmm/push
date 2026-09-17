#!/usr/bin/env python3
"""P1 실행: 실제 UDP swapping transaction → 시간 검증 → 독립 NetSquid reference 비교."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

import numpy as np

from p1_quantum import EventLog, P1Quantum
from p1_validation import decode_dm, normalize_config, validate_report
from run_p0 import MODULE_DIR, NS3_DIR, Participant


def find_worker():
    candidates = [p for p in (NS3_DIR / 'build' / 'contrib' / 'cosim').rglob('*cosim-p1*')
                  if p.is_file() and os.access(str(p), os.X_OK)]
    if len(candidates) != 1:
        raise RuntimeError('Build ./ns3 build cosim-p1, or specify --ns3-binary')
    return candidates[0]


class P1Participant(Participant):
    """P0의 소켓 framing/종료 관리를 공유하고 P1의 설정·trace 프로토콜을 사용한다."""

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
            if self.read() != ['HELLO', 'COSIM_P1', '1']:
                raise RuntimeError('incompatible P1 participant')
            values = [config['session_id'], config['command_time_ns'],
                      config['command_link']['rate_bps'], config['command_link']['delay_ns'],
                      config['result_link']['rate_bps'], config['result_link']['delay_ns'],
                      config['command_payload_bytes'], config['result_payload_bytes'],
                      len(config['result_replays']), root_cause]
            self.send('CONFIG ' + ' '.join(map(str, values)))
            for replay in config['result_replays']:
                self.send('REPLAY {} {} {}'.format(replay['delay_ns'], replay['xor_m1'], replay['xor_m2']))
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
            raise RuntimeError('P1 boundary mismatch')
        count = int(header[3])
        if not 0 <= count <= 100000:
            raise RuntimeError('invalid P1 trace count')
        self.now_ns = at
        self.next_time = self._time(header[2])
        events = []
        for _ in range(count):
            row = self.read()
            if len(row) != 15 or row[0] != 'TRACE' or int(row[2]) != at or int(row[1]) != self.source_sequence:
                raise RuntimeError('malformed or out-of-order P1 trace')
            self.source_sequence += 1
            events.append(dict(event_id='n:' + row[1], source_sequence=int(row[1]),
                               time_ns=at, event_type=row[3], node_id=int(row[4]),
                               message_id=int(row[5]), cause=row[6], session_id=int(row[7]),
                               request_id=int(row[8]), pair_a=int(row[9]), pair_b=int(row[10]),
                               output_pair_id=int(row[11]), m1=int(row[12]), m2=int(row[13]),
                               packet_bytes=int(row[14])))
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
            raise RuntimeError('invalid P1 INJECTED')
        self.next_time = self._time(reply[1])


def compare_reference(report):
    """측정 비트 일치를 요구하지 않고, 각 경로의 실제 보정 후 상태와 연산 시각을 비교한다."""
    snapshot = report['snapshot']
    # JSON으로 저장했다가 읽으면 정수 dict key가 문자열로 바뀐다.
    bsm = snapshot['requests'].get(1, snapshot['requests'].get('1'))
    correction = snapshot['correction']
    spec = dict(seed=report['config']['seed'], bsm_start_ns=bsm['start_ns'],
                bsm_completion_ns=bsm['completion_ns'], correction_start_ns=correction['start_ns'],
                correction_completion_ns=correction['completion_ns'])
    process = subprocess.run([sys.executable, str(MODULE_DIR / 'python' / 'netsquid_reference.py')],
                             input=json.dumps(spec), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                             universal_newlines=True, timeout=30)
    if process.returncode:
        raise RuntimeError('NetSquid reference failed: ' + process.stderr)
    reference = json.loads(process.stdout)
    error = float(np.max(np.abs(decode_dm(snapshot['ab_pair']['density_matrix']) -
                               decode_dm(reference['density_matrix']))))
    timing = {e['event_type']: e['sim_time_ns'] for e in reference['events']}
    expected = {'BSM_START': spec['bsm_start_ns'], 'BSM_COMPLETE': spec['bsm_completion_ns'],
                'CORRECTION_START': spec['correction_start_ns'],
                'CORRECTION_COMPLETE': spec['correction_completion_ns']}
    if (not np.isfinite(error) or not np.isfinite(reference['fidelity']) or
            error > 1e-12 or abs(reference['fidelity'] - 1) > 1e-12 or
            any(timing.get(k) != t for k, t in expected.items()) or
            reference['time_ns'] != spec['correction_completion_ns']):
        raise RuntimeError('P1/reference state or timing mismatch')
    return dict(passed=True, max_density_matrix_error=error, input_timing=spec, reference=reference)


class P1FederationManager:
    def __init__(self, scenario, binary=None):
        self.config = normalize_config(scenario)
        self.binary = Path(binary) if binary else find_worker()

    def run(self):
        log = EventLog(self.config['session_id'])
        root = log.add('SESSION_CREATED', 0, source='federation')
        quantum = P1Quantum(self.config, log, root)
        participant = P1Participant(self.binary, self.config, root)
        steps = []
        try:
            while True:
                horizon = quantum.next_safe_horizon()
                candidates = [t for t in (horizon, participant.next_time) if t is not None]
                if not candidates:
                    break
                if len(steps) >= 100000:
                    raise RuntimeError('P1 federation step limit exceeded')
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
                    raise RuntimeError('P1 federation clock mismatch')
                steps.append(dict(time_ns=at, quantum_horizon_ns=horizon, inputs=len(inputs),
                                  quantum_next_ns=quantum.next_safe_horizon(), ns3_next_ns=participant.next_time))
            snapshot = quantum.snapshot()
            if not quantum.ab or quantum.ab['state'] != 'USABLE':
                raise RuntimeError('P1 ended without a usable AB pair')
            participant.finish()
        finally:
            participant.close()
        report = dict(schema_version=1, milestone='P1', model='atomic-noiseless-swapping',
                      config=self.config, ns3_binary=str(self.binary), ns3_time_ns=participant.now_ns,
                      time_unit='ns', session_completion_ns=quantum.ab['usable_ns'],
                      nodes={'Controller': 0, 'A': 1, 'R': 2, 'B': 3},
                      snapshot=snapshot, events=log.events, bridge_steps=steps)
        report['validation'] = validate_report(report)
        report['cross_validation'] = compare_reference(report)
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ns3-binary', type=Path)
    args = parser.parse_args()
    report = P1FederationManager(json.loads(args.scenario.read_text()), args.ns3_binary).run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    print('{}: USABLE at {} ns, fidelity={:.16g}, timing/reference PASS; report: {}'.format(
        report['config']['name'], report['session_completion_ns'], report['snapshot']['ab_pair']['fidelity'], args.output))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print('cosim-p1: {}'.format(error), file=sys.stderr)
        sys.exit(1)
