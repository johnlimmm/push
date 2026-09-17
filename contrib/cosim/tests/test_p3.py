"""P3: FIFO와 aging의 결합, session-local ID, 실제 무경합 packet 경로를 검증한다."""

import copy
import hashlib
import json
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
from p2_reference_validation import compare_reference
from p2_validation import decode_dm
from p3_config import analytic_timing, normalize_config
from p3_quantum import P3Quantum
from p3_validation import cross_validate, validate_report
from run_p2 import P2FederationManager
from run_p3 import P3FederationManager
from run_p3_sweep import run_sweep


def make_quantum(raw=None):
    config = normalize_config(raw or {})
    log = EventLog(0)
    roots = {s['session_id']: log.add('SESSION_CREATED', 0, session_id=s['session_id']) for s in config['sessions']}
    return P3Quantum(config, log, roots), roots


def message(sid, **fields):
    return dict(session_id=sid, request_id=1, pair_a=1, pair_b=2, output_pair_id=3, **fields)


def execute_quantum(subdivide=False, skip_waiting=False):
    """입출력 시각을 유지하고 경계 분할과 의도적인 대기 aging 누락을 검사한다."""
    q, roots = make_quantum()
    times = analytic_timing(q.config)
    pending = [(t['command_receive_ns'], 'bsm', int(sid), message(int(sid))) for sid,t in times.items()]
    while pending or q.next_safe_horizon() is not None:
        pending.sort(key=lambda row: row[0])
        candidates = ([pending[0][0]] if pending else []) + ([q.next_safe_horizon()] if q.next_safe_horizon() is not None else [])
        at = min(candidates)
        if subdivide:
            for t in sorted({q.now_ns + (at-q.now_ns)*i//4 for i in (1,2,3)}):
                if t == q.now_ns:
                    continue
                q.advance_to_boundary(t)
                for sid, session in q.sessions.items():
                    if not session['ab_pair']:
                        q.input_states(sid)
                    elif session['ab_pair']['state'] != 'USABLE':
                        q.frame_state(sid)
                q.snapshot()
        completed = q.advance_to_boundary(at)
        for result in completed:
            sid = q.rid_to_sid[result['request_id']]
            pending.append((at+288000, 'correction', sid, message(sid,m1=result['m1'],m2=result['m2'])))
        due = [row for row in pending if row[0] == at]
        pending = [row for row in pending if row[0] != at]
        for _,kind,sid,row in due:
            (q.submit_bsm if kind == 'bsm' else q.submit_correction)(row, roots[sid])
        p = q.processors[2]
        if skip_waiting and p['running'] is None and p['queue']:
            rid = p['queue'][0]
            if q.requests[rid]['arrival_ns'] < at:
                # 의도적 bridge 버그: 대기 종료 시 noise 없이 접근해 저장 이력을 잃는다.
                session = q.sessions[q.rid_to_sid[rid]]
                q.a_memory.peek(session['slot'], skip_noise=True)
                q.b_processor.peek(session['slot'], skip_noise=True)
                p['device'].peek([2*session['slot'], 2*session['slot']+1], skip_noise=True)
        q.schedule_queued()
        q.check_invariants()
    return dict(config=q.config, snapshot=q.snapshot())


class P3IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = P3FederationManager({}).run()
        directory = MODULE/'results/tests'
        directory.mkdir(parents=True, exist_ok=True)
        (directory/'p3-basic.json').write_text(json.dumps(cls.baseline,indent=2,sort_keys=True)+'\n')

    def test_fifo_metrics_and_reference(self):
        report = self.baseline
        self.assertEqual([s['quantum_wait_ns'] for s in report['metrics']['sessions']], [0,1200000,2400000,3600000])
        proc = report['metrics']['processor']
        self.assertEqual((proc['max_queue_length'],proc['queue_area_ns'],proc['utilization']), (3,7200000,1))
        self.assertEqual(proc['time_average_queue_length'], 1.125)
        self.assertEqual(report['batch_completion_ns'], 8298080)
        self.assertLessEqual(report['cross_validation']['max_density_matrix_error'], 1e-12)
        self.assertTrue(validate_report(json.loads(json.dumps(report)))['passed'])
        for sid,snap in report['snapshot']['sessions'].items():
            self.assertTrue(compare_reference(dict(config=report['config'],snapshot=snap),
                report['cross_validation']['sessions'][sid]['reference'])['passed'])

    def test_zero_noise_preserves_timing_and_bell_state(self):
        off = P3FederationManager(dict(memory_noise=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0))).run()
        self.assertEqual(off['bridge_steps'],self.baseline['bridge_steps'])
        for session in off['snapshot']['sessions'].values():
            self.assertAlmostEqual(session['ab_pair']['fidelity'],1,places=12)

    def test_one_session_matches_frozen_p2(self):
        p2 = P2FederationManager({}).run()
        p3 = P3FederationManager(dict(sessions=[dict(session_id=1,command_time_ns=1000000)])).run()
        for stage, expected in p2['snapshot']['checkpoints'].items():
            self.assertEqual(p3['snapshot']['sessions']['1']['checkpoints'][stage],expected)
        self.assertEqual(p3['bridge_steps'],p2['bridge_steps'])

    def test_same_time_completion_prioritizes_older_queued_session(self):
        sessions = [dict(session_id=s,command_time_ns=t) for s,t in ((1,1000000),(2,1400000),(3,2600000))]
        report = P3FederationManager(dict(sessions=sessions)).run()
        self.assertEqual([r['quantum_wait_ns'] for r in report['metrics']['sessions']], [0,1200000,1600000])
        at = 2710080
        kinds = [(e['session_id'],e['event_type']) for e in report['events'] if e['sim_time_ns']==at]
        self.assertLess(kinds.index((1,'BSM_COMPLETE')),kinds.index((3,'BSM_RECEIVED')))
        self.assertLess(kinds.index((3,'BSM_QUEUED')),kinds.index((2,'BSM_START')))

    def test_fifo_uses_arrival_not_session_id_or_config_order(self):
        sessions = [dict(session_id=s,command_time_ns=t) for s,t in ((8,2200000),(99,1000000),(2,1800000),(2**63-1,1400000))]
        report = P3FederationManager(dict(sessions=sessions)).run()
        self.assertEqual([e['session_id'] for e in report['events'] if e['event_type']=='BSM_START'], [99,2**63-1,2,8])
        self.assertEqual({e['request_id'] for e in report['events'] if e['event_type']=='BSM_START'},{1})

    def test_sparse_arrivals_have_idle_processor_and_no_queue(self):
        config = dict(sessions=[dict(session_id=i+1,command_time_ns=1000000+i*3200000) for i in range(4)])
        report = P3FederationManager(config).run()
        p = report['metrics']['processor']
        self.assertEqual(p['max_queue_length'],0)
        self.assertEqual(p['queue_area_ns'],0)
        self.assertAlmostEqual(p['utilization'],6400000/11200000)

    def test_all_branches_across_multi_session_runs(self):
        observed = set()
        for seed in range(8):
            report = P3FederationManager(dict(seed=seed)).run()
            observed.update(c['observed_branch'] for c in report['cross_validation']['sessions'].values())
        self.assertEqual(observed,{'00','01','10','11'})

    def test_native_aging_and_no_wait_counterfactual(self):
        report = self.baseline
        for sid,snap in report['snapshot']['sessions'].items():
            baseline = report['cross_validation']['no_wait_baselines'][sid]
            waited = snap['requests']['1']['start_ns']-snap['requests']['1']['arrival_ns']
            self.assertEqual(baseline['removed_wait_ns'],waited)
            self.assertEqual(baseline['input_timing']['bsm_start_ns'],snap['requests']['1']['arrival_ns'])
            self.assertEqual(baseline['input_timing']['correction_completion_ns']+waited,snap['correction']['completion_ns'])
            if waited:
                before=decode_dm(snap['checkpoints']['arrival']['AR']['density_matrix'],('A','R_AR'))
                after=decode_dm(snap['checkpoints']['bsm_start']['AR']['density_matrix'],('A','R_AR'))
                self.assertGreater(np.max(np.abs(before-after)),0.01)
        self.assertEqual(report['snapshot']['sessions']['1']['ab_pair']['usable_ns'],3498080)
        self.assertAlmostEqual(report['snapshot']['sessions']['1']['ab_pair']['fidelity'],0.534522155608756)

    def test_classical_or_correction_contention_rejected(self):
        cases = [dict(sessions=[dict(session_id=1,command_time_ns=1000000),dict(session_id=2,command_time_ns=1000000)]),
                 dict(result_link=dict(rate_bps=100000,delay_ns=200000)),dict(correction_duration_ns=3000000)]
        for case in cases:
            with self.subTest(case=case),self.assertRaisesRegex(RuntimeError,'queue present'):
                P3FederationManager(case).run()

    def test_corrupted_resource_causality_and_metrics_rejected(self):
        for corruption in ('location','parent','queue','metrics','timestamp','state'):
            broken = copy.deepcopy(self.baseline)
            if corruption=='location':
                broken['snapshot']['sessions']['2']['resources']['1']['locations'][0]['position']=0
            elif corruption=='parent':
                child=next(e for e in broken['events'] if e['session_id']==2 and e['event_type']=='BSM_START')
                child['caused_by_event_id']=next(e['event_id'] for e in broken['events'] if e['session_id']==1 and e['event_type']=='BSM_START')
            elif corruption=='queue':
                next(s for s in broken['queue_samples'] if s['waiting_sessions'])['waiting_sessions']=[]
            elif corruption=='metrics':
                broken['metrics']['processor']['busy_ns']+=1
            elif corruption=='timestamp':
                broken['snapshot']['sessions']['2']['checkpoints']['bsm_start']['AR']['sim_time_ns']+=1
            else:
                next(e for e in broken['events'] if e['event_type']=='BSM_QUEUED')['resource_state']['1']='AVAILABLE'
            with self.subTest(corruption=corruption),self.assertRaises(RuntimeError):
                validate_report(broken)

    def test_sweep_files_and_noise_on_off(self):
        spec=dict(scenario={},session_count=2,arrival_intervals_ns=[400000,3200000])
        with tempfile.TemporaryDirectory(prefix='cosim-p3-') as directory:
            summary=run_sweep(spec,directory)
            self.assertEqual(summary['validation']['batches'],4)
            self.assertEqual(summary['validation']['transactions'],8)
            self.assertEqual(len((Path(directory)/'summary.csv').read_text().splitlines()),9)
            self.assertTrue(all((Path(directory)/row['report']).is_file() for row in summary['rows']))


class P3QuantumGuards(unittest.TestCase):
    def test_native_devices_positions_and_p2_freeze(self):
        q,_=make_quantum()
        self.assertEqual(len(q.processors),1)
        self.assertEqual([len(d.mem_positions) for d in (q.a_memory,q.processors[2]['device'],q.b_processor)],[4,8,4])
        for device in (q.a_memory,q.processors[2]['device'],q.b_processor):
            for position in device.mem_positions:
                self.assertIs(type(position.models['noise_model']),T1T2NoiseModel)
        manifest=json.loads((MODULE/'baselines/p2-freeze.json').read_text())
        for name,digest in manifest['files'].items():
            if not name.startswith('results/'):
                self.assertEqual(hashlib.sha256((MODULE/name).read_bytes()).hexdigest(),digest,name)

    def test_duplicates_and_invalid_ids_do_not_cross_sessions(self):
        q,roots=make_quantum()
        q.advance_to_boundary(1000000)
        for sid in (1,2):
            self.assertEqual(q.submit_bsm(message(sid),roots[sid]),'OK')
        self.assertEqual(q.submit_bsm(message(1),roots[1]),'DUPLICATE')
        wrong=message(1);wrong['pair_b']=4
        self.assertEqual(q.submit_bsm(wrong,roots[1]),'INVALID_RESOURCE_IDENTITY')
        self.assertEqual(len(q.processors[2]['queue']),2)
        q.schedule_queued()
        self.assertEqual(q.submit_bsm(message(1),roots[1]),'DUPLICATE')
        q.advance_to_boundary(2600000)
        m=q.outputs[1]
        self.assertEqual(q.submit_correction(message(2,m1=m['m1'],m2=m['m2']),roots[2]),'INVALID_RESULT')
        valid=message(1,m1=m['m1'],m2=m['m2'])
        self.assertEqual(q.submit_correction(valid,roots[1]),'OK')
        self.assertEqual(q.submit_correction(valid,roots[1]),'DUPLICATE')
        self.assertEqual(q.submit_correction(dict(valid,m1=m['m1']^1),roots[1]),'RESULT_MISMATCH')
        q.schedule_queued()
        q.advance_to_boundary(3100000)
        self.assertEqual(q.sessions[1]['correction_count'],1)
        self.assertEqual(q.sessions[2]['correction_count'],0)
        self.assertEqual(q.submit_correction(valid,roots[1]),'DUPLICATE')
        self.assertEqual(q.sessions[1]['correction_count'],1)
        q.check_invariants()

    def test_boundary_partition_preserves_session_states(self):
        ordinary=execute_quantum()
        divided=execute_quantum(subdivide=True)
        for sid,snap in ordinary['snapshot']['sessions'].items():
            for stage in ('frame','correction_start','usable'):
                np.testing.assert_allclose(decode_dm(snap['checkpoints'][stage]['density_matrix']),
                    decode_dm(divided['snapshot']['sessions'][sid]['checkpoints'][stage]['density_matrix']),atol=1e-12,rtol=0)
        self.assertTrue(cross_validate(divided)['passed'])
        self.assertEqual(ns.sim_count_events(),0)

    def test_reference_detects_lost_queue_aging(self):
        broken=execute_quantum(skip_waiting=True)
        with self.assertRaisesRegex(RuntimeError,'reference checkpoint mismatch: bsm_start'):
            cross_validate(broken)

    def test_scope_and_time_guards(self):
        for raw in (dict(sessions=[]),dict(sessions=[dict(session_id=1,command_time_ns=0)]*2),
                    dict(sessions=[dict(session_id=True,command_time_ns=0)]),dict(background_traffic=True),
                    dict(session_id=1),dict(sessions=[dict(session_id=1,command_time_ns=2**53-1)]),
                    dict(sessions=[dict(session_id=1,command_time_ns=0,created_ns=2)])):
            with self.subTest(raw=raw),self.assertRaises(ValueError):
                normalize_config(raw)
        q,roots=make_quantum()
        with self.assertRaisesRegex(ValueError,'unknown BSM session'):
            q.submit_bsm(message(99),roots[1])
        with self.assertRaisesRegex(ValueError,'unknown correction session'):
            q.submit_correction(message(99,m1=0,m2=0),roots[1])


if __name__=='__main__':
    unittest.main(verbosity=2)
