"""Use existing P5-B workload/thresholds with declared quantum-link provisioning."""
import copy
from native_p5b_workload import validate_plan as native_plan, workload as native_workload
from provisioned_config import normalize_config


def validate_plan(raw):
    raw = copy.deepcopy(raw)
    links = raw.pop('quantum_links')
    plan = native_plan(raw)
    plan['quantum_links'] = normalize_config(dict(quantum_links=links))['quantum_links']
    return plan


def workload(plan, load, request_interval, traffic_seed, quantum_seed):
    config = native_workload(plan, load, request_interval, traffic_seed, quantum_seed)
    config['quantum_links'] = copy.deepcopy(plan['quantum_links'])
    # Extend the same offered-rate traffic through a possibly later ready time.
    horizon = (max(1000000, max(v['delay_ns'] for v in plan['quantum_links'].values())) +
               (plan['sessions']-1)*request_interval + plan['sessions']*config['bsm_duration_ns'] + 3000000)
    for flow in config['background'].values():
        flow['count'] = max(0, (horizon-flow['start_ns'])//flow['interval_ns']+1) if load else 0
    return normalize_config(config)
