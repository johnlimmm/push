"""실제 Q2NS SwapApp의 패킷/비동기 경계가 P5의 시간·양자 결과를 유지하는지 검사한다."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))

from q2ns_validation import validate_q2ns
from run_q2ns import Q2nsFederationManager, Q2nsValidationFailure
from run_p5 import P5FederationManager


def scenario(name):
    return json.loads((MODULE/'scenarios'/('p5-'+name+'.json')).read_text())


def save(name, report):
    (MODULE/'results'/name).write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+'\n')


class Q2nsIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (MODULE/'results').mkdir(parents=True,exist_ok=True)
        cls.runs, cls.baselines = {}, {}
        for name in ('quantum-only','joint-result','joint-both'):
            cls.baselines[name] = P5FederationManager(scenario(name)).run()
            cls.runs[name] = Q2nsFederationManager(scenario(name)).run()
            save('q2ns-'+name+'.json',cls.runs[name])

    def test_01_timing_and_state_match_p5(self):
        for name, run in self.runs.items():
            base = self.baselines[name]
            self.assertEqual(run['snapshot'],base['snapshot'])
            self.assertEqual(run['packets'],base['packets'])
            self.assertEqual(run['metrics'],base['metrics'])
            self.assertEqual(run['batch_completion_ns'],base['batch_completion_ns'])

    def test_02_actual_swapapp_native_events_and_mapping(self):
        run = self.runs['joint-both']
        self.assertEqual(run['q2ns_status'],dict(native_state_count=0,native_qubit_count=0,
                                               sessions=4,corrections_applied=4))
        self.assertEqual(len(run['q2ns_events']),24)
        for mapping in run['q2ns_validation']['resource_mapping'].values():
            self.assertEqual(mapping['q2ns_pair_ids'],[101,102,103])
            self.assertEqual(mapping['netsquid_pair_ids'],[1,2,3])

    def test_03_correction_ack_occurs_only_at_completion(self):
        for run in self.runs.values():
            for sid in run['snapshot']['sessions']:
                own = {r['event_type']:r for r in run['q2ns_events'] if str(r['session_id'])==sid}
                self.assertEqual(own['Q2NS_CORRECTION_APPLIED']['time_ns']-
                                 own['Q2NS_FRAME_RESOLVED']['time_ns'],run['config']['correction_duration_ns'])

    def test_04_noise_off_keeps_native_packet_timing(self):
        cfg=scenario('joint-both')
        cfg['memory_noise']=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0)
        run=Q2nsFederationManager(cfg).run()
        save('q2ns-joint-both-noise-off.json',run)
        self.assertEqual(run['packets'],self.runs['joint-both']['packets'])
        for snap in run['snapshot']['sessions'].values():
            self.assertAlmostEqual(snap['ab_pair']['fidelity'],1,places=12)

    def test_05_all_four_bits_through_native_packets(self):
        refs={sid:c['reference'] for sid,c in self.runs['joint-both']['cross_validation']['sessions'].items()}
        branches,maximum=set(),0
        for seed in range(32):
            cfg=scenario('joint-both');cfg['seed']=seed
            run=Q2nsFederationManager(cfg).run(refs)
            branches.update((e['m1'],e['m2']) for e in run['q2ns_events'] if e['event_type']=='Q2NS_FRAME_RESOLVED')
            maximum=max(maximum,run['cross_validation']['max_density_matrix_error'])
        self.assertEqual(branches,{(0,0),(0,1),(1,0),(1,1)})
        save('q2ns-branch-coverage.json',dict(passed=True,seeds=32,transactions=128,
             observed_branches=sorted(''.join(map(str,b)) for b in branches),max_density_matrix_error=maximum))

    def test_06_native_session_isolation_at_same_timestamp(self):
        cfg=dict(sessions=[dict(session_id=sid,command_time_ns=1000000) for sid in (17,2**63-1,9)],
                 background=dict(command=dict(start_ns=1000000,count=1)))
        run=Q2nsFederationManager(cfg).run()
        self.assertEqual([r['session_id'] for r in run['metrics']['sessions']],[17,2**63-1,9])
        self.assertEqual(run['q2ns_status']['corrections_applied'],3)

    def test_07_zero_time_and_boundary_rounds(self):
        cfg=dict(sessions=[dict(session_id=1,command_time_ns=0),dict(session_id=2,command_time_ns=1600000)])
        run=Q2nsFederationManager(cfg).run()
        self.assertEqual(run['metrics']['sessions'][0]['command_receive_ns'],110080)
        self.assertTrue(run['q2ns_validation']['passed'])

    def test_08_drain_does_not_repeat_app_completion(self):
        cfg=scenario('joint-result');cfg['background']['result']['count']=8
        run=Q2nsFederationManager(cfg).run()
        self.assertGreater(run['traffic_drain_completion_ns'],run['batch_completion_ns'])
        self.assertEqual(run['snapshot']['sessions'],self.runs['joint-result']['snapshot']['sessions'])
        self.assertEqual(run['q2ns_status']['corrections_applied'],4)

    def test_09_reject_native_ownership_and_log_corruption(self):
        for defect in ('state','qubit','count','missing','time','pair','bits','cause'):
            run=copy.deepcopy(self.runs['joint-both'])
            rows=run['q2ns_events']
            if defect=='state': run['q2ns_status']['native_state_count']=1
            elif defect=='qubit': run['q2ns_status']['native_qubit_count']=1
            elif defect=='count': run['q2ns_status']['corrections_applied']=5
            elif defect=='missing': rows.pop()
            elif defect=='time': rows[-1]['time_ns']-=1
            elif defect=='pair': rows[0]['output_pair_id']=3
            elif defect=='bits': next(r for r in rows if r['event_type']=='Q2NS_FRAME_RESOLVED')['m1']^=1
            else: rows[0]['cause']='p:0'
            with self.subTest(defect=defect),self.assertRaises(RuntimeError):
                validate_q2ns(run)

    def test_10_reject_b_wait_and_keep_native_trace(self):
        cfg=scenario('joint-result');cfg['background']['result'].update(interval_ns=50000,count=3)
        with self.assertRaises(Q2nsValidationFailure) as caught:
            Q2nsFederationManager(cfg).run()
        self.assertIn('B correction waiting',str(caught.exception))
        self.assertEqual(caught.exception.report['q2ns_status']['corrections_applied'],4)

    def test_11_cli_drop_failure_preserves_report(self):
        cfg=scenario('joint-both');cfg['queue_packets']=1
        with tempfile.TemporaryDirectory() as folder:
            source,dest=Path(folder)/'input.json',Path(folder)/'failed.json'
            source.write_text(json.dumps(cfg))
            proc=subprocess.run([sys.executable,str(MODULE/'python/run_q2ns.py'),str(source),'--output',str(dest)],
                                stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=30)
            self.assertNotEqual(proc.returncode,0)
            report=json.loads(dest.read_text())
            self.assertIn('drop',report['validation']['error'])
            self.assertEqual(report['q2ns_status']['native_state_count'],0)
            save('q2ns-overflow-rejected.json',report)

    def test_12_p5_baseline_sources_unchanged(self):
        report=json.loads((MODULE/'results/p5-validation-summary.json').read_text())
        for name,digest in report['source_sha256'].items():
            self.assertEqual(hashlib.sha256((MODULE.parents[1]/name).read_bytes()).hexdigest(),digest,name)


if __name__=='__main__':
    unittest.main()
