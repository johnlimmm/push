#!/usr/bin/env python3
"""ns-3와 NetSquid 두 프로세스를 연결하는 P0 실행 진입점.

읽는 순서: main() → FederationManager.run() → Participant의 통신 메서드.
이 Python 프로세스가 관리자와 NetSquid를 함께 실행하고, C++ ns-3는 자식
프로세스로 실행한다. 시나리오 JSON → 소켓 명령 → ns-3 이벤트 → 양자 연산
순으로 이어지며, 양자 연산의 완료 결과는 다시 ns-3 이벤트로 전달된다.

현재는 시간·자원 관리 검증용이다. 소켓은 프로그램 사이의 실제 통신 수단이며,
시뮬레이션 안의 UDP/TCP 패킷 경로를 대신 구현한 것은 아니다.
"""

import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from quantum_scheduler import MAX_TIME_NS, QuantumScheduler, integer, normalize_request


MODULE_DIR = Path(__file__).resolve().parents[1]  # contrib/cosim
NS3_DIR = MODULE_DIR.parents[1]


def find_worker():
    """현재 ns-3 빌드에서 실행 가능한 C++ 참가자 파일을 찾는다."""
    # 버전·빌드 프로필이 파일명에 들어가므로 전체 이름을 고정하지 않는다.
    # 후보가 여러 개라면 임의로 고르지 않고 --ns3-binary 지정을 요구한다.
    candidates = sorted((NS3_DIR / 'build' / 'contrib' / 'cosim').rglob('*cosim-p0*'))
    candidates = [p for p in candidates if p.is_file() and os.access(str(p), os.X_OK)]
    if len(candidates) != 1:
        raise RuntimeError('Build ./ns3 build cosim-p0 first, or specify --ns3-binary')
    return candidates[0]


def request_fields(request):
    """요청을 C++ Parse()가 읽는 고정 순서의 여섯 필드로 직렬화한다."""
    return '{} {} {} {} {} {}'.format(
        request['type'], request['request_id'], request['processor_id'],
        request['pair_a'], request['pair_b'], request['duration_ns'])


def result_fields(result):
    """상태와 측정 비트만 전송한다. 평가용 fidelity는 전송하지 않는다."""
    return '{} {} {} {} {} {}'.format(
        result['request_id'], result['processor_id'], result['state'],
        result['code'], result['m1'], result['m2'])


def parse_result(fields, time_ns):
    """ns-3가 결과 수신 콜백까지 실행했음을 알리는 DELIVERED를 해석한다."""
    if len(fields) != 7 or fields[0] != 'DELIVERED':
        raise RuntimeError('malformed DELIVERED message')
    return dict(time_ns=time_ns, request_id=int(fields[1]), processor_id=int(fields[2]),
                state=fields[3], code=fields[4], m1=int(fields[5]), m2=int(fields[6]))


class Participant:
    """C++ ns-3 참가자의 실행·소켓 통신·종료를 담당하는 래퍼."""

    def __init__(self, binary, scenario, timeout=15):
        # 서로 연결된 Unix 소켓 두 개 중 하나만 자식에게 전달한다.
        # 별도 서버 포트/소켓 파일이 필요 없고, Python 환경도 공유하지 않는다.
        self.process = None
        self.stream = None
        self.sock, peer = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.settimeout(timeout)
        try:
            self.process = subprocess.Popen(
                [str(binary), '--bridgeFd={}'.format(peer.fileno())],
                pass_fds=(peer.fileno(),), stdout=subprocess.DEVNULL)
        except BaseException:
            self.sock.close()
            raise
        finally:
            # 부모가 자식 쪽 소켓을 계속 쥐고 있으면 종료/EOF 감지가 늦어질 수 있다.
            peer.close()
        self.stream = self.sock.makefile('rwb', buffering=0)
        try:
            # 버전 확인 후 초기 입력을 전부 등록한다. 아직 시뮬레이션은 진행하지 않는다.
            if self.read() != ['HELLO', 'COSIM_P0', '1']:
                raise RuntimeError('incompatible participant protocol')
            processors = scenario['processors']
            events = scenario.get('events', [])
            followups = scenario.get('followups', [])
            self.send('CONFIG {} {} {}'.format(len(processors), len(events), len(followups)))
            for pid in processors:
                self.send('PROCESSOR {}'.format(pid))
            for event in events:
                at = integer(event['time_ns'], 'time_ns', maximum=MAX_TIME_NS)
                self.send('EVENT {} {}'.format(at, request_fields(normalize_request(event))))
            for event in followups:
                # 후속 요청의 도착은 Python에서 미리 정하지 않는다.
                # C++가 완료 결과를 실제 수신한 시각 + delay_ns에 예약한다.
                rid = integer(event['after_request_id'], 'after_request_id', 1)
                delay = integer(event.get('delay_ns', 0), 'delay_ns', maximum=MAX_TIME_NS)
                self.send('FOLLOWUP {} {} {}'.format(rid, delay, request_fields(normalize_request(event))))
            ready = self.read()
            if len(ready) != 3 or ready[:2] != ['READY', '0']:
                raise RuntimeError('invalid READY')
            self.now_ns = 0
            self.next_time = self._time(ready[2])
        except BaseException:
            self.close()
            raise

    @staticmethod
    def _time(text):
        """프로토콜의 -1(다음 이벤트 없음)을 Python의 None으로 바꾼다."""
        value = int(text)
        if value == -1:
            return None
        return integer(value, 'participant time', maximum=MAX_TIME_NS)

    def send(self, line):
        # 줄바꿈은 메시지 경계다. sendall()은 소켓의 부분 전송을 처리한다.
        data = (line + '\n').encode('ascii')
        self.sock.sendall(data)

    def read(self):
        # 한 번의 recv가 한 메시지라는 보장은 없으므로 완전한 한 줄을 읽는다.
        line = self.stream.readline(4098)
        if not line or not line.endswith(b'\n') or len(line) > 4097:
            raise RuntimeError('participant disconnected or sent an invalid line')
        return line.decode('ascii').split()

    def advance(self, at):
        """ns-3를 at까지 진행하고 해당 시각의 입력·결과 수신 기록을 받는다.

        반환값 inputs는 양자 스케줄러로 넘길 요청/취소다. deliveries는 이전
        라운드에 주입한 응답을 ns-3가 실제 이벤트로 처리한 기록이다.
        """
        self.send('ADVANCE {}'.format(at))
        header = self.read()
        if len(header) != 5 or header[0] != 'BOUNDARY' or int(header[1]) != at:
            raise RuntimeError('participant boundary mismatch')
        self.now_ns = at
        self.next_time = self._time(header[2])
        inputs, deliveries = [], []
        n_inputs, n_results = int(header[3]), int(header[4])
        if not (0 <= n_inputs <= 100000 and 0 <= n_results <= 100000):
            raise RuntimeError('invalid participant batch size')
        for _ in range(n_inputs):
            row = self.read()
            if len(row) != 7 or row[0] != 'INPUT':
                raise RuntimeError('malformed INPUT')
            inputs.append(normalize_request(dict(type=row[1], request_id=int(row[2]),
                          processor_id=int(row[3]), pair_a=int(row[4]), pair_b=int(row[5]),
                          duration_ns=int(row[6]))))
        for _ in range(n_results):
            deliveries.append(parse_result(self.read(), at))
        return inputs, deliveries

    def inject(self, at, results):
        """응답을 ns-3의 현재 시각에 예약한다. 수신 콜백 실행은 다음 라운드다."""
        if not results:
            return
        self.send('INJECT {} {}'.format(at, len(results)))
        for result in results:
            self.send('RESULT ' + result_fields(result))
        reply = self.read()
        if len(reply) != 2 or reply[0] != 'INJECTED':
            raise RuntimeError('invalid INJECTED')
        self.next_time = self._time(reply[1])

    def finish(self):
        """프로토콜 종료 응답과 자식의 정상 종료를 모두 확인한다."""
        self.send('QUIT')
        if self.read() != ['BYE']:
            raise RuntimeError('invalid shutdown acknowledgement')
        if self.process.wait(timeout=5) != 0:
            raise RuntimeError('ns-3 participant failed')

    def close(self):
        """오류가 발생해도 이 runner가 만든 자식 프로세스를 남기지 않는다."""
        if self.stream:
            self.stream.close()
        self.sock.close()
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)


class FederationManager:
    """두 이벤트 엔진이 서로의 사건을 건너뛰지 않도록 진행 순서를 조정한다."""

    def __init__(self, scenario, binary=None):
        # P0가 지원하지 않는 잡음·만료 등의 설정을 조용히 무시하지 않는다.
        allowed = {'name', 'seed', 'processors', 'resources', 'events', 'followups'}
        if set(scenario) - allowed:
            raise ValueError('unsupported P0 scenario fields: {}'.format(set(scenario) - allowed))
        if not 0 < len(scenario['processors']) <= 1000 or len(scenario['resources']) > 10000:
            raise ValueError('P0 scenario size limit exceeded')
        for resource in scenario['resources']:
            if set(resource) != {'pair_id', 'processor_id'}:
                raise ValueError('P0 resource accepts only pair_id and processor_id')
            integer(resource['processor_id'], 'processor_id', maximum=2 ** 32 - 1)
        for field in ('events', 'followups'):
            events = scenario.get(field, [])
            if len(events) > 10000:
                raise ValueError('P0 event count limit exceeded')
            for event in events:
                keys = {'type', 'request_id', 'processor_id', 'pair_a', 'pair_b', 'duration_ns'}
                keys |= {'time_ns'} if field == 'events' else {'after_request_id', 'delay_ns'}
                if set(event) - keys:
                    raise ValueError('unsupported P0 event fields')
                normalize_request(event)
        self.scenario = scenario
        self.binary = Path(binary) if binary else find_worker()

    def run(self):
        """SPEC-P0.md의 여섯 처리 단계를 반복하고 재현 가능한 기록을 반환한다."""
        scenario = self.scenario
        quantum = QuantumScheduler(scenario['processors'], scenario['resources'],
                                   seed=scenario.get('seed', 7))
        participant = Participant(self.binary, scenario)
        steps, arrivals, deliveries = [], [], []
        try:
            while True:
                horizon = quantum.next_safe_horizon()
                # ns-3의 다음 사건과 양자 완료 중 더 이른 쪽을 먼저 처리한다.
                # 예: 양자 완료가 39 ms여도 새 요청이 38 ms라면 38 ms에서 만난다.
                candidates = [t for t in (horizon, participant.next_time) if t is not None]
                if not candidates:
                    break
                at = min(candidates)
                if len(steps) >= 100000:
                    raise RuntimeError('federation step limit exceeded')
                # 1·2단계: 완료된 양자 연산과 자원 상태를 먼저 확정한다.
                # 3단계: 같은 시각의 ns-3 입력들을 이벤트 UID 순서로 모두 모은다.
                results = quantum.advance_to_boundary(at)
                inputs, received = participant.advance(at)
                deliveries.extend(received)
                for request in inputs:
                    arrivals.append(dict(time_ns=at, order=len(arrivals), **request))
                    results.append(quantum.submit_request(request))
                # 4·5단계: 요청/취소를 모두 반영한 뒤 빈 프로세서를 배정한다.
                # 완료 콜백 안에서 다음 작업을 바로 시작하면 같은 시각의 취소가 늦어진다.
                results.extend(quantum.schedule_queued())
                # 6단계: 결과를 같은 시각의 ns-3 이벤트로 예약한다.
                # 결과가 후속 요청을 만들면 at은 그대로인 채 다음 인과적 라운드를 돈다.
                # 따라서 완료 결과보다 그 결과에 반응한 요청이 앞서 처리되지 않는다.
                participant.inject(at, results)
                steps.append(dict(time_ns=at, quantum_horizon_ns=horizon,
                                  inputs=len(inputs), outputs=len(results),
                                  quantum_next_ns=quantum.next_safe_horizon(),
                                  ns3_next_ns=participant.next_time))
                if quantum.now_ns != participant.now_ns:
                    raise RuntimeError('federation clocks diverged')
            snapshot = quantum.snapshot()
            # 두 엔진의 다음 사건이 없는데 실행/대기 요청이 남으면 정상 종료가 아니다.
            if any(r['state'] in ('QUEUED', 'RUNNING') for r in quantum.requests.values()):
                raise RuntimeError('federation ended with unfinished requests')
            participant.finish()
        finally:
            participant.close()
        return {
            'schema_version': 1, 'scenario': scenario.get('name', 'p0'),
            'model': 'atomic-noiseless-bsm', 'time_unit': 'ns',
            'seed': scenario.get('seed', 7), 'ns3_binary': str(self.binary),
            'ns3_time_ns': participant.now_ns, 'snapshot': snapshot,
            'quantum_events': quantum.trace, 'ns3_inputs': arrivals,
            'ns3_results': deliveries, 'bridge_steps': steps,
        }


def main():
    """시나리오 읽기 → federation 실행 → JSON 결과 저장의 명령행 흐름."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario', type=Path)
    parser.add_argument('--ns3-binary', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    with args.scenario.open() as stream:
        scenario = json.load(stream)
    report = FederationManager(scenario, args.ns3_binary).run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + '\n')
    requests = report['snapshot']['requests']
    print('{}: {} requests, t={} ns; report: {}'.format(
        report['scenario'], len(requests), report['ns3_time_ns'], args.output))


if __name__ == '__main__':
    try:
        main()
    except (ValueError, RuntimeError, OSError) as error:
        print('cosim-p0: {}'.format(error), file=sys.stderr)
        sys.exit(1)
