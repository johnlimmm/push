#!/usr/bin/env python3
"""실제 Q2NS SwapApp/TeleportationApp을 같은 federation/core에서 실행한다."""
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys

from run_p0 import NS3_DIR
from run_q2ns import Q2nsParticipant
from hybrid_config import normalize_config
from hybrid_core import HybridExecutionCore, HybridFederation
from hybrid_adapters import SwapAdapter, TeleportAdapter


class HybridParticipant(Q2nsParticipant):
    """기존 packet 계측/소켓 lifecycle을 재사용하며 session protocol을 명시한다."""
    def __init__(self,binary,config,roots):
        self.process=None;self.stream=None
        self.sock,peer=socket.socketpair(socket.AF_UNIX,socket.SOCK_STREAM)
        self.sock.settimeout(15)
        try:
            self.process=subprocess.Popen([str(binary),'--bridgeFd='+str(peer.fileno())],
                                          pass_fds=(peer.fileno(),),stdout=subprocess.DEVNULL)
        except BaseException:
            self.sock.close();raise
        finally: peer.close()
        self.stream=self.sock.makefile('rwb',buffering=0);self.source_sequence=0
        try:
            if self.read()!=['HELLO','COSIM_HYBRID','2']: raise RuntimeError('invalid hybrid handshake')
            c=config
            self.send('CONFIG '+' '.join(map(str,[c['result_link']['rate_bps'],c['result_link']['delay_ns'],
                c['result_payload_bytes'],c['queue_packets'],len(c['sessions'])])))
            for s in c['sessions']:
                self.send('SESSION {} {} {} {}'.format(s['session_id'],s['session_start_ns'],roots[s['session_id']],
                                                      int(s['protocol']=='teleport')))
            for side in ('result',):
                f=c['background'][side]
                self.send('FLOW {} {} {} {} {}'.format(side,f['start_ns'],f['interval_ns'],f['count'],f['payload_bytes']))
            topology=self.read()
            if topology!=['NODES','3','0','1','2']: raise RuntimeError('invalid native topology')
            self.nodes=dict(zip(('A','R','B'),map(int,topology[2:])))
            row=self.read()
            if len(row)!=3 or row[:2]!=['READY','0']: raise RuntimeError('invalid READY')
            self.now_ns=0;self.next_time=self._time(row[2])
        except BaseException:
            self.close();raise

    def inject(self,at,completed):
        if not completed:return
        bsm=[r for r in completed if r['operation']=='BSM']
        correction=[r for r in completed if r['operation']=='CORRECTION']
        self.send('INJECT {} {} {}'.format(at,len(bsm),len(correction)))
        for r in bsm:
            self.send('RESULT {} 1 {} {} {}'.format(r['session_id'],*r['measurement_bits'],r['cause']))
        for r in correction: self.send('CORRECT {} {}'.format(r['session_id'],r['cause']))
        row=self.read()
        if len(row)!=2 or row[0]!='INJECTED': raise RuntimeError('invalid INJECTED')
        self.next_time=self._time(row[1])


class HybridValidationFailure(RuntimeError):
    def __init__(self,report,error):
        super().__init__(str(error));self.report=report


class HybridManager:
    def __init__(self,scenario,binary=None,*,no_dq=False):
        self.no_dq=no_dq
        self.config=normalize_config(scenario)
        if binary is None:
            found=[p for p in (NS3_DIR/'build/contrib/cosim').rglob('*cosim-hybrid*') if p.is_file() and os.access(str(p),os.X_OK)]
            if len(found)!=1: raise RuntimeError('Build ./ns3 build cosim-hybrid')
            binary=found[0]
        self.binary=Path(binary)

    def run(self,references=None):
        core=HybridExecutionCore(self.config, r_capacity=len(self.config['sessions']) if self.no_dq else 1)
        for slot,s in enumerate(self.config['sessions']):
            adapter=(SwapAdapter if s['protocol']=='swap' else TeleportAdapter)(core,s,slot)
            core.adapters[s['session_id']]=adapter
        core.drain()
        p=HybridParticipant(self.binary,self.config,core.roots)
        federation=HybridFederation(core,p)
        try:
            snapshot=federation.run();p.finish()
        finally:p.close()
        report=dict(schema_version=2,milestone='Hybrid-Direct-Start',architecture='direct-session-start-v2',
            model='No-Dq-R' if self.no_dq else 'Full-Sync',nodes=p.nodes,config=self.config,
            execution_core='HybridExecutionCore',federation='HybridFederation',ns3_binary=str(self.binary),
            ns3_time_ns=p.now_ns,time_unit='ns',snapshot=snapshot,events=core.events,
            ns3_events=federation.rows,bridge_steps=federation.steps,q2ns_status=p.q2ns_status)
        from hybrid_validation import validate_report, cross_validate
        try:
            report['validation']=validate_report(report)
            report['cross_validation']=cross_validate(report,references)
            report['metrics']=session_metrics(report)
            report['batch_completion_ns']=max(r['completion_ns'] for r in report['metrics']['sessions'])
        except (ValueError,RuntimeError,KeyError) as error:
            report['validation']=dict(passed=False,error=str(error))
            raise HybridValidationFailure(report,error) from error
        return report


def session_metrics(report):
    """Latency starts at the local Q2NS session activation, before the R FIFO."""
    rows=[]
    packets={p['session_id']:p for p in report['validation']['expected_timing']['packets'] if p['session_id']}
    for s in report['config']['sessions']:
        sid=s['session_id']
        req={r['operation']:r for r in report['snapshot']['requests'] if r['session_id']==sid}
        b,c=req['BSM'],req['CORRECTION'];p=packets[sid]
        rows.append(dict(session_id=sid,session_start_ns=s['session_start_ns'],
            quantum_wait_ns=b['start_ns']-b['arrival_ns'],correction_wait_ns=c['start_ns']-c['arrival_ns'],
            bsm_start_ns=b['start_ns'],bsm_completion_ns=b['completion_ns'],
            result_delay_ns=c['arrival_ns']-b['completion_ns'],result_queue_ns=p['queue_wait_ns'],
            correction_start_ns=c['start_ns'],completion_ns=c['completion_ns'],
            transaction_latency_ns=c['completion_ns']-s['session_start_ns'],
            usable_fidelity=report['snapshot']['sessions'][str(sid)]['checkpoints']['usable']['fidelity']))
    return dict(sessions=rows)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario',type=Path);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--ns3-binary',type=Path);args=parser.parse_args()
    error=None
    try:report=HybridManager(json.loads(args.scenario.read_text()),args.ns3_binary).run()
    except HybridValidationFailure as failure:report=failure.report;error=failure
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    if error:raise error
    print('Hybrid {}: {} sessions; state error {:.3g}; PASS'.format(report['config']['name'],
        len(report['snapshot']['sessions']),report['cross_validation']['max_density_matrix_error']))

if __name__=='__main__': main()
