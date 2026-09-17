"""평가 전용 R 무대기 모델. native memory/state와 B FIFO는 P3 그대로다."""
from collections import deque

from p3_quantum import P3Quantum


class NoWaitQuantum(P3Quantum):
    def __init__(self, config, log, roots):
        super().__init__(config, log, roots)
        # 서로 다른 session의 메모리 칸은 그대로 두고 실행 슬롯만 session마다 부여한다.
        # 물리 processor가 늘었다는 주장이 아니라 R capacity 제약을 없앤 근사다.
        device = self.processors[2]['device']
        for session in self.sessions.values():
            lane = 2 + session['slot']
            if lane != 2:
                self.processors[lane] = dict(device=device, queue=deque(), running=None)
            for pair in session['pairs']:
                self.resources[pair]['processor_id'] = lane

    def submit_request(self, raw):
        raw = dict(raw)
        raw['processor_id'] = 2 + self.sessions[self.rid_to_sid[raw['request_id']]]['slot']
        return super().submit_request(raw)

    def queue_sample(self):
        active = [self.requests[p['running']] for p in self.processors.values()
                  if p['running'] is not None]
        active.sort(key=lambda r: (r['arrival_ns'], r['request_id']))
        return dict(sim_time_ns=self.now_ns, round=self.round, waiting_sessions=[],
                    running_sessions=[self.rid_to_sid[r['request_id']] for r in active],
                    running_session=None)

    def snapshot(self):
        result = super().snapshot()
        result['R_execution_capacity'] = len(self.sessions)
        result['R_capacity_model'] = 'unbounded-per-session-virtual-lanes'
        return result
