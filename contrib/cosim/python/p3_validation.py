"""P3의 FIFO 시간, packet 무경합, session 자원 격리와 관측값을 독립 검사한다."""

import copy
import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from p2_reference_validation import compare_reference
from p2_validation import decode_dm, validate_quantum_snapshot
from p3_config import analytic_timing, normalize_config
from quantum_scheduler import MAX_TIME_NS


def require(condition, message):
    if not condition:
        raise RuntimeError('P3 validation: ' + message)


def calculate_metrics(report):
    """종료 시각이 다른 session의 F_usable과 batch 시계를 분리한다."""
    rows = []
    events = report['events']
    for sid, snap in report['snapshot']['sessions'].items():
        request = snap['requests']['1']
        correction = snap['correction']
        def time(kind):
            values = [e['sim_time_ns'] for e in events if str(e['session_id']) == sid and e['event_type'] == kind]
            require(len(values) == 1, 'metric event count: ' + kind)
            return values[0]
        def packet_wait(kind):
            sent = next(e for e in events if str(e['session_id']) == sid and e['event_type'] == kind + '_TX')
            phy = next(e for e in events if str(e['session_id']) == sid and e['event_type'] == 'PHY_TX' and
                       e['message_id'] == sent['message_id'])
            return phy['sim_time_ns'] - sent['sim_time_ns']
        created = [r['created_ns'] for r in snap['resources'].values()]
        require(created == [0, 0], 'P3 requires t=0 EPR creation')
        rows.append(dict(session_id=int(sid), created_ns=0, command_receive_ns=time('COMMAND_RX'),
            command_queue_ns=packet_wait('COMMAND'), result_queue_ns=packet_wait('RESULT'),
            age_on_arrival_ns=request['arrival_ns'], quantum_wait_ns=request['start_ns'] - request['arrival_ns'],
            age_at_bsm_start_ns=request['start_ns'], bsm_start_ns=request['start_ns'],
            bsm_completion_ns=request['completion_ns'], correction_start_ns=correction['start_ns'],
            correction_wait_ns=correction['start_ns'] - correction['arrival_ns'],
            completion_ns=correction['completion_ns'], transaction_latency_ns=correction['completion_ns'] - time('COMMAND_TX'),
            input_fidelity={p: point['fidelity'] for p, point in snap['checkpoints']['bsm_start'].items()},
            frame_fidelity=snap['checkpoints']['frame']['fidelity'], usable_fidelity=snap['ab_pair']['fidelity']))
    rows.sort(key=lambda r: r['command_receive_ns'])
    first = min(r['command_receive_ns'] for r in rows)
    last = max(r['bsm_completion_ns'] for r in rows)
    busy = sum(r['bsm_completion_ns'] - r['bsm_start_ns'] for r in rows)
    area, peak = 0, 0
    samples = report['queue_samples']
    for i, sample in enumerate(samples):
        at = sample['sim_time_ns']
        until = samples[i + 1]['sim_time_ns'] if i + 1 < len(samples) else last
        if first <= at < last:
            peak = max(peak, len(sample['waiting_sessions']))
        area += max(0, min(until, last) - max(at, first)) * len(sample['waiting_sessions'])
    return dict(sessions=rows, processor=dict(processor_id=2, observation_start_ns=first,
        observation_end_ns=last, observation_duration_ns=last-first, busy_ns=busy,
        utilization=busy / (last-first), max_queue_length=peak,
        queue_area_ns=area, time_average_queue_length=area / (last-first),
        mean_waiting_ns=sum(r['quantum_wait_ns'] for r in rows) / len(rows)))


def validate_report(report):
    config = normalize_config(report['config'])
    expected = analytic_timing(config)
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
        require(not (t['command_queue_ns'] or t['result_queue_ns']), 'classical queue present; outside P3 scope')
        require(t['correction_queue_ns'] == 0, 'correction queue present; outside P3 scope')
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
            ptx = one('PHY_TX', sent['sim_time_ns'], mid)
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
    last = max(t['correction_completion_ns'] for t in expected.values())
    for time in (report['ns3_time_ns'], report['snapshot']['netsquid_time_ns'], report['snapshot']['time_ns'], report['batch_completion_ns']):
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
    require(metrics == report['metrics'], 'metric mismatch')
    require(metrics['processor']['queue_area_ns'] == sum(r['quantum_wait_ns'] for r in metrics['sessions']), 'queue integral != sum waiting time')
    return dict(passed=True, expected_timing=expected, checks=['packet_path', 'FIFO_timing', 'classical_no_queue',
        'correction_no_queue', 'session_isolation', 'resource_lifecycle', 'causal_log', 'integer_time',
        'quantum_checkpoints', 'queue_integral', 'utilization'])


def cross_validate(report):
    comparisons, baselines = {}, {}
    config = report['config']
    for sid, snapshot in report['snapshot']['sessions'].items():
        comparison = compare_reference(dict(config=config, snapshot=snapshot))
        comparisons[sid] = comparison
        # 동일 EPR 생성시각과 R 도착시각에서 Dq만 0으로 둔 반사실적 기준.
        # 추가 co-sim 실행이라고 부르지 않는다. native reference가 네 분기를 정확히 가중한다.
        wait = snapshot['requests']['1']['start_ns'] - snapshot['requests']['1']['arrival_ns']
        spec = copy.deepcopy(comparison['input_timing'])
        for key in ('bsm_start_ns', 'bsm_completion_ns', 'correction_start_ns', 'correction_completion_ns'):
            spec[key] -= wait
        if wait == 0:
            reference = comparison['reference']
        else:
            proc = subprocess.run([sys.executable, str(Path(__file__).with_name('netsquid_reference_p2.py'))],
                input=json.dumps(spec), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                universal_newlines=True, timeout=30)
            if proc.returncode:
                raise RuntimeError('P3 no-wait reference failed: ' + proc.stderr)
            reference = json.loads(proc.stdout)
        for pair, order in (('AR', ('A','R_AR')), ('RB', ('R_RB','B'))):
            observed = snapshot['checkpoints']['arrival'][pair]
            expected = reference['inputs']['bsm_start'][pair]
            require(observed['sim_time_ns'] == expected['sim_time_ns'] and
                    np.max(np.abs(decode_dm(observed['density_matrix'], order) - decode_dm(expected['density_matrix'], order))) <= 1e-12,
                    'arrival/reference state mismatch')
        baselines[sid] = dict(model='independent-reference-with-R-wait-removed', input_timing=spec,
            removed_wait_ns=wait, reference=reference,
            ensemble_fidelity_delta=comparison['reference']['ensemble']['fidelity'] - reference['ensemble']['fidelity'])
    return dict(passed=True, sessions=comparisons, no_wait_baselines=baselines,
                max_density_matrix_error=max(c['max_density_matrix_error'] for c in comparisons.values()))
