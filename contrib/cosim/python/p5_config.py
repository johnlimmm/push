"""P5-A 설정과 독립 기준: command FIFO → R FIFO → result FIFO → B FIFO.

예상값은 설정만 사용한다. 실제 simulator의 trace나 완료시각을 기준식에 넣지 않는다.
모든 EPR은 t=0 생성이며, 동일 시각에서는 background 다음 설정 순서의 command다.
"""

import copy

from p1_validation import tx_duration_ns
from p3_config import normalize_config as normalize_p3
from p4_config import normalize_config as normalize_p4
from quantum_scheduler import MAX_TIME_NS


def normalize_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('P5 configuration must be an object')
    raw = copy.deepcopy(raw)
    background = raw.pop('background', {})
    capacity = raw.pop('queue_packets', 128)
    expect = raw.pop('expected_queueing', dict(command='any', result='any', R='any'))
    if (not isinstance(expect, dict) or set(expect) != {'command', 'result', 'R'} or
            any(v not in ('zero', 'positive', 'any') for v in expect.values())):
        raise ValueError('expected_queueing requires command/result/R: zero/positive/any')
    raw.setdefault('name', 'p5-joint')
    raw.setdefault('sessions', [dict(session_id=i+1, command_time_ns=1000000+i*800000)
                                for i in range(4)])
    config = normalize_p3(raw)
    # P3의 session 검증과 P4의 packet/flow 검증을 그대로 재사용한다.
    single = {k: v for k, v in config.items() if k != 'sessions'}
    single.update(config['sessions'][0])
    single.update(background=background, queue_packets=capacity,
                  expected_queueing={k: expect[k] for k in ('command', 'result')})
    checked = normalize_p4(single)
    config.update(background=checked['background'], queue_packets=capacity,
                  expected_queueing=expect)
    if analytic_timing(config)['simulation_completion_ns'] > MAX_TIME_NS:
        raise ValueError('P5 simulation time overflow')
    return config


def fifo(config, side, controls):
    """송신 예정 packet으로 유한 FIFO 일정을 계산한다. control에는 session ID가 있다."""
    flow, link = config['background'][side], config[side+'_link']
    offset = 1000 if side == 'command' else 100000
    packets = [dict(packet_id=offset+i, session_id=0, traffic_class='background', link=side,
                    app_tx_ns=flow['start_ns']+i*flow['interval_ns'], payload_bytes=flow['payload_bytes'])
               for i in range(flow['count'])]
    packets.extend(dict(p, traffic_class='control', link=side,
                        payload_bytes=config[side+'_payload_bytes']) for p in controls)
    packets.sort(key=lambda p: (p['app_tx_ns'], p['traffic_class']=='control', p['packet_id']))
    free = 0
    for packet in packets:
        at = packet['app_tx_ns']
        start = max(at, free)
        duration = tx_duration_ns(packet['payload_bytes'], link['rate_bps'])
        free = start + duration
        packet.update(wire_bytes=packet['payload_bytes']+30, enqueue_ns=at, dequeue_ns=start,
            phy_tx_ns=start, phy_tx_end_ns=free, phy_rx_ns=free+link['delay_ns'],
            app_rx_ns=free+link['delay_ns'], queue_wait_ns=start-at,
            serialization_ns=duration, propagation_ns=link['delay_ns'], total_delay_ns=free+link['delay_ns']-at)
    return packets


def analytic_timing(config):
    commands = [dict(packet_id=2*i+1, session_id=s['session_id'], app_tx_ns=s['command_time_ns'])
                for i, s in enumerate(config['sessions'])]
    command = fifo(config, 'command', commands)
    sessions, results = {}, []
    r_free = 0
    for packet in command:
        if packet['traffic_class'] != 'control':
            continue
        sid, arrival = packet['session_id'], packet['app_rx_ns']
        start = max(arrival, r_free)
        r_free = start + config['bsm_duration_ns']
        sessions[str(sid)] = dict(command_send_ns=packet['app_tx_ns'],
            command_phy_tx_ns=packet['phy_tx_ns'], command_receive_ns=arrival,
            command_serialization_ns=packet['serialization_ns'], command_queue_ns=packet['queue_wait_ns'],
            bsm_start_ns=start, bsm_completion_ns=r_free, quantum_wait_ns=start-arrival)
        results.append(dict(packet_id=packet['packet_id']+1, session_id=sid, app_tx_ns=r_free))
    result = fifo(config, 'result', results)
    b_free = 0
    for packet in result:
        if packet['traffic_class'] != 'control':
            continue
        arrival = packet['app_rx_ns']
        start = max(arrival, b_free)
        b_free = start + config['correction_duration_ns']
        sessions[str(packet['session_id'])].update(result_send_ns=packet['app_tx_ns'],
            result_phy_tx_ns=packet['phy_tx_ns'], result_receive_ns=arrival,
            result_serialization_ns=packet['serialization_ns'], result_queue_ns=packet['queue_wait_ns'],
            correction_start_ns=start, correction_completion_ns=b_free, correction_queue_ns=start-arrival)
    drain = max(p['app_rx_ns'] for p in command+result)
    batch = max(t['correction_completion_ns'] for t in sessions.values())
    return dict(packets=command+result, sessions=sessions, batch_completion_ns=batch,
                traffic_drain_completion_ns=drain, simulation_completion_ns=max(drain, batch))
