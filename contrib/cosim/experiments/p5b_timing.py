"""Independent schedules for direct-start P5-B; Dc is exclusively R→B."""
from hybrid_config import expected_timing


def no_dq_timing(config):
    return expected_timing(config,no_dq=True)


def fixed_timing(config,delays):
    if set(delays)!={'result_ns'} or type(delays['result_ns']) is not int or delays['result_ns']<0:
        raise ValueError('Fixed-Dc requires only a nonnegative integer result_ns')
    sessions={};packets=[];r_free=b_free=0
    for slot,s in sorted(enumerate(config['sessions']),key=lambda item:item[1]['session_start_ns']):
        at=s['session_start_ns'];start=max(at,r_free);r_free=start+config['bsm_duration_ns']
        rx=r_free+delays['result_ns'];correction=max(rx,b_free);b_free=correction+config['correction_duration_ns']
        sessions[str(s['session_id'])]=dict(session_start_ns=at,bsm_arrival_ns=at,bsm_start_ns=start,
            bsm_completion_ns=r_free,bsm_wait_ns=start-at,correction_arrival_ns=rx,
            correction_start_ns=correction,correction_completion_ns=b_free,correction_wait_ns=correction-rx)
        # A virtual delay event, explicitly not an ns-3 packet/queue observation.
        packets.append(dict(session_id=s['session_id'],app_tx_ns=r_free,app_rx_ns=rx,queue_wait_ns=None))
    return dict(sessions=sessions,packets=packets,batch_completion_ns=b_free,simulation_completion_ns=b_free)


def decoupled(config,classical):
    """Measured No-Dq-R result delay + independent R FIFO wait at local starts.

    Does not reschedule result packets after adding R wait. State is undefined.
    """
    free=0;rows=[];measured={m['session_id']:m for m in classical['metrics']['sessions']}
    for s in sorted(config['sessions'],key=lambda s:s['session_start_ns']):
        arrival=s['session_start_ns'];start=max(arrival,free);free=start+config['bsm_duration_ns']
        c=measured[s['session_id']]
        latency=start-arrival+config['bsm_duration_ns']+c['result_delay_ns']+config['correction_duration_ns']
        rows.append(dict(session_id=s['session_id'],transaction_latency_ns=latency,
            completion_ns=arrival+latency,session_start_ns=arrival,quantum_wait_ns=start-arrival,
            result_delay_ns=c['result_delay_ns'],usable_fidelity=None,
            source='C=No-Dq-R result delay; Q=local-session-start R FIFO'))
    return rows
