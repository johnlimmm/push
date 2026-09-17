"""traffic seed와 quantum seed를 분리한 유한 workload/calibration 계약."""
import copy
import hashlib
import json
import math
import random

from p5_config import normalize_config
from p1_validation import tx_duration_ns
from quantum_scheduler import integer


def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()


def validate_plan(raw):
    keys={'classical_loads','request_intervals_ns','sessions','calibration_traffic_seeds',
          'test_traffic_seeds','quantum_seeds','calibration_request_interval_ns','correction_duration_ns',
          'fidelity_min','deadline_ns','bootstrap_samples'}
    if not isinstance(raw,dict) or set(raw)!=keys: raise ValueError('invalid P5-B plan fields')
    p=copy.deepcopy(raw)
    for key in ('calibration_traffic_seeds','test_traffic_seeds','quantum_seeds','request_intervals_ns'):
        values=p[key]
        if not isinstance(values,list) or not values or len(values)!=len(set(values)): raise ValueError('empty/duplicate '+key)
        for v in values: integer(v,key,1 if key=='request_intervals_ns' else 0,2**32-1)
    if set(p['calibration_traffic_seeds']) & set(p['test_traffic_seeds']): raise ValueError('calibration/test leakage')
    loads=p['classical_loads']
    if not isinstance(loads,list) or not loads or len(loads)!=len(set(loads)) or any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<1 for v in loads):
        raise ValueError('classical loads must be unique in [0,1)')
    integer(p['sessions'],'sessions',1,64)
    for k in ('calibration_request_interval_ns','correction_duration_ns','deadline_ns','bootstrap_samples'):
        integer(p[k],k,1)
    if type(p['fidelity_min']) not in (float,int) or not 0<=p['fidelity_min']<=1: raise ValueError('invalid fidelity threshold')
    return p


def workload(plan, load, request_interval, traffic_seed, quantum_seed):
    rng=random.Random(traffic_seed)
    config=normalize_config(dict(name='p5b',seed=quantum_seed,
        sessions=[dict(session_id=i+1,command_time_ns=1000000+i*request_interval) for i in range(plan['sessions'])],
        correction_duration_ns=plan['correction_duration_ns']))
    # 모든 모델에 동일한 packet 입력을 공급한다. seed는 background의 시작 phase만 변경한다.
    horizon=1000000+(plan['sessions']-1)*request_interval+plan['sessions']*config['bsm_duration_ns']+3000000
    for side in ('command','result'):
        serial=tx_duration_ns(1000,config[side+'_link']['rate_bps'])
        interval=max(serial,int(round(serial/load))) if load else serial
        start=rng.randrange(interval)
        config['background'][side]=dict(start_ns=start,interval_ns=interval,
            count=max(0,(horizon-start)//interval+1) if load else 0,payload_bytes=1000)
    return normalize_config(config)


def workload_digest(config):
    data=copy.deepcopy(config);data.pop('seed');data.pop('name')
    return digest(data)


def rounded_mean(values):
    # 양수 ns 평균은 가장 가까운 정수로, 정확히 절반이면 위로 반올림한다.
    return (2*sum(values)+len(values))//(2*len(values))


def calibration_entry(load, records):
    delays={side+'_ns':rounded_mean([m[side+'_delay_ns'] for r in records for m in r['metrics']['sessions']])
            for side in ('command','result')}
    return dict(classical_load=load,delays=delays,rounding='nearest integer ns; half up',
        sample_count=sum(len(r['metrics']['sessions']) for r in records),
        measured_delays={side:[m[side+'_delay_ns'] for r in records for m in r['metrics']['sessions']]
                         for side in ('command','result')})
