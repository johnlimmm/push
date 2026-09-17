#!/usr/bin/env python3
"""P2 독립 reference: native 메모리/T1T2 + Protocol timer + 네 Bell 분기의 정확한 조건화.

co-sim 모듈을 import하지 않는다. 잡음은 여기서도 내장 모델이 계산한다.
BSM은 co-sim의 CNOT/H/측정 코드 대신 Bell bra로 네 분기를 직접 계산한다.
"""

import json
import sys

import netsquid as ns
import numpy as np
from netsquid.components import QuantumMemory
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.protocols import Protocol
from netsquid.qubits import qubitapi as qapi


def run_reference(spec):
    keys = ('bsm_start_ns', 'bsm_completion_ns', 'correction_start_ns', 'correction_completion_ns')
    times = [spec[k] for k in keys]
    if (any(type(t) is not int or not 0 <= t <= 2 ** 53 - 1 for t in times) or
            times != sorted(times) or times[0] == times[1] or times[2] == times[3]):
        raise ValueError('reference requires ordered integer times and positive durations')
    noise = spec['memory_noise']
    if (set(noise) != {'model', 'T1_ns', 'T2_ns'} or noise['model'] != 'T1T2NoiseModel' or
            any(type(noise[k]) is not int or not 0 <= noise[k] <= 2 ** 53 - 1 for k in ('T1_ns', 'T2_ns')) or
            (noise['T1_ns'] and noise['T2_ns'] > noise['T1_ns'])):
        raise ValueError('invalid reference T1/T2 configuration')
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    # 각 분기는 동일한 t=0 EPR의 독립 복제본이다. 분기 조건화 후에도 원래 A/B 메모리를 유지한다.
    memories, branches, inputs = {}, {}, {}
    phi = np.array([1, 0, 0, 1], dtype=complex) / np.sqrt(2)
    for bits in ('00', '01', '10', '11'):
        qubits = qapi.create_qubits(4)
        for left, right in ((0, 1), (2, 3)):
            qapi.operate(qubits[left], ns.H)
            qapi.operate([qubits[left], qubits[right]], ns.CNOT)
        memory = QuantumMemory('reference_' + bits, num_positions=4, memory_noise_models=[
            T1T2NoiseModel(T1=noise['T1_ns'], T2=noise['T2_ns']) for _ in range(4)])
        memory.put(qubits)
        memories[bits] = memory
        branches[bits] = dict(measurement_bits=list(map(int, bits)))
    records = [dict(event_type='EPR_CREATED', sim_time_ns=0)]

    def clock(expected):
        if ns.sim_time() != expected:
            raise RuntimeError('reference native clock mismatch')
        return expected

    def state(qubits, order, at, target=phi):
        dm = qapi.reduced_dm(qubits)
        return dict(sim_time_ns=clock(at), fidelity=float(np.real(target.conj() @ dm @ target)),
                    density_matrix=dict(qubit_order=order, real=dm.real.tolist(), imag=dm.imag.tolist()))

    def input_states(memory, at):
        qubits = memory.peek([0, 1, 2, 3])
        return dict(AR=state(qubits[:2], ['A', 'R_AR'], at),
                    RB=state(qubits[2:], ['R_RB', 'B'], at))

    def target(bits):
        # frame 평가용 Bell ket. B에 X^m2 Z^m1을 적용한 Phi+와 같다.
        m1, m2 = map(int, bits)
        vec = np.zeros(4, dtype=complex)
        vec[m2] = 1 / np.sqrt(2)
        vec[2 + (m2 ^ 1)] = (-1) ** m1 / np.sqrt(2)
        return vec

    class Transaction(Protocol):
        def run(self):
            for key, kind in zip(keys, ('BSM_START', 'BSM_COMPLETE', 'CORRECTION_START', 'CORRECTION_COMPLETE')):
                at = spec[key]
                yield self.await_timer(at - ns.sim_time())
                records.append(dict(event_type=kind, sim_time_ns=clock(at)))
                for bits, memory in memories.items():
                    branch = branches[bits]
                    if kind == 'BSM_START':
                        observed = input_states(memory, at)
                        if bits == '00':
                            inputs['bsm_start'] = observed
                    elif kind == 'BSM_COMPLETE':
                        observed = input_states(memory, at)
                        if bits == '00':
                            inputs['bsm_end_inputs'] = observed
                        qubits = memory.peek([0, 1, 2, 3])
                        rho = qapi.reduced_dm(qubits).reshape(2, 4, 2, 2, 4, 2)
                        bell = target(bits)
                        # R 두 큐빗에 Bell bra/ket을 수축하고 A,B만 남긴 비정규화 조건부 상태.
                        conditional = np.einsum('i,aibcjd,j->abcd', bell.conj(), rho, bell).reshape(4, 4)
                        probability = float(np.real(np.trace(conditional)))
                        if probability < -1e-14:
                            raise RuntimeError('negative branch probability')
                        branch['probability'] = max(0.0, probability)
                        for qubit in memory.pop([1, 2]):
                            qapi.discard(qubit)
                        if probability > 0:
                            # 큐빗/메모리 위치와 마지막 접근 시각은 유지한다. 새 EPR을 생성하지 않는다.
                            qapi.assign_qstate([qubits[0], qubits[3]], conditional / probability)
                            branch['frame'] = state(memory.peek([0, 3]), ['A', 'B'], at, bell)
                    elif branch['probability'] > 0:
                        endpoints = memory.peek([0, 3])
                        if kind == 'CORRECTION_START':
                            branch['correction_start'] = state(endpoints, ['A', 'B'], at, target(bits))
                        else:
                            # duration 전체의 memory noise는 위 peek에서 반영하고 순간 보정한다.
                            m1, m2 = map(int, bits)
                            qapi.operate(endpoints[1], (ns.Z if m1 else ns.I) * (ns.X if m2 else ns.I))
                            branch['usable'] = state(endpoints, ['A', 'B'], at)

    protocol = Transaction()
    protocol.start()
    ns.sim_run()
    probability_sum = sum(b['probability'] for b in branches.values())
    if abs(probability_sum - 1) > 1e-12:
        raise RuntimeError('reference branch probabilities do not sum to one')
    ensemble = np.zeros((4, 4), dtype=complex)
    for branch in branches.values():
        if branch['probability'] > 0:
            encoded = branch['usable']['density_matrix']
            ensemble += branch['probability'] * (np.array(encoded['real']) + 1j * np.array(encoded['imag']))
    return dict(model='independent-native-T1T2-Bell-projection', time_ns=clock(times[-1]),
                memory_noise=noise, events=records, inputs=inputs, branches=branches,
                ensemble=dict(fidelity=float(np.real(phi.conj() @ ensemble @ phi)),
                    density_matrix=dict(qubit_order=['A', 'B'], real=ensemble.real.tolist(), imag=ensemble.imag.tolist())))


if __name__ == '__main__':
    json.dump(run_reference(json.load(sys.stdin)), sys.stdout, allow_nan=False)
    sys.stdout.write('\n')
