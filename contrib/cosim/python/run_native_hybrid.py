#!/usr/bin/env python3
"""Q2NS/ns-3 + NetSquid-native timed instruction chains, preserving the atomic runner."""
import argparse
import json
from pathlib import Path
from run_hybrid import HybridManager, HybridParticipant, HybridValidationFailure, session_metrics
from native_config import normalize_config
from native_core import NativeExecutionCore, NativeHybridFederation
from native_adapters import NativeSwapAdapter, NativeTeleportAdapter
from native_validation import validate_report, cross_validate


class NativeHybridManager:
    def __init__(self, scenario, binary=None):
        self.config=normalize_config(scenario)
        atomic={k:v for k,v in self.config.items() if k!='native_instructions'}
        self.binary=HybridManager(atomic,binary).binary

    def run(self,references=None,*,capture_states=True):
        core=NativeExecutionCore(self.config,capture_states)
        for slot,s in enumerate(self.config['sessions']):
            adapter=(NativeSwapAdapter if s['protocol']=='swap' else NativeTeleportAdapter)(core,s,slot)
            core.adapters[s['session_id']]=adapter
        participant=HybridParticipant(self.binary,self.config,core.roots)
        federation=NativeHybridFederation(core,participant)
        try:
            snapshot=federation.run();participant.finish()
        finally:participant.close()
        report=dict(schema_version=3,milestone='Native-Timed-Hybrid',architecture='native-timed-v3',model='Full-Sync',
            nodes=participant.nodes,config=self.config,execution_core='NativeExecutionCore(HybridExecutionCore)',
            federation='NativeHybridFederation',ns3_binary=str(self.binary),ns3_time_ns=participant.now_ns,time_unit='ns',
            snapshot=snapshot,events=core.events,ns3_events=federation.rows,bridge_steps=federation.steps,
            native_instructions=core.instruction_events,instruction_state_recording=capture_states,
            q2ns_status=participant.q2ns_status)
        try:
            report['validation']=validate_report(report)
            report['cross_validation']=cross_validate(report,references)
            report['metrics']=session_metrics(report)
            report['batch_completion_ns']=max(r['completion_ns'] for r in report['metrics']['sessions'])
        except (ValueError,RuntimeError,KeyError) as error:
            report['validation']=dict(passed=False,error=str(error))
            raise HybridValidationFailure(report,error) from error
        return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('scenario',type=Path);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--ns3-binary',type=Path);args=parser.parse_args()
    failure=None
    try:report=NativeHybridManager(json.loads(args.scenario.read_text()),args.ns3_binary).run()
    except HybridValidationFailure as error:report=error.report;failure=error
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')
    if failure:raise failure
    print('Native timed: {} sessions; state error {:.3g}; PASS'.format(len(report['config']['sessions']),
        report['cross_validation']['max_density_matrix_error']))


if __name__=='__main__':main()
