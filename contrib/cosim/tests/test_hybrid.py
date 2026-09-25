"""공통 core 재사용, 기존 Swap 동등성, 입력 상태/분기, mixed FIFO 및 실패 검출."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from run_hybrid import HybridManager,HybridValidationFailure
from run_q2ns import Q2nsFederationManager
from hybrid_config import normalize_config
from hybrid_core import HybridExecutionCore
from hybrid_adapters import TeleportAdapter,STATES
from hybrid_validation import validate_report,cross_validate


def scenario(name):return json.loads((MODULE/'scenarios'/(name+'.json')).read_text())
def save(name,value):
    (MODULE/'results/direct-start').mkdir(exist_ok=True)
    (MODULE/'results/direct-start'/name).write_text(json.dumps(value,indent=2,sort_keys=True,allow_nan=False)+'\n')
def dm(state):
    d=state['density_matrix'];return np.array(d['real'])+1j*np.array(d['imag'])


class HybridIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tele=HybridManager(scenario('hybrid-teleport')).run()
        cls.mixed=HybridManager(scenario('hybrid-mixed')).run()
        save('hybrid-teleport.json',cls.tele);save('hybrid-mixed.json',cls.mixed)

    def test_01_swap_equivalence_at_matched_operation_arrivals(self):
        # Historical runner is independently rerun, with local starts set to its
        # command receipt times. Default direct starts deliberately occur earlier.
        for name in ('quantum-only','joint-result'):
            old=Q2nsFederationManager(scenario('p5-'+name)).run()
            cfg=scenario('hybrid-swap-'+name)
            for item in cfg['sessions']:
                item['session_start_ns']=next(m['bsm_start_ns']-m['quantum_wait_ns']
                    for m in old['metrics']['sessions'] if m['session_id']==item['session_id'])
            new=HybridManager(cfg).run()
            for sid,new_s in new['snapshot']['sessions'].items():
                old_s=old['snapshot']['sessions'][sid]
                self.assertEqual(new_s['measurement_bits'],old_s['correction']['measurement_bits'])
                own={r['operation']:r for r in new['snapshot']['requests'] if str(r['session_id'])==sid}
                bsm=old_s['requests'].get('1',old_s['requests'].get(1))
                for op,r in [('BSM',bsm),('CORRECTION',old_s['correction'])]:
                    for k in ('arrival_ns','start_ns','completion_ns'):self.assertEqual(own[op][k],r[k])
                for stage in ('bsm_start','bsm_end_inputs','frame','correction_start','usable'):
                    a,b=new_s['checkpoints'][stage],old_s['checkpoints'][stage]
                    pairs=[(a,b)] if 'density_matrix' in a else [(a[k],b[k]) for k in a]
                    for left,right in pairs:self.assertLessEqual(float(np.max(np.abs(dm(left)-dm(right)))),1e-12)
            # Result packets retain native payload and all on-wire timestamps.
            for p in new['validation']['expected_timing']['packets']:
                old_id=2*p['packet_id'] if p['session_id'] else p['packet_id']
                other=next(q for q in old['packets'] if q['packet_id']==old_id)
                for k in ('app_tx_ns','app_rx_ns','phy_tx_ns','phy_rx_ns','queue_wait_ns'):
                    self.assertEqual(p[k],other[k])
            save('hybrid-swap-matched-'+name+'.json',new)

    def test_02_each_input_all_four_branches_noiseless(self):
        cfg=dict(name='hybrid-branch-coverage',memory_noise=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0),
                 sessions=[dict(session_id=i+1,protocol='teleport',input_state=state,session_start_ns=1000000)
                           for i,state in enumerate(STATES)])
        seen={state:set() for state in STATES};cache={};maximum=0
        for seed in range(32):
            cfg['seed']=seed;run=HybridManager(cfg).run(cache)
            for s in run['snapshot']['sessions'].values():
                seen[s['input_state']].add(''.join(map(str,s['measurement_bits'])))
                self.assertAlmostEqual(s['checkpoints']['usable']['fidelity'],1,places=12)
            maximum=max(maximum,run['cross_validation']['max_density_matrix_error'])
        for state,branches in seen.items():self.assertEqual(branches,{'00','01','10','11'},state)
        save('hybrid-branch-coverage.json',dict(passed=True,seeds=32,transactions=160,
             branches={s:sorted(b) for s,b in seen.items()},max_density_matrix_error=maximum))

    def test_03_native_input_epr_and_post_bsm_aging(self):
        cp=self.tele['snapshot']['sessions']['1']['checkpoints']
        self.assertLess(cp['bsm_start']['input']['fidelity'],cp['initial']['input']['fidelity'])
        self.assertLess(cp['bsm_start']['epr']['fidelity'],cp['initial']['epr']['fidelity'])
        self.assertGreater(np.max(np.abs(dm(cp['frame'])-dm(cp['packet_arrival']))),1e-6)
        self.assertGreater(np.max(np.abs(dm(cp['packet_arrival'])-dm(cp['usable']))),1e-6)
        self.assertLessEqual(self.tele['cross_validation']['max_density_matrix_error'],1e-12)

    def test_04_shared_R_fifo_and_physical_positions(self):
        run=self.mixed;requests=[r for r in run['snapshot']['requests'] if r['operation']=='BSM']
        self.assertEqual([r['protocol'] for r in requests],['swap','teleport','swap','teleport'])
        self.assertEqual({r['processor_id'] for r in requests},{'R'})
        for previous,current in zip(requests,requests[1:]):
            self.assertEqual(previous['completion_ns'],current['start_ns'])
            self.assertGreater(current['start_ns']-current['arrival_ns'],0)
        positions=[tuple(p) for r in requests for p in r['targets']]
        self.assertEqual(len(positions),len(set(positions)))
        self.assertEqual(run['execution_core'],'HybridExecutionCore')
        self.assertEqual(run['q2ns_status']['native_qubit_count'],0)

    def test_05_protocol_delay_changes_other_protocol_wait(self):
        cfg=scenario('hybrid-mixed');cfg['sessions']=cfg['sessions'][1:]
        run=HybridManager(cfg).run()
        original=next(r for r in self.mixed['snapshot']['requests'] if r['session_id']==2 and r['operation']=='BSM')
        reduced=next(r for r in run['snapshot']['requests'] if r['session_id']==2 and r['operation']=='BSM')
        self.assertGreater(original['start_ns']-original['arrival_ns'],reduced['start_ns']-reduced['arrival_ns'])

    def test_06_native_payload_and_result_queueing(self):
        packets=self.mixed['validation']['expected_timing']['packets']
        results={p['session_id']:p for p in packets if p['link']=='result' and p['session_id']}
        self.assertEqual(results[1]['payload_bytes'],80)
        self.assertEqual(results[2]['payload_bytes'],2)
        self.assertTrue(any(p['queue_wait_ns']>0 for p in results.values()))
        cfg=scenario('hybrid-mixed');cfg['bsm_duration_ns']=10000
        cfg['background']={};run=HybridManager(cfg).run()
        # 짧은 BSM이면 서로 다른 앱의 결과 패킷 자체도 동일 link FIFO에서 경쟁한다.
        self.assertTrue(any(p['queue_wait_ns']>0 for p in run['validation']['expected_timing']['packets']
                            if p['link']=='result' and p['session_id']))
        self.assertTrue(any(r['start_ns']>r['arrival_ns'] for r in run['snapshot']['requests'] if r['operation']=='CORRECTION'))
        save('hybrid-mixed-fast-bsm.json',run)

    def test_07_result_delay_keeps_pre_bsm_state(self):
        cfg=scenario('hybrid-teleport');cfg['result_link']=dict(rate_bps=10000000,delay_ns=5000000)
        delayed=HybridManager(cfg).run()
        a=self.tele['snapshot']['sessions']['1']['checkpoints'];b=delayed['snapshot']['sessions']['1']['checkpoints']
        self.assertEqual(a['bsm_start'],b['bsm_start']);self.assertEqual(a['frame'],b['frame'])
        self.assertGreater(np.max(np.abs(dm(a['packet_arrival'])-dm(b['packet_arrival']))),1e-6)

    def test_08_same_timestamp_completion_before_arrival(self):
        cfg=dict(memory_noise=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0),sessions=[
            dict(session_id=9,protocol='teleport',input_state='+',session_start_ns=0),
            dict(session_id=4,protocol='swap',session_start_ns=1600000)])
        run=HybridManager(cfg).run()
        bsm=[r for r in run['snapshot']['requests'] if r['operation']=='BSM']
        self.assertEqual(bsm[0]['completion_ns'],bsm[1]['arrival_ns'])
        self.assertEqual(bsm[1]['start_ns'],bsm[1]['arrival_ns'])

    def test_09_traffic_drain_keeps_historical_output(self):
        cfg=scenario('hybrid-teleport');cfg['background']=dict(result=dict(start_ns=20000000,count=2))
        run=HybridManager(cfg).run()
        self.assertEqual(run['snapshot']['sessions'],self.tele['snapshot']['sessions'])
        self.assertGreater(run['ns3_time_ns'],self.tele['ns3_time_ns'])

    def test_10_corrupted_trace_state_and_ownership_rejected(self):
        for defect in ('clock','native','packet','causal','identity','resource'):
            run=copy.deepcopy(self.mixed)
            if defect=='clock':run['snapshot']['netsquid_time_ns']+=1
            elif defect=='native':run['q2ns_status']['native_state_count']=1
            elif defect=='packet':next(r for r in run['ns3_events'] if r['event_type']=='RESULT_RX')['m1']^=1
            elif defect=='causal':run['events'][-1]['caused_by_event_id']='absent'
            elif defect=='identity':run['snapshot']['requests'][0]['processor_id']='B'
            else:run['snapshot']['resources'][0]['owner']='other-session'
            with self.subTest(defect=defect),self.assertRaises(RuntimeError):validate_report(run)
        run=copy.deepcopy(self.tele)
        run['snapshot']['sessions']['1']['checkpoints']['usable']['density_matrix']['real'][0][0]+=0.01
        with self.assertRaises(RuntimeError):cross_validate(run)

    def test_11_invalid_configuration_rejected(self):
        for field,value in [('protocol','other'),('input_state','unknown'),('input_created_ns',1),('epr_created_ns',1)]:
            cfg=scenario('hybrid-teleport');cfg['sessions'][0][field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):HybridManager(cfg)
        cfg=scenario('hybrid-teleport');cfg['sessions']*=2
        with self.assertRaises(ValueError):HybridManager(cfg)

    def test_12_overflow_is_explicit_failure(self):
        cfg=scenario('hybrid-mixed');cfg['queue_packets']=1
        cfg['background']['result']=dict(start_ns=2590000,interval_ns=1000,count=5,payload_bytes=1000)
        with self.assertRaises(HybridValidationFailure) as caught:HybridManager(cfg).run()
        self.assertIn('packet drop',str(caught.exception))
        save('hybrid-overflow-rejected.json',caught.exception.report)

    def test_13_core_rejects_conflict_unsafe_advance_and_duplicates(self):
        cfg=normalize_config(scenario('hybrid-teleport'));core=HybridExecutionCore(cfg)
        adapter=TeleportAdapter(core,cfg['sessions'][0],0);core.adapters[1]=adapter;core.drain()
        row=dict(event_type='BSM_REQUEST',session_id=1,event_id=core.roots[1])
        self.assertTrue(adapter.receive(row));self.assertFalse(adapter.receive(row))
        with self.assertRaises(ValueError):core.submit(adapter,'OTHER','R',['input'],[('R',0)],1,core.roots[1])
        # handle이 달라도 같은 물리 position을 예약하려는 다른 session은 거부한다.
        other=type('OtherAdapter',(),dict(sid=2,protocol='swap'))()
        core.register(2,'alias','qubit',[('R',0)])
        with self.assertRaisesRegex(ValueError,'physical resource conflict'):
            core.submit(other,'BSM','R',['alias'],[('R',0)],1,core.roots[1])
        core.dispatch()
        with self.assertRaises(RuntimeError):core.advance(core.horizon()+1)
        with self.assertRaises(ValueError):core.submit(adapter,'OTHER','B',['input'],[('R',0)],1,core.roots[1])
        core.advance(core.horizon())
        with self.assertRaises(RuntimeError):core.advance(0)

    def test_14_frozen_sources_unchanged(self):
        # 동일한 원본 manifest 검사는 기존 P5-B suite에서도 수행한다.
        sys.path.insert(0,str(MODULE/'experiments'))
        from run_p5b import verify_frozen
        verify_frozen()

    def test_15_no_controller_and_no_command_configuration(self):
        for run in (self.tele,self.mixed):
            self.assertEqual(run['nodes'],dict(A=0,R=1,B=2))
            self.assertEqual(set(run['config']['background']),{'result'})
            self.assertFalse(any('command' in k for k in run['config']))
            self.assertFalse(any(r['event_type'].startswith('COMMAND_') for r in run['ns3_events']))
            for session in run['config']['sessions']:
                own=[r for r in run['ns3_events'] if r['session_id']==session['session_id']]
                for kind in ('SESSION_START','BSM_REQUEST'):
                    self.assertEqual([r['time_ns'] for r in own if r['event_type']==kind],[session['session_start_ns']])
            self.assertEqual(len([r for r in run['ns3_events'] if r['event_type']=='RESULT_TX']),len(run['config']['sessions']))
        for bad in (dict(command_link=dict(rate_bps=1,delay_ns=0)),dict(command_payload_bytes=96),
                    dict(background=dict(command={})),dict(sessions=[dict(session_id=1,command_time_ns=0)])):
            with self.subTest(bad=bad),self.assertRaises(ValueError):normalize_config(bad)

    def test_16_simultaneous_mixed_starts_use_input_order(self):
        cfg=scenario('hybrid-mixed');cfg['background']={}
        cfg['sessions']=cfg['sessions'][:2]
        cfg['sessions'][0]['session_id']=9;cfg['sessions'][1]['session_id']=3
        run=HybridManager(cfg).run()
        requests=[r for r in run['snapshot']['requests'] if r['operation']=='BSM']
        self.assertEqual([r['session_id'] for r in requests],[9,3])
        self.assertEqual([r['arrival_ns'] for r in requests],[1000000,1000000])
        self.assertEqual([r['start_ns'] for r in requests],[1000000,2600000])
        # Config order controls ties, not numeric session IDs or a hidden link.
        cfg['sessions'].reverse();reverse=HybridManager(cfg).run()
        self.assertEqual([r['session_id'] for r in reverse['snapshot']['requests'] if r['operation']=='BSM'],[3,9])

if __name__=='__main__':unittest.main()
