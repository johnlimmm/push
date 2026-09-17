"""설정 기반 FIFO, 실제 Q2NS 경계, 자원/인과 로그 및 독립 quantum 상태 검증."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from hybrid_config import expected_timing


def require(ok,message):
    if not ok:raise RuntimeError('Hybrid validation: '+message)


def validate_report(report):
    c=report['config'];snap=report['snapshot'];rows=report['ns3_events'];events=report['events']
    expected=expected_timing(c)
    require(report['ns3_time_ns']==snap['time_ns']==snap['netsquid_time_ns'],'clock mismatch')
    def times(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k.endswith('_ns') and v is not None:require(type(v) is int,'integer time: '+k)
                times(v)
        elif isinstance(value,list):
            for v in value:times(v)
    times(report)
    require(report['q2ns_status']==dict(native_state_count=0,native_qubit_count=0,
            sessions=len(c['sessions']),corrections_applied=len(c['sessions'])),'Q2NS ownership/completion')
    require(not any('DROP' in r['event_type'] for r in rows),'packet drop')
    packet_types={'COMMAND_TX','RESULT_TX','BACKGROUND_TX','COMMAND_RX','RESULT_RX','BACKGROUND_RX',
                  'QUEUE_ENQUEUE','QUEUE_DEQUEUE','PHY_TX','PHY_TX_END','PHY_RX'}
    packet_rows=[r for r in rows if r['event_type'] in packet_types]
    require({r['message_id'] for r in packet_rows}=={p['packet_id'] for p in expected['packets']},'packet IDs')
    for p in expected['packets']:
        own=[r for r in packet_rows if r['message_id']==p['packet_id']]
        tx='BACKGROUND_TX' if not p['session_id'] else ('COMMAND_TX' if p['link']=='command' else 'RESULT_TX')
        rx=tx.replace('TX','RX')
        schedule={tx:'app_tx_ns',rx:'app_rx_ns','QUEUE_ENQUEUE':'enqueue_ns','QUEUE_DEQUEUE':'dequeue_ns',
                  'PHY_TX':'phy_tx_ns','PHY_TX_END':'phy_tx_end_ns','PHY_RX':'phy_rx_ns'}
        require(len(own)==len(schedule),'packet trace count')
        for kind,key in schedule.items():
            matches=[r for r in own if r['event_type']==kind]
            require(len(matches)==1 and matches[0]['time_ns']==p[key],'FIFO packet timing '+kind)
            r=matches[0]
            require(r['session_id']==p['session_id'],'packet session')
            require(r['packet_bytes']==p['payload_bytes']+(0 if kind in (tx,rx) else 30),'wire bytes')
    requests=snap['requests'];require(len(requests)==2*len(c['sessions']),'request count')
    for s in c['sessions']:
        sid=s['session_id'];out=snap['sessions'][str(sid)];pred=expected['sessions'][str(sid)]
        require(out['protocol']==s['protocol'] and out['correction_count']==1,'protocol completion')
        require(out['output']['state']=='USABLE','output not usable')
        for op in ('BSM','CORRECTION'):
            req=[r for r in requests if r['session_id']==sid and r['operation']==op]
            require(len(req)==1,'unique operation');r=req[0]
            require(r['state']=='COMPLETED' and r['protocol']==s['protocol'],'operation terminal state')
            for field in ('arrival_ns','start_ns','completion_ns'):
                require(r[field]==pred[op.lower()+'_'+field],'quantum FIFO timing')
            require(r['processor_id']==('R' if op=='BSM' else 'B'),'shared processor mapping')
        own=[r for r in rows if r['session_id']==sid]
        prefix='Q2NS_' if s['protocol']=='swap' else 'Q2NS_TELEPORT_'
        for suffix,key in [('BSM_REQUEST','bsm_arrival_ns'),('BSM_DONE','bsm_completion_ns'),
                           ('CORRECTION_REQUEST','correction_arrival_ns'),('CORRECTION_APPLIED','correction_completion_ns')]:
            selected=[r for r in own if r['event_type']==prefix+suffix]
            require(len(selected)==1 and selected[0]['time_ns']==pred[key],'native app '+suffix)
        for name in ('RESULT_TX','RESULT_RX','CORRECTION_REQUEST'):
            selected=[r for r in own if r['event_type']==name]
            require(len(selected)==1 and [selected[0]['m1'],selected[0]['m2']]==out['measurement_bits'],'actual payload bits')
        resources=[r for r in snap['resources'] if r['session_id']==sid]
        require(len(resources)==3,'resource lifecycle count')
        for r in resources:
            require(r['owner'] is None and r['state']==('USABLE' if r['handle']=='output' else 'CONSUMED'),'resource lifecycle')
        if s['protocol']=='teleport':
            require(out['output']['kind']=='qubit' and out['logical_handles']==dict(input=201,epr=202,output=203),'teleport handles')
    known=set();last=-1
    for sequence,e in enumerate(events):
        require(e['sequence']==sequence and e['sim_time_ns']>=last,'log sequence/time')
        require(e['event_id'] not in known,'event ID reused')
        require(e['caused_by_event_id'] is None or e['caused_by_event_id'] in known,'causal parent missing/future')
        known.add(e['event_id']);last=e['sim_time_ns']
    require(snap['time_ns']==max([p['app_rx_ns'] for p in expected['packets']]+
            [s['correction_completion_ns'] for s in expected['sessions'].values()]),'final drain boundary')
    return dict(passed=True,checks=['packet_FIFO','processor_FIFO','native_apps','resource_lifecycle',
                'causal_log','integer_time','single_state_owner'],expected_timing=expected)


def cross_validate(report,references=None):
    refs={} if references is None else references
    result={}
    for sid,s in report['snapshot']['sessions'].items():
        # 실제 실행 시각과 독립 FIFO가 이미 일치함을 확인했다. reference에는 관측 시각을 넣는다.
        own={r['operation']:r for r in report['snapshot']['requests'] if str(r['session_id'])==sid}
        spec=dict(protocol=s['protocol'],input_state=s['input_state'],input_created_ns=s['input_created_ns'],
            epr_created_ns=s['epr_created_ns'],memory_noise=report['config']['memory_noise'],
            bsm_start_ns=own['BSM']['start_ns'],bsm_completion_ns=own['BSM']['completion_ns'],
            correction_arrival_ns=own['CORRECTION']['arrival_ns'],
            correction_start_ns=own['CORRECTION']['start_ns'],correction_completion_ns=own['CORRECTION']['completion_ns'])
        key=json.dumps(spec,sort_keys=True)
        if key not in refs:
            proc=subprocess.run([sys.executable,str(Path(__file__).with_name('netsquid_reference_hybrid.py'))],
                input=json.dumps(spec),stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=30)
            require(proc.returncode==0,'reference subprocess: '+proc.stderr)
            refs[key]=json.loads(proc.stdout)
        ref=refs[key]
        require(ref['spec']==spec and ref['time_ns']==spec['correction_completion_ns'],'reference spec/time')
        expected_events=list(zip(['bsm_start','bsm_end_inputs','packet_arrival','correction_start','usable'],
            [spec[k] for k in ('bsm_start_ns','bsm_completion_ns','correction_arrival_ns','correction_start_ns','correction_completion_ns')]))
        require([(e['event_type'],e['sim_time_ns']) for e in ref['events']]==expected_events,'reference operation times')
        require(set(ref['branches'])=={'00','01','10','11'},'reference branches')
        probabilities=[b['probability'] for b in ref['branches'].values()]
        require(all(np.isfinite(p) and 0<=p<=1+1e-12 for p in probabilities) and abs(sum(probabilities)-1)<1e-12,'branch probabilities')
        bits=''.join(map(str,s['measurement_bits']));branch=ref['branches'][bits]
        require(branch['probability']>0,'impossible observed branch')
        errors={};ferrors={}
        def compare(label,a,b):
            da,db=a['density_matrix'],b['density_matrix']
            require(da['qubit_order']==db['qubit_order'] and a['sim_time_ns']==b['sim_time_ns'],'checkpoint identity '+label)
            left=np.array(da['real'])+1j*np.array(da['imag']);right=np.array(db['real'])+1j*np.array(db['imag'])
            require(left.shape==right.shape and np.all(np.isfinite(left)) and np.all(np.isfinite(right)),'density matrix shape/value')
            err=float(np.max(np.abs(left-right)));ferr=abs(a['fidelity']-b['fidelity'])
            require(np.isfinite(ferr) and err<=1e-12 and ferr<=1e-12,'quantum reference '+label)
            errors[label]=err;ferrors[label]=ferr
        cp=s['checkpoints']
        for stage in ('bsm_start','bsm_end_inputs'):
            for name in ref['inputs'][stage]:compare(stage+'.'+name,cp[stage][name],ref['inputs'][stage][name])
        for stage in ('frame','packet_arrival','correction_start','usable'):compare(stage,cp[stage],branch[stage])
        result[sid]=dict(passed=True,observed_branch=bits,max_density_matrix_error=max(errors.values()),
            max_fidelity_error=max(ferrors.values()),checkpoint_errors=errors,reference=ref)
    return dict(passed=True,sessions=result,max_density_matrix_error=max(r['max_density_matrix_error'] for r in result.values()))
