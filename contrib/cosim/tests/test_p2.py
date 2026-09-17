"""P2: native T1/T2 시간 누적, 네 조건부 분기, 실제 UDP 지연과 독립 reference 검증."""

import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import tempfile
import unittest

import netsquid as ns
import numpy as np
from netsquid.components.models.qerrormodels import T1T2NoiseModel

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))

from p1_quantum import EventLog
from p1_validation import analytic_timing
from p2_quantum import P2Quantum
from p2_reference_validation import compare_reference
from p2_validation import DEFAULT_NOISE, decode_dm, normalize_config, validate_report
from run_p1 import P1FederationManager
from run_p2 import P2FederationManager
from run_p2_sweep import run_sweep, validate_sweep


def make_quantum(config):
    log = EventLog(config['session_id'])
    root = log.add('SESSION_CREATED', 0, source='federation')
    return P2Quantum(config, log, root), root


def execute_quantum(seed=7, subdivide=False, skip_packet_aging=False, **options):
    """프로세스 없는 경계 검사. 연산 시각은 ns-3 기준식과 동일하게 두고 관측 횟수만 바꾼다."""
    config = normalize_config(dict(seed=seed, **options))
    timing = analytic_timing(config)
    quantum, root = make_quantum(config)
    original_qubits = [quantum.memories[name][0].peek(quantum.memories[name][1])[0] for name in ('A', 'B')]
    message = dict(session_id=config['session_id'], request_id=1, pair_a=1, pair_b=2, output_pair_id=3)
    def advance(at, inputs):
        if subdivide:
            for boundary in sorted({quantum.now_ns + (at - quantum.now_ns) * k // 5 for k in (1, 2, 3, 4)}):
                quantum.advance_to_boundary(boundary)
                # peek 자체도 native elapsed time을 갱신하므로 분할 불변성을 검증해야 한다.
                for _ in range(2):
                    quantum.input_states() if inputs else quantum.frame_state()
                quantum.snapshot()
        quantum.advance_to_boundary(at)
    advance(timing['bsm_start_ns'], True)
    quantum.submit_bsm(message, root)
    quantum.schedule_queued()
    advance(timing['bsm_completion_ns'], True)
    result = quantum.outputs[1]
    message.update(m1=result['m1'], m2=result['m2'])
    advance(timing['correction_start_ns'], False)
    if skip_packet_aging:
        # 의도적인 버그: noise 없이 접근해 결과 패킷 대기 구간의 last-access를 초기화한다.
        for name in ('A', 'B'):
            memory, position = quantum.memories[name]
            memory.peek(position, skip_noise=True)
    quantum.submit_correction(message, root)
    quantum.schedule_queued()
    advance(timing['correction_completion_ns'], False)
    current_qubits = [quantum.memories[name][0].peek(quantum.memories[name][1])[0] for name in ('A', 'B')]
    if any(before is not after for before, after in zip(original_qubits, current_qubits)):
        raise AssertionError('surviving qubit replaced')
    return dict(config=config, snapshot=quantum.snapshot())


class P2IntegrationTests(unittest.TestCase):
    def execute(self, reference=None, **options):
        report = P2FederationManager(options).run(reference)
        self.assertTrue(report['validation']['passed'])
        self.assertTrue(report['cross_validation']['passed'])
        directory = MODULE / 'results/tests'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (report['config']['name'] + '.json')).write_text(
            json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + '\n')
        return report

    def test_end_to_end_native_noise_and_json_roundtrip(self):
        report = self.execute(name='p2-basic')
        self.assertEqual(report['session_completion_ns'], 3498080)
        self.assertLess(report['snapshot']['ab_pair']['fidelity'], 0.9)
        self.assertLessEqual(report['cross_validation']['max_density_matrix_error'], 1e-12)
        stored = json.loads(json.dumps(report))
        self.assertTrue(validate_report(stored)['passed'])
        self.assertTrue(compare_reference(stored, stored['cross_validation']['reference'])['passed'])

    def test_zero_noise_reproduces_p1(self):
        p1 = P1FederationManager({}).run()
        off = dict(model='T1T2NoiseModel', T1_ns=0, T2_ns=0)
        p2 = self.execute(name='p2-noise-off', memory_noise=off)
        self.assertEqual(p1['bridge_steps'], p2['bridge_steps'])
        self.assertEqual(p1['snapshot']['ab_pair'], p2['snapshot']['ab_pair'])
        self.assertEqual(p1['snapshot']['requests'], p2['snapshot']['requests'])
        self.assertEqual([(e['event_type'], e['sim_time_ns']) for e in p1['events']],
                         [(e['event_type'], e['sim_time_ns']) for e in p2['events']])

    def test_all_branches_match_conditional_reference(self):
        reference, observed = None, set()
        for seed in range(32):
            with self.subTest(seed=seed):
                report = self.execute(name='p2-branch-{}'.format(seed), seed=seed, reference=reference)
                reference = report['cross_validation']['reference']
                observed.add(report['cross_validation']['observed_branch'])
        self.assertEqual(observed, {'00', '01', '10', '11'})
        matrices = [decode_dm(b['usable']['density_matrix']) for b in reference['branches'].values()]
        self.assertGreater(max(np.max(np.abs(matrices[0] - m)) for m in matrices[1:]), 0.01)

    def test_outcome_distribution_against_exact_probabilities(self):
        baseline = self.execute(name='p2-distribution-reference')
        reference = baseline['cross_validation']['reference']
        counts = {key: 0 for key in reference['branches']}
        sample_dm = np.zeros((4, 4), dtype=complex)
        samples = 256
        for seed in range(samples):
            # Native noise는 DM의 기대 상태로 계산한다. 반복 실행에서 달라지는 것은 BSM 표본이다.
            report = P2FederationManager(dict(seed=seed)).run(reference)
            counts[report['cross_validation']['observed_branch']] += 1
            sample_dm += decode_dm(report['snapshot']['ab_pair']['density_matrix']) / samples
        # 네 범주를 동시에 검사하는 Hoeffding union bound, 유의수준 1%.
        tolerance = math.sqrt(math.log(8 / 0.01) / (2 * samples))
        for key in counts:
            self.assertLessEqual(abs(counts[key] / samples - reference['branches'][key]['probability']), tolerance)
        expected_dm = decode_dm(reference['ensemble']['density_matrix'])
        # 각 분기의 상태는 이미 정확히 비교했다. 표본 평균 오차는 빈도 오차의 합으로 제한된다.
        self.assertLessEqual(float(np.max(np.abs(sample_dm - expected_dm))), 4 * tolerance)
        evidence = dict(samples=samples, seed_range=[0, samples - 1], counts=counts,
                        expected_probabilities={k: v['probability'] for k, v in reference['branches'].items()},
                        probability_tolerance=tolerance, familywise_alpha=0.01,
                        ensemble_max_density_matrix_error=float(np.max(np.abs(sample_dm - expected_dm))), passed=True)
        (MODULE / 'results/tests/p2-outcome-distribution.json').write_text(json.dumps(evidence, indent=2) + '\n')

    def test_result_delay_changes_only_post_bsm_aging(self):
        baseline = self.execute(name='p2-result-delay-base')
        delayed = self.execute(name='p2-result-delay-long', result_link=dict(rate_bps=10000000, delay_ns=5000000))
        for key in ('bsm_start', 'bsm_end_inputs', 'frame'):
            self.assertEqual(baseline['snapshot']['checkpoints'][key], delayed['snapshot']['checkpoints'][key])
        self.assertEqual(delayed['session_completion_ns'] - baseline['session_completion_ns'], 4800000)
        self.assertGreater(np.max(np.abs(decode_dm(baseline['snapshot']['ab_pair']['density_matrix']) -
                                         decode_dm(delayed['snapshot']['ab_pair']['density_matrix']))), 0.01)

    def test_command_delay_and_bsm_duration_age_inputs(self):
        baseline = self.execute(name='p2-command-delay-base')
        delayed = self.execute(name='p2-command-delay-long', command_link=dict(rate_bps=100000000, delay_ns=5000000))
        longer_bsm = self.execute(name='p2-bsm-long', bsm_duration_ns=5000000)
        self.assertEqual(baseline['snapshot']['checkpoints']['bsm_start'], longer_bsm['snapshot']['checkpoints']['bsm_start'])
        for pair in ('AR', 'RB'):
            self.assertLess(delayed['snapshot']['checkpoints']['bsm_start'][pair]['fidelity'],
                            baseline['snapshot']['checkpoints']['bsm_start'][pair]['fidelity'])
            self.assertLess(longer_bsm['snapshot']['checkpoints']['bsm_end_inputs'][pair]['fidelity'],
                            baseline['snapshot']['checkpoints']['bsm_end_inputs'][pair]['fidelity'])

    def test_correction_duration_including_00_ages_memories(self):
        reference = None
        baseline = None
        for seed in range(32):
            candidate = P2FederationManager(dict(seed=seed)).run(reference)
            reference = candidate['cross_validation']['reference']
            if candidate['cross_validation']['observed_branch'] == '00':
                baseline = candidate
                break
        self.assertIsNotNone(baseline)
        longer = self.execute(name='p2-correction-00-long', seed=seed, correction_duration_ns=5000000)
        self.assertEqual(longer['cross_validation']['observed_branch'], '00')
        self.assertEqual(baseline['snapshot']['checkpoints']['correction_start'], longer['snapshot']['checkpoints']['correction_start'])
        self.assertGreater(np.max(np.abs(decode_dm(baseline['snapshot']['ab_pair']['density_matrix']) -
                                         decode_dm(longer['snapshot']['ab_pair']['density_matrix']))), 0.01)

    def test_reference_rejects_wrong_branch_state(self):
        report = self.execute(name='p2-negative-branch')
        corrupted = copy.deepcopy(report['cross_validation']['reference'])
        key = report['cross_validation']['observed_branch']
        other = next(k for k in corrupted['branches'] if k[1] != key[1])
        corrupted['branches'][key]['usable'] = corrupted['branches'][other]['usable']
        with self.assertRaisesRegex(RuntimeError, 'checkpoint mismatch: usable'):
            compare_reference(report, corrupted)

    def test_reference_rejects_wrong_checkpoint_time(self):
        report = self.execute(name='p2-negative-time')
        report['snapshot']['checkpoints']['bsm_start']['AR']['sim_time_ns'] += 1
        with self.assertRaisesRegex(RuntimeError, 'checkpoint timing'):
            validate_report(report)

    def test_sweep_outputs_and_rejects_missing_condition(self):
        spec = dict(scenario={}, command_delays_ns=[100000, 1000000], result_delays_ns=[200000, 1000000])
        with tempfile.TemporaryDirectory(prefix='cosim-p2-sweep-') as directory:
            summary = run_sweep(spec, directory)
            self.assertTrue(summary['validation']['passed'])
            self.assertEqual(len(summary['rows']), 8)
            self.assertEqual(len((Path(directory) / 'summary.csv').read_text().splitlines()), 9)
            for row in summary['rows']:
                self.assertTrue((Path(directory) / row['report']).is_file())
            with self.assertRaisesRegex(RuntimeError, 'incomplete'):
                validate_sweep(summary['rows'][:-1], spec['command_delays_ns'], spec['result_delays_ns'])


class P2QuantumGuards(unittest.TestCase):
    def test_native_model_attachment_and_p1_freeze(self):
        quantum, _ = make_quantum(normalize_config({}))
        for memory, position in quantum.memories.values():
            model = memory.mem_positions[position].models['noise_model']
            self.assertIs(type(model), T1T2NoiseModel)
            self.assertEqual((model.T1, model.T2), (20000000, 10000000))
        manifest = json.loads((MODULE / 'baselines/p1-freeze.json').read_text())
        for name, digest in manifest['files'].items():
            if '/results/' in name:
                continue  # 결과 재생성은 허용하되 P0/P1 소스·테스트·명세는 보존한다.
            self.assertEqual(hashlib.sha256((MODULE.parents[1] / name).read_bytes()).hexdigest(), digest, name)

    def test_access_and_boundary_partition_invariance(self):
        ordinary = execute_quantum()
        subdivided = execute_quantum(subdivide=True)
        for stage in ('frame', 'correction_start', 'usable'):
            np.testing.assert_allclose(decode_dm(ordinary['snapshot']['checkpoints'][stage]['density_matrix']),
                decode_dm(subdivided['snapshot']['checkpoints'][stage]['density_matrix']), atol=1e-12, rtol=0)
        self.assertEqual(ns.sim_count_events(), 0)
        self.assertTrue(compare_reference(subdivided)['passed'])

    def test_reference_detects_missing_packet_interval_noise(self):
        broken = execute_quantum(skip_packet_aging=True)
        with self.assertRaisesRegex(RuntimeError, 'checkpoint mismatch: correction_start'):
            compare_reference(broken)

    def test_parameter_and_scope_guards(self):
        for changes in (dict(T1_ns=100, T2_ns=200), dict(T1_ns=-1), dict(T2_ns=0.5),
                        dict(T1_ns=True), dict(model='custom'), dict(extra=1)):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                normalize_config(dict(memory_noise=dict(DEFAULT_NOISE, **changes)))
        for config in (dict(background_traffic=True), dict(sessions=2), dict(noise=True),
                       dict(result_replays=[dict(delay_ns=0)]), dict(memory_noise=None)):
            with self.subTest(config=config), self.assertRaises(ValueError):
                normalize_config(config)

    def test_t1_only_t2_only_and_strong_aging(self):
        for t1, t2 in ((20000000, 0), (0, 10000000), (1, 1)):
            with self.subTest(T1=t1, T2=t2):
                report = execute_quantum(memory_noise=dict(model='T1T2NoiseModel', T1_ns=t1, T2_ns=t2))
                self.assertTrue(compare_reference(report)['passed'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
