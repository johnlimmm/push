"""P3 설정: 동일한 t=0 EPR, 실제 공유 UDP 링크, R의 FIFO contention만 허용한다."""

import copy

from p1_validation import tx_duration_ns
from p2_validation import normalize_config as normalize_p2
from quantum_scheduler import MAX_TIME_NS, integer


def normalize_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('P3 configuration must be an object')
    raw = copy.deepcopy(raw)
    sessions = raw.pop('sessions', [dict(session_id=i + 1, command_time_ns=1000000 + i * 400000)
                                  for i in range(4)])
    if set(raw) & {'session_id', 'command_time_ns', 'result_replays'}:
        raise ValueError('P3 requires per-session command times and no replays')
    raw.setdefault('name', 'p3-quantum-contention')
    config = normalize_p2(raw)
    for key in ('session_id', 'command_time_ns', 'result_replays'):
        del config[key]
    if not isinstance(sessions, list) or not 1 <= len(sessions) <= 64:
        raise ValueError('P3 requires 1..64 sessions')
    seen = set()
    for item in sessions:
        if not isinstance(item, dict) or set(item) != {'session_id', 'command_time_ns'}:
            raise ValueError('session requires session_id and command_time_ns')
        sid = integer(item['session_id'], 'session_id', 1)
        integer(item['command_time_ns'], 'command_time_ns', maximum=MAX_TIME_NS)
        if sid in seen:
            raise ValueError('duplicate session ID')
        seen.add(sid)
    config['sessions'] = sessions
    # 정렬은 같은 시각에서 설정 목록 순서를 유지한다. 실제 FIFO 순서는 도착 로그로도 검사한다.
    times = analytic_timing(config)
    if max(t['correction_completion_ns'] for t in times.values()) > MAX_TIME_NS:
        raise ValueError('P3 transaction time overflow')
    return config


def analytic_timing(config):
    """trace를 읽지 않고 설정만으로 두 장치 FIFO, R FIFO, B FIFO의 시각을 계산한다.

    경합이 잘못 섞인 설정도 시간을 계산한 뒤 검증에서 명시적으로 거절한다.
    P3에서 허용하는 지연은 R의 BSM 대기뿐이다.
    """
    tx = tx_duration_ns(config['command_payload_bytes'], config['command_link']['rate_bps'])
    rx = tx_duration_ns(config['result_payload_bytes'], config['result_link']['rate_bps'])
    command_free = result_free = r_free = b_free = 0
    result = {}
    for session in sorted(config['sessions'], key=lambda s: s['command_time_ns']):
        sent = session['command_time_ns']
        phy = max(sent, command_free)
        command_free = phy + tx
        arrival = command_free + config['command_link']['delay_ns']
        start = max(arrival, r_free)
        r_free = start + config['bsm_duration_ns']
        result_phy = max(r_free, result_free)
        result_free = result_phy + rx
        result_arrival = result_free + config['result_link']['delay_ns']
        correction_start = max(result_arrival, b_free)
        b_free = correction_start + config['correction_duration_ns']
        result[str(session['session_id'])] = dict(
            command_send_ns=sent, command_phy_tx_ns=phy, command_receive_ns=arrival,
            bsm_start_ns=start, bsm_completion_ns=r_free,
            result_send_ns=r_free, result_phy_tx_ns=result_phy, result_receive_ns=result_arrival,
            correction_start_ns=correction_start, correction_completion_ns=b_free,
            command_serialization_ns=tx, result_serialization_ns=rx,
            command_queue_ns=phy - sent, result_queue_ns=result_phy - r_free,
            correction_queue_ns=correction_start - result_arrival, quantum_wait_ns=start - arrival)
    return result
