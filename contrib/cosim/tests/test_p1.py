"""P1 종료 기준: 실제 UDP 경로, 독립 시간 계산, 네 BSM 분기, 보정 멱등성, reference."""

import copy
import json
from pathlib import Path
import sys
import unittest

import numpy as np

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))

from p1_quantum import EventLog, P1Quantum
from p1_validation import decode_dm, normalize_config, validate_report
from quantum_scheduler import MAX_TIME_NS
from run_p1 import P1FederationManager, compare_reference


class P1IntegrationTests(unittest.TestCase):
    def execute(self, **config):
        report = P1FederationManager(config).run()
        self.assertTrue(report['validation']['passed'])
        self.assertTrue(report['cross_validation']['passed'])
        directory = MODULE / 'results' / 'tests'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (report['config']['name'] + '.json')).write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        return report

    def test_end_to_end_timing(self):
        """헤더 포함 126/110 bytes의 전송시간을 손으로 계산한 기본 transaction과 비교한다."""
        report = self.execute(name='p1-basic')
        request = report['snapshot']['requests'][1]
        correction = report['snapshot']['correction']
        self.assertEqual((request['start_ns'], request['completion_ns']), (1110080, 2710080))
        self.assertEqual((correction['start_ns'], correction['completion_ns']), (2998080, 3498080))
        self.assertEqual(report['session_completion_ns'], 3498080)
        events = report['events']
        self.assertEqual([e['node_id'] for e in events if e['event_type'] == 'COMMAND_RX'], ['R'])
        self.assertEqual([e['node_id'] for e in events if e['event_type'] == 'RESULT_RX'], ['B'])
        self.assertEqual([e['node_id'] for e in events if e['event_type'] == 'CORRECTION_START'], ['B'])
        self.assertEqual(report['snapshot']['ab_pair']['locations'], [
            dict(node_id='A', memory_id='A', position=0), dict(node_id='B', memory_id='B', position=0)])
        stored = json.loads(json.dumps(report))
        self.assertIs(type(stored['snapshot']['netsquid_time_ns']), int)
        self.assertEqual(stored['snapshot']['netsquid_time_ns'], 3498080)
        self.assertEqual(stored['snapshot']['ab_pair']['input_pair_ids'], [1, 2])
        for event in stored['events']:
            if event['event_type'].startswith('CORRECTION_') or event['event_type'] == 'PAIR_USABLE':
                self.assertEqual(event['input_pair_ids'], [3])
                self.assertEqual(event['output_pair_id'], 3)
                self.assertEqual(event['details']['ancestor_pair_ids'], [1, 2])
        self.assertTrue(validate_report(stored)['passed'])
        self.assertTrue(compare_reference(stored)['passed'])

    def test_all_measurement_branches(self):
        """특정 seed의 비트를 정답으로 두지 않고 32회 실제 transaction에서 네 분기를 모두 검증한다."""
        observed = set()
        for seed in range(32):
            with self.subTest(seed=seed):
                report = self.execute(name='p1-branch-{}'.format(seed), seed=seed)
                bits = tuple(report['snapshot']['correction']['measurement_bits'])
                observed.add(bits)
                correction = report['snapshot']['correction']
                # 00도 동일한 양의 correction duration을 소비해야 한다.
                self.assertEqual(correction['completion_ns'] - correction['start_ns'], 500000)
                self.assertLessEqual(abs(1 - report['snapshot']['ab_pair']['fidelity']), 1e-12)
        self.assertEqual(observed, {(0, 0), (0, 1), (1, 0), (1, 1)})

    def test_changed_delays_change_time_not_noiseless_state(self):
        baseline = self.execute(name='p1-delay-base')
        changed = self.execute(name='p1-delay-changed',
                               command_link=dict(rate_bps=100000000, delay_ns=112345),
                               result_link=dict(rate_bps=10000000, delay_ns=223456))
        self.assertEqual(changed['session_completion_ns'] - baseline['session_completion_ns'], 35801)
        np.testing.assert_allclose(decode_dm(changed['snapshot']['ab_pair']['density_matrix']),
                                   decode_dm(baseline['snapshot']['ab_pair']['density_matrix']), atol=1e-12, rtol=0)

    def test_duplicates_and_conflicting_bits_during_and_after_correction(self):
        """다른 message ID를 가진 재전송/변조 결과를 보정 실행 중과 완료 후 모두 검사한다."""
        report = self.execute(name='p1-result-replays', result_replays=[
            dict(delay_ns=100000), dict(delay_ns=200000, xor_m1=1),
            dict(delay_ns=700000), dict(delay_ns=1000000, xor_m2=1)])
        events = report['events']
        duplicates = [e for e in events if e['event_type'] == 'CORRECTION_DUPLICATE']
        mismatch = [e for e in events if e['event_type'] == 'CORRECTION_RESULT_MISMATCH']
        self.assertEqual([e['request_state'] for e in duplicates], ['RUNNING', 'COMPLETED'])
        self.assertEqual(len(mismatch), 2)
        self.assertEqual(report['snapshot']['correction_count'], 1)
        self.assertGreater(report['ns3_time_ns'], report['session_completion_ns'])

    def test_duplicate_packets_wait_for_link_serialization(self):
        """동일 시각에 보낸 결과 복제도 실제 장치 큐를 거치며, 보정을 재실행하지 않는다."""
        report = self.execute(name='p1-packet-queue', result_replays=[dict(delay_ns=0), dict(delay_ns=0)])
        sends = [e['sim_time_ns'] for e in report['events'] if e['event_type'] == 'RESULT_TX']
        receives = [e['sim_time_ns'] for e in report['events'] if e['event_type'] == 'RESULT_RX']
        self.assertEqual(sends, [2710080] * 3)
        self.assertEqual(receives, [2998080, 3086080, 3174080])
        self.assertEqual(report['snapshot']['correction_count'], 1)

    def test_zero_propagation_and_ns_rounding(self):
        self.execute(name='p1-zero-propagation', command_time_ns=0,
                     command_link=dict(rate_bps=33300000, delay_ns=0),
                     result_link=dict(rate_bps=7000000, delay_ns=0),
                     bsm_duration_ns=1, correction_duration_ns=1)

    def test_slow_link_replays_remain_lossless_fifo(self):
        """재전송이 오래 대기해도 기본 AQM의 drop 없이 명시한 FIFO 모델을 유지한다."""
        report = self.execute(name='p1-slow-link',
                              result_link=dict(rate_bps=10000, delay_ns=200000),
                              result_replays=[dict(delay_ns=0) for _ in range(5)])
        self.assertEqual(len([e for e in report['events'] if e['event_type'] == 'RESULT_RX']), 6)

    def test_validator_detects_bad_timing_and_metadata_despite_perfect_fidelity(self):
        report = self.execute(name='p1-validator-negative')
        corrupted = copy.deepcopy(report)
        next(e for e in corrupted['events'] if e['event_type'] == 'RESULT_RX')['sim_time_ns'] += 1
        with self.assertRaisesRegex(RuntimeError, 'RESULT_RX timing'):
            validate_report(corrupted)
        self.assertAlmostEqual(corrupted['snapshot']['ab_pair']['fidelity'], 1)
        # 시간·양자 결과가 모두 맞아도 보정 대상/생성 이력을 잘못 기록하면 검증에 실패한다.
        for field, value, error in (
                ('input_pair_ids', [1, 2], 'correction target resource'),
                ('details', {}, 'correction ancestry'),
                ('sim_time_ns', 2998080.0, 'integer event time')):
            with self.subTest(field=field):
                corrupted = copy.deepcopy(report)
                event = next(e for e in corrupted['events'] if e['event_type'] == 'CORRECTION_START')
                event[field] = value
                with self.assertRaisesRegex(RuntimeError, error):
                    validate_report(corrupted)
        corrupted = copy.deepcopy(report)
        corrupted['snapshot']['netsquid_time_ns'] = float(report['ns3_time_ns'])
        with self.assertRaisesRegex(RuntimeError, 'integer clocks'):
            validate_report(corrupted)

    def test_independent_reference_detects_wrong_final_state(self):
        report = self.execute(name='p1-reference-negative')
        # Phi-는 물리적으로 다른 Bell 상태다. fidelity 필드를 그대로 둬도 rho 비교가 잡아낸다.
        rho = report['snapshot']['ab_pair']['density_matrix']['real']
        rho[0][3] = rho[3][0] = -0.5
        with self.assertRaisesRegex(RuntimeError, 'reference state or timing mismatch'):
            compare_reference(report)


class P1QuantumGuards(unittest.TestCase):
    def create_completed_bsm(self):
        config = normalize_config(dict(bsm_duration_ns=100, correction_duration_ns=50))
        log = EventLog(1)
        root = log.add('SESSION_CREATED', 0)
        quantum = P1Quantum(config, log, root)
        message = dict(session_id=1, request_id=1, pair_a=1, pair_b=2, output_pair_id=3)
        quantum.submit_bsm(message, root)
        quantum.schedule_queued()
        result = quantum.advance_to_boundary(100)[0]
        message.update(m1=result['m1'], m2=result['m2'])
        return quantum, message, root

    def test_consumed_epr_cannot_be_reused(self):
        quantum, _, _ = self.create_completed_bsm()
        reply = quantum.submit_request(dict(request_id=99, processor_id=2,
                                            pair_a=1, pair_b=2, duration_ns=100))
        self.assertEqual(reply['code'], 'RESOURCE_CONFLICT')
        self.assertEqual(quantum.ab['state'], 'FRAME_PENDING')
        self.assertEqual(len(quantum.outputs), 1)

    def test_correction_horizon_and_exact_completion(self):
        quantum, message, root = self.create_completed_bsm()
        quantum.advance_to_boundary(120)
        quantum.submit_correction(message, root)
        quantum.schedule_queued()
        self.assertEqual(quantum.next_safe_horizon(), 170)
        with self.assertRaisesRegex(ValueError, 'safe horizon'):
            quantum.advance_to_boundary(171)
        quantum.advance_to_boundary(169)
        self.assertEqual(quantum.ab['state'], 'CORRECTING')
        self.assertIsNone(quantum.ab['fidelity'])
        quantum.advance_to_boundary(170)
        self.assertEqual(quantum.ab['state'], 'USABLE')
        self.assertEqual(quantum.correction_count, 1)

    def test_first_received_bits_are_used_without_hidden_oracle(self):
        quantum, message, root = self.create_completed_bsm()
        message['m1'] ^= 1
        quantum.submit_correction(message, root)
        quantum.schedule_queued()
        quantum.advance_to_boundary(150)
        self.assertAlmostEqual(quantum.ab['fidelity'], 0)

    def test_configuration_guards(self):
        for config in (dict(noise=True), dict(correction_duration_ns=0),
                       dict(bsm_duration_ns=0.5), dict(command_time_ns=MAX_TIME_NS),
                       dict(result_replays=[dict(delay_ns=-1)])):
            with self.subTest(config=config), self.assertRaises(ValueError):
                normalize_config(config)


if __name__ == '__main__':
    unittest.main(verbosity=2)
