#!/usr/bin/env python3
"""Q2NS SwapApp → 실제 UDP → NetSquid 비동기 실행/완료 연결 검증."""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from p1_quantum import EventLog
from p3_quantum import P3Quantum
from p5_config import normalize_config
from p5_validation import cross_validate, validate_report
from q2ns_validation import validate_q2ns
from run_p0 import NS3_DIR
from run_p1 import P1Participant
from run_p4 import P4Participant


def find_worker():
    found = [p for p in (NS3_DIR / 'build/contrib/cosim').rglob('*cosim-q2ns*')
             if p.is_file() and os.access(str(p), os.X_OK)]
    if len(found) != 1:
        raise RuntimeError('Build ./ns3 build cosim-q2ns or specify --ns3-binary')
    return found[0]


class Q2nsParticipant(P1Participant):
    """P0의 소켓 framing/종료 관리를 공유하고 P5의 설정·trace 프로토콜을 사용한다."""

    def __init__(self, binary, config, roots):
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
            if self.read() != ['HELLO', 'COSIM_Q2NS', '1']:
                raise RuntimeError('incompatible P5 participant')
            values = [config['command_link']['rate_bps'], config['command_link']['delay_ns'],
                      config['result_link']['rate_bps'], config['result_link']['delay_ns'],
                      config['command_payload_bytes'], config['result_payload_bytes'], config['queue_packets'], len(config['sessions'])]
            self.send('CONFIG ' + ' '.join(map(str, values)))
            for session in config['sessions']:
                self.send('SESSION {} {} {}'.format(session['session_id'], session['command_time_ns'], roots[session['session_id']]))
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

    # packet trace 형식은 P4와 같다. background/queue/PHY까지 모두 수집한다.
    advance = P4Participant.advance

    def inject_completions(self, at, results, causes, rid_to_sid, corrections):
        if not results and not corrections:
            return
        self.send('INJECT {} {} {}'.format(at, len(results), len(corrections)))
        for result in results:
            self.send('RESULT {} 1 {} {} {}'.format(rid_to_sid[result['request_id']], result['m1'],
                      result['m2'], causes[result['request_id']]))
        for event in corrections:
            self.send('CORRECT {} {}'.format(event['session_id'], event['event_id']))
        reply = self.read()
        if len(reply) != 2 or reply[0] != 'INJECTED':
            raise RuntimeError('invalid P5 INJECTED')
        self.next_time = self._time(reply[1])


    def finish(self):
        self.send('STATUS')
        row = self.read()
        if len(row) != 5 or row[0] != 'Q2NS_STATUS':
            raise RuntimeError('invalid Q2NS status')
        self.q2ns_status = dict(zip(('native_state_count', 'native_qubit_count', 'sessions',
                                    'corrections_applied'), map(int, row[1:])))
        super().finish()


class Q2nsValidationFailure(RuntimeError):
    """탈락 실행도 packet/quantum trace와 실패 사유를 보존한다."""
    def __init__(self, report, error):
        super().__init__(str(error))
        self.report = report


class Q2nsFederationManager:
    def __init__(self, scenario, binary=None):
        self.config = normalize_config(scenario)
        self.binary = Path(binary) if binary else find_worker()

    def run(self, references=None):
        log = EventLog(0)
        roots = {s['session_id']: log.add('SESSION_CREATED', 0, source='federation', session_id=s['session_id'])
                 for s in self.config['sessions']}
        quantum = P3Quantum(self.config, log, roots)
        participant = Q2nsParticipant(self.binary, self.config, roots)
        steps, samples, raw_rows = [], [], []
        notified_corrections = set()
        try:
            while True:
                horizon = quantum.next_safe_horizon()
                candidates = [t for t in (horizon, participant.next_time) if t is not None]
                if not candidates:
                    break
                if len(steps) >= 100000:
                    raise RuntimeError('P5 federation step limit exceeded')
                at = min(candidates)
                quantum.round = len(steps)
                quantum.phase = 'COMMIT'
                completed = quantum.advance_to_boundary(at)
                # P0와 동일하게 완료 → ns-3 현재 시각 배출 → 입력 → 배정 → 결과 주입 순서다.
                rows = participant.advance(at)
                raw_rows.extend(rows)
                inputs = []
                for row in rows:
                    # 기존 v1 event log의 transaction 인과관계와 별도 packet 계측을 유지한다.
                    if row['kind'] > 2 or row['event_type'].startswith('QUEUE_') or row['event_type'] in (
                            'PHY_TX_END', 'PHY_TX_DROP', 'PHY_RX_DROP', 'TC_DROP'):
                        continue
                    if row['session_id'] not in roots:
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
                            row['cause'], row['event_id'], source='ns3', session_id=row['session_id'],
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
                # 보정도 비동기 완료를 Q2NS에 돌려준다. 같은 시각 다음 round에서 앱 trace가 발생한다.
                corrections = [e for e in log.events if e['event_type'] == 'CORRECTION_COMPLETE' and
                               e['session_id'] not in notified_corrections]
                participant.inject_completions(at, completed, quantum.complete_causes, quantum.rid_to_sid, corrections)
                notified_corrections.update(e['session_id'] for e in corrections)
                samples.append(quantum.queue_sample())
                quantum.check_invariants()
                if quantum.now_ns != participant.now_ns:
                    raise RuntimeError('P5 federation clock mismatch')
                steps.append(dict(time_ns=at, quantum_horizon_ns=horizon, inputs=len(inputs),
                                  quantum_next_ns=quantum.next_safe_horizon(), ns3_next_ns=participant.next_time))
            snapshot = quantum.snapshot()
            participant.finish()
        finally:
            participant.close()
        report = dict(schema_version=1, milestone='Q2NS-adapter', model='Q2NS-SwapApp-native-NetSquid-T1T2',
                      config=self.config, ns3_binary=str(self.binary), ns3_time_ns=participant.now_ns,
                      time_unit='ns', batch_completion_ns=max((s['ab_pair']['usable_ns'] for s in quantum.sessions.values()
                          if s['ab_pair'] and s['ab_pair']['usable_ns'] is not None), default=0),
                      nodes={'Controller': 0, 'A': 1, 'R': 2, 'B': 3},
                      snapshot=snapshot, events=log.events, bridge_steps=steps, queue_samples=samples)
        report['q2ns_status'] = participant.q2ns_status
        report['q2ns_events'] = [r for r in raw_rows if r['kind'] == 5]
        report['ns3_events'] = raw_rows
        report['packet_events'] = [dict(row, packet_id=row['message_id'],
            traffic_class='background' if row['kind'] > 2 else 'control',
            link='command' if row['kind'] in (1, 3) else 'result') for row in raw_rows
            if row['message_id'] and row['event_type'] not in ('BSM_REQUEST', 'CORRECTION_REQUEST')]
        report['traffic_drain_completion_ns'] = max((row['time_ns'] for row in raw_rows
            if row['event_type'] in ('COMMAND_RX', 'RESULT_RX', 'BACKGROUND_RX')), default=0)
        report['simulation_completion_ns'] = participant.now_ns
        try:
            report['validation'] = validate_report(report)
            report['q2ns_validation'] = validate_q2ns(report)
            report['cross_validation'] = cross_validate(report, references)
        except (RuntimeError, ValueError, KeyError) as error:
            report['validation'] = dict(passed=False, error=str(error))
            raise Q2nsValidationFailure(report, error) from error
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--ns3-binary', type=Path)
    args = parser.parse_args()
    failure = None
    try:
        report = Q2nsFederationManager(json.loads(args.scenario.read_text()), args.ns3_binary).run()
    except Q2nsValidationFailure as error:
        report, failure = error.report, error
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
    if failure is not None:
        raise failure
    print('Q2NS {}: {} sessions, Dq={} ns, max state error={:.3g}; PASS'.format(
        report['config']['name'], len(report['metrics']['sessions']),
        [s['quantum_wait_ns'] for s in report['metrics']['sessions']],
        report['cross_validation']['max_density_matrix_error']))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError, subprocess.TimeoutExpired) as error:
        print('cosim-q2ns: {}'.format(error), file=sys.stderr)
        sys.exit(1)
