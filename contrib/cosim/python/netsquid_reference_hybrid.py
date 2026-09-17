#!/usr/bin/env python3
"""독립 검증기: co-sim을 import하지 않고 native memory + Bell projection으로 계산한다."""
import json
import sys
import numpy as np
import netsquid as ns
from netsquid.components import QuantumMemory
from netsquid.components.models.qerrormodels import T1T2NoiseModel
from netsquid.protocols import Protocol
from netsquid.qubits import qubitapi as qapi


def run_reference(spec):
    tele=spec['protocol']=='teleport';n=3 if tele else 4
    times=[spec[k] for k in ('bsm_start_ns','bsm_completion_ns','correction_arrival_ns','correction_start_ns','correction_completion_ns')]
    if any(type(t) is not int or not 0<=t<=2**53-1 for t in times) or times!=sorted(times):
        raise ValueError('invalid reference timestamps')
    if spec['epr_created_ns']!=0 or (tele and spec['input_created_ns']!=0): raise ValueError('requires t=0 preparation')
    noise=spec['memory_noise'];phi=np.array([1,0,0,1],complex)/np.sqrt(2)
    states={'0':[1,0],'1':[0,1],'+':[1,1],'-':[1,-1],'+i':[1,1j]}
    target=np.array(states[spec['input_state']],complex) if tele else phi.copy()
    target/=np.linalg.norm(target)
    ns.sim_reset();ns.set_qstate_formalism(ns.QFormalism.DM)
    memories={};branches={};inputs={};records=[]
    for bits in ('00','01','10','11'):
        qubits=qapi.create_qubits(n)
        if tele: qapi.assign_qstate(qubits[:1],target)
        for left,right in ([(1,2)] if tele else [(0,1),(2,3)]):
            qapi.operate(qubits[left],ns.H);qapi.operate([qubits[left],qubits[right]],ns.CNOT)
        memory=QuantumMemory('reference_'+bits,num_positions=n,memory_noise_models=[
            T1T2NoiseModel(T1=noise['T1_ns'],T2=noise['T2_ns']) for _ in range(n)])
        memory.put(qubits);memories[bits]=memory;branches[bits]={}
    def bell(bits):
        m1,m2=map(int,bits);v=np.zeros(4,complex)
        v[m2]=1/np.sqrt(2);v[2+(m2^1)]=(-1)**m1/np.sqrt(2)
        return v
    def encode(qubits,order,at,ref):
        dm=qapi.reduced_dm(qubits)
        return dict(sim_time_ns=at,fidelity=float(np.real(ref.conj()@dm@ref)),
                    density_matrix=dict(qubit_order=order,real=dm.real.tolist(),imag=dm.imag.tolist()))
    def initial(memory,at):
        qs=memory.peek(list(range(n)))
        if tele:
            return dict(input=encode(qs[:1],['input'],at,target),epr=encode(qs[1:],['Alice_EPR','B'],at,phi))
        return dict(AR=encode(qs[:2],['A','R_AR'],at,phi),RB=encode(qs[2:],['R_RB','B'],at,phi))
    def output(memory,bits,at,corrected=False):
        qs=memory.peek([2] if tele else [0,3]);ref=target
        m1,m2=map(int,bits)
        if not corrected:
            x=np.array([[0,1],[1,0]]);z=np.diag([1,-1])
            inverse=((z if m1 else np.eye(2))@(x if m2 else np.eye(2))).conj().T
            ref=(inverse if tele else np.kron(np.eye(2),inverse))@target
        return encode(qs,['B'] if tele else ['A','B'],at,ref)
    class Transaction(Protocol):
        def run(self):
            for stage,at in zip(['bsm_start','bsm_end_inputs','packet_arrival','correction_start','usable'],times):
                # packet arrival와 correction start가 같으면 새 0-delay timer 없이 이어서 처리한다.
                if at>ns.sim_time():
                    yield self.await_timer(at-ns.sim_time())
                if ns.sim_time()!=at: raise RuntimeError('reference clock mismatch')
                records.append(dict(event_type=stage,sim_time_ns=at))
                for bits,memory in memories.items():
                    branch=branches[bits]
                    if stage in ('bsm_start','bsm_end_inputs'):
                        observed=initial(memory,at)
                        if bits=='00': inputs[stage]=observed
                        if stage=='bsm_start': continue
                        qs=memory.peek(list(range(n)));rho=qapi.reduced_dm(qs);bra=bell(bits)
                        if tele:
                            conditional=np.einsum('i,ibjd,j->bd',bra.conj(),rho.reshape(4,2,4,2),bra)
                        else:
                            conditional=np.einsum('i,aibcjd,j->abcd',bra.conj(),rho.reshape(2,4,2,2,4,2),bra).reshape(4,4)
                        probability=float(np.real(np.trace(conditional)));branch['probability']=probability
                        for q in memory.pop([0,1] if tele else [1,2]): qapi.discard(q)
                        if probability>0:
                            survivors=[qs[2]] if tele else [qs[0],qs[3]]
                            qapi.assign_qstate(survivors,conditional/probability)
                            branch['frame']=output(memory,bits,at)
                    elif branch['probability']>0:
                        if stage=='usable':
                            qs=memory.peek([2] if tele else [0,3]);m1,m2=map(int,bits)
                            qapi.operate(qs[-1],(ns.Z if m1 else ns.I)*(ns.X if m2 else ns.I))
                        branch[stage]=output(memory,bits,at,stage=='usable')
    protocol=Transaction();protocol.start();ns.sim_run()
    return dict(model='independent-native-memory-Bell-projection',spec=spec,events=records,
                time_ns=int(ns.sim_time()),inputs=inputs,branches=branches)

if __name__=='__main__':
    json.dump(run_reference(json.load(sys.stdin)),sys.stdout,allow_nan=False)
    sys.stdout.write('\n')
