"""P0 스케줄러 위에 단일 A–R–B 출력 자원과 B의 원자적 보정을 추가한다."""

import copy

import netsquid as ns
from netsquid.components import QuantumMemory, QuantumProcessor
from netsquid.components.instructions import INSTR_X, INSTR_Z
from netsquid.qubits import ketstates, qubitapi as qapi

from quantum_scheduler import MAX_TIME_NS, QuantumScheduler


class EventLog:
    """공통 로그 v1. event_id는 고유 ID, sequence는 동일 시각을 포함한 기록 순서다."""

    def __init__(self, session_id):
        self.session_id = session_id
        self.events = []
        self.ids = set()

    def add(self, event_type, at, node_id=None, cause=None, event_id=None, **fields):
        event_id = event_id or 'p:{}'.format(len(self.events))
        if event_id in self.ids or (cause is not None and cause not in self.ids):
            raise RuntimeError('duplicate event ID or missing causal parent')
        if self.events and at < self.events[-1]['sim_time_ns']:
            raise RuntimeError('event log time reversal')
        row = dict(schema_version=1, session_id=self.session_id, event_id=event_id,
                   event_type=event_type, sim_time_ns=at, node_id=node_id,
                   sequence=len(self.events), source='quantum', source_sequence=None,
                   round=None, phase=None, caused_by_event_id=cause,
                   request_id=None, message_id=None, processor_id=None,
                   input_pair_ids=[], output_pair_id=None,
                   request_state=None, resource_state={}, measurement_bits=None,
                   fidelity=None, fidelity_kind=None, details={})
        row.update(fields)
        self.events.append(copy.deepcopy(row))
        self.ids.add(event_id)
        return event_id


def encode_dm(matrix):
    """JSON은 complex를 지원하지 않으므로 실수부·허수부와 큐빗 순서를 함께 저장한다."""
    return dict(qubit_order=['A', 'B'], real=matrix.real.tolist(), imag=matrix.imag.tolist())


class P1Quantum(QuantumScheduler):
    """BSM은 R(2), correction은 B(3). 새로운 세션을 동시에 생성하지 않는다."""

    def __init__(self, config, log, root_cause):
        self.config = config
        self.log = log
        self.root_cause = root_cause
        self.external_cause = root_cause
        self.request_causes = {}
        self.complete_causes = {}
        self.round = 0
        self.phase = 'INITIALIZE'
        self.ab = None
        self.correction = None
        self.correction_cause = None
        self.correction_count = 0
        super().__init__([2], [dict(pair_id=i, processor_id=2) for i in (1, 2)], config['seed'])
        for pair, endpoint in ((1, 'A'), (2, 'B')):
            # 입력 EPR의 논리적 소모와 살아 있는 endpoint 큐빗의 수명은 구분한다.
            self.resources[pair]['locations'] = [
                dict(node_id=endpoint, memory_id=endpoint, position=0),
                dict(node_id='R', memory_id='processor_2', position=pair - 1)]
            remote = self.resources[pair]['endpoint'].peek(0)
            local = self.processors[2]['device'].peek(pair - 1)
            fidelity = float(qapi.fidelity(remote + local, ketstates.b00, squared=True))
            self.log.add('EPR_CREATED', 0, cause=root_cause, processor_id=2,
                         input_pair_ids=[pair], resource_state={str(pair): 'AVAILABLE'},
                         fidelity=fidelity, fidelity_kind='initial',
                         details=dict(locations=self.resources[pair]['locations']))

    def _create_endpoint(self, pair_id):
        if pair_id == 2:
            return QuantumProcessor('B', num_positions=1)
        return QuantumMemory('A', num_positions=1)

    def states(self):
        states = {str(k): r['state'] for k, r in self.resources.items()}
        if self.ab is not None:
            states['3'] = self.ab['state']
        return states

    def _record(self, event, request=None, **fields):
        """P0의 실제 전이 순간에 공통 로그를 남긴다. 사후 최종 상태로 과거를 덮지 않는다."""
        super()._record(event, request, **fields)
        if request is None:
            return
        rid = request['request_id']
        transitions = {'RECEIVED', 'QUEUED', 'RUNNING', 'BSM_MEASURED', 'COMPLETED', 'REJECTED'}
        cause = self.request_causes.get(rid, self.external_cause)
        if event in ('RECEIVED', 'DUPLICATE', 'REQUEST_ID_REUSE'):
            cause = self.external_cause
        names = {'RUNNING': 'BSM_START', 'COMPLETED': 'BSM_COMPLETE'}
        bits = [request['m1'], request['m2']] if 'm1' in request else None
        eid = self.log.add(names.get(event, 'BSM_' + event) if event != 'BSM_MEASURED'
                           else event, self.now_ns, 'R', cause,
                           request_id=rid, processor_id=2, input_pair_ids=[1, 2],
                           output_pair_id=3 if self.ab is not None else None,
                           request_state=request.get('state'), resource_state=self.states(),
                           measurement_bits=bits, round=self.round, phase=self.phase,
                           fidelity=fields.get('frame_fidelity'),
                           fidelity_kind='frame' if 'frame_fidelity' in fields else None,
                           details=fields)
        if event in transitions:
            self.request_causes[rid] = eid
        if event == 'COMPLETED':
            self.complete_causes[rid] = eid

    def submit_bsm(self, message, cause):
        self.external_cause = cause
        if message['session_id'] != self.config['session_id']:
            raise ValueError('BSM session mismatch')
        if (message['pair_a'], message['pair_b'], message['output_pair_id']) != (1, 2, 3):
            raise ValueError('P1 requires ordered AR/RB inputs and AB output')
        return self.submit_request(dict(request_id=message['request_id'], processor_id=2,
                                   pair_a=1, pair_b=2, duration_ns=self.config['bsm_duration_ns']))

    def _complete_bsm(self, request):
        if self.ab is not None:
            raise RuntimeError('P1 can create only one AB pair')
        super()._complete_bsm(request)
        self.ab = dict(pair_id=3, input_pair_ids=[1, 2], state='FRAME_PENDING',
                       bsm_request_id=request['request_id'], created_ns=self.now_ns,
                       locations=[dict(node_id='A', memory_id='A', position=0),
                                  dict(node_id='B', memory_id='B', position=0)],
                       usable_ns=None, fidelity=None, density_matrix=None)

    def next_safe_horizon(self):
        horizon = super().next_safe_horizon()
        times = [horizon] if horizon is not None else []
        if self.correction and self.correction['state'] == 'RUNNING':
            times.append(self.correction['completion_ns'])
        return min(times) if times else None

    def correction_event(self, event, cause, code='OK'):
        request = self.correction
        # 같은 AB 자원에 제자리 보정을 적용한다. AR/RB는 이 연산의 입력이 아니라 생성 이력이다.
        return self.log.add(event, self.now_ns, 'B', cause, request_id=2, processor_id=3,
                            input_pair_ids=[3], output_pair_id=3,
                            request_state=request['state'] if request else 'REJECTED',
                            resource_state=self.states(),
                            measurement_bits=request['measurement_bits'] if request else None,
                            round=self.round, phase=self.phase,
                            details=dict(code=code, ancestor_pair_ids=[1, 2]))

    def submit_correction(self, message, cause):
        """재전송의 message_id는 달라도 논리 작업의 식별자와 내용이 같으면 한 번만 보정한다."""
        identity = (message['session_id'], message['request_id'], message['pair_a'],
                    message['pair_b'], message['output_pair_id'])
        bits = (message['m1'], message['m2'])
        expected = (self.config['session_id'], self.ab['bsm_request_id'], 1, 2, 3) if self.ab else None
        if identity != expected or any(type(b) is not int or b not in (0, 1) for b in bits):
            self.correction_event('CORRECTION_REJECTED', cause, 'INVALID_RESULT')
            return 'INVALID_RESULT'
        if self.correction is not None:
            code = 'DUPLICATE' if list(bits) == self.correction['measurement_bits'] else 'RESULT_MISMATCH'
            self.correction_event('CORRECTION_' + code, cause, code)
            return code
        # 최초 패킷의 비트를 사용한다. 평가용 fidelity나 R의 숨은 측정 상태로 보정하지 않는다.
        if self.now_ns + self.config['correction_duration_ns'] > MAX_TIME_NS:
            self.correction_event('CORRECTION_REJECTED', cause, 'TIME_OVERFLOW')
            return 'TIME_OVERFLOW'
        self.correction = dict(request_id=2, bsm_request_id=message['request_id'],
                               state='QUEUED', arrival_ns=self.now_ns, start_ns=None,
                               completion_ns=None, measurement_bits=list(bits))
        self.correction_cause = self.correction_event('CORRECTION_QUEUED', cause)
        return 'OK'

    def schedule_queued(self):
        replies = super().schedule_queued()
        if self.correction and self.correction['state'] == 'QUEUED':
            self.correction.update(state='RUNNING', start_ns=self.now_ns,
                                   completion_ns=self.now_ns + self.config['correction_duration_ns'])
            self.ab['state'] = 'CORRECTING'
            self.correction_cause = self.correction_event('CORRECTION_START', self.correction_cause)
        return replies

    def advance_to_boundary(self, time_ns):
        completed = super().advance_to_boundary(time_ns)
        for result in completed:
            self.log.add('AB_CREATED', self.now_ns, cause=self.complete_causes[result['request_id']],
                         request_id=result['request_id'], input_pair_ids=[1, 2], output_pair_id=3,
                         resource_state=self.states(), round=self.round, phase=self.phase,
                         details=dict(locations=self.ab['locations']))
        if (self.correction and self.correction['state'] == 'RUNNING' and
                self.correction['completion_ns'] == time_ns):
            m1, m2 = self.correction['measurement_bits']
            device = self.resources[2]['endpoint']
            # 00도 양의 고정 실행시간을 소비한다. 상태 갱신은 완료 시 한 번만 한다.
            if m2:
                device.execute_instruction(INSTR_X, [0], physical=False)
            if m1:
                device.execute_instruction(INSTR_Z, [0], physical=False)
            self.correction_count += 1
            self.correction['state'] = 'COMPLETED'
            self.ab.update(state='USABLE', usable_ns=self.now_ns)
            self.outputs[self.ab['bsm_request_id']]['frame_pending'] = False
            self.correction_cause = self.correction_event('CORRECTION_COMPLETE', self.correction_cause)
            remote = self.resources[1]['endpoint'].peek(0) + self.resources[2]['endpoint'].peek(0)
            self.ab['fidelity'] = float(qapi.fidelity(remote, ketstates.b00, squared=True))
            self.ab['density_matrix'] = encode_dm(qapi.reduced_dm(remote))
            self.log.add('PAIR_USABLE', self.now_ns, 'B', self.correction_cause,
                         request_id=2, processor_id=3, output_pair_id=3,
                         input_pair_ids=[3], request_state='COMPLETED',
                         resource_state=self.states(), measurement_bits=[m1, m2],
                         fidelity=self.ab['fidelity'], fidelity_kind='usable',
                         round=self.round, phase=self.phase, details=dict(ancestor_pair_ids=[1, 2]))
            self._drain_current_timestamp()
        return completed

    def snapshot(self):
        snapshot = super().snapshot()
        snapshot.update(ab_pair=self.ab, correction=self.correction, correction_count=self.correction_count)
        return copy.deepcopy(snapshot)

    def check_invariants(self):
        super().check_invariants()
        if self.ab is not None:
            if any(r['state'] != 'CONSUMED' for r in self.resources.values()):
                raise RuntimeError('AB pair exists before input consumption')
            if self.requests[self.ab['bsm_request_id']]['state'] != 'COMPLETED':
                raise RuntimeError('AB pair has no completed BSM owner')
        if self.correction is None:
            if self.correction_count or (self.ab and self.ab['state'] != 'FRAME_PENDING'):
                raise RuntimeError('AB state without correction request')
        else:
            state = self.correction['state']
            expected = {'QUEUED': 'FRAME_PENDING', 'RUNNING': 'CORRECTING', 'COMPLETED': 'USABLE'}
            if not self.ab or self.ab['state'] != expected[state]:
                raise RuntimeError('correction/output state mismatch')
            if self.correction_count != (1 if state == 'COMPLETED' else 0):
                raise RuntimeError('correction must commit exactly once')
