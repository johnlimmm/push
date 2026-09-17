"""모델별 독립 일정: 실제 trace를 입력으로 쓰지 않는 검증식."""
from p5_config import fifo


def no_dq_timing(config):
    command = fifo(config, 'command', [dict(packet_id=2*i+1, session_id=s['session_id'],
                   app_tx_ns=s['command_time_ns']) for i,s in enumerate(config['sessions'])])
    sessions, controls = {}, []
    for p in command:
        if p['traffic_class'] != 'control':
            continue
        start = p['app_rx_ns']
        end = start + config['bsm_duration_ns']
        sessions[str(p['session_id'])] = dict(command_send_ns=p['app_tx_ns'],
            command_phy_tx_ns=p['phy_tx_ns'], command_receive_ns=start,
            command_serialization_ns=p['serialization_ns'], command_queue_ns=p['queue_wait_ns'],
            bsm_start_ns=start, bsm_completion_ns=end, quantum_wait_ns=0)
        controls.append(dict(packet_id=p['packet_id']+1, session_id=p['session_id'], app_tx_ns=end))
    result = fifo(config, 'result', controls)
    free = 0
    for p in result:
        if p['traffic_class'] != 'control':
            continue
        arrival = p['app_rx_ns']; start = max(arrival, free)
        free = start + config['correction_duration_ns']
        sessions[str(p['session_id'])].update(result_send_ns=p['app_tx_ns'],
            result_phy_tx_ns=p['phy_tx_ns'], result_receive_ns=arrival,
            result_serialization_ns=p['serialization_ns'], result_queue_ns=p['queue_wait_ns'],
            correction_start_ns=start, correction_completion_ns=free, correction_queue_ns=start-arrival)
    drain = max(p['app_rx_ns'] for p in command+result)
    batch = max(t['correction_completion_ns'] for t in sessions.values())
    return dict(packets=command+result, sessions=sessions, batch_completion_ns=batch,
                traffic_drain_completion_ns=drain, simulation_completion_ns=max(batch,drain))


def fixed_timing(config, delays):
    result = {}; r_free = b_free = 0
    for s in sorted(config['sessions'], key=lambda s:s['command_time_ns']):
        arrival = s['command_time_ns'] + delays['command_ns']
        start = max(arrival,r_free); r_free = start + config['bsm_duration_ns']
        rx = r_free + delays['result_ns']; correction = max(rx,b_free)
        b_free = correction + config['correction_duration_ns']
        result[str(s['session_id'])] = dict(command_send_ns=s['command_time_ns'], command_receive_ns=arrival,
            bsm_start_ns=start, bsm_completion_ns=r_free, result_receive_ns=rx,
            correction_start_ns=correction, correction_completion_ns=b_free,
            quantum_wait_ns=start-arrival, correction_queue_ns=correction-rx)
    return result


def decoupled(config, classical):
    """C-run 실측 Dc + Q-run(무부하 command delay)의 R FIFO wait를 합성한다.

    결과 packet을 W_R만큼 이동하여 재실행하지 않으므로 fidelity는 정의하지 않는다.
    """
    from p1_validation import tx_duration_ns
    dc0 = tx_duration_ns(config['command_payload_bytes'],config['command_link']['rate_bps']) + config['command_link']['delay_ns']
    free = 0; rows = []
    measured = {m['session_id']:m for m in classical['metrics']['sessions']}
    for s in sorted(config['sessions'],key=lambda s:s['command_time_ns']):
        arrival=s['command_time_ns']+dc0; start=max(arrival,free)
        free=start+config['bsm_duration_ns']; c=measured[s['session_id']]
        latency=c['command_delay_ns']+(start-arrival)+config['bsm_duration_ns']+c['result_delay_ns']+config['correction_duration_ns']
        rows.append(dict(session_id=s['session_id'], transaction_latency_ns=latency,
            completion_ns=s['command_time_ns']+latency, quantum_wait_ns=start-arrival,
            command_delay_ns=c['command_delay_ns'],result_delay_ns=c['result_delay_ns'],
            usable_fidelity=None, source='C=No-Dq-R; Q=unloaded-command-arrival-FIFO'))
    return rows
