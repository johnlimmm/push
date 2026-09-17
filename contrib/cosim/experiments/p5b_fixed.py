"""Fixed-Dc: 고정 classical delay 위에서 실제 P3 quantum FIFO/NetSquid를 재실행."""
import heapq

from p1_quantum import EventLog
from p3_quantum import P3Quantum
from p5_config import normalize_config
from p5_validation import cross_validate
from p2_validation import validate_quantum_snapshot
from p5b_timing import fixed_timing


def run_fixed(raw, delays, references=None):
    if set(delays) != {'command_ns','result_ns'} or any(type(v) is not int or v<0 for v in delays.values()):
        raise ValueError('Fixed-Dc requires nonnegative integer delays')
    config=normalize_config(raw); log=EventLog(0)
    roots={s['session_id']:log.add('SESSION_CREATED',0,source='federation',session_id=s['session_id']) for s in config['sessions']}
    quantum=P3Quantum(config,log,roots)
    future=[]; counter=0; rounds=0
    for s in config['sessions']:
        heapq.heappush(future,(s['command_time_ns']+delays['command_ns'],counter,'BSM',s['session_id'],None))
        counter+=1
    while future or quantum.next_safe_horizon() is not None:
        candidates=[t for t in (future[0][0] if future else None,quantum.next_safe_horizon()) if t is not None]
        at=min(candidates); quantum.round=rounds; quantum.phase='COMMIT'
        done=quantum.advance_to_boundary(at)
        for r in done:
            heapq.heappush(future,(at+delays['result_ns'],counter,'CORRECTION',quantum.rid_to_sid[r['request_id']],r))
            counter+=1
        quantum.phase='INPUT'
        while future and future[0][0]==at:
            _,_,kind,sid,result=heapq.heappop(future)
            msg=dict(session_id=sid,request_id=1,pair_a=1,pair_b=2,output_pair_id=3)
            cause=log.add('FIXED_'+kind+'_ARRIVAL',at,source='fixed-delay',session_id=sid,
                cause=roots[sid] if result is None else quantum.complete_causes[result['request_id']])
            if result is None: quantum.submit_bsm(msg,cause)
            else:
                msg.update(m1=result['m1'],m2=result['m2']); quantum.submit_correction(msg,cause)
        quantum.phase='DISPATCH'; quantum.schedule_queued(); rounds+=1
    snapshot=quantum.snapshot(); expected=fixed_timing(config,delays); metrics=[]
    for sid,s in snapshot['sessions'].items():
        b,c=s['requests']['1'],s['correction']; t=expected[sid]
        for actual,wanted in ((b['arrival_ns'],t['command_receive_ns']),(b['start_ns'],t['bsm_start_ns']),
            (b['completion_ns'],t['bsm_completion_ns']),(c['arrival_ns'],t['result_receive_ns']),
            (c['start_ns'],t['correction_start_ns']),(c['completion_ns'],t['correction_completion_ns'])):
            if actual!=wanted: raise RuntimeError('Fixed-Dc FIFO timing mismatch')
        if t['correction_queue_ns']: raise RuntimeError('Fixed-Dc B correction waiting must be zero')
        if s['correction_count']!=1 or s['ab_pair']['state']!='USABLE': raise RuntimeError('Fixed-Dc lifecycle')
        validate_quantum_snapshot(s,t)
        metrics.append(dict(session_id=int(sid),command_delay_ns=delays['command_ns'],result_delay_ns=delays['result_ns'],
            quantum_wait_ns=t['quantum_wait_ns'],correction_wait_ns=0,bsm_start_ns=b['start_ns'],
            bsm_completion_ns=b['completion_ns'],correction_start_ns=c['start_ns'],completion_ns=c['completion_ns'],
            transaction_latency_ns=c['completion_ns']-t['command_send_ns'],usable_fidelity=s['ab_pair']['fidelity']))
    report=dict(model='Fixed-Dc',config=config,snapshot=snapshot,events=log.events,
        fixed_delays=delays,metrics=dict(sessions=metrics),validation=dict(passed=True,expected_timing=expected),
        transport='constant-delay-events; no ns-3 packet network',batch_completion_ns=quantum.now_ns)
    report['cross_validation']=cross_validate(report,references)
    return report
