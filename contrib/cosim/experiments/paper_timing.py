"""Independent native timed-processor validation of the frozen atomic scheduler.

Only the workload is shared. The native dispatcher advances on QuantumProcessor
program-done callbacks, never on a predicted completion timestamp. This validates
timing under a specified capacity-one FIFO policy, not hardware durations or noisy
gate-level state equivalence. The core adapter below is a timing-test fixture.
"""
from collections import deque
import copy
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE / 'python'))
import netsquid as ns
import pydynaa
from netsquid.components import QuantumProcessor, PhysicalInstruction
from netsquid.components.instructions import INSTR_MEASURE_BELL, IGate
from netsquid.qubits import qubitapi as qapi
from hybrid_core import HybridExecutionCore


def now():
    value = ns.sim_time()
    if value != int(value):
        raise RuntimeError('non-integer native timestamp')
    return int(value)


def instruction(job):
    if job['operation'] == 'BSM':
        return INSTR_MEASURE_BELL
    z, x = job['bits']
    op = (ns.Z if z else ns.I) * (ns.X if x else ns.I)
    return IGate('correction_{}_{}'.format(job['duration_ns'], 2*z+x), op)


def workload(count, pattern, family):
    duration = {'bsm': 1600000, 'correction_hybrid': 500000,
                'correction_p5b': 50000, 'variable_correction': 500000}[family]
    jobs = []
    edge = [0, duration-1, duration, duration, duration+1, 2*duration, 2*duration+1]
    for i in range(count):
        arrival = {'idle': i*2*duration, 'saturated': i*(duration//2),
                   'simultaneous': 0, 'burst': (i//4)*5*duration,
                   'boundary': (i//len(edge))*4*duration+edge[i % len(edge)]}[pattern]
        bsm = family == 'bsm'
        jobs.append(dict(session_id=count-i, arrival_ns=arrival,
            operation='BSM' if bsm else 'CORRECTION', processor='R' if bsm else 'B',
            positions=[2*i, 2*i+1] if bsm else [i], bits=[(i//2) % 2, i % 2],
            duration_ns=50000 if family == 'variable_correction' and i % 2 else duration))
    return jobs


def timing_row(job, start, end):
    return dict(session_id=job['session_id'], operation=job['operation'],
                arrival_ns=job['arrival_ns'], start_ns=start, completion_ns=end,
                waiting_ns=start-job['arrival_ns'])


class TimingAdapter:
    protocol = 'atomic-timing-fixture'

    def __init__(self, core, job):
        self.core, self.job, self.sid = core, job, job['session_id']
        self.bits = job['bits']
        self.checkpoints = {'usable': {'fidelity': None}}
        targets = [(job['processor'], p) for p in job['positions']]
        core.register(self.sid, 'fixture', 'timing-fixture', targets,
                      'AVAILABLE' if job['operation'] == 'BSM' else 'FRAME_PENDING')
        core.devices[job['processor']].put(qapi.create_qubits(len(targets)),
                                            positions=job['positions'])

    def on_start(self, request):
        pass

    def on_complete(self, request):
        # State action still runs at completion through the production core.
        self.core.devices[self.job['processor']].execute_instruction(
            instruction(self.job), self.job['positions'], physical=False)


def run_core(jobs):
    config = dict(seed=7, memory_noise=dict(T1_ns=0, T2_ns=0),
                  sessions=[dict(session_id=j['session_id'], protocol='atomic-timing-fixture') for j in jobs])
    core = HybridExecutionCore(config)
    for j in jobs:
        core.adapters[j['session_id']] = TimingAdapter(core, j)
    core.drain()
    pending = deque(sorted(copy.deepcopy(jobs), key=lambda j: j['arrival_ns']))
    while pending or core.horizon() is not None:
        candidates = [t for t in (pending[0]['arrival_ns'] if pending else None, core.horizon()) if t is not None]
        at = min(candidates)
        core.advance(at)  # completion before same-time input, as in HybridFederation
        while pending and pending[0]['arrival_ns'] == at:
            j = pending.popleft()
            core.submit(core.adapters[j['session_id']], j['operation'], j['processor'],
                        ['fixture'], [(j['processor'], p) for p in j['positions']],
                        j['duration_ns'], core.roots[j['session_id']], j['bits'])
        core.dispatch()
    by_id = {j['session_id']: j for j in jobs}
    return [timing_row(by_id[r['session_id']], r['start_ns'], r['completion_ns'])
            for r in core.requests.values()]


class NativeFifo(pydynaa.Entity):
    def __init__(self, jobs, duration_offset=0):
        self.queue, self.active, self.rows = deque(), None, []
        self.arrivals = {}
        physical = {}
        self.ops = {}
        for j in jobs:
            key = (j['operation'], j['duration_ns'], tuple(j['bits']) if j['operation'] != 'BSM' else ())
            if key not in physical:
                op = instruction(j)
                physical[key] = PhysicalInstruction(op, duration=j['duration_ns']+duration_offset, parallel=False)
            self.ops[j['session_id']] = physical[key].instruction
        positions = max(max(j['positions']) for j in jobs)+1
        self.processor = QuantumProcessor('native-reference', num_positions=positions,
                                          phys_instructions=list(physical.values()))
        self.processor.put(qapi.create_qubits(positions))
        self.processor.set_program_done_callback(self.completed, once=False)
        self.processor.set_program_fail_callback(self.failed, once=False)
        event_type = pydynaa.EventType('ARRIVAL', 'Externally specified request arrival')
        self._wait(pydynaa.EventHandler(self.arrived), entity=self, event_type=event_type)
        # Native events at equal timestamps do not define our workload's tie
        # policy. One arrival batch per timestamp explicitly preserves input
        # order, independently of event insertion order in PyDynAA.
        batches = {}
        for job in sorted(jobs, key=lambda j: j['arrival_ns']):
            batches.setdefault(job['arrival_ns'], []).append(job)
        for at, batch in batches.items():
            self.arrivals[self._schedule_at(at, event_type)] = batch

    def failed(self):
        raise RuntimeError('native timed instruction failed: '+str(self.processor.fail_exception))

    def arrived(self, event):
        self.queue.extend(self.arrivals.pop(event))
        self.dispatch()

    def dispatch(self):
        if self.active is not None or not self.queue:
            return
        job = self.queue.popleft()
        self.active = (job, now())
        self.processor.execute_instruction(self.ops[job['session_id']], job['positions'], physical=True)

    def completed(self):
        job, start = self.active
        self.rows.append(timing_row(job, start, now()))
        self.active = None
        self.dispatch()


def run_native(jobs, duration_offset=0):
    ns.sim_reset()
    ns.set_qstate_formalism(ns.QFormalism.DM)
    ns.set_random_state(seed=7)
    native = NativeFifo(copy.deepcopy(jobs), duration_offset)
    ns.sim_run()
    if native.active is not None or native.queue or native.arrivals or len(native.rows) != len(jobs):
        raise RuntimeError('native workload did not drain')
    return native.rows


def compare(core, native):
    if [r['session_id'] for r in core] != [r['session_id'] for r in native]:
        raise RuntimeError('FIFO order mismatch')
    errors = {key: max(abs(a[key]-b[key]) for a, b in zip(core, native))
              for key in ('start_ns', 'completion_ns', 'waiting_ns')}
    if any(errors.values()):
        raise RuntimeError('timing mismatch: '+str(errors))
    return errors


def evaluate(plan):
    cases = []
    for family in ('bsm', 'correction_hybrid', 'correction_p5b', 'variable_correction'):
        for pattern in plan['timing_patterns']:
            for count in plan['session_counts']:
                jobs = workload(count, pattern, family)
                core, native = run_core(jobs), run_native(jobs)
                cases.append(dict(family=family, pattern=pattern, sessions=count,
                                  max_absolute_error_ns=compare(core, native),
                                  jobs=jobs, qucl=core, native=native))
    return dict(passed=True, native_version=ns.__version__, cases=cases,
                case_count=len(cases), requests=sum(c['sessions'] for c in cases),
                max_absolute_completion_error_ns=max(c['max_absolute_error_ns']['completion_ns'] for c in cases),
                scope='Capacity-one, nonpreemptive FIFO with stable input order at ties; noiseless physical Bell/Pauli instructions. Timing equivalence only.')


def replay_production_trace(report):
    """Replay arrivals from real mixed-protocol federation runs on native devices.

    Native timing receives only arrival, operation, targets and duration, not
    expected start/completion timestamps. Native state is a noiseless timing
    fixture and is deliberately not compared to the co-sim noisy state.
    """
    result = {}
    for processor in ('R', 'B'):
        requests = [r for r in report['snapshot']['requests'] if r['processor_id'] == processor]
        jobs = [dict(session_id=r['session_id'], arrival_ns=r['arrival_ns'],
                     operation=r['operation'], processor=processor,
                     positions=[position for _, position in r['targets']],
                     bits=r['bits'] or [0, 0], duration_ns=r['duration_ns']) for r in requests]
        actual = [timing_row(j, r['start_ns'], r['completion_ns']) for j, r in zip(jobs, requests)]
        native = run_native(jobs)
        result[processor] = dict(jobs=jobs, qucl=actual, native=native,
                                 max_absolute_error_ns=compare(actual, native))
    return result
