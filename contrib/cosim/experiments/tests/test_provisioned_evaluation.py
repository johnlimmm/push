"""Native execution variants, model comparability and production cost accounting."""
import copy
import json
from pathlib import Path
import sys
import unittest
import numpy as np

MODULE = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(MODULE/'experiments'), str(MODULE/'python')]
from provisioned_p5b_models import execute, model_rows
from provisioned_p5b_workload import workload, validate_plan
from provisioned_paper_scaling import run_once, timing_rows
from run_provisioned import ProvisionedManager
from provisioned_validation import validate_report, cross_validate
from provisioned_p5b_timing import decoupled


class ProvisionedEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((MODULE/'scenarios/provisioned-p5b-expanded.json').read_text())
        cls.cache = {}
        cls.config = workload(validate_plan(cls.plan), .7, 800000, 200, 7)
        cls.reports = {m:execute(cls.config,m,cls.cache,dict(result_ns=288000))[0]
                       for m in ('Full-Sync','No-Dq-R','Fixed-Dc')}

    def test_instrumentation_is_production_native(self):
        report, measurement = run_once(self.config,self.cache)
        self.assertEqual(report, ProvisionedManager(self.config).run(self.cache))
        self.assertEqual(measurement['counters']['native_instruction_completions'],24)
        self.assertAlmostEqual(measurement['simulation_seconds'],sum(measurement[k] for k in
            ('core_initialization_seconds','participant_startup_seconds','federation_seconds','participant_finish_seconds')))

    def test_no_dq_uses_concurrent_real_native_programs(self):
        report = self.reports['No-Dq-R']
        bsms = [r for r in report['snapshot']['requests'] if r['operation']=='BSM']
        self.assertTrue(all(r['start_ns']==r['arrival_ns'] for r in bsms))
        self.assertLess(bsms[1]['start_ns'],bsms[0]['completion_ns'])
        self.assertEqual(report['snapshot']['R_execution_capacity'],4)
        self.assertEqual(report['q2ns_status']['native_qubit_count'],0)
        for r in bsms:
            packet = next(e for e in report['ns3_events'] if e['event_type']=='RESULT_TX' and e['session_id']==r['session_id'])
            self.assertEqual(packet['time_ns'],r['completion_ns'])

    def test_all_models_share_instruction_and_noise_configuration(self):
        for model,report in self.reports.items():
            self.assertEqual(report['config']['native_instructions'],self.config['native_instructions'])
            self.assertEqual(report['config']['memory_noise'],self.config['memory_noise'])
            self.assertLess(report['cross_validation']['max_density_matrix_error'],1e-12)
            self.assertTrue(all(r['correction_wait_ns']==0 for r in report['metrics']['sessions']))
            rows=model_rows(report,.5,5000000)
            for row in rows:
                branches=report['cross_validation']['sessions'][str(row['session_id'])]['reference']['branches']
                self.assertAlmostEqual(row['expected_fidelity'],sum(b['probability']*b['checkpoints']['usable']['fidelity'] for b in branches.values()))
        self.assertNotIn('ns3_events',self.reports['Fixed-Dc'])

    def test_noncontending_no_dq_reproduces_full(self):
        config=workload(self.plan,.7,2000000,200,7)
        full=execute(config,'Full-Sync',self.cache)[0];nodq=execute(config,'No-Dq-R',self.cache)[0]
        for a,b in zip(model_rows(full,.5,5000000),model_rows(nodq,.5,5000000)):
            self.assertEqual(a['transaction_latency_ns'],b['transaction_latency_ns'])
            self.assertAlmostEqual(a['expected_fidelity'],b['expected_fidelity'],places=12)

    def test_no_load_fixed_delay_reproduces_full(self):
        cfg=workload(self.plan,0,800000,200,7)
        full=execute(cfg,'Full-Sync',self.cache)[0]
        fixed=execute(cfg,'Fixed-Dc',self.cache,dict(result_ns=288000))[0]
        for a,b in zip(model_rows(full,.5,5000000),model_rows(fixed,.5,5000000)):
            self.assertEqual(a['transaction_latency_ns'],b['transaction_latency_ns'])
            self.assertAlmostEqual(a['expected_fidelity'],b['expected_fidelity'],places=12)

    def test_decoupled_keeps_result_phase_error_and_no_state_prediction(self):
        full=self.reports['Full-Sync'];nodq=self.reports['No-Dq-R']
        rows=decoupled(self.config,nodq)
        self.assertTrue(all(r['usable_fidelity'] is None for r in rows))
        self.assertTrue(any(a['result_delay_ns']!=b['result_delay_ns'] for a,b in
                            zip(full['metrics']['sessions'],nodq['metrics']['sessions'])))

    def test_b_wait_rejected_and_plan_thresholds_retained(self):
        cfg=copy.deepcopy(self.config)
        cfg['native_instructions'].update(x_ns=250000,z_ns=250000);cfg['correction_duration_ns']=500000
        for s in cfg['sessions']:s['session_start_ns']=1000000
        with self.assertRaisesRegex(ValueError,'B wait=0'):execute(cfg,'No-Dq-R',self.cache)
        invalid=copy.deepcopy(self.plan);invalid['native_instructions']['x_ns']=1
        with self.assertRaises(ValueError):validate_plan(invalid)
        invalid=copy.deepcopy(self.plan);invalid['test_traffic_seeds']=[100]
        with self.assertRaises(ValueError):validate_plan(invalid)

    def test_corrupted_gate_or_cached_reference_rejected(self):
        report=copy.deepcopy(self.reports['No-Dq-R'])
        report['native_instructions'][0]['completion_ns']+=1
        with self.assertRaises(RuntimeError):validate_report(report)
        cache=copy.deepcopy(self.cache)
        for ref in cache.values():ref['spec']['bsm_start_ns']+=1
        with self.assertRaises(RuntimeError):cross_validate(self.reports['No-Dq-R'],cache)

    def test_timing_oracle_detects_mutated_actual_completion(self):
        report=copy.deepcopy(self.reports['Full-Sync'])
        self.assertEqual(sum(len(c['native']) for c in timing_rows(report)),8)
        report['snapshot']['requests'][0]['completion_ns']+=1
        with self.assertRaisesRegex(RuntimeError,'timing mismatch'):timing_rows(report)

    def test_resource_wait_is_retained_in_every_model(self):
        for report in self.reports.values():
            rows=report['metrics']['sessions']
            self.assertEqual([r['resource_ready_ns'] for r in rows],[1200000]*4)
            self.assertEqual([r['resource_wait_ns'] for r in rows],[200000,0,0,0])
            self.assertEqual(len(report['snapshot']['quantum_network']['deliveries']),8)
        replicas=self.reports['No-Dq-R']['snapshot']['quantum_network']['nodes']['R']['execution_replicas']
        self.assertEqual(sum(d['positions'] for d in replicas),8)
        self.assertEqual(len({d['name'] for d in replicas}),4)

    def test_decoupled_accounts_for_readiness_once(self):
        cfg=workload(self.plan,0,800000,200,7)
        full=execute(cfg,'Full-Sync',self.cache)[0]
        nodq=execute(cfg,'No-Dq-R',self.cache)[0]
        rows=decoupled(cfg,nodq)
        for actual,composed in zip(full['metrics']['sessions'],rows):
            self.assertEqual(actual['transaction_latency_ns'],composed['transaction_latency_ns'])
            self.assertEqual(actual['resource_wait_ns'],composed['resource_wait_ns'])
        self.assertEqual(rows[0]['resource_wait_ns'],200000)
        self.assertEqual(rows[0]['quantum_wait_ns'],0)

    def test_late_mixed_readiness_and_channel_noise_in_all_models(self):
        cfg=workload(self.plan,.7,400000,200,7)
        cfg['quantum_links']['RA'].update(delay_ns=2000000,depolar_rate_hz=50)
        cfg['quantum_links']['RB']['depolar_rate_hz']=50
        for slot,s in enumerate(cfg['sessions']):
            if slot%2:s.update(protocol='teleport',input_state='+i')
        for model in ('Full-Sync','No-Dq-R','Fixed-Dc'):
            report=execute(cfg,model,self.cache,dict(result_ns=288000))[0]
            bsm=[r for r in report['snapshot']['requests'] if r['operation']=='BSM']
            self.assertEqual(bsm[0]['session_id'],2)
            self.assertEqual(bsm[0]['start_ns'],1400000)
            self.assertLess(report['cross_validation']['max_density_matrix_error'],1e-12)
            self.assertEqual(len(report['snapshot']['quantum_network']['deliveries']),6)

    def test_zero_quantum_delay_matches_v3_model_expectations(self):
        from native_p5b_models import execute as execute_v3, model_rows as v3_rows
        cfg=workload(self.plan,.35,800000,200,7)
        for link in cfg['quantum_links'].values():link['delay_ns']=0
        old=copy.deepcopy(cfg);old.pop('quantum_links')
        for model in ('Full-Sync','No-Dq-R','Fixed-Dc'):
            report=execute(cfg,model,self.cache,dict(result_ns=400000))[0]
            reference=execute_v3(old,model,{},dict(result_ns=400000))[0]
            for actual,baseline in zip(model_rows(report,.5,5000000),v3_rows(reference,.5,5000000)):
                self.assertEqual(actual['transaction_latency_ns'],baseline['transaction_latency_ns'])
                self.assertAlmostEqual(actual['expected_fidelity'],baseline['expected_fidelity'],places=12)


if __name__ == '__main__':unittest.main()
