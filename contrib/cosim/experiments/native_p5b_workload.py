"""Keep the prior workload family and thresholds, explicitly fixing native gates."""
import copy
from native_config import normalize_config
from p5b_workload import validate_plan as validate_atomic, workload as atomic_workload


def validate_plan(raw):
    raw = copy.deepcopy(raw)
    instructions = raw.pop('native_instructions')
    plan = validate_atomic(raw)
    config = normalize_config(dict(native_instructions=instructions,
                                   correction_duration_ns=plan['correction_duration_ns']))
    plan['native_instructions'] = config['native_instructions']
    return plan


def workload(plan, load, request_interval, traffic_seed, quantum_seed):
    config = atomic_workload(plan, load, request_interval, traffic_seed, quantum_seed)
    config.pop('bsm_duration_ns')
    config['native_instructions'] = plan['native_instructions']
    config = normalize_config(config)
    horizon = (1000000+(plan['sessions']-1)*request_interval+
               plan['sessions']*config['bsm_duration_ns']+3000000)
    for flow in config['background'].values():
        flow['count'] = max(0, (horizon-flow['start_ns'])//flow['interval_ns']+1) if load else 0
    return normalize_config(config)
