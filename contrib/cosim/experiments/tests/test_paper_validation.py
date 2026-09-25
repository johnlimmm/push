"""Guard independent timing comparison and benchmark instrumentation semantics."""
import copy
import json
from pathlib import Path
import sys
import unittest

MODULE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MODULE/'experiments'))
from paper_timing import workload, run_core, run_native, compare, replay_production_trace
from paper_scaling import run_once, scenario, statistics
from run_hybrid import HybridManager


class PaperValidationTests(unittest.TestCase):
    def test_timing_boundary_and_all_arrival_patterns(self):
        for family in ('bsm', 'correction_hybrid', 'correction_p5b', 'variable_correction'):
            for pattern in ('idle', 'saturated', 'simultaneous', 'burst', 'boundary'):
                with self.subTest(family=family, pattern=pattern):
                    jobs = workload(8, pattern, family)
                    self.assertEqual(compare(run_core(jobs), run_native(jobs))['completion_ns'], 0)

    def test_native_duration_perturbation_is_detected(self):
        jobs = workload(4, 'saturated', 'bsm')
        with self.assertRaisesRegex(RuntimeError, 'timing mismatch'):
            compare(run_core(jobs), run_native(jobs, duration_offset=1))

    def test_same_timestamp_order_is_input_order_not_session_id(self):
        jobs = workload(8, 'simultaneous', 'bsm')
        expected = [j['session_id'] for j in jobs]
        self.assertNotEqual(expected, sorted(expected))
        for run in (run_core, run_native):
            self.assertEqual([r['session_id'] for r in run(jobs)], expected)

    def test_identity_correction_reserves_full_duration(self):
        jobs = workload(4, 'simultaneous', 'correction_hybrid')
        for run in (run_core, run_native):
            self.assertEqual([r['completion_ns'] for r in run(jobs)], [500000, 1000000, 1500000, 2000000])

    def test_corrupt_completion_order_is_detected(self):
        jobs = workload(4, 'simultaneous', 'bsm')
        native = run_native(jobs)
        native[0], native[1] = native[1], native[0]
        with self.assertRaisesRegex(RuntimeError, 'FIFO order'):
            compare(run_core(jobs), native)

    def test_instrumentation_preserves_full_production_report(self):
        plan = json.loads((MODULE/'scenarios/hybrid-paper-validation.json').read_text())
        cfg = scenario(plan, 4, .7)
        cache = {}
        measured, row = run_once(cfg, cache)
        production = HybridManager(cfg).run(cache)
        self.assertEqual(measured, production)
        for result in replay_production_trace(measured).values():
            self.assertEqual(result['max_absolute_error_ns']['completion_ns'], 0)
        self.assertEqual(row['counters']['completed_transactions'], 4)
        self.assertGreater(row['counters']['ipc_tx_lines'], row['counters']['synchronization_rounds'])
        self.assertGreater(row['offline_validation_seconds'], 0)
        self.assertAlmostEqual(row['simulation_seconds'], sum(row[k] for k in (
            'core_initialization_seconds', 'participant_startup_seconds',
            'federation_seconds', 'participant_finish_seconds')))

    def test_scaling_maximum_workload_and_repeat_statistics(self):
        plan = json.loads((MODULE/'scenarios/hybrid-paper-validation.json').read_text())
        cfg = scenario(plan, 64, .7)
        self.assertEqual(len(HybridManager(cfg).config['sessions']), 64)
        self.assertTrue(all(f['count'] <= 2000 for f in cfg['background'].values()))
        stats = statistics([2.0]*10, 1000)
        self.assertEqual(stats['ci95_repetition_bootstrap'], [2.0, 2.0])


if __name__ == '__main__':
    unittest.main()
