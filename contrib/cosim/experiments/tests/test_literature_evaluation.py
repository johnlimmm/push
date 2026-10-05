import copy
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import numpy as np

MODULE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(MODULE/'experiments'),str(MODULE/'python')]
import netsquid as ns
from netsquid.components import QuantumProcessor
from netsquid.components.instructions import INSTR_H, INSTR_CNOT
from netsquid.qubits import qubitapi as qapi
from literature_physics import INSTRUCTIONS, BSM_NS, install_gate_noise, split_config
from native_programs import IDLE_X
from run_literature_evaluation import workload
from literature_chained import ChainedManager
from run_chained import ChainedManager as FrozenManager
from literature_models import run_model, model_rows
from literature_validation import cross_validate_chained
import literature_reference_client as reference_client


class LiteratureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((MODULE/'scenarios/literature-evaluation.json').read_text())

    def device(self,p):
        ns.sim_reset();ns.set_qstate_formalism(ns.QFormalism.DM)
        d=QuantumProcessor('test',num_positions=2)
        core=SimpleNamespace(devices={'R':d},config=dict(native_instructions=INSTRUCTIONS,
            memory_noise=dict(T1_ns=0,T2_ns=0),gate_depolar_probability=p))
        install_gate_noise(core);return d

    def test_native_single_qubit_depolarization_parameter(self):
        d=self.device(.01);qs=qapi.create_qubits(1);d.put(qs,positions=[0])
        d.execute_instruction(INSTR_H,[0]);ns.sim_run()
        self.assertAlmostEqual(qapi.fidelity(d.peek([0]),ns.h0,squared=True),.995,places=12)
        self.assertEqual(ns.sim_time(),5)

    def test_two_qubit_noise_is_independent_per_operand(self):
        d=self.device(.01);qs=qapi.create_qubits(2);qapi.operate(qs[0],ns.H);d.put(qs)
        d.execute_instruction(INSTR_CNOT,[0,1]);ns.sim_run()
        self.assertAlmostEqual(qapi.fidelity(d.peek([0,1]),ns.b00,squared=True),.995**2,places=12)

    def test_idle_slot_has_no_gate_noise(self):
        d=self.device(1);d.put(qapi.create_qubits(1),positions=[0])
        d.execute_instruction(IDLE_X,[0]);ns.sim_run()
        np.testing.assert_allclose(qapi.reduced_dm(d.peek([0])),[[1,0],[0,0]],atol=1e-12)

    def test_invalid_gate_probability_rejected(self):
        for p in (-.1,1.01,float('nan'),True):
            with self.assertRaises(ValueError):split_config({'gate_depolar_probability':p})

    def test_reference_worker_rotation_preserves_states(self):
        cfg=workload(self.plan,2*BSM_NS,0,1000,True);cfg['chains']=cfg['chains'][:1]
        reference_client.close_workers()
        with patch.object(reference_client,'MAX_REQUESTS',1):
            first=ChainedManager(cfg).run(enumerate_branches=True)
            old=reference_client.WORKERS['chained'].pid
            second=ChainedManager(cfg).run(enumerate_branches=True)
            self.assertNotEqual(old,reference_client.WORKERS['chained'].pid)
            self.assertEqual(first['cross_validation'],second['cross_validation'])

    def test_zero_gate_noise_matches_existing_backend(self):
        cfg=workload(self.plan,2*BSM_NS,0,1000,True);cfg['chains']=cfg['chains'][:1]
        cfg['gate_depolar_probability']=0
        new=ChainedManager(cfg).run();oldcfg=copy.deepcopy(cfg);oldcfg.pop('gate_depolar_probability')
        old=FrozenManager(oldcfg).run()
        self.assertEqual(new['metrics'],old['metrics'])
        self.assertEqual(new['native_instructions'],old['native_instructions'])

    def test_chained_reference_and_wrong_noise_detected(self):
        cfg=workload(self.plan,BSM_NS,0,1000,True);cfg['chains']=cfg['chains'][:1]
        report=ChainedManager(cfg).run(enumerate_branches=True)
        self.assertLess(report['cross_validation']['max_density_matrix_error'],1e-12)
        self.assertEqual(len(report['cross_validation']['chains']['1']['reference']['branches']),16)
        bad=copy.deepcopy(report);bad['config']['gate_depolar_probability']=0
        with self.assertRaisesRegex(RuntimeError,'reference state mismatch'):cross_validate_chained(bad)

    def test_noncontending_no_dq_control(self):
        cfg=workload(self.plan,2*BSM_NS,.75,1000)
        full=run_model(cfg,'Full-Sync',{});nodq=run_model(cfg,'No-Dq-R',{})
        a=model_rows(full,.5,5000000);b=model_rows(nodq,.5,5000000)
        for x,y in zip(a,b):
            self.assertEqual(x['transaction_latency_ns'],y['transaction_latency_ns'])
            self.assertAlmostEqual(x['expected_fidelity'],y['expected_fidelity'],places=12)

    def test_intervals_and_zero_load_serialization_control(self):
        self.assertEqual(self.plan['request_intervals_ns'],[(BSM_NS+1)//2,BSM_NS,2*BSM_NS])
        cfg=workload(self.plan,(BSM_NS+1)//2,0,1000);cache={}
        full=run_model(cfg,'Full-Sync',cache)
        fixed=run_model(cfg,'Fixed-Dc',cache,dict(result_ns=108800))
        for a,b in zip(model_rows(full,.5,5000000),model_rows(fixed,.5,5000000)):
            self.assertEqual(a['transaction_latency_ns'],b['transaction_latency_ns'])
            self.assertAlmostEqual(a['expected_fidelity'],b['expected_fidelity'],places=12)


if __name__=='__main__':unittest.main()
