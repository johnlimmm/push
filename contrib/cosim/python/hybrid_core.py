"""두 protocol이 공유하는 atomic 실행 core: clock, FIFO, 예약, 완료와 인과 로그.

protocol의 pair/qubit 의미는 adapters에 있다. core의 자원은 (session, handle)과
물리 memory position이다. 미래 native QuantumProgram/channel 이벤트는 아직 지원하지 않는다.
"""
from collections import deque
import copy

import netsquid as ns
from netsquid.components import QuantumMemory, QuantumProcessor
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from quantum_scheduler import MAX_TIME_NS, integer


class HybridExecutionCore:
    def __init__(self, config, r_capacity=1):
        ns.sim_reset()
        ns.set_qstate_formalism(ns.QFormalism.DM)
        ns.set_random_state(seed=config['seed'])
        self.config, self.now_ns = config, 0
        self.events, self.resources, self.requests = [], {}, {}
        self.adapters, self.roots = {}, {}
        self.round, self.phase = 0, 'INITIALIZE'
        n = len(config['sessions'])
        self.devices = {'A': QuantumMemory('A', num_positions=n),
                        'R': QuantumProcessor('R', num_positions=2*n),
                        'B': QuantumProcessor('B', num_positions=n)}
        noise = config['memory_noise']
        for device in self.devices.values():
            for position in device.mem_positions:
                position.models['noise_model'] = T1T2NoiseModel(T1=noise['T1_ns'], T2=noise['T2_ns'])
        integer(r_capacity, 'R execution capacity', 1, n)
        self.r_capacity = r_capacity
        self.processors = {name: dict(queue=deque(), running=[], capacity=r_capacity if name=='R' else 1)
                           for name in ('R','B')}
        for session in config['sessions']:
            self.roots[session['session_id']] = self.emit('SESSION_CREATED', session['session_id'],
                                                       protocol=session['protocol'])

    def emit(self, kind, sid, cause=None, **fields):
        event = dict(event_id='p:'+str(len(self.events)), sequence=len(self.events),
                     event_type=kind, sim_time_ns=self.now_ns, session_id=sid,
                     caused_by_event_id=cause, source='quantum', round=self.round, phase=self.phase)
        event.update(fields)
        self.events.append(event)
        return event['event_id']

    def import_rows(self, rows):
        for row in rows:
            self.events.append(dict(event_id=row['event_id'], sequence=len(self.events),
                event_type=row['event_type'], sim_time_ns=row['time_ns'], session_id=row['session_id'],
                caused_by_event_id=None if row['cause']=='-' else row['cause'], source='ns3',
                round=self.round, phase='NS3', details=copy.deepcopy(row)))

    def register(self, sid, handle, kind, locations, state='AVAILABLE'):
        key=(sid,handle)
        if key in self.resources:
            raise ValueError('resource handle reused')
        if len(set(locations)) != len(locations):
            raise ValueError('duplicate physical resource position')
        self.resources[key]=dict(session_id=sid, handle=handle, kind=kind,
            locations=list(locations), state=state, owner=None, created_ns=self.now_ns)
        return key

    def peek(self, location):
        return self.devices[location[0]].peek(location[1])[0]

    def drain(self):
        # put/pop와 physical=False가 만든 현재 시각 알림만 허용한다.
        ns.sim_run()
        if ns.sim_time()!=self.now_ns or ns.sim_count_events():
            raise RuntimeError('unsupported autonomous native events')

    def horizon(self):
        times=[r['completion_ns'] for r in self.requests.values() if r['state']=='RUNNING']
        return min(times) if times else None

    def submit(self, adapter, operation, processor, handles, targets, duration, cause, bits=None):
        if operation not in ('BSM', 'CORRECTION'):
            raise ValueError('unsupported atomic operation')
        sid=adapter.sid
        key=(sid,operation)
        if key in self.requests:
            old=self.requests[key]
            if old['bits'] != bits: raise ValueError('request reuse with different measurement bits')
            self.emit(operation+'_DUPLICATE',sid,cause,protocol=adapter.protocol)
            return False
        if processor not in self.processors or any(p!=processor for p,_ in targets):
            raise ValueError('operation targets must be local to processor')
        keys=[(sid,h) for h in handles]
        expected='AVAILABLE' if operation=='BSM' else 'FRAME_PENDING'
        owned=[]
        for resource in keys:
            r=self.resources[resource]
            if r['owner'] is not None or r['state']!=expected:
                raise ValueError('resource unavailable')
            owned.extend(r['locations'])
        if len(set(keys))!=len(keys) or not set(targets).issubset(owned):
            raise ValueError('invalid operation resources')
        active_locations={tuple(loc) for r in self.resources.values() if r['owner'] is not None for loc in r['locations']}
        if active_locations.intersection(owned): raise ValueError('physical resource conflict')
        integer(duration,'duration',1,MAX_TIME_NS)
        pending=sum(r['duration_ns'] for r in self.requests.values()
                    if r['processor_id']==processor and r['state'] in ('QUEUED','RUNNING'))
        if self.now_ns+pending+duration>MAX_TIME_NS: raise ValueError('operation time overflow')
        request=dict(session_id=sid,protocol=adapter.protocol,operation=operation,
            request_id=str(sid)+':'+operation,processor_id=processor,handles=list(handles),targets=list(targets),
            duration_ns=duration,arrival_ns=self.now_ns,start_ns=None,completion_ns=None,
            state='QUEUED',bits=copy.deepcopy(bits),cause=cause)
        self.requests[key]=request
        for k in keys: self.resources[k].update(state='RESERVED',owner=request['request_id'])
        request['cause']=self.emit(operation+'_QUEUED',sid,cause,request_id=request['request_id'],
                                  protocol=adapter.protocol,processor_id=processor,resource_handles=handles)
        self.processors[processor]['queue'].append(key)
        return True

    def dispatch(self):
        for processor,p in self.processors.items():
            while len(p['running']) < p['capacity'] and p['queue']:
                key=p['queue'].popleft(); r=self.requests[key]
                r.update(state='RUNNING',start_ns=self.now_ns,completion_ns=self.now_ns+r['duration_ns'])
                p['running'].append(key)
                for h in r['handles']: self.resources[(r['session_id'],h)]['state']='IN_USE'
                self.adapters[r['session_id']].on_start(r)
                r['cause']=self.emit(r['operation']+'_START',r['session_id'],r['cause'],
                    protocol=r['protocol'],request_id=r['request_id'],processor_id=processor,
                    resource_handles=r['handles'],waiting_ns=self.now_ns-r['arrival_ns'])
        self.check()

    def advance(self, at):
        integer(at,'boundary',0,MAX_TIME_NS)
        h=self.horizon()
        if at<self.now_ns or (h is not None and at>h): raise RuntimeError('unsafe quantum advance')
        if at>self.now_ns: ns.sim_run(end_time=at)
        self.now_ns=at
        completed=[]
        for processor,p in self.processors.items():
            for key in list(p['running']):
                r=self.requests[key]
                if r['completion_ns']!=at: continue
                adapter=self.adapters[r['session_id']]
                adapter.on_complete(r)
                for handle in r['handles']:
                    self.resources[(adapter.sid,handle)].update(owner=None,
                        state='CONSUMED' if r['operation']=='BSM' else 'USABLE')
                r['state']='COMPLETED';p['running'].remove(key)
                r['cause']=self.emit(r['operation']+'_COMPLETE',adapter.sid,r['cause'],
                    protocol=adapter.protocol,request_id=r['request_id'],processor_id=processor,
                    resource_handles=r['handles'],measurement_bits=adapter.bits,
                    fidelity=adapter.checkpoints['usable']['fidelity'] if r['operation']=='CORRECTION' else None)
                completed.append(dict(session_id=adapter.sid,operation=r['operation'],
                                      measurement_bits=adapter.bits,cause=r['cause']))
        self.drain();self.check()
        return completed

    def check(self):
        if ns.sim_time()!=self.now_ns or ns.sim_count_events(): raise RuntimeError('native clock mismatch')
        seen=set();locations=set()
        for name,p in self.processors.items():
            if len(p['running']) > p['capacity']: raise RuntimeError('processor capacity exceeded')
            for key in list(p['queue'])+p['running']:
                if key in seen: raise RuntimeError('request dispatched twice')
                seen.add(key);r=self.requests[key]
                if r['state']!=('RUNNING' if key in p['running'] else 'QUEUED') or r['processor_id']!=name:
                    raise RuntimeError('request/FIFO mismatch')
                for handle in r['handles']:
                    res=self.resources[(r['session_id'],handle)]
                    if res['owner']!=r['request_id'] or res['state']!=('IN_USE' if key in p['running'] else 'RESERVED'):
                        raise RuntimeError('resource ownership mismatch')
                    if locations.intersection(res['locations']): raise RuntimeError('resource positions overlap')
                    locations.update(res['locations'])
        if seen!={k for k,r in self.requests.items() if r['state'] in ('QUEUED','RUNNING')}:
            raise RuntimeError('orphaned request')

    def snapshot(self):
        self.check()
        return dict(time_ns=self.now_ns,netsquid_time_ns=int(ns.sim_time()),R_execution_capacity=self.r_capacity,
            requests=copy.deepcopy(list(self.requests.values())),resources=copy.deepcopy(list(self.resources.values())),
            sessions={str(sid):a.snapshot() for sid,a in self.adapters.items()})


class HybridFederation:
    """Swap/Teleport 모두 이 한 루프에서 완료→ns-3→입력→배정→완료 주입을 거친다."""
    def __init__(self, core, participant):
        self.core,self.participant=core,participant
        self.steps,self.rows=[],[]

    def run(self):
        c,p=self.core,self.participant
        while True:
            horizon=c.horizon()
            candidates=[t for t in (horizon,p.next_time) if t is not None]
            if not candidates: break
            if len(self.steps)>=100000: raise RuntimeError('federation step limit')
            at=min(candidates);c.round=len(self.steps);c.phase='COMMIT'
            completed=c.advance(at)
            rows=p.advance(at);self.rows.extend(rows);c.import_rows(rows)
            c.phase='INPUT'
            for row in rows:
                if row['event_type'] in ('BSM_REQUEST','CORRECTION_REQUEST'):
                    c.adapters[row['session_id']].receive(row)
            c.phase='DISPATCH';c.dispatch()
            p.inject(at,completed)
            if c.now_ns!=p.now_ns: raise RuntimeError('federation clock mismatch')
            self.steps.append(dict(time_ns=at,quantum_horizon_ns=horizon,
                ns3_next_ns=p.next_time,quantum_next_ns=c.horizon()))
        return c.snapshot()
