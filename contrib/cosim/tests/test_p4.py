"""실제 FIFO 대기, quantum 격리, drain 이후 평가 불변성 및 실패 검출을 검증한다."""

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

from p2_reference_validation import compare_reference
from p2_validation import decode_dm
from p4_config import normalize_config
from p4_validation import validate_report
from run_p2 import P2FederationManager
from run_p4 import P4FederationManager, P4ValidationFailure
from run_p4_sweep import run_sweep


def scenario(name):
    return json.loads((MODULE/'scenarios'/('p4-'+name+'.json')).read_text())


class P4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        (MODULE/'results').mkdir(parents=True, exist_ok=True)
        cls.runs = {}
        for name in ('zero', 'command-only', 'result-only', 'both'):
            report = P4FederationManager(scenario(name)).run()
            cls.runs[name] = report
            (MODULE/'results'/('p4-'+name+'.json')).write_text(json.dumps(report, indent=2, sort_keys=True)+'\n')

    def test_01_zero_matches_p2(self):
        old = P2FederationManager({}).run()
        run = self.runs['zero']
        self.assertEqual(old['snapshot'], run['snapshot'])
        self.assertEqual(old['session_completion_ns'], run['session_completion_ns'])

    def test_02_deterministic_fifo_delays(self):
        for name, waits in (('zero', (0, 0)), ('command-only', (312000, 0)),
                            ('result-only', (0, 2361920)), ('both', (312000, 2049920))):
            run = self.runs[name]
            self.assertEqual(tuple(run['metrics']['classical'][s]['queue_wait_ns'] for s in ('command', 'result')), waits)
            self.assertEqual(run['metrics']['quantum_wait'], dict(bsm_ns=0, correction_ns=0))

    def test_03_result_only_isolates_bsm(self):
        base, run = self.runs['zero'], self.runs['result-only']
        for stage in ('bsm_start', 'bsm_end_inputs', 'frame'):
            self.assertEqual(base['snapshot']['checkpoints'][stage], run['snapshot']['checkpoints'][stage])
        self.assertEqual(run['session_completion_ns']-base['session_completion_ns'], 2361920)
        self.assertGreater(np.max(np.abs(decode_dm(base['snapshot']['checkpoints']['correction_start']['density_matrix'])-
                                           decode_dm(run['snapshot']['checkpoints']['correction_start']['density_matrix']))), 1e-3)

    def test_04_command_only_moves_absolute_downstream_time(self):
        base, run = self.runs['zero'], self.runs['command-only']
        self.assertEqual(run['session_completion_ns']-base['session_completion_ns'], 312000)
        self.assertEqual(run['metrics']['classical']['result']['total_delay_ns'],
                         base['metrics']['classical']['result']['total_delay_ns'])
        self.assertEqual(run['snapshot']['correction']['start_ns']-base['snapshot']['correction']['start_ns'], 312000)

    def test_05_background_isolation(self):
        run = self.runs['both']
        self.assertEqual(len(run['events']), 24)
        for kind in ('BSM_REQUEST', 'CORRECTION_REQUEST', 'BSM_COMPLETE', 'CORRECTION_COMPLETE'):
            self.assertEqual(sum(e['event_type'] == kind for e in run['events']), 1)
        self.assertEqual(sum(e['event_type'] == 'BACKGROUND_RX' for e in run['packet_events']), 8)
        self.assertEqual({e['input_pair_ids'][0] for e in run['events'] if e['event_type'].startswith('CORRECTION_')}, {3})

    def test_06_noise_off_all_paths(self):
        for name in self.runs:
            config = scenario(name)
            config['memory_noise'] = dict(model='T1T2NoiseModel', T1_ns=0, T2_ns=0)
            run = P4FederationManager(config).run()
            self.assertAlmostEqual(run['snapshot']['ab_pair']['fidelity'], 1, places=12)
            self.assertEqual(run['packets'], self.runs[name]['packets'])

    def test_07_all_bsm_branches_with_contention(self):
        reference = self.runs['both']['cross_validation']['reference']
        branches = set()
        for seed in range(32):
            config = scenario('both')
            config['seed'] = seed
            run = P4FederationManager(config).run(reference)
            branches.add(run['cross_validation']['observed_branch'])
        self.assertEqual(branches, {'00', '01', '10', '11'})

    def test_08_tail_drain_does_not_re_evaluate_usable(self):
        config = scenario('result-only')
        config['background']['result'] = dict(start_ns=2600000, interval_ns=1000000, count=6, payload_bytes=1000)
        run = P4FederationManager(config).run()
        self.assertGreater(run['traffic_drain_completion_ns'], run['session_completion_ns'])
        self.assertEqual(run['ns3_time_ns'], run['traffic_drain_completion_ns'])
        self.assertEqual(run['snapshot']['checkpoints']['usable']['sim_time_ns'], run['session_completion_ns'])
        # transaction 후의 패킷들을 없애도 transaction 자체는 동일하다.
        config['background']['result']['count'] = 1
        short = P4FederationManager(config).run()
        self.assertEqual(run['snapshot']['checkpoints'], short['snapshot']['checkpoints'])

    def test_09_same_timestamp_background_first(self):
        run = P4FederationManager(dict(background=dict(command=dict(start_ns=1000000, count=1)))).run()
        self.assertEqual(run['metrics']['classical']['command']['queue_wait_ns'], 82400)
        order = [e['packet_id'] for e in run['packet_events'] if e['event_type'] == 'QUEUE_ENQUEUE' and e['time_ns'] == 1000000]
        self.assertEqual(order, [1000, 1])
        run = P4FederationManager(dict(background=dict(result=dict(start_ns=2710080, count=1)))).run()
        self.assertEqual(run['metrics']['classical']['result']['queue_wait_ns'], 824000)

    def test_10_overflow_fails_and_preserves_trace(self):
        config = scenario('both')
        config['queue_packets'] = 1
        with self.assertRaises(P4ValidationFailure) as caught:
            P4FederationManager(config).run()
        run = caught.exception.report
        self.assertFalse(run['validation']['passed'])
        self.assertIn('drop', run['validation']['error'])
        self.assertTrue(any(e['event_type'] in ('QUEUE_DROP', 'TC_DROP') for e in run['packet_events']))
        self.assertEqual({e['traffic_class'] for e in run['packet_events'] if e['event_type'].endswith('DROP')},
                         {'control', 'background'})

    def test_11_cli_failed_report_saved(self):
        with tempfile.TemporaryDirectory() as folder:
            config = scenario('both')
            config['queue_packets'] = 1
            source, dest = Path(folder)/'input.json', Path(folder)/'failed.json'
            source.write_text(json.dumps(config))
            proc = subprocess.run([sys.executable, str(MODULE/'python/run_p4.py'), str(source), '--output', str(dest)],
                                  stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(json.loads(dest.read_text())['validation']['passed'])

    def test_12_detects_trace_corruption(self):
        for kind, field, value in (('QUEUE_DEQUEUE', 'time_ns', 9999999),
                                   ('QUEUE_ENQUEUE', 'queue_depth', 90),
                                   ('PHY_TX', 'packet_bytes', 60),
                                   ('BACKGROUND_RX', 'kind', 1)):
            run = copy.deepcopy(self.runs['both'])
            next(e for e in run['packet_events'] if e['event_type'] == kind)[field] = value
            with self.assertRaises(RuntimeError):
                validate_report(run)

    def test_13_detects_quantum_wait_and_clock_errors(self):
        run = copy.deepcopy(self.runs['both'])
        run['snapshot']['requests'][1]['start_ns'] += 1
        with self.assertRaisesRegex(RuntimeError, 'quantum waiting'):
            validate_report(run)
        run = copy.deepcopy(self.runs['both'])
        run['snapshot']['netsquid_time_ns'] = float(run['ns3_time_ns'])
        with self.assertRaisesRegex(RuntimeError, 'integer clocks'):
            validate_report(run)

    def test_14_detects_missing_aging(self):
        run = copy.deepcopy(self.runs['result-only'])
        # packet queue로 늘어난 저장 시간을 quantum 경로가 누락한 오류를 흉내 낸다.
        run['snapshot']['checkpoints']['correction_start']['density_matrix'] = self.runs['zero']['snapshot']['checkpoints']['correction_start']['density_matrix']
        with self.assertRaises(RuntimeError):
            compare_reference(run, self.runs['result-only']['cross_validation']['reference'])

    def test_15_configuration_guards(self):
        for raw in (dict(queue_packets=0), dict(background=dict(command=dict(count=-1))),
                    dict(background=dict(result=dict(payload_bytes=1500))), dict(background=dict(x={})),
                    dict(background=dict(command=dict(interval_ns=0))), dict(sessions=[]),
                    dict(expected_queueing=dict(command='maybe', result='zero')),
                    dict(background=dict(result=dict(start_ns=2**53-1, count=1)))):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                normalize_config(raw)

    def test_16_small_characterization(self):
        with tempfile.TemporaryDirectory() as folder:
            summary = run_sweep(folder, loads=(0, 950000), packet_count=4)
            self.assertEqual(summary['runs'], 12)
            self.assertTrue(summary['passed'])
            self.assertTrue((Path(folder)/'summary.csv').is_file())

    def test_17_p3_baseline_unchanged(self):
        manifest = json.loads((MODULE/'baselines/p3-freeze.json').read_text())
        archive = MODULE/'baselines'/manifest['archive']
        self.assertEqual(hashlib.sha256(archive.read_bytes()).hexdigest(), manifest['archive_sha256'])
        for name, digest in manifest['files'].items():
            if '/results/' in name:
                continue
            self.assertEqual(hashlib.sha256((MODULE.parents[1]/name).read_bytes()).hexdigest(), digest, name)

    def test_18_nondefault_link_and_packet_parameters(self):
        raw = dict(command_time_ns=700000, bsm_duration_ns=900000, correction_duration_ns=1100000,
                   command_payload_bytes=211, result_payload_bytes=333,
                   command_link=dict(rate_bps=54000000, delay_ns=400000),
                   result_link=dict(rate_bps=16000000, delay_ns=600000),
                   background=dict(command=dict(start_ns=650000, interval_ns=20000, count=4, payload_bytes=900),
                                   result=dict(start_ns=1000000, interval_ns=200000, count=8, payload_bytes=750)))
        run = P4FederationManager(raw).run()
        self.assertTrue(run['validation']['passed'])
        self.assertTrue(run['cross_validation']['passed'])


if __name__ == '__main__':
    unittest.main()
