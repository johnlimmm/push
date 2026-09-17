"""실제 양자 상태와 프로세서별 FIFO·자원 예약을 관리하는 P0 스케줄러.

모델: 고정 시간 동안 자원을 점유한 뒤 완료 시점에 무잡음 BSM을 한 번 적용한다.
BSM은 Bell 상태 측정이다. 실행시간은 이 어댑터가 관리하고, 양자 상태 변화는
NetSquid가 계산한다. NetSquid 자체의 timed QuantumProgram 실행은 아직 사용하지 않는다.

호출 흐름: advance_to_boundary(t) → submit_request()들 → schedule_queued().
자율적인 미래 이벤트가 없는 P0에 한정해 시각 경계에서 정확히 멈추고 재개한다.
"""

from collections import deque

import netsquid as ns
import numpy as np
from netsquid.components import QuantumMemory, QuantumProcessor
from netsquid.components.instructions import INSTR_CNOT, INSTR_H, INSTR_MEASURE
from netsquid.qubits import ketstates, qubitapi as qapi


MAX_TIME_NS = 2 ** 53 - 1  # NetSquid의 double 시간에서도 정수 ns를 정확히 표현하는 범위
MAX_ID = 2 ** 63 - 1


def integer(value, name, minimum=0, maximum=MAX_ID):
    """정수형과 범위를 함께 검사한다. bool도 정수 ID/시간으로 받지 않는다."""
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError('{} must be an integer in [{}, {}]'.format(name, minimum, maximum))
    return value


def normalize_request(event):
    """SUBMIT/CANCEL을 동일한 전송 형식으로 정규화한다.

    CANCEL은 ID만 필요하므로 사용하지 않는 자원·시간 필드는 0으로 채운다.
    여기서는 형식만 검사하며, 자원 존재·예약 충돌은 실제 도착 시점에 검사한다.
    """
    kind = event.get('type', 'SUBMIT')
    if kind not in ('SUBMIT', 'CANCEL'):
        raise ValueError('type must be SUBMIT or CANCEL')
    request = {
        'type': kind,
        'request_id': integer(event['request_id'], 'request_id', 1),
        'processor_id': integer(event.get('processor_id', 0), 'processor_id', maximum=2 ** 32 - 1),
    }
    if kind == 'SUBMIT':
        request.update(
            pair_a=integer(event['pair_a'], 'pair_a', 1),
            pair_b=integer(event['pair_b'], 'pair_b', 1),
            duration_ns=integer(event['duration_ns'], 'duration_ns', 1, MAX_TIME_NS),
        )
    else:
        request.update(pair_a=0, pair_b=0, duration_ns=0)
    return request


class QuantumScheduler:
    """양자 참가자 하나의 상태. NetSquid 엔진은 Python 프로세스마다 하나다."""

    def __init__(self, processor_ids, resources, seed=7):
        if not processor_ids or len(set(processor_ids)) != len(processor_ids):
            raise ValueError('processor_ids must be nonempty and unique')
        for pid in processor_ids:
            integer(pid, 'processor_id', maximum=2 ** 32 - 1)
        pair_ids = [r['pair_id'] for r in resources]
        if len(set(pair_ids)) != len(pair_ids):
            raise ValueError('pair IDs must be unique')
        for resource in resources:
            integer(resource['pair_id'], 'pair_id', 1)
            if resource['processor_id'] not in processor_ids:
                raise ValueError('resource has unknown processor')
        integer(seed, 'seed', maximum=2 ** 32 - 1)

        # 새 시나리오를 시작할 때만 초기화한다. 진행 중 시간을 되돌리는 데 쓰지 않는다.
        ns.sim_reset()
        ns.set_random_state(seed=seed)
        ns.set_qstate_formalism(ns.QFormalism.DM)
        self.now_ns = 0
        self.requests = {}   # request_id → 현재 상태, 최초 도착·시작·완료 시각, 결과 비트
        self.resources = {}  # pair_id → 예약 소유자, 메모리 위치, 원격 큐빗 보관 장소
        self.outputs = {}    # BSM 이후 남은 원격 얽힘의 handle과 평가용 정보
        self.trace = []      # 같은 timestamp 안에서도 sequence로 처리 순서를 구분
        self.processors = {}
        for pid in sorted(processor_ids):
            owned = sorted((r for r in resources if r['processor_id'] == pid),
                           key=lambda r: r['pair_id'])
            processor = QuantumProcessor('processor_{}'.format(pid),
                                         num_positions=max(1, len(owned)))
            self.processors[pid] = {'device': processor, 'queue': deque(), 'running': None}
            for slot, spec in enumerate(owned):
                # Bell pair의 local 절반만 repeater 프로세서에 넣는다.
                # remote 절반은 별도 메모리에 남아 BSM 후 원격 얽힘을 이룬다.
                pair_id = spec['pair_id']
                remote, local = qapi.create_qubits(2)
                qapi.operate(remote, ns.H)
                qapi.operate([remote, local], ns.CNOT)
                endpoint = self._create_endpoint(pair_id)
                endpoint.put(remote)
                processor.put(local, positions=slot)
                self.resources[pair_id] = {
                    'state': 'AVAILABLE', 'owner': None, 'processor_id': pid,
                    'slot': slot, 'endpoint': endpoint, 'created_ns': 0,
                }
        self._drain_current_timestamp()

    def _create_endpoint(self, pair_id):
        """P1은 B 쪽 메모리만 보정 가능한 QuantumProcessor로 구체화한다."""
        return QuantumMemory('endpoint_pair_{}'.format(pair_id), num_positions=1)

    def _drain_current_timestamp(self):
        # put/pop이 만든 현재 시각의 알림을 모두 처리한다. 이 P0 모델에는
        # 미래 native 이벤트·사용자 콜백이 없으므로 무제한 run()이 현재 시각에 끝난다.
        # 이 가정이 깨지면 아래 검사가 실패한다. 일반 timed program용 step API가 아니다.
        ns.sim_run()
        if ns.sim_time() != self.now_ns or ns.sim_count_events() != 0:
            raise RuntimeError('P0 requires only current-timestamp native events')

    def next_safe_horizon(self):
        """모든 실행 중 프로세서의 완료 중 가장 이른 시각. 없으면 None.

        새 외부 입력을 받으면 다시 계산한다. 자율 실패·만료가 없는 P0에서만
        '다음 완료'가 곧 '다음 외부 알림이 발생할 수 있는 시각'이다.
        """
        times = [self.requests[p['running']]['completion_ns']
                 for p in self.processors.values() if p['running'] is not None]
        return min(times) if times else None

    def _record(self, event, request=None, **fields):
        """진단 기록을 남긴다. 이 함수 자체가 ns-3에 이벤트를 보내지는 않는다."""
        row = {'time_ns': self.now_ns, 'sequence': len(self.trace), 'event': event}
        if request is not None:
            row.update(request_id=request['request_id'], processor_id=request['processor_id'])
        row.update(fields)
        self.trace.append(row)

    def _state(self, request, state, code='OK'):
        """요청 상태 갱신과 기록을 한곳에서 수행해 전이 이력을 보존한다."""
        request['state'] = state
        request['code'] = code
        self._record(state, request, code=code)

    def _reply(self, request, code=None, state=None):
        # 현재 상태의 복사본을 만든다. 이후 QUEUED → RUNNING으로 바뀌어도
        # 앞서 생성한 접수 응답의 내용이 함께 바뀌지 않도록 한다.
        return {
            'time_ns': self.now_ns,
            'request_id': request['request_id'],
            'processor_id': request['processor_id'],
            'state': state or request['state'],
            'code': code or request.get('code', 'OK'),
            'm1': request.get('m1', -1), 'm2': request.get('m2', -1),
        }

    def advance_to_boundary(self, time_ns):
        """t의 완료를 확정한다. 대기 중인 다음 작업은 아직 시작하지 않는다."""
        integer(time_ns, 'time_ns', maximum=MAX_TIME_NS)
        if time_ns < self.now_ns:
            raise ValueError('quantum time reversal')
        horizon = self.next_safe_horizon()
        if horizon is not None and time_ns > horizon:
            raise ValueError('advance would skip safe horizon')
        if ns.sim_count_events():
            raise RuntimeError('undrained native events')
        # native timeline은 비어 있다. 시계만 t로 이동한 뒤 어댑터의 완료를 처리하므로,
        # sim_run(end_time=t)가 t의 native 이벤트를 제외하는 문제를 피한다.
        ns.sim_run(end_time=time_ns)
        self.now_ns = time_ns
        if ns.sim_time() != time_ns:
            raise RuntimeError('NetSquid clock mismatch')
        completed = []
        for pid in sorted(self.processors):
            processor = self.processors[pid]
            rid = processor['running']
            if rid is not None and self.requests[rid]['completion_ns'] == time_ns:
                request = self.requests[rid]
                self._complete_bsm(request)
                processor['running'] = None
                self._state(request, 'COMPLETED')
                completed.append(self._reply(request))
        self._drain_current_timestamp()
        return completed

    def _complete_bsm(self, request):
        """예약된 두 local 큐빗을 실제로 측정하고 원격 생존 큐빗을 기록한다."""
        ra = self.resources[request['pair_a']]
        rb = self.resources[request['pair_b']]
        device = self.processors[request['processor_id']]['device']
        a, b = ra['slot'], rb['slot']
        # 완료 시 한 번에 상태를 바꾸는 P0 모델이다. physical=False는 의도적이다.
        # 네이티브 명령의 시간/잡음까지 모사한다고 해석하면 안 된다.
        # BSM 회로: CNOT(a→b), H(a), Z 측정(a,b). m1은 Z, m2는 X 보정 비트다.
        device.execute_instruction(INSTR_CNOT, [a, b], physical=False)
        device.execute_instruction(INSTR_H, [a], physical=False)
        m1 = int(device.execute_instruction(INSTR_MEASURE, [a], physical=False)[0]['instr'][0])
        m2 = int(device.execute_instruction(INSTR_MEASURE, [b], physical=False)[0]['instr'][0])
        request.update(m1=m1, m2=m2)
        # 측정한 local 큐빗은 소모하지만 원격 두 큐빗은 메모리에 유지한다.
        for qubit in device.pop([a, b]):
            qapi.discard(qubit)
        ra['state'] = rb['state'] = 'CONSUMED'

        # 평가용 진단: 원격 큐빗을 실제로 보정하지 않고, 해당 측정 비트에 맞는
        # Bell 상태와 비교한다. correction = Z^m1 X^m2이며 아래 reference는
        # 그 보정을 역으로 적용한 기준 상태다. squared=True로 제곱 fidelity를 쓴다.
        # ns-3는 측정 비트만 받는다. 이 정확한 fidelity를 제어기가 아는 것으로 가정하지 않는다.
        remote = ra['endpoint'].peek(0) + rb['endpoint'].peek(0)
        x = np.array([[0, 1], [1, 0]])
        z = np.diag([1, -1])
        correction = (z if m1 else np.eye(2)) @ (x if m2 else np.eye(2))
        reference = np.kron(np.eye(2), correction.conj().T) @ ketstates.b00
        fidelity = float(qapi.fidelity(remote, reference, squared=True))
        self.outputs[request['request_id']] = {
            'handle': 'swap:{}'.format(request['request_id']),
            'input_pairs': [request['pair_a'], request['pair_b']],
            'created_ns': self.now_ns, 'frame_pending': True,
            'm1': m1, 'm2': m2, 'frame_fidelity': fidelity,
        }
        self._record('BSM_MEASURED', request, m1=m1, m2=m2, frame_fidelity=fidelity)

    @staticmethod
    def _fingerprint(request):
        # 재시도 도착 시각은 제외한다. 자원 순서는 BSM 비트의 의미를 바꾸므로 보존한다.
        return tuple(request[key] for key in
                     ('processor_id', 'pair_a', 'pair_b', 'duration_ns'))

    def submit_request(self, raw):
        """도착한 요청을 검사·예약하거나 기존 응답을 반환한다. 실행은 별도 단계다."""
        request = normalize_request(raw)
        rid = request['request_id']
        if request['type'] == 'CANCEL':
            return self._cancel(request)
        if rid in self.requests:
            # 멱등성: 같은 ID는 상태 조회/재시도로 처리하며 양자 측정을 다시 하지 않는다.
            original = self.requests[rid]
            if self._fingerprint(original) != self._fingerprint(request):
                self._record('REQUEST_ID_REUSE', request)
                return self._reply(request, state='REJECTED', code='REQUEST_ID_REUSE')
            self._record('DUPLICATE', original)
            return self._reply(original, code='DUPLICATE')

        request.update(arrival_ns=self.now_ns, start_ns=None, completion_ns=None)
        self.requests[rid] = request
        self._state(request, 'RECEIVED')
        pid = request['processor_id']
        pairs = (request['pair_a'], request['pair_b'])
        error = None
        if pid not in self.processors:
            error = 'UNKNOWN_PROCESSOR'
        elif pairs[0] == pairs[1]:
            error = 'INVALID_PAIR_SET'
        elif any(pair not in self.resources for pair in pairs):
            error = 'UNKNOWN_RESOURCE'
        elif any(self.resources[pair]['processor_id'] != pid for pair in pairs):
            error = 'RESOURCE_LOCATION'
        elif any(self.resources[pair]['state'] != 'AVAILABLE' for pair in pairs):
            error = 'RESOURCE_CONFLICT'
        else:
            processor = self.processors[pid]
            # 이미 예약된 FIFO까지 고려해 표현 가능한 시간 범위를 검사한다.
            # 대기 취소는 이 예상 시각을 줄일 수 있지만 늘리지는 않는다.
            finish = (self.requests[processor['running']]['completion_ns']
                      if processor['running'] is not None else self.now_ns)
            finish += sum(self.requests[q]['duration_ns'] for q in processor['queue'])
            if finish + request['duration_ns'] > MAX_TIME_NS:
                error = 'TIME_OVERFLOW'
        if error:
            self._state(request, 'REJECTED', error)
            return self._reply(request)

        # 두 자원의 검사를 모두 통과한 뒤 예약한다. 하나만 먼저 예약해 두면
        # 다른 자원에서 충돌한 거절 요청이 첫 자원을 계속 붙잡는 오류가 생긴다.
        for pair in pairs:
            self.resources[pair].update(state='RESERVED', owner=rid)
        self.processors[pid]['queue'].append(rid)
        self._state(request, 'QUEUED')
        return self._reply(request)

    def _cancel(self, cancel):
        """QUEUED만 취소한다. 이미 RUNNING인 양자 상태를 원상복구하지 않는다."""
        rid = cancel['request_id']
        if rid not in self.requests:
            self._record('CANCEL_UNKNOWN', cancel)
            return self._reply(cancel, state='REJECTED', code='UNKNOWN_REQUEST')
        request = self.requests[rid]
        if request['state'] == 'QUEUED':
            self.processors[request['processor_id']]['queue'].remove(rid)
            for pair in (request['pair_a'], request['pair_b']):
                self.resources[pair].update(state='AVAILABLE', owner=None)
            self._state(request, 'CANCELLED')
            return self._reply(request)
        if request['state'] == 'RUNNING':
            self._record('CANCEL_DENIED', request)
            return self._reply(request, code='NOT_CANCELLABLE')
        self._record('CANCEL_NOOP', request)
        return self._reply(request, code='ALREADY_TERMINAL')

    def schedule_queued(self):
        """같은 시각의 입력을 모두 반영한 뒤, 프로세서마다 FIFO 하나를 실행한다."""
        replies = []
        for pid in sorted(self.processors):
            processor = self.processors[pid]
            if processor['running'] is None and processor['queue']:
                rid = processor['queue'].popleft()
                request = self.requests[rid]
                request.update(start_ns=self.now_ns,
                               completion_ns=self.now_ns + request['duration_ns'])
                # 여기서는 자원 점유와 완료 예약만 한다. 실제 BSM은 완료 시점에 수행한다.
                processor['running'] = rid
                for pair in (request['pair_a'], request['pair_b']):
                    self.resources[pair]['state'] = 'IN_USE'
                self._state(request, 'RUNNING')
                replies.append(self._reply(request))
        self.check_invariants()
        return replies

    def check_invariants(self):
        """항상 지켜야 할 조건: 중복 배정 없음, 예약 소유자 일치, 두 시간 표현 일치."""
        seen = set()
        for processor in self.processors.values():
            active = processor['running']
            members = list(processor['queue']) + ([active] if active is not None else [])
            for rid in members:
                if rid in seen:
                    raise RuntimeError('request scheduled more than once')
                seen.add(rid)
                request = self.requests[rid]
                state = 'RUNNING' if rid == active else 'QUEUED'
                if request['state'] != state:
                    raise RuntimeError('queue/request state mismatch')
                for pair in (request['pair_a'], request['pair_b']):
                    resource = self.resources[pair]
                    expected = 'IN_USE' if state == 'RUNNING' else 'RESERVED'
                    if resource['owner'] != rid or resource['state'] != expected:
                        raise RuntimeError('reservation ownership mismatch')
        if any(r['state'] in ('QUEUED', 'RUNNING') and rid not in seen
               for rid, r in self.requests.items()):
            raise RuntimeError('orphaned request')
        if ns.sim_time() != self.now_ns or ns.sim_count_events():
            raise RuntimeError('native engine boundary mismatch')

    def snapshot(self):
        """실행 결과를 JSON으로 저장할 수 있도록 native 메모리 객체를 제외한다."""
        native_time = ns.sim_time()
        # float 시계를 정수 ns로 기록하되, 소수·비유한 값·범위 초과를 잘라내거나 반올림하지 않는다.
        if (not np.isfinite(native_time) or not 0 <= native_time <= MAX_TIME_NS or
                native_time != int(native_time)):
            raise RuntimeError('NetSquid clock must be exact integer nanoseconds within range')
        self.check_invariants()
        return {
            'time_ns': self.now_ns,
            'netsquid_time_ns': int(native_time),
            'requests': self.requests,
            'resources': {pair: {k: v for k, v in resource.items() if k != 'endpoint'}
                          for pair, resource in self.resources.items()},
            'outputs': self.outputs,
        }
