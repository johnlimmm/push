"""P4 검증: trace와 독립 FIFO 예측을 대조하고 P2의 자원·상태 규약을 유지한다."""

from collections import Counter, defaultdict, deque
from p2_validation import validate_quantum_snapshot
from p4_config import analytic_timing
from quantum_scheduler import MAX_TIME_NS


def validate_packets(report):
    """측정값으로 기준식을 보정하지 않는다. config로 계산한 전 패킷 일정을 대조한다."""
    config, rows = report['config'], report['packet_events']
    expected = analytic_timing(config)
    def require(ok, message):
        if not ok:
            raise RuntimeError('P4 packet validation: ' + message)
    drops = [r for r in rows if r['event_type'].endswith('DROP')]
    require(not drops, 'packet drop: {}'.format([(r['packet_id'], r['event_type']) for r in drops]))
    by_packet = defaultdict(list)
    previous, source_sequence, identifiers = -1, -1, set()
    for row in rows:
        require(type(row['time_ns']) is int and previous <= row['time_ns'] <= MAX_TIME_NS, 'trace time')
        require(row['source_sequence'] > source_sequence and
                row['event_id'] == 'n:{}'.format(row['source_sequence']), 'trace sequence')
        require(row['packet_id'] == row['message_id'], 'packet identity')
        source_sequence = row['source_sequence']
        require(row['event_id'] not in identifiers, 'duplicate packet event')
        identifiers.add(row['event_id'])
        previous = row['time_ns']
        by_packet[row['packet_id']].append(row)
    require(set(by_packet) == {p['packet_id'] for p in expected['packets']}, 'packet IDs/count')
    actual = []
    for predicted in expected['packets']:
        pid, side, traffic = predicted['packet_id'], predicted['link'], predicted['traffic_class']
        events = by_packet[pid]
        prefix = 'BACKGROUND' if traffic == 'background' else side.upper()
        stages = {prefix+'_TX': 'app_tx_ns', 'QUEUE_ENQUEUE': 'enqueue_ns',
                  'QUEUE_DEQUEUE': 'dequeue_ns', 'PHY_TX': 'phy_tx_ns',
                  'PHY_TX_END': 'phy_tx_end_ns', 'PHY_RX': 'phy_rx_ns', prefix+'_RX': 'app_rx_ns'}
        require(Counter(e['event_type'] for e in events) == Counter(stages.keys()),
                'packet {} stage count'.format(pid))
        require([e['event_type'] for e in events] == list(stages), 'packet stage ordering')
        source, destination = (0, 2) if side == 'command' else (2, 3)
        kind = (1 if side == 'command' else 2) + (2 if traffic == 'background' else 0)
        tx = next(e for e in events if e['event_type'] == prefix+'_TX')
        packet = {k: predicted[k] for k in ('packet_id', 'traffic_class', 'link', 'payload_bytes', 'wire_bytes')}
        for event in events:
            et = event['event_type']
            require(event['kind'] == kind and event['link'] == side and event['traffic_class'] == traffic,
                    'packet classification')
            require(event['session_id'] == (0 if traffic == 'background' else config['session_id']), 'packet session')
            require(event['node_id'] == (destination if et in (prefix+'_RX', 'PHY_RX') else source), 'packet path')
            require(event['cause'] == tx['event_id'] or et == prefix+'_TX', 'packet cause')
            require(event['packet_bytes'] == predicted['payload_bytes' if et in (prefix+'_TX', prefix+'_RX') else 'wire_bytes'], 'packet bytes')
            require(event['time_ns'] == predicted[stages[et]], 'independent FIFO {} {}'.format(pid, et))
            packet[stages[et]] = event['time_ns']
        packet.update(queue_wait_ns=packet['dequeue_ns']-packet['enqueue_ns'],
                      serialization_ns=packet['phy_tx_end_ns']-packet['phy_tx_ns'],
                      propagation_ns=packet['phy_rx_ns']-packet['phy_tx_end_ns'],
                      total_delay_ns=packet['app_rx_ns']-packet['app_tx_ns'])
        require(packet['total_delay_ns'] == packet['queue_wait_ns']+packet['serialization_ns']+packet['propagation_ns'], 'delay decomposition')
        actual.append(packet)
    # queue occupancy 적분과 모든 패킷 대기시간 합이 일치해야 한다. 전송 중 패킷은 제외한다.
    links = {}
    window = expected['traffic_drain_completion_ns']
    for side in ('command', 'result'):
        queue, peak, area, last = deque(), 0, 0, 0
        for row in rows:
            if row['link'] != side or not row['event_type'].startswith('QUEUE_'):
                continue
            area += len(queue)*(row['time_ns']-last)
            last = row['time_ns']
            if row['event_type'] == 'QUEUE_ENQUEUE':
                queue.append(row['packet_id'])
            else:
                require(queue and queue.popleft() == row['packet_id'], 'queue FIFO ordering')
            require(row['queue_depth'] == len(queue), 'queue depth')
            require(len(queue) <= config['queue_packets'], 'queue capacity')
            peak = max(peak, len(queue))
        require(not queue, 'queue not drained')
        packets = [p for p in actual if p['link'] == side]
        require(area == sum(p['queue_wait_ns'] for p in packets), 'queue area / waiting sum')
        busy = sum(p['serialization_ns'] for p in packets)
        flow = config['background'][side]
        links[side] = dict(observation_start_ns=0, observation_end_ns=window,
            queue_peak_packets=peak, queue_area_packet_ns=area, queue_mean_packets=area/window,
            busy_ns=busy, utilization=busy/window, control_tx=1, control_rx=1,
            background_tx=flow['count'], background_rx=flow['count'], control_drops=0, background_drops=0,
            offered_background_load=((flow['payload_bytes']+30)*8*10**9 /
                (flow['interval_ns']*config[side+'_link']['rate_bps'])) if flow['count'] else 0.0)
    control = {p['link']: p for p in actual if p['traffic_class'] == 'control'}
    snapshot = report['snapshot']
    require(snapshot['ab_pair'] is not None, 'missing AB pair')
    bsm = snapshot['requests'].get(1, snapshot['requests'].get('1'))
    waits = dict(bsm_ns=bsm['start_ns']-control['command']['app_rx_ns'],
                 correction_ns=snapshot['correction']['start_ns']-control['result']['app_rx_ns'])
    require(all(v == 0 for v in waits.values()), 'quantum waiting must be zero')
    for side in ('command', 'result'):
        value, rule = control[side]['queue_wait_ns'], config['expected_queueing'][side]
        require(rule == 'any' or (rule == 'zero' and value == 0) or (rule == 'positive' and value > 0),
                side+' required queueing absent/unexpected')
    for key in ('traffic_drain_completion_ns', 'simulation_completion_ns'):
        require(type(report[key]) is int and report[key] == expected[key], key)
    require(report['session_completion_ns'] == expected['correction_completion_ns'], 'transaction end')
    require(report['ns3_time_ns'] == expected['simulation_completion_ns'], 'drain/quantum final time')
    require(snapshot['ab_pair']['usable_ns'] == report['session_completion_ns'], 'usable timestamp')
    # P2 공통 event/resource 검증에 제공할 명시적인 command/result 시각들.
    expected.update(command_send_ns=control['command']['app_tx_ns'],
        command_receive_ns=expected['bsm_start_ns'], command_phy_tx_ns=control['command']['phy_tx_ns'],
        results=[dict(send_ns=expected['bsm_completion_ns'], phy_tx_ns=control['result']['phy_tx_ns'],
                      receive_ns=expected['correction_start_ns'])])
    return expected, dict(links=links, classical=control, quantum_wait=waits), actual

def validate_report(report):
    """시간, 실제 경로, 자원, 고정 target fidelity를 서로 독립적으로 확인한다."""
    config, events = report['config'], report['events']
    expected, metrics, packets = validate_packets(report)
    report['metrics'], report['packets'] = metrics, packets
    def require(condition, message):
        if not condition:
            raise RuntimeError('P4 validation: ' + message)
    def select(kind, message_id=None):
        return [e for e in events if e['event_type'] == kind and
                (message_id is None or e['message_id'] == message_id)]
    def one(kind, at, message_id=None):
        found = select(kind, message_id)
        require(len(found) == 1, kind + ' count')
        require(found[0]['sim_time_ns'] == at, kind + ' timing')
        return found[0]
    for kind, key in (
            ('COMMAND_TX', 'command_send_ns'), ('COMMAND_RX', 'command_receive_ns'),
            ('BSM_REQUEST', 'command_receive_ns'), ('BSM_START', 'bsm_start_ns'),
            ('BSM_COMPLETE', 'bsm_completion_ns'), ('BSM_RESULT_LOCAL', 'bsm_completion_ns'),
            ('CORRECTION_START', 'correction_start_ns'),
            ('CORRECTION_COMPLETE', 'correction_completion_ns'),
            ('PAIR_USABLE', 'correction_completion_ns')):
        one(kind, expected[key])
    command = one('COMMAND_TX', expected['command_send_ns'])
    one('PHY_TX', expected['command_phy_tx_ns'], command['message_id'])
    one('PHY_RX', expected['command_receive_ns'], command['message_id'])
    sends = select('RESULT_TX')
    require(len(sends) == len(expected['results']), 'result packet count')
    require(len(select('RESULT_RX')) == len(sends), 'result packet loss/duplication')
    require(len(select('CORRECTION_REQUEST')) == len(sends), 'correction input count')
    for sent, times in zip(sends, expected['results']):
        mid = sent['message_id']
        require(sent['sim_time_ns'] == times['send_ns'], 'result send time')
        one('PHY_TX', times['phy_tx_ns'], mid)
        one('PHY_RX', times['receive_ns'], mid)
        one('RESULT_RX', times['receive_ns'], mid)
        one('CORRECTION_REQUEST', times['receive_ns'], mid)
    for event in select('PHY_TX') + select('PHY_RX'):
        payload = config['command_payload_bytes'] if event['message_id'] == command['message_id'] else config['result_payload_bytes']
        require(event['details']['packet_bytes'] == payload + 30, 'on-link packet size')
    snapshot = report['snapshot']
    require(snapshot['memory_noise'] == config['memory_noise'], 'memory noise configuration')
    require(snapshot['ab_pair']['state'] == 'USABLE', 'AB state')
    require(snapshot['ab_pair']['input_pair_ids'] == [1, 2], 'AB creation ancestry')
    require(snapshot['correction_count'] == 1, 'correction executed more than once')
    require(len(snapshot['resources']) == 2 and
            all(r['state'] == 'CONSUMED' for r in snapshot['resources'].values()), 'input EPR state')
    initial = select('EPR_CREATED')
    require(len(initial) == 2 and all(abs(1 - e['fidelity']) <= 1e-12 for e in initial), 'initial EPR fidelity')
    require(len(select('BSM_MEASURED')) == 1, 'BSM count')
    validate_quantum_snapshot(snapshot, expected)
    require(one('PAIR_USABLE', expected['correction_completion_ns'])['fidelity'] ==
            snapshot['ab_pair']['fidelity'], 'usable event fidelity')
    require(one('BSM_MEASURED', expected['bsm_completion_ns'])['fidelity'] ==
            snapshot['checkpoints']['frame']['fidelity'], 'frame event fidelity')
    require(report['ns3_time_ns'] == snapshot['netsquid_time_ns'] == snapshot['time_ns'], 'final clocks')
    # 3498080.0 == 3498080이므로 값 비교만으로는 JSON의 정수 시간 규약을 검사할 수 없다.
    require(all(type(t) is int and 0 <= t <= MAX_TIME_NS for t in (
        report['ns3_time_ns'], snapshot['netsquid_time_ns'], snapshot['time_ns'],
        report['session_completion_ns'])), 'integer clocks')
    # 원인 ID가 존재하고 시간 역행이 없으며 동일 timestamp 순서가 보존돼야 한다.
    seen, previous = {}, -1
    for sequence, event in enumerate(events):
        require(type(event['sim_time_ns']) is int and 0 <= event['sim_time_ns'] <= MAX_TIME_NS,
                'integer event time')
        if event['event_type'].startswith('CORRECTION_') or event['event_type'] == 'PAIR_USABLE':
            require(event['input_pair_ids'] == [3] and event['output_pair_id'] == 3,
                    'correction target resource')
            require(event['details'].get('ancestor_pair_ids') == [1, 2], 'correction ancestry')
        require(event['sequence'] == sequence and event['sim_time_ns'] >= previous, 'log ordering')
        require(event['event_id'] not in seen, 'event uniqueness')
        parent = event['caused_by_event_id']
        require(parent is None or parent in seen, 'causal parent')
        seen[event['event_id']] = event
        previous = event['sim_time_ns']
    return dict(passed=True, expected_timing=expected,
                checks=['packet_path', 'analytic_timing', 'resources', 'usable_state', 'causal_log',
                        'resource_log', 'integer_time', 'density_matrices', 'checkpoint_timing',
                        'independent_fifo', 'queue_trace', 'no_drop', 'quantum_wait_zero', 'separate_completion_times'])
