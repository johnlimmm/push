"""End-to-end Swap -> A/B Teleport validation; never recreates the swapped pair."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import unittest

MODULE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(MODULE/'python'))
from chained_config import normalize_config
from chained_validation import validate_report, cross_validate
from run_chained import ChainedManager
from run_hybrid import HybridValidationFailure
from run_provisioned import save_report

NOISE_OFF=dict(model='T1T2NoiseModel',T1_ns=0,T2_ns=0)
BRANCH_SEEDS=[0,1,2,3,5,6,10,11,14,15,16,25,26,29,33,49]
OUT=MODULE/'results/chained-tests'


def batch(interval=800000,count=4):
    return [dict(chain_id=i+1,session_start_ns=1000000+i*interval,input_state='+i') for i in range(count)]


class ChainedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        OUT.mkdir(parents=True,exist_ok=True)
        cls.single=ChainedManager({}).run(enumerate_branches=True)
        save_report(OUT/'single.json.gz',cls.single)

    def test_single_native_end_to_end(self):
        r=self.single
        self.assertTrue(r['validation']['passed'])
        self.assertLess(r['cross_validation']['max_density_matrix_error'],1e-12)
        self.assertEqual(r['metrics']['chains'][0]['completion_ns'],6612800)
        self.assertEqual(r['metrics']['chains'][0]['latency_ns'],5612800)
        self.assertEqual(len(r['snapshot']['quantum_network']['deliveries']),2)
        self.assertEqual(r['validation']['packet_hops'],5)

    def test_all_joint_branches_for_five_noiseless_inputs(self):
        coverage={};maximum=0;transactions=0
        for state in ('0','1','+','-','+i'):
            branches=set()
            for seed in BRANCH_SEEDS:
                r=ChainedManager(dict(seed=seed,memory_noise=NOISE_OFF,
                    chains=[dict(chain_id=1,session_start_ns=1000000,input_state=state)])).run()
                bits=''.join(str(x) for sid in ('1','2') for x in r['snapshot']['sessions'][sid]['measurement_bits'])
                branches.add(bits);transactions+=1
                self.assertAlmostEqual(r['metrics']['chains'][0]['output_fidelity'],1.,places=12)
                maximum=max(maximum,r['cross_validation']['max_density_matrix_error'])
                save_report(OUT/('branch-'+state.replace('+','plus').replace('-','minus')+'-'+str(seed)+'.json.gz'),r)
            self.assertEqual(branches,{format(i,'04b') for i in range(16)})
            coverage[state]=sorted(branches)
        (OUT/'branch-coverage.json').write_text(json.dumps(dict(passed=True,branches=coverage,seeds=BRANCH_SEEDS,
            transactions=transactions,max_density_matrix_error=maximum),indent=2)+'\n')

    def test_reference_joint_probability_normalization(self):
        ref=self.single['cross_validation']['chains']['1']['reference']
        self.assertEqual(len(ref['branches']),16)
        self.assertAlmostEqual(sum(b['probability'] for b in ref['branches'].values()),1.,places=12)
        self.assertTrue(0<=ref['expected_fidelity']<=1)

    def test_result_burst_causes_A_and_B_contention(self):
        c=dict(chains=batch(),background={'result':dict(start_ns=2000000,interval_ns=100000,count=20,payload_bytes=1000)})
        r=ChainedManager(c).run();save_report(OUT/'burst.json.gz',r)
        self.assertTrue(any(m['delays']['swap_R_wait_ns']>0 for m in r['metrics']['chains']))
        self.assertTrue(any(m['delays']['teleport_A_wait_ns']>0 for m in r['metrics']['chains']))
        self.assertTrue(any(m['delays']['swap_B_wait_ns']>0 or m['delays']['teleport_B_wait_ns']>0 for m in r['metrics']['chains']))

    def test_shared_B_fifo_between_protocols(self):
        c=dict(chains=batch(interval=100000),native_instructions=dict(cnot_ns=20000,h_ns=20000,measure_ns=20000))
        r=ChainedManager(c).run();save_report(OUT/'fast-bsm.json.gz',r)
        self.assertTrue(any(m['delays']['teleport_B_wait_ns']>0 for m in r['metrics']['chains']))
        self.assertEqual({v['protocol'] for v in r['snapshot']['requests'] if v['processor_id']=='B'},{'swap','teleport'})

    def test_access_delay_isolates_swap_from_teleport(self):
        r=ChainedManager(dict(access_link=dict(rate_bps=10000000,delay_ns=1000000))).run()
        save_report(OUT/'access-delay.json.gz',r)
        self.assertEqual(r['snapshot']['sessions']['1']['checkpoints'],self.single['snapshot']['sessions']['1']['checkpoints'])
        a,b=r['metrics']['chains'][0],self.single['metrics']['chains'][0]
        self.assertEqual(a['ready_received_ns']-b['ready_received_ns'],800000)
        self.assertEqual(a['completion_ns']-b['completion_ns'],1600000)
        self.assertLess(a['input_at_teleport_fidelity'],b['input_at_teleport_fidelity'])
        self.assertNotEqual(r['snapshot']['sessions']['2']['checkpoints']['bsm_start']['epr']['density_matrix'],
                            self.single['snapshot']['sessions']['2']['checkpoints']['bsm_start']['epr']['density_matrix'])

    def test_simultaneous_zero_delay_and_zero_start(self):
        c=dict(chains=[dict(chain_id=i+1,session_start_ns=0,input_state='+') for i in range(3)],
               quantum_links={'RA':dict(delay_ns=0),'RB':dict(delay_ns=0)})
        r=ChainedManager(c).run();save_report(OUT/'ties.json.gz',r)
        swap=[v for v in r['snapshot']['requests'] if v['operation']=='BSM' and v['protocol']=='swap']
        self.assertEqual([v['start_ns'] for v in swap],[0,1600000,3200000])

    def test_channel_noise_reaches_consumed_pair(self):
        r=ChainedManager(dict(quantum_links={'RA':dict(depolar_rate_hz=150),'RB':dict(depolar_rate_hz=300)})).run()
        save_report(OUT/'channel-noise.json.gz',r)
        self.assertNotEqual(r['snapshot']['sessions']['2']['checkpoints']['usable']['density_matrix'],
                            self.single['snapshot']['sessions']['2']['checkpoints']['usable']['density_matrix'])

    def test_actual_resource_provenance_and_positions(self):
        res={(v['session_id'],v['handle']):v for v in self.single['snapshot']['resources']}
        self.assertEqual(res[1,'output']['state'],'TRANSFERRED')
        self.assertEqual(tuple(res[2,'epr']['origin']),(1,'output'))
        self.assertEqual(res[2,'epr']['locations'],[('A',1),('B',0)])
        self.assertEqual(res[2,'epr']['state'],'CONSUMED')
        self.assertEqual(res[2,'input']['state'],'CONSUMED')

    def test_tampered_handoff_rejected(self):
        r=copy.deepcopy(self.single)
        next(v for v in r['snapshot']['resources'] if v['session_id']==2 and v['handle']=='epr')['origin']=(99,'output')
        with self.assertRaisesRegex(RuntimeError,'provenance'):validate_report(r)

    def test_tampered_early_teleport_rejected(self):
        r=copy.deepcopy(self.single)
        next(v for v in r['snapshot']['requests'] if v['session_id']==2 and v['operation']=='BSM')['arrival_ns']-=1
        with self.assertRaises(RuntimeError):validate_report(r)

    def test_tampered_packet_timing_rejected(self):
        r=copy.deepcopy(self.single)
        next(v for v in r['ns3_events'] if v['event_type']=='PAIR_READY_RX')['time_ns']-=1
        with self.assertRaises(RuntimeError):validate_report(r)

    def test_tampered_quantum_state_rejected(self):
        r=copy.deepcopy(self.single)
        r['snapshot']['sessions']['2']['checkpoints']['usable']['density_matrix']['real'][0][0]+=.1
        with self.assertRaisesRegex(RuntimeError,'state mismatch'):cross_validate(r)

    def test_overflow_rejected_with_report(self):
        c=dict(queue_packets=1,background={'result':dict(start_ns=2200000,interval_ns=10000,count=20,payload_bytes=1000)})
        with self.assertRaises(HybridValidationFailure) as ctx:ChainedManager(c).run()
        self.assertTrue(any('DROP' in e['event_type'] for e in ctx.exception.report['ns3_events']))
        save_report(OUT/'overflow-rejected.json.gz',ctx.exception.report)

    def test_invalid_config_rejected(self):
        bad=[dict(sessions=[]),dict(chains=[]),dict(chains=[dict(chain_id=1,session_start_ns=-1)]),
             dict(chains=[dict(chain_id=1,session_start_ns=0,input_state='invalid')]),
             dict(chains=[dict(chain_id=1,session_start_ns=0)]*2),dict(access_link={'rate_bps':0,'delay_ns':0}),
             dict(quantum_links={'RA':dict(loss=0.1)}),dict(command_link={})]
        for c in bad:
            with self.subTest(c=c),self.assertRaises(ValueError):normalize_config(c)

    def test_frozen_v4_sources(self):
        frozen=json.loads((MODULE/'baselines/provisioned-v4-freeze.json').read_text())
        root=MODULE.parents[1]
        for path,digest in frozen['source_sha256'].items():
            self.assertEqual(hashlib.sha256((root/path).read_bytes()).hexdigest(),digest,path)


if __name__=='__main__':unittest.main()
