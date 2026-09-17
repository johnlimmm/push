"""P5-A: 실제 packet FIFO와 R FIFO, session 격리, native memory aging을 검증한다.

P3/P4 검증의 범위를 결합한 별도 파일이다. 보존한 baseline 코드는 수정하지 않는다.
"""
from collections import Counter, defaultdict, deque

import numpy as np

from p2_reference_validation import compare_reference
from p2_validation import decode_dm, validate_quantum_snapshot
from p3_validation import calculate_metrics as quantum_metrics
from p5_config import analytic_timing, normalize_config
from quantum_scheduler import MAX_TIME_NS


def require(condition, message):
    if not condition:
        raise RuntimeError('P5 validation: ' + message)


def calculate_metrics(report):
    """P3의 R queue 통계에 실제 수신 기반 Dc와 result 도착시각을 더한다."""
    metrics = quantum_metrics(report)
    controls = {(p['session_id'], p['link']): p for p in report['packets']
                if p['traffic_class'] == 'control'}
    for row in metrics['sessions']:
        command = controls[row['session_id'], 'command']
        result = controls[row['session_id'], 'result']
        row.update(command_delay_ns=command['total_delay_ns'],
                   result_delay_ns=result['total_delay_ns'], result_receive_ns=result['app_rx_ns'])
    return metrics


def validate_packets(report):
    """측정값으로 기준식을 보정하지 않는다. config로 계산한 전 패킷 일정을 대조한다."""
    config, rows = report['config'], report['packet_events']
    expected = analytic_timing(config)
    def require(ok, message):
        if not ok:
            raise RuntimeError('P5 packet validation: ' + message)
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
        packet = {k: predicted[k] for k in ('packet_id', 'session_id', 'traffic_class', 'link', 'payload_bytes', 'wire_bytes')}
        for event in events:
            et = event['event_type']
            require(event['kind'] == kind and event['link'] == side and event['traffic_class'] == traffic,
                    'packet classification')
            require(event['session_id'] == predicted['session_id'], 'packet session')
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
            busy_ns=busy, utilization=busy/window, control_tx=len(config['sessions']), control_rx=len(config['sessions']),
            background_tx=flow['count'], background_rx=flow['count'], control_drops=0, background_drops=0,
            offered_background_load=((flow['payload_bytes']+30)*8*10**9 /
                (flow['interval_ns']*config[side+'_link']['rate_bps'])) if flow['count'] else 0.0)
    control = {str(s['session_id']): {p['link']: p for p in actual
               if p['traffic_class'] == 'control' and p['session_id'] == s['session_id']}
               for s in config['sessions']}
    for side, field in (('command', 'command_queue_ns'), ('result', 'result_queue_ns'), ('R', 'quantum_wait_ns')):
        values = [t[field] for t in expected['sessions'].values()]
        rule = config['expected_queueing'][side]
        require(rule == 'any' or (rule == 'zero' and all(v == 0 for v in values)) or
                (rule == 'positive' and any(v > 0 for v in values)), side+' required queueing absent/unexpected')
    for key in ('traffic_drain_completion_ns', 'simulation_completion_ns', 'batch_completion_ns'):
        require(type(report[key]) is int and report[key] == expected[key], key)
    return expected, dict(links=links, classical=control), actual

def validate_report(report):
    config = normalize_config(report['config'])
    full, packet_metrics, packets = validate_packets(report)
    expected = full['sessions']
    report['packets'] = packets
    report['metrics'] = dict(calculate_metrics(report), **packet_metrics)
    sessions = report['snapshot']['sessions']
    require(set(sessions) == set(expected), 'session set mismatch')
    events, seen = report['events'], {}
    previous = -1
    for index, e in enumerate(events):
        at = e['sim_time_ns']
        require(type(at) is int and 0 <= at <= MAX_TIME_NS and at >= previous, 'integer event time/order')
        require(str(e['session_id']) in sessions and e['event_id'] not in seen and e['sequence'] == index,
                'session/event identity')
        parent = e['caused_by_event_id']
        require(parent is None or parent in seen, 'missing causal parent')
        require(parent is None or seen[parent]['session_id'] == e['session_id'], 'cross-session causal parent')
        if e['event_type'].startswith('CORRECTION_') or e['event_type'] == 'PAIR_USABLE':
            require(e['request_id'] == 2 and e['input_pair_ids'] == [3] and e['output_pair_id'] == 3 and
                    e['details'].get('ancestor_pair_ids') == [1, 2], 'correction resource identity')
        seen[e['event_id']] = e
        previous = at
    occupied = set()
    for sid, snap in sessions.items():
        t = expected[sid]
        require(t['correction_queue_ns'] == 0, 'B correction waiting must be zero')
        own = [e for e in events if str(e['session_id']) == sid]
        def one(kind, at=None, message=None):
            found = [e for e in own if e['event_type'] == kind and (message is None or e['message_id'] == message)]
            require(len(found) == 1, '{} count/session {}'.format(kind, sid))
            if at is not None:
                require(found[0]['sim_time_ns'] == at, '{} timing/session {}'.format(kind, sid))
            return found[0]
        event_times = dict(COMMAND_TX='command_send_ns', COMMAND_RX='command_receive_ns',
            BSM_REQUEST='command_receive_ns', BSM_RECEIVED='command_receive_ns', BSM_QUEUED='command_receive_ns',
            BSM_START='bsm_start_ns', BSM_MEASURED='bsm_completion_ns', BSM_COMPLETE='bsm_completion_ns',
            AB_CREATED='bsm_completion_ns', BSM_RESULT_LOCAL='bsm_completion_ns', RESULT_TX='result_send_ns',
            RESULT_RX='result_receive_ns', CORRECTION_REQUEST='result_receive_ns',
            CORRECTION_QUEUED='result_receive_ns', CORRECTION_START='correction_start_ns',
            CORRECTION_COMPLETE='correction_completion_ns', PAIR_USABLE='correction_completion_ns')
        for kind, field in event_times.items():
            one(kind, t[field])
        require(len(own) == 24, 'unexpected per-session event count')
        chain = dict(COMMAND_TX='SESSION_CREATED', BSM_REQUEST='COMMAND_RX', BSM_RECEIVED='BSM_REQUEST',
            BSM_QUEUED='BSM_RECEIVED', BSM_START='BSM_QUEUED', BSM_MEASURED='BSM_START',
            BSM_COMPLETE='BSM_MEASURED', AB_CREATED='BSM_COMPLETE', BSM_RESULT_LOCAL='BSM_COMPLETE',
            RESULT_TX='BSM_RESULT_LOCAL', CORRECTION_REQUEST='RESULT_RX', CORRECTION_QUEUED='CORRECTION_REQUEST',
            CORRECTION_START='CORRECTION_QUEUED', CORRECTION_COMPLETE='CORRECTION_START', PAIR_USABLE='CORRECTION_COMPLETE')
        for child, parent in chain.items():
            require(one(child)['caused_by_event_id'] == one(parent)['event_id'], 'transaction causal chain')
        for kind, request_state, states in (
                ('BSM_RECEIVED', 'RECEIVED', {'1':'AVAILABLE','2':'AVAILABLE'}),
                ('BSM_QUEUED', 'QUEUED', {'1':'RESERVED','2':'RESERVED'}),
                ('BSM_START', 'RUNNING', {'1':'IN_USE','2':'IN_USE'}),
                ('BSM_COMPLETE', 'COMPLETED', {'1':'CONSUMED','2':'CONSUMED','3':'FRAME_PENDING'}),
                ('CORRECTION_QUEUED', 'QUEUED', {'1':'CONSUMED','2':'CONSUMED','3':'FRAME_PENDING'}),
                ('CORRECTION_START', 'RUNNING', {'1':'CONSUMED','2':'CONSUMED','3':'CORRECTING'}),
                ('CORRECTION_COMPLETE', 'COMPLETED', {'1':'CONSUMED','2':'CONSUMED','3':'USABLE'})):
            require(one(kind)['request_state'] == request_state and one(kind)['resource_state'] == states,
                    'resource/request transition log')
        for prefix in ('COMMAND', 'RESULT'):
            lower = prefix.lower()
            sent, arrived = one(prefix + '_TX'), one(prefix + '_RX')
            mid = sent['message_id']
            require(arrived['message_id'] == mid, 'packet identity mismatch')
            ptx = one('PHY_TX', t[lower+'_phy_tx_ns'], mid)
            prx = one('PHY_RX', arrived['sim_time_ns'], mid)
            require(ptx['details']['packet_bytes'] == prx['details']['packet_bytes'] == config[lower+'_payload_bytes']+30,
                    'on-wire bytes')
            require(sent['details']['packet_bytes'] == arrived['details']['packet_bytes'] == config[lower+'_payload_bytes'],
                    'UDP payload bytes')
            require(arrived['sim_time_ns'] - ptx['sim_time_ns'] ==
                    t[lower+'_serialization_ns'] + config[lower+'_link']['delay_ns'], 'packet delay')
            require(ptx['caused_by_event_id'] == prx['caused_by_event_id'] == arrived['caused_by_event_id'] == sent['event_id'],
                    'packet causal linkage')
        require(snap['session_id'] == int(sid) and set(snap['requests']) == {'1'}, 'session/request IDs')
        bsm = snap['requests']['1']
        correction = snap['correction']
        require((bsm['request_id'], bsm['pair_a'], bsm['pair_b'], bsm['processor_id']) == (1, 1, 2, 2), 'BSM resource IDs')
        require(bsm['state'] == correction['state'] == 'COMPLETED', 'request completion')
        require([bsm['m1'], bsm['m2']] == correction['measurement_bits'] == one('RESULT_RX')['measurement_bits'],
                'measurement/result/correction routing')
        for key, field in (('arrival_ns','command_receive_ns'), ('start_ns','bsm_start_ns'), ('completion_ns','bsm_completion_ns')):
            require(bsm[key] == t[field], 'BSM snapshot timing')
        for key, field in (('arrival_ns','result_receive_ns'), ('start_ns','correction_start_ns'), ('completion_ns','correction_completion_ns')):
            require(correction[key] == t[field], 'correction snapshot timing')
        require(correction['request_id'] == 2 and correction['bsm_request_id'] == 1 and snap['correction_count'] == 1,
                'exactly one correction')
        require(snap['ab_pair']['state'] == 'USABLE' and snap['ab_pair']['usable_ns'] == t['correction_completion_ns'] and
                snap['ab_pair']['created_ns'] == t['bsm_completion_ns'], 'AB lifecycle/times')
        require(snap['ab_pair']['pair_id'] == 3 and snap['ab_pair']['input_pair_ids'] == [1, 2], 'AB identity')
        require(set(snap['resources']) == {'1','2'} and all(r['state'] == 'CONSUMED' and r['owner'] == 1
                for r in snap['resources'].values()), 'input resource consumption')
        for resource in snap['resources'].values():
            for loc in resource['locations']:
                key = (loc['node_id'], loc['memory_id'], loc['position'])
                require(key not in occupied, 'memory position shared by distinct pairs/sessions')
                occupied.add(key)
        require(snap['ab_pair']['locations'] == [snap['resources']['1']['locations'][0], snap['resources']['2']['locations'][0]],
                'AB endpoint identity changed')
        initial = [e for e in own if e['event_type'] == 'EPR_CREATED']
        require(len(initial) == 2 and all(e['sim_time_ns'] == 0 and abs(e['fidelity']-1) <= 1e-12 for e in initial), 'initial EPR')
        require(snap['memory_noise'] == config['memory_noise'], 'noise configuration')
        validate_quantum_snapshot(snap, t)
        require(one('BSM_MEASURED')['fidelity'] == snap['checkpoints']['frame']['fidelity'] and
                one('PAIR_USABLE')['fidelity'] == snap['ab_pair']['fidelity'], 'fidelity log')
        for pair, order in (('AR', ('A','R_AR')), ('RB', ('R_RB','B'))):
            point = snap['checkpoints']['arrival'][pair]
            require(type(point['sim_time_ns']) is int and point['sim_time_ns'] == t['command_receive_ns'], 'arrival checkpoint time')
            matrix = decode_dm(point['density_matrix'], order)
            phi = np.array([1, 0, 0, 1]) / np.sqrt(2)
            require(np.isfinite(point['fidelity']) and abs(point['fidelity'] - float(np.real(phi @ matrix @ phi))) <= 1e-12,
                    'arrival checkpoint fidelity')
    last = full['simulation_completion_ns']
    for time in (report['ns3_time_ns'], report['snapshot']['netsquid_time_ns'], report['snapshot']['time_ns']):
        require(type(time) is int and time == last, 'final integer clock mismatch')
    require(report['snapshot']['bsm_processor_count'] == report['snapshot']['correction_processor_count'] == 1, 'physical processor count')
    require(report['snapshot']['memory_layout'] == dict(A=len(sessions), R=2*len(sessions), B=len(sessions)), 'memory layout')
    # 매 dispatch 후 안정된 queue 상태와 RUNNING 구간을 독립 시간식으로 대조한다.
    samples = report['queue_samples']
    require(len(samples) == len(report['bridge_steps']) and samples, 'queue samples missing')
    for sample, step in zip(samples, report['bridge_steps']):
        at = step['time_ns']
        require(sample['sim_time_ns'] == at, 'queue sample timestamp')
        waiting = [int(sid) for sid,t in expected.items() if t['command_receive_ns'] <= at < t['bsm_start_ns']]
        running = [int(sid) for sid,t in expected.items() if t['bsm_start_ns'] <= at < t['bsm_completion_ns']]
        require(sample['waiting_sessions'] == waiting and sample['running_session'] == (running[0] if running else None), 'FIFO queue sample')
    metrics = calculate_metrics(report)
    require(all(metrics[k] == report['metrics'][k] for k in metrics), 'metric mismatch')
    require(metrics['processor']['queue_area_ns'] == sum(r['quantum_wait_ns'] for r in metrics['sessions']), 'queue integral != sum waiting time')
    return dict(passed=True, expected_timing=full, checks=['packet_path', 'FIFO_timing', 'independent_packet_fifo', 'no_drop', 'separate_completion_times',
        'correction_no_queue', 'session_isolation', 'resource_lifecycle', 'causal_log', 'integer_time',
        'quantum_checkpoints', 'queue_integral', 'utilization'])



def cross_validate(report, references=None):
    """session마다 실제 operation 시각으로 독립 NetSquid reference를 실행한다.

    R 대기를 뺀 뒤 result 시각도 단순 이동하는 P3 진단값은 여기서 사용하지 않는다.
    references는 같은 물리 설정/시각을 가진 분기 표의 재사용용이며 compare_reference가 확인한다.
    """
    comparisons = {}
    for sid, snapshot in report['snapshot']['sessions'].items():
        reference = None if references is None else references[sid]
        comparisons[sid] = compare_reference(dict(config=report['config'], snapshot=snapshot), reference)
    return dict(passed=True, sessions=comparisons,
                max_density_matrix_error=max(c['max_density_matrix_error'] for c in comparisons.values()),
                max_fidelity_error=max(c['max_fidelity_error'] for c in comparisons.values()))
