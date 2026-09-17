"""P2 설정·기록 검증. 고전 경로의 기준식은 보존한 P1과 동일하다."""

import copy
import numpy as np

from p1_validation import analytic_timing, normalize_config as normalize_p1
from quantum_scheduler import MAX_TIME_NS, integer


DEFAULT_NOISE = dict(model='T1T2NoiseModel', T1_ns=20000000, T2_ns=10000000)


def normalize_config(raw):
    if not isinstance(raw, dict):
        raise ValueError('P2 configuration must be an object')
    raw = copy.deepcopy(raw)
    noise = raw.pop('memory_noise', copy.deepcopy(DEFAULT_NOISE))
    raw.setdefault('name', 'p2-memory-aging')
    config = normalize_p1(raw)
    if config['result_replays']:
        raise ValueError('P2 allows one transaction without result replays')
    if not isinstance(noise, dict) or set(noise) != set(DEFAULT_NOISE) or noise['model'] != 'T1T2NoiseModel':
        raise ValueError('P2 requires built-in T1T2NoiseModel with T1_ns and T2_ns')
    for key in ('T1_ns', 'T2_ns'):
        integer(noise[key], key, maximum=MAX_TIME_NS)
    if noise['T1_ns'] and noise['T2_ns'] > noise['T1_ns']:
        raise ValueError('NetSquid 1.1.7 requires T2 <= T1 when T1 is positive')
    config['memory_noise'] = noise
    return config


def decode_dm(encoded, order=('A', 'B')):
    if encoded['qubit_order'] != list(order):
        raise RuntimeError('P2 density matrix qubit order mismatch')
    matrix = np.array(encoded['real'], dtype=float) + 1j * np.array(encoded['imag'], dtype=float)
    if (matrix.shape != (4, 4) or not np.all(np.isfinite(matrix)) or
            np.max(np.abs(matrix - matrix.conj().T)) > 1e-12 or
            abs(np.trace(matrix) - 1) > 1e-12 or np.min(np.linalg.eigvalsh(matrix)) < -1e-12):
        raise RuntimeError('P2 invalid density matrix')
    return matrix


def validate_quantum_snapshot(snapshot, expected):
    checkpoints = snapshot['checkpoints']
    phi = np.array([1, 0, 0, 1]) / np.sqrt(2)
    bits = snapshot['correction']['measurement_bits']
    frame = np.zeros(4)
    frame[bits[1]], frame[2 + (bits[1] ^ 1)] = 1 / np.sqrt(2), (-1) ** bits[0] / np.sqrt(2)
    def check(point, at, order, target):
        if type(point['sim_time_ns']) is not int or point['sim_time_ns'] != at:
            raise RuntimeError('P2 checkpoint timing mismatch')
        dm = decode_dm(point['density_matrix'], order)
        value = float(np.real(target.conj() @ dm @ target))
        if not np.isfinite(point['fidelity']) or abs(point['fidelity'] - value) > 1e-12:
            raise RuntimeError('P2 fidelity/density matrix mismatch')
    for stage, key in (('bsm_start', 'bsm_start_ns'), ('bsm_end_inputs', 'bsm_completion_ns')):
        for pair, order in (('AR', ('A', 'R_AR')), ('RB', ('R_RB', 'B'))):
            check(checkpoints[stage][pair], expected[key], order, phi)
    for stage, key in (('frame', 'bsm_completion_ns'), ('correction_start', 'correction_start_ns'),
                       ('usable', 'correction_completion_ns')):
        check(checkpoints[stage], expected[key], ('A', 'B'), phi if stage == 'usable' else frame)
    if (snapshot['ab_pair']['density_matrix'] != checkpoints['usable']['density_matrix'] or
            snapshot['ab_pair']['fidelity'] != checkpoints['usable']['fidelity']):
        raise RuntimeError('P2 final state/checkpoint mismatch')
    bsm = snapshot['requests'].get(1, snapshot['requests'].get('1'))
    if ((bsm['start_ns'], bsm['completion_ns']) != (expected['bsm_start_ns'], expected['bsm_completion_ns']) or
            (snapshot['correction']['start_ns'], snapshot['correction']['completion_ns']) !=
            (expected['correction_start_ns'], expected['correction_completion_ns'])):
        raise RuntimeError('P2 operation snapshot timing mismatch')


def validate_report(report):
    """시간, 실제 경로, 자원, 고정 target fidelity를 서로 독립적으로 확인한다."""
    config, events = report['config'], report['events']
    expected = analytic_timing(config)
    def require(condition, message):
        if not condition:
            raise RuntimeError('P2 validation: ' + message)
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
                        'resource_log', 'integer_time', 'density_matrices', 'checkpoint_timing'])
