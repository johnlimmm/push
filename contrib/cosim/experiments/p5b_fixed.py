"""Fixed R→B delay with the same local starts, HybridExecutionCore and native aging."""
import heapq
from hybrid_config import normalize_config
from hybrid_core import HybridExecutionCore, HybridFederation
from hybrid_adapters import SwapAdapter, TeleportAdapter
from hybrid_validation import validate_report, cross_validate
from run_hybrid import session_metrics
from p5b_timing import fixed_timing


class FixedParticipant:
    """Virtual result delivery only; explicitly not an ns-3/Q2NS packet simulation."""
    def __init__(self,config,roots,delay):
        self.now_ns=0;self.future=[];self.sequence=0;self.delay=delay
        for s in config['sessions']:
            self.schedule(s['session_start_ns'],'BSM_REQUEST',s['session_id'],roots[s['session_id']])

    @property
    def next_time(self):return self.future[0][0] if self.future else None

    def schedule(self,at,kind,sid,cause,bits=None):
        sequence=self.sequence;self.sequence+=1
        heapq.heappush(self.future,(at,sequence,dict(event_id='fixed:'+str(sequence),time_ns=at,
            event_type=kind,session_id=sid,cause=cause,m1=None if bits is None else bits[0],
            m2=None if bits is None else bits[1])))

    def advance(self,at):
        self.now_ns=at;rows=[]
        while self.future and self.future[0][0]==at:rows.append(heapq.heappop(self.future)[2])
        return rows

    def inject(self,at,completed):
        for r in completed:
            if r['operation']=='BSM':self.schedule(at+self.delay,'CORRECTION_REQUEST',r['session_id'],r['cause'],r['measurement_bits'])


def run_fixed(raw,delays,references=None):
    config=normalize_config(raw);expected=fixed_timing(config,delays)
    if any(t['correction_wait_ns'] for t in expected['sessions'].values()):
        raise RuntimeError('Fixed-Dc B correction waiting must be zero')
    core=HybridExecutionCore(config)
    for slot,s in enumerate(config['sessions']):
        core.adapters[s['session_id']]=(SwapAdapter if s['protocol']=='swap' else TeleportAdapter)(core,s,slot)
    core.drain();participant=FixedParticipant(config,core.roots,delays['result_ns'])
    federation=HybridFederation(core,participant);snapshot=federation.run()
    # The common core imports participant rows as ns3; label virtual events honestly.
    for event in core.events:
        if event['source']=='ns3':event['source']='fixed-delay'
    report=dict(schema_version=2,architecture='direct-session-start-v2',model='Fixed-Dc',config=config,
        snapshot=snapshot,events=core.events,bridge_steps=federation.steps,fixed_delays=delays,
        execution_core='HybridExecutionCore',federation='HybridFederation',
        transport='constant result-delay events; no ns-3 packet network')
    report['validation']=validate_report(report,expected,network=False)
    report['metrics']=session_metrics(report)
    report['batch_completion_ns']=expected['batch_completion_ns']
    report['cross_validation']=cross_validate(report,references)
    return report
