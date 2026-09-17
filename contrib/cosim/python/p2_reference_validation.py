"""독립 P2 reference를 별도 프로세스로 실행하고 실제 측정 분기의 상태와 비교한다."""

import json
from pathlib import Path
import subprocess
import sys

import numpy as np

from p2_validation import decode_dm


def reference_spec(report):
    snapshot = report['snapshot']
    bsm = snapshot['requests'].get(1, snapshot['requests'].get('1'))
    correction = snapshot['correction']
    return dict(bsm_start_ns=bsm['start_ns'], bsm_completion_ns=bsm['completion_ns'],
                correction_start_ns=correction['start_ns'], correction_completion_ns=correction['completion_ns'],
                memory_noise=report['config']['memory_noise'])


def compare_reference(report, reference=None):
    spec = reference_spec(report)
    if reference is None:
        script = Path(__file__).with_name('netsquid_reference_p2.py')
        process = subprocess.run([sys.executable, str(script)], input=json.dumps(spec),
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 universal_newlines=True, timeout=30)
        if process.returncode:
            raise RuntimeError('P2 reference failed: ' + process.stderr)
        reference = json.loads(process.stdout)
    expected_times = dict(EPR_CREATED=0, BSM_START=spec['bsm_start_ns'],
        BSM_COMPLETE=spec['bsm_completion_ns'], CORRECTION_START=spec['correction_start_ns'],
        CORRECTION_COMPLETE=spec['correction_completion_ns'])
    if (reference['memory_noise'] != spec['memory_noise'] or
            type(reference['time_ns']) is not int or reference['time_ns'] != spec['correction_completion_ns'] or
            len(reference['events']) != len(expected_times) or
            any(type(e['sim_time_ns']) is not int or expected_times.get(e['event_type']) != e['sim_time_ns']
                for e in reference['events']) or
            {e['event_type'] for e in reference['events']} != set(expected_times)):
        raise RuntimeError('P2 reference configuration/time mismatch')
    errors, fidelity_errors = {}, {}
    def compare(name, actual, expected, order=('A', 'B')):
        error = float(np.max(np.abs(decode_dm(actual['density_matrix'], order) -
                                   decode_dm(expected['density_matrix'], order))))
        fidelity_error = abs(actual['fidelity'] - expected['fidelity'])
        if (not np.isfinite(fidelity_error) or error > 1e-12 or fidelity_error > 1e-12 or
                type(expected['sim_time_ns']) is not int or actual['sim_time_ns'] != expected['sim_time_ns']):
            raise RuntimeError('P2 reference checkpoint mismatch: ' + name)
        errors[name], fidelity_errors[name] = error, fidelity_error
    checkpoints = report['snapshot']['checkpoints']
    for stage in ('bsm_start', 'bsm_end_inputs'):
        for pair, order in (('AR', ('A', 'R_AR')), ('RB', ('R_RB', 'B'))):
            compare(stage + '.' + pair, checkpoints[stage][pair], reference['inputs'][stage][pair], order)
    branches = reference['branches']
    if set(branches) != {'00', '01', '10', '11'}:
        raise RuntimeError('P2 reference requires all four BSM branches')
    probabilities = {key: branch['probability'] for key, branch in branches.items()}
    if (any(not np.isfinite(p) or not 0 <= p <= 1 for p in probabilities.values()) or
            abs(sum(probabilities.values()) - 1) > 1e-12):
        raise RuntimeError('P2 reference invalid branch probabilities')
    observed = ''.join(map(str, report['snapshot']['correction']['measurement_bits']))
    if observed not in branches or probabilities[observed] <= 0:
        raise RuntimeError('P2 sampled an impossible reference branch')
    for stage in ('frame', 'correction_start', 'usable'):
        compare(stage, checkpoints[stage], branches[observed][stage])
    return dict(passed=True, comparison='conditional-on-observed-BSM-branch', observed_branch=observed,
                max_density_matrix_error=max(errors.values()), max_fidelity_error=max(fidelity_errors.values()),
                checkpoint_density_matrix_errors=errors, branch_probabilities=probabilities,
                input_timing=spec, reference=reference)
