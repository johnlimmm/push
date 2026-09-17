"""P3: P0 FIFO를 한 번 초기화하고 session별 자원을 공유 R/A/B 장치에 배치한다.

외부 ID는 (session_id, local_id), P0 내부 ID는 충돌 없는 정수로 매핑한다.
메모리 잡음은 P2와 동일한 native T1T2NoiseModel만 사용한다.
"""

import copy
from collections import deque

import netsquid as ns
import numpy as np
from netsquid.components import QuantumMemory, QuantumProcessor
from netsquid.components.instructions import INSTR_X, INSTR_Z
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.qubits import ketstates

from p2_quantum import encode_state
from quantum_scheduler import MAX_TIME_NS, QuantumScheduler


class MemoryPosition:
    """P0의 endpoint 한 칸 API를 공유 native 메모리의 특정 position에 연결한다.

    큐빗을 복제하거나 이동하지 않는다. 생성부터 모든 접근이 같은 native position을 사용한다.
    """
    def __init__(self, device, position):
        self.device, self.position = device, position

    def put(self, qubit):
        self.device.put(qubit, positions=self.position)

    def peek(self, position=0):
        if position != 0:
            raise ValueError('endpoint view exposes one position')
        return self.device.peek(self.position)


class P3Quantum(QuantumScheduler):
    def __init__(self, config, log, roots):
        self.config, self.log, self.roots = config, log, roots
        self.round, self.phase = 0, 'INITIALIZE'
        self.external_cause = None
        self.request_causes, self.complete_causes = {}, {}
        self.sessions, self.rid_to_sid, self.pair_to_location = {}, {}, {}
        self.a_memory = self.b_processor = None
        self.correction_queue, self.correction_running = deque(), None
        for slot, item in enumerate(config['sessions']):
            sid, rid = item['session_id'], slot + 1
            pairs = [2 * slot + 1, 2 * slot + 2]
            self.rid_to_sid[rid] = sid
            self.sessions[sid] = dict(session_id=sid, rid=rid, pairs=pairs, slot=slot,
                ab_pair=None, correction=None, correction_count=0, checkpoints={})
            self.pair_to_location[pairs[0]] = ('A', slot)
            self.pair_to_location[pairs[1]] = ('B', slot)
        # 이 한 번의 초기화만 ns.sim_reset()을 수행한다. R의 native processor는 정확히 하나다.
        resources = [dict(pair_id=p, processor_id=2) for p in self.pair_to_location]
        super().__init__([2], resources, config['seed'])
        noise = config['memory_noise']
        for device in (self.a_memory, self.processors[2]['device'], self.b_processor):
            for position in device.mem_positions:
                position.models['noise_model'] = T1T2NoiseModel(T1=noise['T1_ns'], T2=noise['T2_ns'])
        for sid, session in self.sessions.items():
            initial = self.input_states(sid)
            session['original_endpoints'] = tuple(self.endpoints(sid))
            for local, pair in enumerate(session['pairs'], 1):
                self.resources[pair]['locations'] = self.locations(sid, local)
                self.emit(sid, 'EPR_CREATED', roots[sid], input_pair_ids=[local],
                    fidelity=initial['AR' if local == 1 else 'RB']['fidelity'], fidelity_kind='initial',
                    details=dict(locations=self.locations(sid, local), created_ns=0))

    def _create_endpoint(self, pair_id):
        if self.a_memory is None:
            self.a_memory = QuantumMemory('A', num_positions=len(self.sessions))
            self.b_processor = QuantumProcessor('B', num_positions=len(self.sessions))
        node, slot = self.pair_to_location[pair_id]
        return MemoryPosition(self.a_memory if node == 'A' else self.b_processor, slot)

    def locations(self, sid, pair):
        slot = self.sessions[sid]['slot']
        a = dict(node_id='A', memory_id='A', position=slot)
        b = dict(node_id='B', memory_id='B', position=slot)
        if pair == 3:
            return [a, b]
        return [a if pair == 1 else b,
                dict(node_id='R', memory_id='processor_2', position=2 * slot + pair - 1)]

    def states(self, sid):
        session = self.sessions[sid]
        states = {str(i): self.resources[p]['state'] for i, p in enumerate(session['pairs'], 1)}
        if session['ab_pair']:
            states['3'] = session['ab_pair']['state']
        return states

    def emit(self, sid, kind, cause, **fields):
        fields.setdefault('resource_state', self.states(sid))
        return self.log.add(kind, self.now_ns, cause=cause, session_id=sid,
                            round=self.round, phase=self.phase, **fields)

    def endpoints(self, sid):
        slot = self.sessions[sid]['slot']
        return self.a_memory.peek(slot) + self.b_processor.peek(slot)

    def input_states(self, sid):
        session = self.sessions[sid]
        a, b = self.endpoints(sid)
        r1, r2 = self.processors[2]['device'].peek([2 * session['slot'], 2 * session['slot'] + 1])
        return dict(AR=encode_state([a, r1], ['A', 'R_AR'], self.now_ns),
                    RB=encode_state([r2, b], ['R_RB', 'B'], self.now_ns))

    def frame_state(self, sid):
        output = self.outputs[self.sessions[sid]['rid']]
        x, z = np.array([[0, 1], [1, 0]]), np.diag([1, -1])
        correction = (z if output['m1'] else np.eye(2)) @ (x if output['m2'] else np.eye(2))
        target = np.kron(np.eye(2), correction.conj().T) @ ketstates.b00
        return encode_state(self.endpoints(sid), ['A', 'B'], self.now_ns, target)

    def _record(self, event, request=None, **fields):
        super()._record(event, request, **fields)
        if request is None:
            return
        rid = request['request_id']
        sid = self.rid_to_sid[rid]
        session = self.sessions[sid]
        cause = self.request_causes.get(rid, self.external_cause)
        if event in ('RECEIVED', 'DUPLICATE', 'REQUEST_ID_REUSE'):
            cause = self.external_cause
        if event == 'RUNNING':
            session['checkpoints']['bsm_start'] = self.input_states(sid)
            fields.update(input_states=session['checkpoints']['bsm_start'],
                          waiting_ns=self.now_ns - request['arrival_ns'])
        if event == 'BSM_MEASURED':
            session['checkpoints']['frame'] = self.frame_state(sid)
            fields['density_matrix'] = session['checkpoints']['frame']['density_matrix']
        fields['queue_length'] = len(self.processors[2]['queue'])
        name = {'RUNNING': 'BSM_START', 'COMPLETED': 'BSM_COMPLETE', 'BSM_MEASURED': 'BSM_MEASURED'}
        eid = self.emit(sid, name.get(event, 'BSM_' + event), cause, node_id='R', processor_id=2,
            request_id=1, input_pair_ids=[1, 2], output_pair_id=3 if session['ab_pair'] else None,
            request_state=request.get('state'),
            measurement_bits=[request['m1'], request['m2']] if 'm1' in request else None,
            fidelity=fields.get('frame_fidelity'),
            fidelity_kind='frame' if 'frame_fidelity' in fields else None, details=fields)
        if event in ('RECEIVED', 'QUEUED', 'RUNNING', 'BSM_MEASURED', 'COMPLETED', 'REJECTED'):
            self.request_causes[rid] = eid
        if event == 'COMPLETED':
            self.complete_causes[rid] = eid

    def submit_bsm(self, message, cause):
        sid = message['session_id']
        if type(sid) is not int or sid not in self.sessions:
            raise ValueError('unknown BSM session')
        self.external_cause = cause
        identity = tuple(message.get(k) for k in ('request_id', 'pair_a', 'pair_b', 'output_pair_id'))
        if identity != (1, 1, 2, 3) or any(type(v) is not int for v in identity):
            self.emit(sid, 'BSM_REJECTED', cause, node_id='R', processor_id=2, request_id=1,
                      details=dict(code='INVALID_RESOURCE_IDENTITY'))
            return 'INVALID_RESOURCE_IDENTITY'
        session = self.sessions[sid]
        rid = session['rid']
        if rid not in self.requests:
            session['checkpoints']['arrival'] = self.input_states(sid)
        reply = self.submit_request(dict(request_id=rid, processor_id=2,
            pair_a=session['pairs'][0], pair_b=session['pairs'][1], duration_ns=self.config['bsm_duration_ns']))
        return reply['code']

    def _complete_bsm(self, request):
        sid = self.rid_to_sid[request['request_id']]
        session = self.sessions[sid]
        if session['ab_pair']:
            raise RuntimeError('session cannot create AB twice')
        session['checkpoints']['bsm_end_inputs'] = self.input_states(sid)
        super()._complete_bsm(request)
        session['ab_pair'] = dict(pair_id=3, input_pair_ids=[1, 2], bsm_request_id=1,
            state='FRAME_PENDING', created_ns=self.now_ns, locations=self.locations(sid, 3),
            usable_ns=None, fidelity=None, density_matrix=None)

    def next_safe_horizon(self):
        horizon = super().next_safe_horizon()
        times = [] if horizon is None else [horizon]
        if self.correction_running is not None:
            times.append(self.sessions[self.correction_running]['correction']['completion_ns'])
        return min(times) if times else None

    def correction_event(self, sid, kind, cause, code='OK'):
        correction = self.sessions[sid]['correction']
        return self.emit(sid, kind, cause, node_id='B', processor_id=3, request_id=2,
            input_pair_ids=[3], output_pair_id=3,
            request_state=correction['state'] if correction else 'REJECTED',
            measurement_bits=correction['measurement_bits'] if correction else None,
            details=dict(code=code, ancestor_pair_ids=[1, 2]))

    def submit_correction(self, message, cause):
        sid = message['session_id']
        if type(sid) is not int or sid not in self.sessions:
            raise ValueError('unknown correction session')
        session = self.sessions[sid]
        identity = tuple(message.get(k) for k in ('request_id', 'pair_a', 'pair_b', 'output_pair_id'))
        bits = [message.get('m1'), message.get('m2')]
        if (not session['ab_pair'] or identity != (1, 1, 2, 3) or
                any(type(v) is not int for v in identity) or
                any(type(v) is not int or v not in (0, 1) for v in bits)):
            self.correction_event(sid, 'CORRECTION_REJECTED', cause, 'INVALID_RESULT')
            return 'INVALID_RESULT'
        if session['correction']:
            code = 'DUPLICATE' if bits == session['correction']['measurement_bits'] else 'RESULT_MISMATCH'
            self.correction_event(sid, 'CORRECTION_' + code, cause, code)
            return code
        # 수신한 패킷의 비트를 그대로 사용한다. 숨은 R 측정값으로 잘못된 패킷을 고치지 않는다.
        finish = (self.sessions[self.correction_running]['correction']['completion_ns']
                  if self.correction_running is not None else self.now_ns)
        if finish + (len(self.correction_queue) + 1) * self.config['correction_duration_ns'] > MAX_TIME_NS:
            self.correction_event(sid, 'CORRECTION_REJECTED', cause, 'TIME_OVERFLOW')
            return 'TIME_OVERFLOW'
        session['correction'] = dict(request_id=2, bsm_request_id=1, state='QUEUED',
            arrival_ns=self.now_ns, start_ns=None, completion_ns=None, measurement_bits=bits)
        self.correction_queue.append(sid)
        session['correction_cause'] = self.correction_event(sid, 'CORRECTION_QUEUED', cause)
        return 'OK'

    def schedule_queued(self):
        replies = super().schedule_queued()
        if self.correction_running is None and self.correction_queue:
            sid = self.correction_queue.popleft()
            session = self.sessions[sid]
            session['checkpoints']['correction_start'] = self.frame_state(sid)
            session['correction'].update(state='RUNNING', start_ns=self.now_ns,
                completion_ns=self.now_ns + self.config['correction_duration_ns'])
            session['ab_pair']['state'] = 'CORRECTING'
            self.correction_running = sid
            session['correction_cause'] = self.correction_event(sid, 'CORRECTION_START', session['correction_cause'])
        self.check_invariants()
        return replies

    def advance_to_boundary(self, at):
        completed = super().advance_to_boundary(at)
        for result in completed:
            sid = self.rid_to_sid[result['request_id']]
            self.emit(sid, 'AB_CREATED', self.complete_causes[result['request_id']], request_id=1,
                input_pair_ids=[1, 2], output_pair_id=3, details=dict(locations=self.locations(sid, 3)))
        sid = self.correction_running
        if sid is not None and self.sessions[sid]['correction']['completion_ns'] == at:
            session = self.sessions[sid]
            correction = session['correction']
            m1, m2 = correction['measurement_bits']
            if m2:
                self.b_processor.execute_instruction(INSTR_X, [session['slot']], physical=False)
            if m1:
                self.b_processor.execute_instruction(INSTR_Z, [session['slot']], physical=False)
            # 00도 실제 native peek가 전체 보정 duration의 aging을 반영한다.
            qubits = self.endpoints(sid)
            if any(a is not b for a, b in zip(qubits, session['original_endpoints'])):
                raise RuntimeError('surviving qubit identity changed')
            usable = encode_state(qubits, ['A', 'B'], self.now_ns)
            session['checkpoints']['usable'] = usable
            correction['state'] = 'COMPLETED'
            session['correction_count'] += 1
            session['ab_pair'].update(state='USABLE', usable_ns=at,
                fidelity=usable['fidelity'], density_matrix=usable['density_matrix'])
            self.outputs[session['rid']]['frame_pending'] = False
            cause = self.correction_event(sid, 'CORRECTION_COMPLETE', session['correction_cause'])
            self.emit(sid, 'PAIR_USABLE', cause, node_id='B', processor_id=3, request_id=2,
                input_pair_ids=[3], output_pair_id=3, request_state='COMPLETED', measurement_bits=[m1, m2],
                fidelity=usable['fidelity'], fidelity_kind='usable', details=dict(ancestor_pair_ids=[1, 2]))
            self.correction_running = None
            self._drain_current_timestamp()
        return completed

    def check_invariants(self):
        super().check_invariants()
        active = list(self.correction_queue)
        if self.correction_running is not None:
            active.append(self.correction_running)
        if len(active) != len(set(active)):
            raise RuntimeError('correction scheduled twice')
        for sid, session in self.sessions.items():
            ab, correction = session['ab_pair'], session['correction']
            if ab:
                if any(self.resources[p]['state'] != 'CONSUMED' for p in session['pairs']):
                    raise RuntimeError('AB before input consumption')
                if self.requests[session['rid']]['state'] != 'COMPLETED':
                    raise RuntimeError('AB without completed BSM')
            if correction:
                state = correction['state']
                expected = {'QUEUED': 'FRAME_PENDING', 'RUNNING': 'CORRECTING', 'COMPLETED': 'USABLE'}
                if not ab or ab['state'] != expected[state]:
                    raise RuntimeError('correction/AB lifecycle mismatch')
                if (state == 'RUNNING') != (self.correction_running == sid):
                    raise RuntimeError('B processor ownership mismatch')
                if (state == 'QUEUED') != (sid in self.correction_queue):
                    raise RuntimeError('orphan correction')
                if session['correction_count'] != int(state == 'COMPLETED'):
                    raise RuntimeError('correction must commit once')
            elif session['correction_count'] or (ab and ab['state'] != 'FRAME_PENDING'):
                raise RuntimeError('AB state without correction')

    def queue_sample(self):
        p = self.processors[2]
        return dict(sim_time_ns=self.now_ns, round=self.round,
                    waiting_sessions=[self.rid_to_sid[r] for r in p['queue']],
                    running_session=self.rid_to_sid[p['running']] if p['running'] is not None else None)

    def snapshot(self):
        base = super().snapshot()
        sessions = {}
        for sid, session in self.sessions.items():
            rid = session['rid']
            requests = {}
            if rid in self.requests:
                requests['1'] = dict(self.requests[rid], request_id=1, pair_a=1, pair_b=2)
            resources = {}
            for local, pair in enumerate(session['pairs'], 1):
                resource = dict(base['resources'][pair])
                resource['owner'] = 1 if resource['owner'] is not None else None
                resources[str(local)] = resource
            # 완료했던 session의 fidelity는 그 session의 usable 시각 값이다.
            # 전체 batch 종료 때 다시 peek해서 과거의 F_usable을 덮어쓰지 않는다.
            sessions[str(sid)] = dict(session_id=sid, requests=requests, resources=resources,
                ab_pair=session['ab_pair'], correction=session['correction'],
                correction_count=session['correction_count'], checkpoints=session['checkpoints'],
                memory_noise=self.config['memory_noise'])
        return copy.deepcopy(dict(time_ns=base['time_ns'], netsquid_time_ns=base['netsquid_time_ns'],
            sessions=sessions, memory_layout=dict(A=len(self.sessions), R=2 * len(self.sessions), B=len(self.sessions)),
            bsm_processor_count=1, correction_processor_count=1))
