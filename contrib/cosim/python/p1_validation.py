"""P1 설정과 독립 시간 계산. ns-3 trace의 값을 정답 생성에 사용하지 않는다."""

import copy
import numpy as np

from quantum_scheduler import MAX_TIME_NS, integer


DEFAULT_CONFIG = dict(
    name='p1-swapping', session_id=1, seed=7, command_time_ns=1000000,
    bsm_duration_ns=1600000, correction_duration_ns=500000,
    command_payload_bytes=96, result_payload_bytes=80,
    command_link=dict(rate_bps=100000000, delay_ns=100000),
    result_link=dict(rate_bps=10000000, delay_ns=200000), result_replays=[])


def tx_duration_ns(payload_bytes, rate_bps):
    # 이 모델은 IPv4 options/fragmentation 없음: PPP 2 + IPv4 20 + UDP 8 bytes.
    # 양의 시간을 정수 ns로 반올림한다. 정확한 half-ns 경계는 아래 설정 검사에서 제외한다.
    numerator = (payload_bytes + 30) * 8 * 1000000000
    return (2 * numerator + rate_bps) // (2 * rate_bps)


def normalize_config(raw):
    if not isinstance(raw, dict) or set(raw) - set(DEFAULT_CONFIG):
        raise ValueError('unsupported P1 configuration fields')
    config = copy.deepcopy(DEFAULT_CONFIG)
    config.update(copy.deepcopy(raw))
    if not isinstance(config['name'], str):
        raise ValueError('name must be a string')
    integer(config['session_id'], 'session_id', 1)
    integer(config['seed'], 'seed', maximum=2 ** 32 - 1)
    for key in ('command_time_ns', 'bsm_duration_ns', 'correction_duration_ns'):
        integer(config[key], key, 0 if key == 'command_time_ns' else 1, MAX_TIME_NS)
    for side in ('command', 'result'):
        payload = integer(config[side + '_payload_bytes'], 'payload_bytes', 60, 1400)
        link = config[side + '_link']
        if not isinstance(link, dict) or set(link) != {'rate_bps', 'delay_ns'}:
            raise ValueError('link requires rate_bps and delay_ns only')
        rate = integer(link['rate_bps'], 'rate_bps', 1, 10 ** 12)
        integer(link['delay_ns'], 'delay_ns', maximum=MAX_TIME_NS)
        # Q64 변환 오차로 .5 ns에서 반올림 방향이 달라질 수 있는 입력은 P1에서 받지 않는다.
        remainder = ((payload + 30) * 8 * 1000000000) % rate
        if remainder * 2 == rate or tx_duration_ns(payload, rate) < 1:
            raise ValueError('P1 requires positive serialization time away from half-ns ties')
    replays = config['result_replays']
    if not isinstance(replays, list) or len(replays) > 100:
        raise ValueError('result_replays must be a list with at most 100 entries')
    for replay in replays:
        if not isinstance(replay, dict) or set(replay) - {'delay_ns', 'xor_m1', 'xor_m2'}:
            raise ValueError('invalid result replay fields')
        integer(replay.get('delay_ns'), 'replay delay', maximum=MAX_TIME_NS)
        for key in ('xor_m1', 'xor_m2'):
            replay.setdefault(key, 0)
            integer(replay[key], key, maximum=1)
    expected = analytic_timing(config)
    if max([expected['correction_completion_ns']] + [r['receive_ns'] for r in expected['results']]) > MAX_TIME_NS:
        raise ValueError('P1 transaction time overflow')
    return config


def analytic_timing(config):
    """단일 transaction과 검증용 재전송을 설정값만으로 계산한다. IFG=0, 무손실이다."""
    command_tx = tx_duration_ns(config['command_payload_bytes'], config['command_link']['rate_bps'])
    result_tx = tx_duration_ns(config['result_payload_bytes'], config['result_link']['rate_bps'])
    command_rx = config['command_time_ns'] + command_tx + config['command_link']['delay_ns']
    bsm_end = command_rx + config['bsm_duration_ns']
    sends = [bsm_end] + [bsm_end + r['delay_ns'] for r in config['result_replays']]
    available = bsm_end
    results = []
    for at in sorted(sends):
        # 재전송 테스트에서 앞 패킷이 직렬화 중이면 장치 큐 대기시간도 계산한다.
        phy_tx = max(available, at)
        available = phy_tx + result_tx
        results.append(dict(send_ns=at, phy_tx_ns=phy_tx,
                            receive_ns=available + config['result_link']['delay_ns']))
    corr_start = results[0]['receive_ns']
    return dict(command_send_ns=config['command_time_ns'], command_receive_ns=command_rx,
                command_serialization_ns=command_tx, result_serialization_ns=result_tx,
                bsm_start_ns=command_rx, bsm_completion_ns=bsm_end,
                correction_start_ns=corr_start,
                correction_completion_ns=corr_start + config['correction_duration_ns'], results=results)


def decode_dm(encoded):
    if encoded['qubit_order'] != ['A', 'B']:
        raise ValueError('density matrix qubit order mismatch')
    return np.array(encoded['real']) + 1j * np.array(encoded['imag'])


def validate_report(report):
    """시간, 실제 경로, 자원, 고정 target fidelity를 서로 독립적으로 확인한다."""
    config, events = report['config'], report['events']
    expected = analytic_timing(config)
    def require(condition, message):
        if not condition:
            raise RuntimeError('P1 validation: ' + message)
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
    one('PHY_TX', expected['command_send_ns'], command['message_id'])
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
    require(snapshot['ab_pair']['state'] == 'USABLE', 'AB state')
    require(snapshot['ab_pair']['input_pair_ids'] == [1, 2], 'AB creation ancestry')
    require(snapshot['correction_count'] == 1, 'correction executed more than once')
    require(len(snapshot['resources']) == 2 and
            all(r['state'] == 'CONSUMED' for r in snapshot['resources'].values()), 'input EPR state')
    initial = select('EPR_CREATED')
    require(len(initial) == 2 and all(abs(1 - e['fidelity']) <= 1e-12 for e in initial), 'initial EPR fidelity')
    require(len(select('BSM_MEASURED')) == 1, 'BSM count')
    require(abs(1 - snapshot['ab_pair']['fidelity']) <= 1e-12, 'usable fidelity')
    phi = np.array([1, 0, 0, 1]) / np.sqrt(2)
    require(np.max(np.abs(decode_dm(snapshot['ab_pair']['density_matrix']) - np.outer(phi, phi))) <= 1e-12,
            'final Bell density matrix')
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
                        'resource_log', 'integer_time'])
