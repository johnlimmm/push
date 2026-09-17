#!/usr/bin/env python3
"""독립 NetSquid-only reference: 공동 시뮬레이터의 스케줄러/회로 코드를 import하지 않는다.

stdin의 JSON으로 연산 시작·완료 시각을 받고 stdout으로 상태와 사건 기록을 반환한다.
별도 프로세스로 실행하므로 NetSquid 전역 엔진 reset이 co-sim 상태를 바꾸지 않는다.
"""

import json
import sys
import numpy as np
import netsquid as ns
from netsquid.protocols import Protocol
from netsquid.qubits import qubitapi as qapi


def run_reference(spec):
    keys = ('bsm_start_ns', 'bsm_completion_ns', 'correction_start_ns', 'correction_completion_ns')
    times = [spec[k] for k in keys]
    if (any(type(t) is not int or not 0 <= t <= 2 ** 53 - 1 for t in times) or
            times != sorted(times) or times[0] == times[1] or times[2] == times[3]):
        raise ValueError('reference requires ordered integer times and positive operation durations')
    if type(spec['seed']) is not int or not 0 <= spec['seed'] < 2 ** 32:
        raise ValueError('invalid reference seed')
    ns.sim_reset()
    ns.set_random_state(seed=spec['seed'])
    ns.set_qstate_formalism(ns.QFormalism.DM)
    # 명시적인 순서 A, R_AR, R_RB, B. co-sim과 다른 생성/보정 구현 경로다.
    a, left, right, b = qapi.create_qubits(4)
    qapi.operate(a, ns.H)
    qapi.operate([a, left], ns.CNOT)
    qapi.operate(right, ns.H)
    qapi.operate([right, b], ns.CNOT)
    records = [dict(event_type='EPR_CREATED', sim_time_ns=0)]
    result = {}

    def clock_ns(expected_ns):
        # 검증된 정수 예약 시각과 실제 시계가 정확히 같을 때만 int로 저장한다.
        # co-sim 시간 변환 코드를 공유하지 않아 reference의 독립성을 유지한다.
        at = ns.sim_time()
        if at != expected_ns:
            raise RuntimeError('reference native clock does not match integer operation time')
        return int(at)

    class Transaction(Protocol):
        def mark(self, kind, expected_ns):
            records.append(dict(event_type=kind, sim_time_ns=clock_ns(expected_ns)))

        def run(self):
            # NetSquid native timer만 사용하며 federation boundary 코드는 사용하지 않는다.
            for key, kind in (('bsm_start_ns', 'BSM_START'), ('bsm_completion_ns', 'BSM_COMPLETE')):
                yield self.await_timer(spec[key] - ns.sim_time())
                self.mark(kind, spec[key])
            qapi.operate([left, right], ns.CNOT)
            qapi.operate(left, ns.H)
            m1 = int(qapi.measure(left, observable=ns.Z)[0])
            m2 = int(qapi.measure(right, observable=ns.Z)[0])
            qapi.discard(left)
            qapi.discard(right)
            for key, kind in (('correction_start_ns', 'CORRECTION_START'),
                              ('correction_completion_ns', 'CORRECTION_COMPLETE')):
                yield self.await_timer(spec[key] - ns.sim_time())
                self.mark(kind, spec[key])
            # X와 Z를 개별 실행하는 co-sim과 달리 한 합성 연산자로 B를 보정한다.
            correction = (ns.Z if m1 else ns.I) * (ns.X if m2 else ns.I)
            qapi.operate(b, correction)
            dm = qapi.reduced_dm([a, b])
            phi = np.array([1, 0, 0, 1]) / np.sqrt(2)
            result.update(measurement_bits=[m1, m2],
                          fidelity=float(np.real(phi.conj() @ dm @ phi)),
                          density_matrix=dict(qubit_order=['A', 'B'],
                                              real=dm.real.tolist(), imag=dm.imag.tolist()))

    protocol = Transaction()
    protocol.start()
    ns.sim_run()
    result.update(events=records, time_ns=clock_ns(times[-1]), model='independent-atomic-noiseless')
    return result


if __name__ == '__main__':
    json.dump(run_reference(json.load(sys.stdin)), sys.stdout)
    sys.stdout.write('\n')
