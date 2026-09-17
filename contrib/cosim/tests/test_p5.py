"""P5-A의 joint FIFO/aging, 기존 단계와의 동등성 및 실패 검출 검증."""

import copy
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import numpy as np

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))

from p2_validation import decode_dm
from p5_config import normalize_config
from p5_validation import cross_validate, validate_report
from run_p3 import P3FederationManager
from run_p4 import P4FederationManager
from run_p5 import P5FederationManager, P5ValidationFailure
from quantum_scheduler import MAX_ID


def scenario(name):
    return json.loads((MODULE/'scenarios'/('p5-'+name+'.json')).read_text())


def save(name, report):
    (MODULE/'results'/name).write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False)+'\n')


class P5Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (MODULE/'results').mkdir(parents=True, exist_ok=True)
        cls.runs = {}
        for name in ('quantum-only', 'joint-result', 'joint-both'):
            report = P5FederationManager(scenario(name)).run()
            cls.runs[name] = report
            save('p5-'+name+'.json', report)

    def test_01_zero_background_matches_p3(self):
        config = scenario('quantum-only')
        for key in ('background', 'expected_queueing'):
            del config[key]
        old = P3FederationManager(config).run()
        run = self.runs['quantum-only']
        self.assertEqual(old['snapshot'], run['snapshot'])
        self.assertEqual(old['metrics']['processor'], run['metrics']['processor'])

    def test_02_single_session_matches_p4(self):
        config = scenario('joint-both')
        config['sessions'] = config['sessions'][:1]
        config['expected_queueing']['R'] = 'zero'
        run = P5FederationManager(config).run()
        single = copy.deepcopy(config)
        single.update(single.pop('sessions')[0])
        del single['expected_queueing']['R']
        old = P4FederationManager(single).run()
        # P3의 arrival checkpoint는 추가 native memory 접근을 한다. 분할 aging의
        # 부동소수점 차이는 허용하되 timestamp/branch는 정확히 같아야 한다.
        points = run['snapshot']['sessions']['1']['checkpoints']
        def compare(a, b):
            if 'density_matrix' not in a:
                for key in a:
                    compare(a[key], b[key])
                return
            self.assertEqual(a['sim_time_ns'], b['sim_time_ns'])
            self.assertAlmostEqual(a['fidelity'], b['fidelity'], places=12)
            order = a['density_matrix']['qubit_order']
            self.assertLessEqual(np.max(np.abs(decode_dm(a['density_matrix'], order)-
                                              decode_dm(b['density_matrix'], order))), 1e-12)
        compare(old['snapshot']['checkpoints'], {k:v for k,v in points.items() if k != 'arrival'})
        self.assertEqual(old['snapshot']['correction']['measurement_bits'],
                         run['snapshot']['sessions']['1']['correction']['measurement_bits'])
        self.assertEqual(old['session_completion_ns'], run['batch_completion_ns'])

    def test_03_hand_calculated_joint_timing(self):
        for name, command, waits, result, end in (
                ('quantum-only', [0]*4, [0,800000,1600000,2400000], 0, 8298080),
                ('joint-result', [0]*4, [0,800000,1600000,2400000], 713920, 9012000),
                ('joint-both', [312000,0,0,0], [0,1112000,1912000,2712000], 401920, 9012000)):
            run = self.runs[name]
            rows = run['metrics']['sessions']
            self.assertEqual([r['command_queue_ns'] for r in rows], command)
            self.assertEqual([r['quantum_wait_ns'] for r in rows], waits)
            self.assertEqual([r['result_queue_ns'] for r in rows], [result]*4)
            self.assertEqual([r['correction_wait_ns'] for r in rows], [0]*4)
            self.assertEqual(run['batch_completion_ns'], end)
            for r in rows:
                self.assertEqual(r['command_delay_ns'], r['command_queue_ns']+110080)
                self.assertEqual(r['result_delay_ns'], r['result_queue_ns']+288000)

    def test_04_result_queue_preserves_bsm_checkpoints(self):
        base, run = self.runs['quantum-only'], self.runs['joint-result']
        for sid in base['snapshot']['sessions']:
            a, b = [x['snapshot']['sessions'][sid]['checkpoints'] for x in (base, run)]
            for stage in ('arrival', 'bsm_start', 'bsm_end_inputs', 'frame'):
                self.assertEqual(a[stage], b[stage])
            self.assertGreater(np.max(np.abs(decode_dm(a['correction_start']['density_matrix'])-
                                             decode_dm(b['correction_start']['density_matrix']))), 1e-3)

    def test_05_r_wait_changes_result_queue_phase(self):
        # 동일 session 2의 명령시각/traffic에서 경쟁 session만 제거한다.
        config = scenario('joint-result')
        config['sessions'] = [config['sessions'][1]]
        config['expected_queueing'].update(R='zero', result='zero')
        solo = P5FederationManager(config).run()
        save('p5-isolated-session-2.json', solo)
        joint = self.runs['joint-result']
        a = solo['metrics']['sessions'][0]
        b = next(r for r in joint['metrics']['sessions'] if r['session_id'] == 2)
        self.assertEqual(a['command_receive_ns'], b['command_receive_ns'])
        self.assertEqual((a['quantum_wait_ns'], b['quantum_wait_ns']), (0, 800000))
        self.assertEqual((a['bsm_completion_ns'], b['bsm_completion_ns']), (3510080, 4310080))
        self.assertEqual((a['result_queue_ns'], b['result_queue_ns']), (0, 713920))
        self.assertEqual(b['completion_ns']-a['completion_ns'], 800000+713920)
        for pair in ('AR', 'RB'):
            self.assertGreater(a['input_fidelity'][pair], b['input_fidelity'][pair])
        save('p5-phase-witness.json', dict(passed=True, isolated=a, joint=b,
             explanation='Removing competing sessions changes R wait, result emission time and actual result FIFO wait.'))

    def test_06_background_and_session_isolation(self):
        run = self.runs['joint-both']
        self.assertEqual(len(run['events']), 4*24)
        self.assertEqual(sum(e['event_type']=='BACKGROUND_RX' for e in run['packet_events']), 9)
        for sid in range(1, 5):
            own = [e for e in run['events'] if e['session_id'] == sid]
            for kind in ('BSM_REQUEST', 'CORRECTION_REQUEST', 'BSM_COMPLETE', 'CORRECTION_COMPLETE'):
                self.assertEqual(sum(e['event_type']==kind for e in own), 1)
            self.assertEqual(run['snapshot']['sessions'][str(sid)]['ab_pair']['pair_id'], 3)

    def test_07_noise_off_keeps_actual_packet_timing(self):
        for name, base in self.runs.items():
            config = scenario(name)
            config['memory_noise'] = dict(model='T1T2NoiseModel', T1_ns=0, T2_ns=0)
            run = P5FederationManager(config).run()
            save('p5-'+name+'-noise-off.json', run)
            self.assertEqual(base['packets'], run['packets'])
            for snap in run['snapshot']['sessions'].values():
                self.assertAlmostEqual(snap['ab_pair']['fidelity'], 1, places=12)

    def test_08_all_measurement_branches(self):
        references = {sid: c['reference'] for sid,c in self.runs['joint-both']['cross_validation']['sessions'].items()}
        branches, maximum = set(), 0
        for seed in range(32):
            config = scenario('joint-both')
            config['seed'] = seed
            run = P5FederationManager(config).run(references)
            branches.update(c['observed_branch'] for c in run['cross_validation']['sessions'].values())
            maximum = max(maximum, run['cross_validation']['max_density_matrix_error'])
        self.assertEqual(branches, {'00','01','10','11'})
        save('p5-branch-coverage.json', dict(passed=True, seeds=32, transactions=128,
             observed_branches=sorted(branches), max_density_matrix_error=maximum))

    def test_09_completion_new_request_and_background_same_time(self):
        config = scenario('joint-result')
        config['background']['result'] = dict(start_ns=2710080, count=1)
        run = P5FederationManager(config).run()
        at = 2710080
        events = [e for e in run['events'] if e['sim_time_ns'] == at]
        commit = next(e['sequence'] for e in events if e['event_type']=='BSM_COMPLETE' and e['session_id']==1)
        arrival = next(e['sequence'] for e in events if e['event_type']=='BSM_REQUEST' and e['session_id']==3)
        dispatch = next(e['sequence'] for e in events if e['event_type']=='BSM_START' and e['session_id']==2)
        self.assertLess(commit, arrival)
        self.assertLess(arrival, dispatch)
        packets = [e['packet_id'] for e in run['packet_events']
                   if e['event_type']=='QUEUE_ENQUEUE' and e['time_ns']==at and e['link']=='result']
        self.assertEqual(packets, [100000, 2])

    def test_10_same_time_commands_and_large_session_ids(self):
        config = dict(sessions=[dict(session_id=sid,command_time_ns=1000000) for sid in (9,MAX_ID,17)],
                      background=dict(command=dict(start_ns=1000000, count=1)))
        run = P5FederationManager(config).run()
        self.assertEqual([r['session_id'] for r in run['metrics']['sessions']], [9,MAX_ID,17])
        packets = [e['packet_id'] for e in run['packet_events']
                   if e['event_type']=='QUEUE_ENQUEUE' and e['time_ns']==1000000]
        self.assertEqual(packets, [1000,1,3,5])

    def test_11_traffic_drain_preserves_session_usable(self):
        config = scenario('joint-result')
        config['background']['result']['count'] = 8
        run = P5FederationManager(config).run()
        self.assertGreater(run['traffic_drain_completion_ns'], run['batch_completion_ns'])
        self.assertEqual(run['simulation_completion_ns'], run['traffic_drain_completion_ns'])
        self.assertEqual(run['snapshot']['sessions'], self.runs['joint-result']['snapshot']['sessions'])

    def test_12_correction_contention_rejected(self):
        config = scenario('joint-result')
        config['background']['result'].update(interval_ns=50000, count=3)
        with self.assertRaises(P5ValidationFailure) as caught:
            P5FederationManager(config).run()
        report = caught.exception.report
        self.assertIn('B correction waiting', str(caught.exception))
        self.assertTrue(any(s['correction']['start_ns'] > s['correction']['arrival_ns']
                            for s in report['snapshot']['sessions'].values()))
        save('p5-b-wait-rejected.json', report)

    def test_13_overflow_rejected_and_saved_by_cli(self):
        config = scenario('joint-both')
        config['queue_packets'] = 1
        with tempfile.TemporaryDirectory() as folder:
            source, dest = Path(folder)/'input.json', Path(folder)/'failed.json'
            source.write_text(json.dumps(config))
            proc = subprocess.run([sys.executable, str(MODULE/'python/run_p5.py'), str(source), '--output', str(dest)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertNotEqual(proc.returncode, 0)
            report = json.loads(dest.read_text())
            self.assertFalse(report['validation']['passed'])
            self.assertIn('drop', report['validation']['error'])
            self.assertTrue(any(e['event_type'].endswith('DROP') for e in report['packet_events']))
            save('p5-overflow-rejected.json', report)

    def test_14_detects_packet_corruption(self):
        for kind, field, value in (('QUEUE_DEQUEUE','time_ns',99999999),
                                  ('QUEUE_ENQUEUE','queue_depth',90), ('PHY_TX','packet_bytes',60),
                                  ('BACKGROUND_RX','kind',1), ('RESULT_RX','session_id',999)):
            run = copy.deepcopy(self.runs['joint-both'])
            next(e for e in run['packet_events'] if e['event_type']==kind)[field] = value
            with self.subTest(kind=kind), self.assertRaises(RuntimeError):
                validate_report(run)

    def test_15_detects_quantum_and_resource_corruption(self):
        for defect in ('clock', 'sample', 'parent', 'slot', 'timing'):
            run = copy.deepcopy(self.runs['joint-both'])
            snaps = run['snapshot']['sessions']
            if defect == 'clock':
                run['snapshot']['netsquid_time_ns'] = float(run['ns3_time_ns'])
            elif defect == 'sample':
                next(s for s in run['queue_samples'] if s['waiting_sessions'])['waiting_sessions'] = []
            elif defect == 'parent':
                next(e for e in run['events'] if e['event_type']=='BSM_START' and e['session_id']==2)['caused_by_event_id'] = 'p:0'
            elif defect == 'slot':
                snaps['2']['resources']['1']['locations'] = copy.deepcopy(snaps['1']['resources']['1']['locations'])
            else:
                snaps['2']['requests']['1']['start_ns'] -= 1
            with self.subTest(defect=defect), self.assertRaises(RuntimeError):
                validate_report(run)

    def test_16_reference_detects_missing_queue_aging(self):
        run = copy.deepcopy(self.runs['joint-result'])
        refs = {sid:c['reference'] for sid,c in run['cross_validation']['sessions'].items()}
        run['snapshot']['sessions']['2']['checkpoints']['correction_start']['density_matrix'] = (
            self.runs['quantum-only']['snapshot']['sessions']['2']['checkpoints']['correction_start']['density_matrix'])
        with self.assertRaises(RuntimeError):
            cross_validate(run, refs)

    def test_17_configuration_guards(self):
        for raw in (dict(sessions=[]), dict(queue_packets=0), dict(background=dict(result=dict(count=-1))),
                    dict(sessions=[dict(session_id=1,command_time_ns=0)]*2),
                    dict(sessions=[dict(session_id=MAX_ID+1,command_time_ns=0)]),
                    dict(background=dict(result=dict(start_ns=2**53-1,count=1))),
                    dict(expected_queueing=dict(command='zero',result='zero'))):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_config(raw)

    def test_18_frozen_p4_sources_unchanged(self):
        manifest = json.loads((MODULE/'baselines/p4-freeze.json').read_text())
        self.assertEqual(hashlib.sha256((MODULE/'baselines'/manifest['archive']).read_bytes()).hexdigest(),
                         manifest['archive_sha256'])
        for name,digest in manifest['files'].items():
            if '/results/' not in name:
                self.assertEqual(hashlib.sha256((MODULE.parents[1]/name).read_bytes()).hexdigest(), digest, name)


if __name__ == '__main__':
    unittest.main()
