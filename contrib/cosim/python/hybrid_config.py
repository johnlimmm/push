"""초기 범위: 고정 C/A/R/B 배치, t=0 자원, IPv4/UDP, 두 atomic protocol."""
import copy
from p5_config import normalize_config as normalize_p5
from p1_validation import tx_duration_ns
from hybrid_adapters import STATES


def normalize_config(raw):
    raw=copy.deepcopy(raw)
    raw.setdefault('sessions',[dict(session_id=1,protocol='teleport',input_state='+i',command_time_ns=1000000)])
    sessions=raw['sessions']
    raw['sessions']=[{k:v for k,v in s.items() if k in ('session_id','command_time_ns')} for s in sessions]
    config=normalize_p5(raw)
    for s in sessions:
        if set(s)-{'session_id','command_time_ns','protocol','input_state','input_created_ns','epr_created_ns'}:
            raise ValueError('unknown hybrid session field')
        s.setdefault('protocol','swap');s.setdefault('epr_created_ns',0)
        if s['protocol'] not in ('swap','teleport'): raise ValueError('unknown protocol')
        if type(s['epr_created_ns']) is not int or s['epr_created_ns']!=0:
            raise ValueError('initial scope requires EPR creation at t=0')
        if s['protocol']=='teleport':
            s.setdefault('input_state','+i');s.setdefault('input_created_ns',0)
            if s['input_state'] not in STATES: raise ValueError('unsupported input state')
            if type(s['input_created_ns']) is not int or s['input_created_ns']!=0:
                raise ValueError('initial scope requires input creation at t=0')
        elif 'input_state' in s or 'input_created_ns' in s:
            raise ValueError('swap has no input qubit')
    config['sessions']=sessions
    return config


def expected_timing(config):
    """입력 설정만으로 계산한 유한 FIFO. Teleport의 실제 payload는 2바이트다."""
    def fifo(side,controls):
        flow=config['background'][side];link=config[side+'_link'];offset=1000 if side=='command' else 100000
        packets=[dict(packet_id=offset+i,session_id=0,link=side,app_tx_ns=flow['start_ns']+i*flow['interval_ns'],
            payload_bytes=flow['payload_bytes']) for i in range(flow['count'])]
        packets+=controls
        packets.sort(key=lambda p:(p['app_tx_ns'],p['session_id']!=0,p['packet_id']))
        free=0
        for p in packets:
            start=max(free,p['app_tx_ns']);duration=tx_duration_ns(p['payload_bytes'],link['rate_bps'])
            free=start+duration
            p.update(enqueue_ns=p['app_tx_ns'],dequeue_ns=start,phy_tx_ns=start,phy_tx_end_ns=free,
                phy_rx_ns=free+link['delay_ns'],app_rx_ns=free+link['delay_ns'],queue_wait_ns=start-p['app_tx_ns'])
        return packets
    command=fifo('command',[dict(packet_id=2*i+1,session_id=s['session_id'],link='command',
            app_tx_ns=s['command_time_ns'],payload_bytes=config['command_payload_bytes']) for i,s in enumerate(config['sessions'])])
    by_id={s['session_id']:s for s in config['sessions']};sessions={};results=[];free=0
    for p in command:
        sid=p['session_id']
        if not sid: continue
        start=max(free,p['app_rx_ns']);free=start+config['bsm_duration_ns']
        sessions[str(sid)]=dict(bsm_arrival_ns=p['app_rx_ns'],bsm_start_ns=start,bsm_completion_ns=free,
                               bsm_wait_ns=start-p['app_rx_ns'])
        results.append(dict(packet_id=p['packet_id']+1,session_id=sid,link='result',app_tx_ns=free,
            payload_bytes=2 if by_id[sid]['protocol']=='teleport' else config['result_payload_bytes']))
    result=fifo('result',results);free=0
    for p in result:
        sid=p['session_id']
        if not sid: continue
        start=max(free,p['app_rx_ns']);free=start+config['correction_duration_ns']
        sessions[str(sid)].update(correction_arrival_ns=p['app_rx_ns'],correction_start_ns=start,
            correction_completion_ns=free,correction_wait_ns=start-p['app_rx_ns'])
    return dict(sessions=sessions,packets=command+result)
