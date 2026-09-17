"""P5-B의 실제 재실행, calibration 분리, 상태/판정/통계 계약을 검증한다."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

MODULE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(MODULE/'experiments'),str(MODULE/'python')]
from run_q2ns import Q2nsFederationManager
from run_p5b import evaluate, run_model, ReferenceCache, verify_frozen
from p5b_nodq import NoDqManager, Q2nsValidationFailure
from p5b_nodq_validation import validate_report
from p5b_fixed import run_fixed
from p5b_timing import decoupled, fixed_timing
from p5b_workload import validate_plan, workload, workload_digest, rounded_mean
from p5b_analysis import model_rows, compare, estimate


class P5BTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.cfg=json.loads((MODULE/'scenarios/p5-joint-result.json').read_text())
        cls.cfg['correction_duration_ns']=50000
        cls.cfg['expected_queueing']={k:'any' for k in ('command','result','R')}
        cls.full=Q2nsFederationManager(cls.cfg).run()
        cls.nodq=NoDqManager(cls.cfg).run()
        cls.delays=dict(command_ns=110080,result_ns=288000)
        cls.fixed=run_fixed(cls.cfg,cls.delays)
        cls.plan=json.loads((MODULE/'scenarios/p5b-pilot.json').read_text())

    def test_01_nodq_real_network_reexecution(self):
        full=self.full['metrics']['sessions'][1]; no=self.nodq['metrics']['sessions'][1]
        self.assertEqual(full['quantum_wait_ns'],800000)
        self.assertEqual(no['quantum_wait_ns'],0)
        self.assertEqual(full['result_queue_ns'],713920)
        self.assertEqual(no['result_queue_ns'],1920)
        self.assertNotEqual(no['completion_ns'],full['completion_ns']-full['quantum_wait_ns'])
        self.assertEqual(self.nodq['q2ns_status']['corrections_applied'],4)
        self.assertTrue(self.nodq['q2ns_validation']['passed'])

    def test_02_nodq_keeps_duration_and_ownership(self):
        for s in self.nodq['snapshot']['sessions'].values():
            b=s['requests']['1']
            self.assertEqual(b['start_ns'],b['arrival_ns'])
            self.assertEqual(b['completion_ns']-b['start_ns'],1600000)
            self.assertEqual(s['correction']['completion_ns']-s['correction']['start_ns'],50000)
        self.assertEqual(self.nodq['q2ns_status']['native_state_count'],0)
        self.assertEqual(self.nodq['snapshot']['R_execution_capacity'],4)

    def test_03_fixed_reruns_fifo_and_native_aging(self):
        self.assertEqual([r['quantum_wait_ns'] for r in self.fixed['metrics']['sessions']],[0,800000,1600000,2400000])
        shifted=run_fixed(self.cfg,dict(command_ns=310080,result_ns=288000))
        for a,b in zip(self.fixed['metrics']['sessions'],shifted['metrics']['sessions']):
            self.assertEqual(b['bsm_start_ns']-a['bsm_start_ns'],200000)
        self.assertNotEqual(self.fixed['snapshot']['sessions']['1']['ab_pair']['density_matrix'],
                            shifted['snapshot']['sessions']['1']['ab_pair']['density_matrix'])
        self.assertTrue(shifted['cross_validation']['passed'])

    def test_04_nodq_packet_and_resource_mutations_fail(self):
        for defect in ('packet_time','resource','bits','clock'):
            r=copy.deepcopy(self.nodq)
            if defect=='packet_time': next(e for e in r['packet_events'] if e['event_type']=='PHY_RX')['time_ns']+=1
            elif defect=='resource': r['snapshot']['sessions']['1']['resources']['1']['state']='AVAILABLE'
            elif defect=='bits': r['snapshot']['sessions']['1']['correction']['measurement_bits'][0]^=1
            else:r['snapshot']['netsquid_time_ns']-=1
            with self.subTest(defect=defect),self.assertRaises(RuntimeError):validate_report(r)

    def test_05_all_branches_under_unbounded_r(self):
        refs={sid:c['reference'] for sid,c in self.nodq['cross_validation']['sessions'].items()}
        bits=set()
        for seed in range(8):
            cfg=copy.deepcopy(self.cfg);cfg['seed']=seed
            r=NoDqManager(cfg).run(refs)
            bits.update(tuple(s['correction']['measurement_bits']) for s in r['snapshot']['sessions'].values())
        self.assertEqual(bits,{(0,0),(0,1),(1,0),(1,1)})

    def test_06_noise_off_restores_bell_in_both_baselines(self):
        cfg=copy.deepcopy(self.cfg);cfg['memory_noise']=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0)
        for r in (NoDqManager(cfg).run(),run_fixed(cfg,self.delays)):
            for s in r['snapshot']['sessions'].values():self.assertAlmostEqual(s['ab_pair']['fidelity'],1,places=12)

    def test_07_b_wait_rejected_in_every_execution_model(self):
        cfg=copy.deepcopy(self.cfg);cfg['correction_duration_ns']=500000
        with self.assertRaisesRegex(ValueError,'B wait'):run_model(cfg,'No-Dq-R',ReferenceCache())
        with self.assertRaises(Q2nsValidationFailure):NoDqManager(cfg).run()
        cfg['bsm_duration_ns']=10000
        cfg['sessions']=[dict(session_id=i+1,command_time_ns=1000000) for i in range(2)]
        for name in ('Full-Sync','No-Dq-R','Fixed-Dc'):
            with self.subTest(model=name),self.assertRaisesRegex(ValueError,'B wait'):
                run_model(cfg,name,ReferenceCache(),self.delays)
        with self.assertRaisesRegex(RuntimeError,'B correction'):run_fixed(cfg,self.delays)

    def test_08_calibration_test_leakage_and_invalid_plan(self):
        for mutate in (lambda p:p.update(test_traffic_seeds=[100]),lambda p:p.update(quantum_seeds=[7,7]),
                       lambda p:p.update(classical_loads=[1.0]),lambda p:p.update(fidelity_min=-1)):
            p=copy.deepcopy(self.plan);mutate(p)
            with self.assertRaises(ValueError):validate_plan(p)
        self.assertEqual(rounded_mean([1,2]),2)
        self.assertEqual(rounded_mean([1,1,2]),1)

    def test_09_traffic_and_quantum_seed_separation(self):
        a=workload(self.plan,.35,800000,200,7);b=workload(self.plan,.35,800000,200,11)
        c=workload(self.plan,.35,800000,201,7)
        self.assertEqual(workload_digest(a),workload_digest(b))
        self.assertNotEqual(workload_digest(a),workload_digest(c))
        self.assertEqual(a,workload(self.plan,.35,800000,200,7))

    def test_10_decoupled_is_latency_only_composition(self):
        rows=decoupled(self.nodq['config'],self.nodq)
        for d,c in zip(rows,self.nodq['metrics']['sessions']):
            self.assertEqual(d['transaction_latency_ns'],c['transaction_latency_ns']+d['quantum_wait_ns'])
            self.assertIsNone(d['usable_fidelity'])
        self.assertEqual(rows[1]['quantum_wait_ns'],800000)
        self.assertNotEqual(rows[1]['completion_ns'],self.full['metrics']['sessions'][1]['completion_ns'])

    def test_11_success_probability_uses_branch_thresholds(self):
        report=copy.deepcopy(self.fixed)
        for c in report['cross_validation']['sessions'].values():
            c['reference']['ensemble']['fidelity']=.5
            for i,b in enumerate(c['reference']['branches'].values()):
                b['probability']=.25;b['usable']['fidelity']=.9 if i<2 else .1
        rows=model_rows(report,.4,10**9)
        self.assertTrue(all(r['success_probability']==.5 and r['expected_fidelity']==.5 for r in rows))
        self.assertTrue(all(r['success_probability']==0 for r in model_rows(report,.4,1)))

    def test_12_signed_errors_and_feasibility_directions(self):
        full=[dict(session_id=1,transaction_latency_ns=100,usable_fidelity=.3,expected_fidelity=.3,
                   success_probability=0,feasible=False,deadline_ok=False)]
        baseline=[dict(session_id=1,transaction_latency_ns=80,usable_fidelity=.8,expected_fidelity=.8,
                       success_probability=1,feasible=True)]
        r=compare(full,baseline,{},90)[0]
        self.assertEqual(r['delta_latency_ns'],-20);self.assertEqual(r['false_feasible'],1)
        self.assertEqual(r['false_infeasible'],0);self.assertEqual(r['false_deadline_feasible'],1)

    def test_13_bootstrap_clusters_workloads_not_sessions(self):
        rows=[dict(traffic_seed=t,x=x) for t,x in ((1,1),(1,3),(2,6),(2,10))]
        a=estimate(rows,'x',1000);b=estimate(rows*5,'x',1000)
        self.assertEqual(a,b);self.assertEqual(a['mean'],5);self.assertEqual(a['traffic_clusters'],2)
        self.assertIsNone(estimate(rows[:2],'x',100)['ci95_cluster_bootstrap'])

    def test_14_reference_cache_rejects_wrong_timing(self):
        refs={sid:c['reference'] for sid,c in self.nodq['cross_validation']['sessions'].items()}
        cfg=copy.deepcopy(self.cfg);cfg['bsm_duration_ns']=1600001
        with self.assertRaises(Q2nsValidationFailure):NoDqManager(cfg).run(refs)
        with self.assertRaises(RuntimeError):run_fixed(self.cfg,dict(command_ns=110081,result_ns=288000),refs)

    def test_15_small_evaluation_artifacts(self):
        p=copy.deepcopy(self.plan);p.update(classical_loads=[0.0],request_intervals_ns=[2000000],sessions=1,
            calibration_traffic_seeds=[100],test_traffic_seeds=[200,201],quantum_seeds=[7])
        with tempfile.TemporaryDirectory() as folder:
            r=evaluate(p,folder)
            self.assertEqual(r['paired_cases'],2);self.assertEqual(r['execution_runs'],6)
            errors=json.loads((Path(folder)/'errors.json').read_text())
            self.assertTrue(all(e['delta_latency_ns']==0 for e in errors))
            self.assertTrue(all(e['delta_fidelity'] is None for e in errors if e['model']=='Decoupled'))
            self.assertTrue((Path(folder)/'calibration.json').exists())
            with self.assertRaises(ValueError):evaluate(p,folder)

    def test_16_core_and_nested_q2ns_sources_frozen(self):
        self.assertTrue(verify_frozen())


if __name__=='__main__':unittest.main()
