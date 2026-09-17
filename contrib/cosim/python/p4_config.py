"""P4 설정과 ns-3 trace를 사용하지 않는 두 링크의 독립 FIFO 기준 계산."""

import copy

from p1_validation import tx_duration_ns
from p2_validation import normalize_config as normalize_p2
from quantum_scheduler import MAX_TIME_NS, integer

DEFAULT_FLOW = dict(start_ns=0, interval_ns=1000000, count=0, payload_bytes=1000)


def normalize_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('P4 configuration must be an object')
    raw = copy.deepcopy(raw)
    background = raw.pop('background', {})
    capacity = raw.pop('queue_packets', 128)
    expect = raw.pop('expected_queueing', dict(command='any', result='any'))
    raw.setdefault('name', 'p4-zero')
    config = normalize_p2(raw)
    integer(capacity, 'queue_packets', 1, 65536)
    if not isinstance(background, dict) or set(background) - {'command', 'result'}:
        raise ValueError('background requires command/result flows')
    flows = {}
    for side in ('command', 'result'):
        flow = copy.deepcopy(DEFAULT_FLOW)
        item = background.get(side, {})
        if not isinstance(item, dict) or set(item) - set(flow):
            raise ValueError('unsupported background flow fields')
        flow.update(item)
        integer(flow['start_ns'], 'start_ns', maximum=MAX_TIME_NS)
        integer(flow['interval_ns'], 'interval_ns', 1, MAX_TIME_NS)
        integer(flow['count'], 'count', maximum=2000)
        integer(flow['payload_bytes'], 'background payload', 60, 1400)
        rate = config[side+'_link']['rate_bps']
        if (((flow['payload_bytes']+30)*8*10**9) % rate)*2 == rate or tx_duration_ns(flow['payload_bytes'], rate)<1:
            raise ValueError('background serialization must avoid half-ns ties and zero duration')
        flows[side] = flow
    if not isinstance(expect, dict) or set(expect) != {'command', 'result'} or any(v not in ('zero','positive','any') for v in expect.values()):
        raise ValueError('expected_queueing requires zero/positive/any for each link')
    config.update(background=flows, queue_packets=capacity, expected_queueing=expect)
    if analytic_timing(config)['simulation_completion_ns'] > MAX_TIME_NS:
        raise ValueError('P4 simulation time overflow')
    return config


def fifo(config, side, control_at):
    """송신 예정만으로 FIFO를 계산한다. 같은 시각이면 background를 control보다 먼저 둔다."""
    flow, link = config['background'][side], config[side+'_link']
    offset = 1000 if side=='command' else 100000
    packets = [dict(packet_id=offset+i, traffic_class='background', link=side,
                    app_tx_ns=flow['start_ns']+i*flow['interval_ns'], payload_bytes=flow['payload_bytes'])
               for i in range(flow['count'])]
    packets.append(dict(packet_id=1 if side=='command' else 2, traffic_class='control', link=side,
                        app_tx_ns=control_at, payload_bytes=config[side+'_payload_bytes']))
    packets.sort(key=lambda p: (p['app_tx_ns'], p['traffic_class']=='control', p['packet_id']))
    free = 0
    for packet in packets:
        at = packet['app_tx_ns']
        start = max(at, free)
        duration = tx_duration_ns(packet['payload_bytes'], link['rate_bps'])
        free = start+duration
        packet.update(wire_bytes=packet['payload_bytes']+30, enqueue_ns=at, dequeue_ns=start,
            phy_tx_ns=start, phy_tx_end_ns=free, phy_rx_ns=free+link['delay_ns'],
            app_rx_ns=free+link['delay_ns'], queue_wait_ns=start-at,
            serialization_ns=duration, propagation_ns=link['delay_ns'], total_delay_ns=free+link['delay_ns']-at)
    return packets


def analytic_timing(config):
    command = fifo(config,'command',config['command_time_ns'])
    cmd = next(p for p in command if p['packet_id']==1)
    bsm_start = cmd['app_rx_ns']
    bsm_end = bsm_start+config['bsm_duration_ns']
    result = fifo(config,'result',bsm_end)
    res = next(p for p in result if p['packet_id']==2)
    correction_start = res['app_rx_ns']
    correction_end = correction_start+config['correction_duration_ns']
    drain = max(p['app_rx_ns'] for p in command+result)
    return dict(packets=command+result, bsm_start_ns=bsm_start, bsm_completion_ns=bsm_end,
                correction_start_ns=correction_start, correction_completion_ns=correction_end,
                traffic_drain_completion_ns=drain, simulation_completion_ns=max(drain,correction_end))
