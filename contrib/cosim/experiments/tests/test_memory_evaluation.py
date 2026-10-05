import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import numpy as np

MODULE=Path(__file__).resolve().parents[2]
sys.path[:0]=[str(MODULE/'experiments'),str(MODULE/'python')]
from run_memory_evaluation import workload, validate_plan, timing_signature
from literature_chained import ChainedManager
from literature_validation import cross_validate_chained
from literature_reference_client import close_workers


class MemoryEvaluationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan=json.loads((MODULE/'scenarios/memory-evaluation.json').read_text())

    def tearDown(self):
        close_workers()

    def test_incomplete_input_coverage_is_rejected(self):
        for states in (['0','1','+','-','+i'],['0','1','+','-','+i','+i']):
            bad=copy.deepcopy(self.plan);bad['input_states']=states
            with self.assertRaises(ValueError):validate_plan(bad)

    def test_old_memory_profile_and_seed_leak_are_rejected(self):
        bad=copy.deepcopy(self.plan);bad['memory_noise']['T2_ns']=1000000000
        with self.assertRaises(ValueError):validate_plan(bad)
        bad=copy.deepcopy(self.plan);bad['calibration_traffic_seeds']=[1000]
        with self.assertRaises(ValueError):validate_plan(bad)

    def test_six_inputs_keep_actual_timing_but_have_distinct_fidelity(self):
        signatures=[];fidelities={}
        for state in self.plan['input_states']:
            cfg=workload(self.plan,13703,.5,1000,True)
            cfg['chains']=cfg['chains'][:1];cfg['chains'][0]['input_state']=state
            r=ChainedManager(cfg).run(enumerate_branches=True)
            self.assertTrue(r['validation']['passed'])
            self.assertLess(r['cross_validation']['max_density_matrix_error'],1e-12)
            signatures.append(timing_signature(r))
            fidelities[state]=r['cross_validation']['chains']['1']['reference']['expected_fidelity']
        self.assertTrue(all(s==signatures[0] for s in signatures))
        self.assertGreater(fidelities['0'],fidelities['1'])
        self.assertAlmostEqual(fidelities['+i'],fidelities['-i'],places=12)

    def test_wrong_memory_cannot_pass_state_reference(self):
        cfg=workload(self.plan,27405,0,1000,True);cfg['chains']=cfg['chains'][:1]
        r=ChainedManager(cfg).run()
        r['config']['memory_noise'].update(T1_ns=36000000000000,T2_ns=1000000000)
        with self.assertRaisesRegex(RuntimeError,'reference state mismatch'):
            cross_validate_chained(r)

    def test_chained_reference_uses_native_squared_fidelity(self):
        from netsquid.qubits import qubitapi as qapi
        from literature_reference_chained import run_branch
        spec=dict(input_state='-i',memory_noise=self.plan['memory_noise'],
            quantum_links=self.plan['quantum_links'],native_instructions=self.plan['native_instructions'],
            gate_depolar_probability=.01,stages=[
                dict(bsm=dict(arrival_ns=2000000,start_ns=2000000,completion_ns=2027405),
                     correction=dict(arrival_ns=2150000,start_ns=2150000,completion_ns=2150010)),
                dict(bsm=dict(arrival_ns=2400000,start_ns=2400000,completion_ns=2427405),
                     correction=dict(arrival_ns=2650000,start_ns=2650000,completion_ns=2650010))])
        with patch.object(qapi,'fidelity',wraps=qapi.fidelity) as native:
            result=run_branch(spec,[(1,1),(1,0)])
            self.assertGreater(native.call_count,0)
            self.assertTrue(all(c[1].get('squared') is True for c in native.call_args_list))
        output=result['stages'][1]['checkpoints']['usable']
        rho=output['density_matrix'];dm=np.array(rho['real'])+1j*np.array(rho['imag'])
        target=np.array([1,-1j])/np.sqrt(2)
        self.assertAlmostEqual(output['fidelity'],float(np.real(target.conj()@dm@target)),places=12)

    def test_swapping_reference_uses_native_squared_fidelity(self):
        from netsquid.qubits import qubitapi as qapi
        from literature_reference_provisioned import run_branch
        spec=dict(protocol='swap',input_state='0',memory_noise=self.plan['memory_noise'],
            quantum_links=self.plan['quantum_links'],native_instructions=self.plan['native_instructions'],
            gate_depolar_probability=.01,bsm_start_ns=2000000,bsm_completion_ns=2027405,
            correction_arrival_ns=2150000,correction_start_ns=2150000,correction_completion_ns=2150010)
        with patch.object(qapi,'fidelity',wraps=qapi.fidelity) as native:
            result=run_branch(spec,(1,1))
            self.assertGreater(native.call_count,0)
            self.assertTrue(all(c[1].get('squared') is True for c in native.call_args_list))
        output=result['checkpoints']['usable']
        rho=output['density_matrix'];dm=np.array(rho['real'])+1j*np.array(rho['imag'])
        target=np.array([1,0,0,1])/np.sqrt(2)
        self.assertAlmostEqual(output['fidelity'],float(np.real(target.conj()@dm@target)),places=12)


if __name__=='__main__':unittest.main()
