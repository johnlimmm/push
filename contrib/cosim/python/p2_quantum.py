"""P1 연산·자원 전이를 그대로 사용하고 native memory noise와 평가용 관측을 추가한다.

잡음 계산은 NetSquid T1T2NoiseModel에만 맡긴다. 이 어댑터는 경과 시간을
직접 noise 함수에 전달하거나 AB 생성 시 큐빗을 꺼내 다시 넣지 않는다.
"""

import copy

import numpy as np
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.qubits import ketstates, qubitapi as qapi

from p1_quantum import P1Quantum


def encode_state(qubits, order, at, target=ketstates.b00):
    dm = qapi.reduced_dm(qubits)
    return dict(sim_time_ns=at, fidelity=float(qapi.fidelity(qubits, target, squared=True)),
                density_matrix=dict(qubit_order=order, real=dm.real.tolist(), imag=dm.imag.tolist()))


class P2Quantum(P1Quantum):
    def __init__(self, config, log, root_cause):
        self.checkpoints = {}
        super().__init__(config, log, root_cause)
        noise = config['memory_noise']
        # 아직 t=0이다. EPR 생성 직후, 시간이 흐르기 전에 네 memory position에 연결한다.
        # 모델은 각 position의 마지막 접근 시각으로 elapsed time을 계산한다.
        self.memories = {
            'A': (self.resources[1]['endpoint'], 0),
            'R_AR': (self.processors[2]['device'], 0),
            'R_RB': (self.processors[2]['device'], 1),
            'B': (self.resources[2]['endpoint'], 0),
        }
        for memory, position in self.memories.values():
            memory.mem_positions[position].models['noise_model'] = T1T2NoiseModel(
                T1=noise['T1_ns'], T2=noise['T2_ns'])

    def input_states(self):
        """BSM 전에 두 EPR을 실제 메모리를 통해 관측해 미반영 aging까지 반영한다."""
        states = {}
        for pair, names in (('AR', ('A', 'R_AR')), ('RB', ('R_RB', 'B'))):
            qubits = [self.memories[name][0].peek(self.memories[name][1])[0] for name in names]
            states[pair] = encode_state(qubits, list(names), self.now_ns)
        return states

    def frame_state(self):
        qubits = self.resources[1]['endpoint'].peek(0) + self.resources[2]['endpoint'].peek(0)
        output = self.outputs[self.ab['bsm_request_id']] if self.ab else self.outputs[1]
        x, z = np.array([[0, 1], [1, 0]]), np.diag([1, -1])
        correction = (z if output['m1'] else np.eye(2)) @ (x if output['m2'] else np.eye(2))
        target = np.kron(np.eye(2), correction.conj().T) @ ketstates.b00
        return encode_state(qubits, ['A', 'B'], self.now_ns, target)

    def _record(self, event, request=None, **fields):
        if event == 'RUNNING':
            self.checkpoints['bsm_start'] = self.input_states()
            fields['input_states'] = self.checkpoints['bsm_start']
        if event == 'BSM_MEASURED':
            self.checkpoints['frame'] = self.frame_state()
            fields['density_matrix'] = self.checkpoints['frame']['density_matrix']
        super()._record(event, request, **fields)

    def _complete_bsm(self, request):
        # 고정 BSM duration 동안 네 큐빗이 모두 계속 저장된다. 순간 회로 직전 상태도 기록한다.
        self.checkpoints['bsm_end_inputs'] = self.input_states()
        super()._complete_bsm(request)

    def correction_event(self, event, cause, code='OK'):
        if event == 'CORRECTION_START':
            # 결과 패킷 전달 구간의 aging을 보여 주는 관측이다. 물리적 보정은 아직 하지 않는다.
            self.checkpoints['correction_start'] = self.frame_state()
        return super().correction_event(event, cause, code)

    def snapshot(self):
        snapshot = super().snapshot()
        # 최종 평가는 P1의 실제 메모리 peek 이후 값이다. 00 분기도 duration 전체가 포함된다.
        if self.ab and self.ab['state'] == 'USABLE':
            self.checkpoints['usable'] = dict(sim_time_ns=self.ab['usable_ns'],
                fidelity=self.ab['fidelity'], density_matrix=self.ab['density_matrix'])
        snapshot['checkpoints'] = copy.deepcopy(self.checkpoints)
        snapshot['memory_noise'] = copy.deepcopy(self.config['memory_noise'])
        return snapshot
