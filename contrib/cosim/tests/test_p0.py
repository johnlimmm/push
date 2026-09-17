"""실제 ns-3/NetSquid 두 프로세스로 P0 시간·자원 규칙을 검증한다.

FederationTests는 C++ 실행파일과 소켓까지 포함한 통합 검증이다.
GuardTests는 양자 어댑터의 잘못된 시간 진행 및 설정 거부를 확인한다.
무잡음·고정 실행시간 모델의 검증이며, 패킷 경로와 잡음 모델의 검증은 포함하지 않는다.
"""

import copy
import json
from pathlib import Path
import random
import sys
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))

from quantum_scheduler import MAX_TIME_NS, QuantumScheduler
from run_p0 import FederationManager


def submit(at, rid, a, b, duration=100, processor=0):
    """도착 시각 at(ns)에 두 EPR을 사용하는 BSM 요청을 만든다."""
    return dict(time_ns=at, request_id=rid, pair_a=a, pair_b=b,
                duration_ns=duration, processor_id=processor)


def cancel(at, rid):
    """요청 ID를 지정해 취소 입력을 만든다. 실행 중인 요청은 취소할 수 없다."""
    return dict(time_ns=at, type='CANCEL', request_id=rid)


def scenario(name, events, followups=None, count=12):
    """두 프로세서에 각각 count개의 EPR을 준비하는 공통 시나리오."""
    return dict(name=name, seed=7, processors=[0, 1], events=events,
                resources=[dict(pair_id=i, processor_id=0 if i <= count else 1)
                           for i in range(1, count * 2 + 1)], followups=followups or [])


class FederationTests(unittest.TestCase):
    """시간 동기화, FIFO, 자원 소유권, 중복·취소의 실제 연동 동작을 확인한다."""

    def execute(self, spec):
        """시나리오별 공통 불변조건을 확인하고 검토 가능한 JSON 기록을 남긴다."""
        report = FederationManager(spec).run()
        snapshot = report['snapshot']
        self.assertEqual(report['ns3_time_ns'], snapshot['time_ns'])
        self.assertEqual(snapshot['time_ns'], snapshot['netsquid_time_ns'])
        self.assertIs(type(json.loads(json.dumps(snapshot))['netsquid_time_ns']), int)
        times = [step['time_ns'] for step in report['bridge_steps']]
        self.assertEqual(times, sorted(times))
        for step in report['bridge_steps']:
            if step['quantum_horizon_ns'] is not None:
                self.assertLessEqual(step['time_ns'], step['quantum_horizon_ns'])
        # 측정 결과의 Pauli frame에 맞는 Bell 상태인지 검사한다.
        # frame_pending=True이므로 endpoint 보정까지 끝났다는 주장은 하지 않는다.
        for output in snapshot['outputs'].values():
            self.assertAlmostEqual(output['frame_fidelity'], 1, places=12)
            self.assertTrue(output['frame_pending'])
        for result in report['ns3_results']:
            if result['state'] == 'COMPLETED' and result['code'] == 'OK':
                self.assertEqual(result['time_ns'],
                                 snapshot['requests'][result['request_id']]['completion_ns'])
        directory = MODULE / 'results' / 'tests'
        directory.mkdir(parents=True, exist_ok=True)
        (directory / (spec['name'] + '.json')).write_text(
            json.dumps(report, indent=2, sort_keys=True) + '\n')
        return report

    def test_1_queue_ordering(self):
        """두 번째 요청은 첫 요청 완료까지 1 ms 대기하고, 자신의 실행시간도 전부 사용한다."""
        spec = scenario('queue-ordering', [
            submit(37400000, 101, 1, 2, 1600000),
            submit(38000000, 102, 3, 4, 1600000),
        ])
        report = self.execute(spec)
        requests = report['snapshot']['requests']
        self.assertEqual((requests[101]['start_ns'], requests[101]['completion_ns']),
                         (37400000, 39000000))
        self.assertEqual((requests[102]['start_ns'], requests[102]['completion_ns']),
                         (39000000, 40600000))
        self.assertEqual(requests[102]['start_ns'] - requests[102]['arrival_ns'], 1000000)
        # 같은 seed와 입력으로 다시 실행하면 측정 비트까지 포함한 기록이 같아야 한다.
        again = self.execute(spec)
        self.assertEqual(report, again)

    def test_2_same_timestamp(self):
        """같은 시각에는 양자 완료 → 모든 입력 접수 → 새 작업 시작 순서를 지킨다."""
        report = self.execute(scenario('same-timestamp', [
            submit(100, 1, 1, 2), submit(200, 2, 3, 4), submit(200, 3, 5, 6)]))
        events = [(e['event'], e.get('request_id')) for e in report['quantum_events']]
        self.assertLess(events.index(('COMPLETED', 1)), events.index(('RECEIVED', 2)))
        self.assertLess(events.index(('RECEIVED', 3)), events.index(('RUNNING', 2)))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[2]['start_ns'], 200)
        self.assertEqual(requests[3]['start_ns'], 300)

    def test_3_resource_collision_is_atomic(self):
        """두 번째 자원에서 충돌해도 첫 번째 자원을 부분 예약한 채 남기지 않는다."""
        report = self.execute(scenario('resource-collision', [
            submit(100, 1, 1, 2), submit(110, 2, 3, 1), submit(110, 3, 3, 4)]))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[2]['code'], 'RESOURCE_CONFLICT')
        self.assertEqual(requests[2]['state'], 'REJECTED')
        self.assertEqual(requests[3]['state'], 'COMPLETED')
        self.assertEqual(report['snapshot']['resources'][3]['owner'], 3)

    def test_4_independent_processors(self):
        """서로 다른 프로세서의 작업은 동시에 시작하고 각자의 완료 시각을 지킨다."""
        report = self.execute(scenario('independent-processors', [
            submit(100, 1, 1, 2, 300), submit(100, 2, 13, 14, 100, processor=1)]))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[1]['start_ns'], requests[2]['start_ns'])
        self.assertEqual(requests[2]['completion_ns'], 200)
        self.assertEqual(requests[1]['completion_ns'], 400)
        self.assertIn(200, [step['time_ns'] for step in report['bridge_steps']])

    def test_5_duplicate_and_id_reuse(self):
        """재전송은 같은 결과를 돌려주며, 같은 ID의 다른 내용은 거절하고 BSM은 한 번만 한다."""
        report = self.execute(scenario('duplicate-request', [
            submit(100, 1, 1, 2), submit(110, 1, 1, 2),
            submit(120, 1, 1, 2, 99), submit(300, 1, 1, 2)]))
        measured = [e for e in report['quantum_events'] if e['event'] == 'BSM_MEASURED']
        self.assertEqual(len(measured), 1)
        replies = report['ns3_results']
        self.assertTrue(any(r['code'] == 'REQUEST_ID_REUSE' for r in replies))
        duplicate = [r for r in replies if r['time_ns'] == 300][0]
        self.assertEqual(duplicate['state'], 'COMPLETED')
        self.assertEqual(duplicate['code'], 'DUPLICATE')
        self.assertEqual((duplicate['m1'], duplicate['m2']),
                         (measured[0]['m1'], measured[0]['m2']))

    def test_6_cancellation(self):
        """대기 취소는 자원을 반환하지만 실행 중 취소는 현재 작업에 영향을 주지 않는다."""
        report = self.execute(scenario('cancellation', [
            submit(100, 1, 1, 2), submit(110, 2, 3, 4), cancel(120, 2),
            submit(130, 3, 3, 4), submit(140, 2, 3, 4), cancel(150, 1)]))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[2]['state'], 'CANCELLED')
        self.assertIsNone(requests[2]['start_ns'])
        self.assertEqual(requests[1]['completion_ns'], 200)
        self.assertEqual(requests[3]['start_ns'], 200)
        self.assertTrue(any(r['code'] == 'NOT_CANCELLABLE' for r in report['ns3_results']))

    def test_cancel_at_completion_before_queue_dispatch(self):
        """프로세서가 비는 시각에 온 취소도 다음 대기 작업을 시작하기 전에 반영한다."""
        report = self.execute(scenario('cancel-at-boundary', [
            submit(100, 1, 1, 2), submit(110, 2, 3, 4),
            cancel(200, 2), submit(200, 3, 3, 4)]))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[2]['state'], 'CANCELLED')
        self.assertEqual(requests[3]['start_ns'], 200)

    def test_same_time_output_triggers_new_input(self):
        """완료 응답이 지연 없이 후속 요청을 만들어도 1 ns 보정 없이 같은 시각에 처리한다."""
        followup = submit(0, 2, 3, 4)
        del followup['time_ns']
        followup.update(after_request_id=1, delay_ns=0)
        report = self.execute(scenario('same-time-feedback', [submit(100, 1, 1, 2)], [followup]))
        requests = report['snapshot']['requests']
        self.assertEqual(requests[2]['arrival_ns'], 200)
        self.assertEqual(requests[2]['start_ns'], 200)
        self.assertEqual(requests[2]['completion_ns'], 300)
        self.assertGreaterEqual(sum(s['time_ns'] == 200 for s in report['bridge_steps']), 2)

    def test_delayed_output_triggers_new_input(self):
        """완료 결과 수신 50 ns 뒤의 후속 요청이 정확히 도착하고, 필요하면 FIFO에서 기다린다."""
        for busy in (False, True):
            with self.subTest(processor_busy=busy):
                followup = submit(0, 2, 3, 4)
                del followup['time_ns']
                followup.update(after_request_id=1, delay_ns=50)
                events = [submit(100, 1, 1, 2)]
                if busy:
                    # 원인 요청은 200 ns에 완료된다. 후속 요청이 250 ns에 도착하기 전에
                    # 다른 작업이 210~410 ns 동안 같은 프로세서를 점유하게 한다.
                    events.append(submit(210, 3, 5, 6, duration=200))
                name = 'delayed-feedback-busy' if busy else 'delayed-feedback'
                report = self.execute(scenario(name, events, [followup]))
                causes = [r for r in report['ns3_results']
                          if r['request_id'] == 1 and r['state'] == 'COMPLETED']
                arrivals = [r for r in report['ns3_inputs'] if r['request_id'] == 2]
                self.assertEqual(len(causes), 1)
                self.assertEqual(len(arrivals), 1)
                self.assertEqual(causes[0]['time_ns'], 200)
                self.assertEqual(arrivals[0]['time_ns'], causes[0]['time_ns'] + 50)
                request = report['snapshot']['requests'][2]
                self.assertEqual(request['arrival_ns'], 250)
                self.assertEqual(request['start_ns'], 410 if busy else 250)
                self.assertEqual(request['completion_ns'], 510 if busy else 350)
                # 사용 중이면 horizon=410 ns여도 ns-3 후속 입력을 250 ns에 먼저 처리한다.
                arrival_step = next(s for s in report['bridge_steps']
                                    if s['time_ns'] == 250 and s['inputs'] == 1)
                self.assertEqual(arrival_step['quantum_horizon_ns'], 410 if busy else None)

    def test_invalid_requests_leave_resources_available(self):
        """존재·위치·중복 쌍 검증에 실패한 요청은 자원 상태를 변경하지 않는다."""
        report = self.execute(scenario('invalid-requests', [
            submit(0, 1, 1, 1), submit(0, 2, 1, 99),
            submit(0, 3, 1, 2, processor=99), submit(0, 4, 1, 13)]))
        requests = report['snapshot']['requests']
        self.assertEqual([requests[i]['code'] for i in range(1, 5)],
                         ['INVALID_PAIR_SET', 'UNKNOWN_RESOURCE', 'UNKNOWN_PROCESSOR',
                          'RESOURCE_LOCATION'])
        self.assertTrue(all(r['state'] == 'AVAILABLE'
                            for r in report['snapshot']['resources'].values()))

    def test_randomized_fifo_matches_analytic_schedule(self):
        """무작위 도착·기간 30개를 프로세서별 독립 FIFO 계산 결과와 비교한다."""
        rng = random.Random(42)
        events = []
        expected = {}
        for i in range(30):
            processor = i % 2
            pair = (i // 2) * 2 + 1 + (40 if processor else 0)
            events.append(submit(rng.randrange(0, 1000), i + 1, pair, pair + 1,
                                 rng.randrange(1, 300), processor=processor))
        # 독립 기준식: 시작 = max(도착, 앞 작업 완료), 완료 = 시작 + 실행시간.
        # 안정 정렬은 동일 도착 시각의 초기 등록 순서를 보존한다.
        finish = {0: 0, 1: 0}
        for event in sorted(events, key=lambda e: e['time_ns']):
            pid = event['processor_id']
            start = max(finish[pid], event['time_ns'])
            finish[pid] = start + event['duration_ns']
            expected[event['request_id']] = (start, finish[pid])
        report = self.execute(scenario('randomized-fifo', events, count=40))
        for rid, times in expected.items():
            actual = report['snapshot']['requests'][rid]
            self.assertEqual((actual['start_ns'], actual['completion_ns']), times)


class GuardTests(unittest.TestCase):
    """제한된 P0 모델이 보장할 수 없는 진행과 설정을 조용히 허용하지 않는지 검사한다."""

    def test_time_reversal_and_unsafe_advance(self):
        """시간 역행과 다음 양자 완료를 건너뛰는 진행을 거부하고, 정확한 경계는 허용한다."""
        q = QuantumScheduler([0], [dict(pair_id=i, processor_id=0) for i in (1, 2)])
        q.advance_to_boundary(100)
        q.submit_request(submit(100, 1, 1, 2))
        q.schedule_queued()
        with self.assertRaisesRegex(ValueError, 'time reversal'):
            q.advance_to_boundary(99)
        with self.assertRaisesRegex(ValueError, 'safe horizon'):
            q.advance_to_boundary(201)
        q.advance_to_boundary(200)
        self.assertEqual(q.requests[1]['state'], 'COMPLETED')

    def test_overflow_and_noninteger_time(self):
        """소수 ns와 NetSquid의 정수 시간 정밀도를 넘는 완료 예약을 거부한다."""
        q = QuantumScheduler([0], [dict(pair_id=i, processor_id=0) for i in (1, 2)])
        with self.assertRaises(ValueError):
            q.advance_to_boundary(0.5)
        q.advance_to_boundary(MAX_TIME_NS - 10)
        reply = q.submit_request(submit(0, 1, 1, 2, 11))
        self.assertEqual(reply['code'], 'TIME_OVERFLOW')
        self.assertEqual(q.resources[1]['state'], 'AVAILABLE')
        q.advance_to_boundary(MAX_TIME_NS)
        stored_time = json.loads(json.dumps(q.snapshot()))['netsquid_time_ns']
        self.assertIs(type(stored_time), int)
        self.assertEqual(stored_time, MAX_TIME_NS)
        # native 시계의 이상을 보고서에서 반올림/절삭으로 숨기면 안 된다.
        for at in (0.5, float('nan'), float('inf'), -float('inf'), -1.0, float(MAX_TIME_NS + 1)):
            with self.subTest(native_time=at), patch('quantum_scheduler.ns.sim_time', return_value=at):
                with self.assertRaisesRegex(RuntimeError, 'exact integer nanoseconds'):
                    q.snapshot()

    def test_unsupported_model_is_rejected(self):
        """구현되지 않은 잡음을 설정하면 무잡음으로 실행하지 않고 오류를 낸다."""
        spec = scenario('unsupported', [])
        spec['noise'] = True
        with self.assertRaisesRegex(ValueError, 'unsupported P0'):
            FederationManager(spec)


if __name__ == '__main__':
    unittest.main(verbosity=2)
