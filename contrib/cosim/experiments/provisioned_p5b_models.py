"""v4 variants preserve actual quantum delivery; only R capacity or result transport changes."""
import time
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))
from native_p5b_models import NativeNoDqCore, model_rows
from provisioned_core import ProvisionedCore, ProvisionedFederation, ProvisionedSwapAdapter, ProvisionedTeleportAdapter
from provisioned_participant import ProvisionedParticipant
from quantum_network_backend import QuantumNetworkBackend
from provisioned_validation import validate_report, cross_validate
from run_provisioned import ProvisionedManager
from run_hybrid import HybridValidationFailure, session_metrics
from p5b_fixed import FixedParticipant
from provisioned_p5b_timing import variant_timing


class ProvisionedNoDqCore(NativeNoDqCore):
    def __init__(self, config, capture_states=True):
        super().__init__(config, capture_states)
        self.pending_ready = []
        # Node.qmemory must be a real QuantumMemory, not the logical position view.
        # The first replica is qmemory; the other physical replicas are child components.
        view = self.devices['R']
        self.devices['R'] = self.r_devices[0]
        self.quantum_network = QuantumNetworkBackend(self)
        self.devices['R'] = view
        for replica in self.r_devices[1:]:
            self.quantum_network.nodes['R'].add_subcomponent(replica)

    def snapshot(self):
        value = super().snapshot()
        if self.pending_ready:
            raise RuntimeError('resource notification not delivered')
        value['quantum_network'] = self.quantum_network.snapshot()
        value['quantum_network']['nodes']['R']['execution_replicas'] = [
            dict(name=device.name, positions=device.num_positions) for device in self.r_devices]
        return value


class ProvisionedFixedParticipant(FixedParticipant):
    """Virtual result transport with actual native resource-ready callbacks."""
    def __init__(self, config, roots, delay):
        self.now_ns=0; self.future=[]; self.sequence=0; self.delay=delay
        self.started=set(); self.ready=set(); self.issued=set()
        for session in config['sessions']:
            sid=session['session_id']
            self.schedule(session['session_start_ns'], 'SESSION_START', sid, roots[sid])

    def advance(self, at):
        rows=[]
        while self.next_time == at:
            batch=super().advance(at)
            rows.extend(batch)
            for row in batch:
                sid=row['session_id']; kind=row['event_type']
                if kind == 'SESSION_START': self.started.add(sid)
                elif kind == 'FIXED_RESOURCES_READY': self.ready.add(sid)
                else: continue
                if sid in self.started and sid in self.ready and sid not in self.issued:
                    self.issued.add(sid)
                    self.schedule(at, 'BSM_REQUEST', sid, row['event_id'])
        self.now_ns=at
        return rows

    def notify_ready(self, at, ready):
        for row in ready:
            sid=row['session_id']
            if sid in self.ready:
                raise RuntimeError('duplicate fixed resource readiness')
            self.schedule(at, 'FIXED_RESOURCES_READY', sid, row['cause'])


class CountedProvisionedParticipant(ProvisionedParticipant):
    def __init__(self, *args):
        self.tx_lines=self.rx_lines=self.tx_bytes=self.rx_bytes=0
        super().__init__(*args)

    def send(self, line):
        super().send(line)
        self.tx_lines+=1; self.tx_bytes+=len((line+'\n').encode('ascii'))

    def read(self):
        line=self.stream.readline(4098)
        if not line or not line.endswith(b'\n') or len(line)>4097:
            raise RuntimeError('invalid/disconnected IPC stream')
        self.rx_lines+=1; self.rx_bytes+=len(line)
        return line.decode('ascii').split()


def execute(raw, model='Full-Sync', references=None, delays=None,
            participant_class=ProvisionedParticipant, require_no_b_wait=True):
    manager=ProvisionedManager(raw); config=manager.config
    expected=variant_timing(config, model, delays)
    if require_no_b_wait and any(s['correction_wait_ns'] for s in expected['sessions'].values()):
        raise ValueError(model+': workload violates B wait=0')
    t0=time.perf_counter()
    core=(ProvisionedNoDqCore if model=='No-Dq-R' else ProvisionedCore)(config)
    for slot, session in enumerate(config['sessions']):
        core.adapters[session['session_id']]=(ProvisionedSwapAdapter if session['protocol']=='swap'
            else ProvisionedTeleportAdapter)(core, session, slot)
    t1=time.perf_counter(); network=model!='Fixed-Dc'
    participant=(participant_class(manager.binary, config, core.roots) if network else
                 ProvisionedFixedParticipant(config, core.roots, delays['result_ns']))
    federation=ProvisionedFederation(core, participant); t2=time.perf_counter()
    try:
        snapshot=federation.run(); t3=time.perf_counter()
        if network: participant.finish()
    finally:
        if network: participant.close()
    t4=time.perf_counter()
    report=dict(schema_version=4, milestone='Quantum-Channel-Provisioning', architecture='provisioned-native-v4',
        model=model, config=config, execution_core='ProvisionedCore(NativeExecutionCore)' if model!='No-Dq-R' else 'ProvisionedNoDqCore',
        federation='ProvisionedFederation(NativeHybridFederation)', time_unit='ns', snapshot=snapshot,
        events=core.events, bridge_steps=federation.steps, native_instructions=core.instruction_events,
        instruction_state_recording=True)
    if network:
        report.update(nodes=participant.nodes, ns3_binary=str(manager.binary), ns3_time_ns=participant.now_ns,
                      ns3_events=federation.rows, q2ns_status=participant.q2ns_status)
    else:
        for event in core.events:
            if event['source']=='ns3': event['source']='fixed-delay'
        report.update(fixed_delays=delays, transport='constant result-delay events; actual native quantum delivery; no ns-3 packet network')
    try:
        report['validation']=validate_report(report, expected, network)
        report['cross_validation']=cross_validate(report, references)
        report['metrics']=session_metrics(report)
        for row in report['metrics']['sessions']:
            pred=expected['sessions'][str(row['session_id'])]
            row.update(resource_ready_ns=pred['resource_ready_ns'], eligible_ns=pred['eligible_ns'],
                       resource_wait_ns=pred['resource_wait_ns'])
        report['batch_completion_ns']=max(row['completion_ns'] for row in report['metrics']['sessions'])
    except (ValueError, RuntimeError, KeyError) as error:
        report['validation']=dict(passed=False, error=str(error))
        raise HybridValidationFailure(report, error) from error
    t5=time.perf_counter()
    return report, dict(core_initialization_seconds=t1-t0, participant_startup_seconds=t2-t1,
        federation_seconds=t3-t2, participant_finish_seconds=t4-t3, simulation_seconds=t4-t0,
        offline_validation_seconds=t5-t4, simulation_seconds_per_transaction=(t4-t0)/len(config['sessions']),
        federation_seconds_per_transaction=(t3-t2)/len(config['sessions'])), participant


def run_model(config, model, cache, delays=None):
    return execute(config, model, cache, delays)[0]
