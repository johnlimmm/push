"""Native internal events, mixed resource contention and independent circuit states."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest
import numpy as np
import netsquid as ns
import pydynaa

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from run_native_hybrid import NativeHybridManager
from run_hybrid import HybridManager, HybridValidationFailure, HybridParticipant
from native_config import normalize_config
from native_core import NativeExecutionCore, NativeHybridFederation
from native_adapters import NativeTeleportAdapter
from native_validation import validate_report, cross_validate
from hybrid_adapters import STATES

OUT=MODULE/'results/native-timed'
def scenario(name):return json.loads((MODULE/'scenarios'/(name+'.json')).read_text())
def save(name,data):
    OUT.mkdir(exist_ok=True,parents=True)
    (OUT/(name+'.json')).write_text(json.dumps(data,indent=2,sort_keys=True,allow_nan=False)+'\n')
def matrix(cp):
    d=cp['density_matrix'];return np.array(d['real'])+1j*np.array(d['imag'])
def final(report,sid='1'):return report['snapshot']['sessions'][sid]['checkpoints']['usable']


class NativeHybridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cache={}
        cls.tele=NativeHybridManager(scenario('hybrid-teleport')).run(cls.cache)
        cls.mixed=NativeHybridManager(scenario('hybrid-mixed')).run(cls.cache)
        save('teleport',cls.tele);save('mixed',cls.mixed)

    def test_01_actual_native_instruction_chain(self):
        rows=self.tele['native_instructions']
        self.assertEqual([r['instruction'] for r in rows[:4]],['CNOT','H','MEASURE_0','MEASURE_1'])
        self.assertEqual([r['completion_ns'] for r in rows[:4]],[1600000,1800000,2200000,2600000])
        for op in ('BSM','CORRECTION'):
            row=next(e for e in self.tele['events'] if e['event_type']==op+'_COMPLETE')
            self.assertEqual(row['completion_source'],'netsquid_program_done')
        self.assertEqual(self.tele['ns3_time_ns'],self.tele['snapshot']['netsquid_time_ns'])

    def test_02_noiseless_states_all_four_branches(self):
        config=dict(memory_noise=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0),
            sessions=[dict(session_id=i+1,protocol='teleport',input_state=state,session_start_ns=0)
                      for i,state in enumerate(STATES)])
        branches={state:set() for state in STATES};maximum=0
        for seed in range(32):
            config['seed']=seed;report=NativeHybridManager(config).run(self.cache)
            for s in report['snapshot']['sessions'].values():
                branches[s['input_state']].add(''.join(map(str,s['measurement_bits'])))
                self.assertAlmostEqual(s['checkpoints']['usable']['fidelity'],1.,places=12)
            maximum=max(maximum,report['cross_validation']['max_density_matrix_error'])
        for state,seen in branches.items():self.assertEqual(seen,{'00','01','10','11'},state)
        save('branch-coverage',dict(passed=True,seeds=32,transactions=160,
            branches={k:sorted(v) for k,v in branches.items()},max_density_matrix_error=maximum))

    def test_03_mixed_shared_fifo_and_native_result(self):
        requests=[r for r in self.mixed['snapshot']['requests'] if r['operation']=='BSM']
        self.assertEqual([r['protocol'] for r in requests],['swap','teleport','swap','teleport'])
        self.assertEqual([r['start_ns']-r['arrival_ns'] for r in requests],[0,1600000,2400000,4000000])
        for r in requests:
            tx=next(e for e in self.mixed['ns3_events'] if e['session_id']==r['session_id'] and e['event_type']=='RESULT_TX')
            self.assertEqual(tx['time_ns'],r['completion_ns'])
        self.assertEqual(self.mixed['q2ns_status']['native_qubit_count'],0)

    def test_04_correction_and_packet_contention(self):
        config=scenario('hybrid-mixed');config['background']={}
        config['native_instructions']=dict(cnot_ns=2000,h_ns=2000,measure_ns=3000)
        report=NativeHybridManager(config).run(self.cache)
        self.assertTrue(any(r['start_ns']>r['arrival_ns'] for r in report['snapshot']['requests'] if r['operation']=='CORRECTION'))
        self.assertTrue(any(p['queue_wait_ns']>0 for p in report['validation']['expected_timing']['packets'] if p['session_id']))
        save('mixed-fast-bsm',report)

    def test_05_same_duration_atomic_timing_but_different_noisy_state(self):
        config=scenario('hybrid-teleport');atomic=HybridManager(config).run()
        a=atomic['snapshot']['requests'];b=self.tele['snapshot']['requests']
        for left,right in zip(a,b):
            for key in ('arrival_ns','start_ns','completion_ns'):self.assertEqual(left[key],right[key])
        # Compare branch-weighted output, not seed-paired branches.
        def average(report,native):
            branches=report['cross_validation']['sessions']['1']['reference']['branches']
            return sum(v['probability']*matrix(v['checkpoints']['usable'] if native else v['usable'])
                       for v in branches.values() if v['probability']>0)
        error=float(np.max(np.abs(average(atomic,False)-average(self.tele,True))))
        self.assertGreater(error,1e-5)
        save('atomic-comparison',dict(timing_equal=True,branch_weighted_density_matrix_difference=error,
                                      explanation='Different noise/gate ordering; not an atomic regression failure'))

    def test_06_gate_partition_changes_state_at_equal_completion(self):
        config=scenario('hybrid-teleport')
        config['native_instructions']=dict(cnot_ns=200000,h_ns=200000,measure_ns=600000)
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual(report['metrics'],dict(sessions=[dict(self.tele['metrics']['sessions'][0],
            usable_fidelity=report['metrics']['sessions'][0]['usable_fidelity'])]))
        self.assertGreater(np.max(np.abs(matrix(final(report))-matrix(final(self.tele)))),1e-6)
        save('different-gate-partition',report)

    def test_07_duration_changes_native_completion_and_packet_generation(self):
        config=scenario('hybrid-teleport');config['native_instructions']=dict(measure_ns=400001)
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual(report['metrics']['sessions'][0]['bsm_completion_ns'],2600002)
        self.assertEqual(report['batch_completion_ns'],self.tele['batch_completion_ns']+2)

    def test_08_result_delay_isolated_from_bsm(self):
        config=scenario('hybrid-teleport');config['result_link']=dict(rate_bps=10000000,delay_ns=5000000)
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual(report['native_instructions'][:4],self.tele['native_instructions'][:4])
        cp=report['snapshot']['sessions']['1']['checkpoints'];old=self.tele['snapshot']['sessions']['1']['checkpoints']
        self.assertEqual(cp['frame'],old['frame'])
        self.assertGreater(np.max(np.abs(matrix(cp['packet_arrival'])-matrix(old['packet_arrival']))),1e-6)
        save('delayed-result',report)

    def test_09_classical_inputs_at_gate_and_program_boundaries(self):
        config=dict(sessions=[dict(session_id=i+1,protocol='swap' if i%2 else 'teleport',session_start_ns=t)
                            for i,t in enumerate([0,600000,800000,1200000,1600000,1600001])])
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual([e['time_ns'] for e in report['ns3_events'] if e['event_type']=='SESSION_START'],
                         [0,600000,800000,1200000,1600000,1600001])
        self.assertEqual([r['start_ns'] for r in report['snapshot']['requests'] if r['operation']=='BSM'],
                         [0,1600000,3200000,4800000,6400000,8000000])
        save('boundary-arrivals',report)

    def test_10_same_time_requests_preserve_config_order(self):
        config=dict(sessions=[dict(session_id=sid,protocol=protocol,session_start_ns=0)
                            for sid,protocol in [(9,'swap'),(4,'teleport'),(2,'swap')]])
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual([r['session_id'] for r in report['snapshot']['requests'] if r['operation']=='BSM'],[9,4,2])

    def test_11_observation_does_not_change_quantum_evolution(self):
        report=NativeHybridManager(scenario('hybrid-mixed')).run(self.cache,capture_states=False)
        for a,b in zip(report['metrics']['sessions'],self.mixed['metrics']['sessions']):
            for key in a:
                if key=='usable_fidelity':self.assertAlmostEqual(a[key],b[key],places=12)
                else:self.assertEqual(a[key],b[key])
        for sid in report['snapshot']['sessions']:
            self.assertLess(np.max(np.abs(matrix(final(report,sid))-matrix(final(self.mixed,sid)))),1e-12)
        self.assertTrue(all(r['state'] is None for r in report['native_instructions']))
        save('without-state-probes',report)

    def test_12_corrupt_native_trace_and_state_rejected(self):
        for field in ('completion_ns','instruction','state','callback'):
            report=copy.deepcopy(self.tele)
            if field=='state':report['native_instructions'][0]['state']['density_matrix']['real'][0][0]+=.01
            elif field=='callback':next(e for e in report['events'] if e['event_type']=='BSM_COMPLETE')['completion_source']='predicted'
            elif field=='instruction':report['native_instructions'][0]['instruction']='H'
            else:report['native_instructions'][0]['completion_ns']+=1
            with self.subTest(field=field),self.assertRaises(RuntimeError):
                validate_report(report);cross_validate(report,self.cache)

    def test_13_invalid_durations_rejected(self):
        for value in (0,-1,1.5,True,2**53):
            with self.subTest(value=value),self.assertRaises(ValueError):
                NativeHybridManager(dict(native_instructions=dict(cnot_ns=value)))
        with self.assertRaises(ValueError):NativeHybridManager(dict(bsm_duration_ns=1))
        with self.assertRaises(ValueError):NativeHybridManager(dict(native_instructions=dict(unknown=1)))

    def test_14_post_transaction_background_drain(self):
        config=scenario('hybrid-teleport');config['background']=dict(result=dict(start_ns=20000000,count=2))
        report=NativeHybridManager(config).run(self.cache)
        self.assertEqual(final(report),final(self.tele))
        self.assertGreater(report['ns3_time_ns'],self.tele['ns3_time_ns'])

    def test_15_packet_drop_is_explicit_failure(self):
        config=scenario('hybrid-mixed');config['queue_packets']=1
        config['background']['result']=dict(start_ns=2590000,interval_ns=1000,count=5,payload_bytes=1000)
        with self.assertRaises(HybridValidationFailure) as caught:NativeHybridManager(config).run(self.cache)
        self.assertIn('packet drop',str(caught.exception))
        save('overflow-rejected',caught.exception.report)

    def test_16_atomic_parent_sources_unchanged(self):
        manifest=json.loads((MODULE/'baselines/native-timed-parent.json').read_text())
        for name,value in manifest['source_sha256'].items():
            if name in manifest['compatibility_fixes']:
                value=manifest['compatibility_fixes'][name]['current_sha256']
            self.assertEqual(hashlib.sha256((MODULE.parents[1]/name).read_bytes()).hexdigest(),value,name)

    def test_17_completion_requires_native_callback(self):
        core=NativeExecutionCore(normalize_config({}))
        with self.assertRaisesRegex(RuntimeError,'unsolicited'):core.program_done('R')
        with self.assertRaisesRegex(RuntimeError,'NativeHybridFederation'):core.advance(1)

    def test_18_extra_native_event_is_processed_between_classical_inputs(self):
        manager=NativeHybridManager(scenario('hybrid-teleport'));core=NativeExecutionCore(manager.config)
        adapter=NativeTeleportAdapter(core,manager.config['sessions'][0],0);core.adapters[1]=adapter
        participant=HybridParticipant(manager.binary,manager.config,core.roots)
        entity=pydynaa.Entity();kind=pydynaa.EventType('EXTRA_NATIVE','test native event')
        seen=[]
        entity._wait_once(pydynaa.EventHandler(lambda e:seen.append(int(ns.sim_time()))),entity=entity,event_type=kind)
        entity._schedule_at(1700000,kind)
        try:snapshot=NativeHybridFederation(core,participant).run();participant.finish()
        finally:participant.close()
        self.assertEqual(seen,[1700000]);self.assertEqual(snapshot['time_ns'],self.tele['snapshot']['time_ns'])

    def test_19_busy_instruction_storage_noise_is_not_omitted_or_doubled(self):
        from netsquid.components import QuantumProcessor
        from netsquid.components.models.qerrormodels import T1T2NoiseModel
        from netsquid.qubits import qubitapi as qapi
        from native_programs import IDLE_X, physical_instructions
        config=normalize_config(dict(memory_noise=dict(model='T1T2NoiseModel',T1_ns=1000000,T2_ns=500000)))
        ns.sim_reset();ns.set_qstate_formalism(ns.QFormalism.DM)
        p=QuantumProcessor('noise-test',num_positions=1,
            mem_noise_models=[T1T2NoiseModel(T1=1000000,T2=500000)],
            phys_instructions=physical_instructions(config['native_instructions'],config['memory_noise']))
        q=qapi.create_qubits(1)[0];qapi.operate(q,ns.X);p.put(q)
        ns.sim_run(end_time=100000)
        p.execute_instruction(IDLE_X,[0],physical=True)
        ns.sim_run(end_time=500000)
        # 100 us waiting + 250 us busy + 150 us waiting, each counted once.
        self.assertAlmostEqual(float(qapi.reduced_dm(p.peek(0))[1,1].real),np.exp(-.5),places=12)


if __name__=='__main__':unittest.main()
