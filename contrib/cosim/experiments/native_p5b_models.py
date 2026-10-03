"""Native evaluation variants. R capacity relaxation changes no gate/noise model."""
import copy
from pathlib import Path
import sys
import time

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))
from netsquid.components import QuantumProcessor
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from native_core import NativeExecutionCore, NativeHybridFederation
from native_adapters import NativeSwapAdapter, NativeTeleportAdapter
from native_programs import physical_instructions
from native_validation import validate_report, cross_validate
from run_native_hybrid import NativeHybridManager
from run_hybrid import HybridParticipant, HybridValidationFailure, session_metrics
from p5b_fixed import FixedParticipant
from p5b_timing import fixed_timing, no_dq_timing
from hybrid_config import expected_timing
from p5b_analysis import model_rows as atomic_model_rows


class RMemoryView:
    """Keep logical R positions while each session has its own execution engine.

    There are still exactly two R memory positions per session, with one state
    owner. Only simultaneous instruction execution capacity changes.
    """
    def __init__(self, devices):
        self.devices = devices

    def put(self, qubit, positions):
        self.devices[positions//2].put(qubit, positions=positions % 2)

    def peek(self, position):
        return self.devices[position//2].peek(position % 2)

    def pop(self, positions):
        return [self.devices[p//2].pop(p % 2)[0] for p in positions]


class NativeNoDqCore(NativeExecutionCore):
    def __init__(self, config, capture_states=True):
        super().__init__(config, capture_states)
        self.r_capacity = len(config['sessions'])
        self.processors['R']['capacity'] = self.r_capacity
        self.r_devices, self.r_slot = [], {}
        for slot, session in enumerate(config['sessions']):
            sid = session['session_id']; noise = config['memory_noise']
            device = QuantumProcessor('R-evaluation-'+str(sid), num_positions=2,
                mem_noise_models=[T1T2NoiseModel(T1=noise['T1_ns'], T2=noise['T2_ns']) for _ in range(2)],
                phys_instructions=physical_instructions(config['native_instructions'], noise))
            device.set_program_done_callback(self.program_done, 'R', (sid, 'BSM'), once=False)
            device.set_program_fail_callback(self.failed_replica, slot, once=False)
            self.r_slot[sid] = slot; self.r_devices.append(device)
        self.devices['R'] = RMemoryView(self.r_devices)

    def failed_replica(self, slot):
        raise RuntimeError('native R evaluation program failed: '+str(self.r_devices[slot].fail_exception))

    def device_for(self, request):
        return (self.r_devices[self.r_slot[request['session_id']]] if request['processor_id']=='R'
                else super().device_for(request))

    def target_positions(self, request):
        return ([0, 1] if request['processor_id']=='R' else super().target_positions(request))


def execute(raw, model='Full-Sync', references=None, delays=None, participant_class=HybridParticipant,
            require_no_b_wait=True):
    if model not in ('Full-Sync', 'No-Dq-R', 'Fixed-Dc'):
        raise ValueError('unknown native model')
    manager = NativeHybridManager(raw); config = manager.config
    expected = (fixed_timing(config, delays) if model=='Fixed-Dc' else
                no_dq_timing(config) if model=='No-Dq-R' else expected_timing(config))
    if require_no_b_wait and any(r['correction_wait_ns'] for r in expected['sessions'].values()):
        raise ValueError(model+': workload violates B wait=0')
    t0 = time.perf_counter()
    core = (NativeNoDqCore if model=='No-Dq-R' else NativeExecutionCore)(config)
    for slot, s in enumerate(config['sessions']):
        core.adapters[s['session_id']] = (NativeSwapAdapter if s['protocol']=='swap' else NativeTeleportAdapter)(core, s, slot)
    t1 = time.perf_counter()
    network = model!='Fixed-Dc'
    participant = (participant_class(manager.binary, config, core.roots) if network else
                   FixedParticipant(config, core.roots, delays['result_ns']))
    federation = NativeHybridFederation(core, participant); t2 = time.perf_counter()
    try:
        snapshot = federation.run(); t3 = time.perf_counter()
        if network: participant.finish()
    finally:
        if network: participant.close()
    t4 = time.perf_counter()
    report = dict(schema_version=3, milestone='Native-Timed-Hybrid', architecture='native-timed-v3', model=model,
        config=config, execution_core='NativeExecutionCore(HybridExecutionCore)' if model!='No-Dq-R' else 'NativeNoDqCore',
        federation='NativeHybridFederation', time_unit='ns', snapshot=snapshot, events=core.events,
        bridge_steps=federation.steps, native_instructions=core.instruction_events, instruction_state_recording=True)
    if network:
        report.update(nodes=participant.nodes, ns3_binary=str(manager.binary), ns3_time_ns=participant.now_ns,
                      ns3_events=federation.rows, q2ns_status=participant.q2ns_status)
    else:
        for e in core.events:
            if e['source']=='ns3': e['source']='fixed-delay'
        report.update(fixed_delays=delays, transport='constant result-delay events; no ns-3 packet network')
    try:
        report['validation'] = validate_report(report, expected, network)
        report['cross_validation'] = cross_validate(report, references)
        report['metrics'] = session_metrics(report)
        report['batch_completion_ns'] = max(r['completion_ns'] for r in report['metrics']['sessions'])
    except (ValueError, RuntimeError, KeyError) as error:
        report['validation'] = dict(passed=False, error=str(error))
        raise HybridValidationFailure(report, error) from error
    t5 = time.perf_counter()
    measurement = dict(core_initialization_seconds=t1-t0, participant_startup_seconds=t2-t1,
        federation_seconds=t3-t2, participant_finish_seconds=t4-t3, simulation_seconds=t4-t0,
        offline_validation_seconds=t5-t4, simulation_seconds_per_transaction=(t4-t0)/len(config['sessions']),
        federation_seconds_per_transaction=(t3-t2)/len(config['sessions']))
    return report, measurement, participant


def run_model(config, model, cache, delays=None):
    return execute(config, model, cache, delays)[0]


def model_rows(report, fmin, deadline):
    # Adapt only the analysis view. Stored native references keep their own
    # schema and complete instruction/checkpoint evidence.
    view = dict(report); view['cross_validation'] = copy.deepcopy(report['cross_validation'])
    for session in view['cross_validation']['sessions'].values():
        for branch in session['reference']['branches'].values():
            branch['usable'] = branch['checkpoints']['usable']
    return atomic_model_rows(view, fmin, deadline)
