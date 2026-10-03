#!/usr/bin/env python3
"""Join independently checked v4 regression and causality evaluation evidence."""
import gzip
import hashlib
import json
from pathlib import Path

MODULE=Path(__file__).resolve().parents[1]
ROOT=MODULE.parents[1]


def load(path):
    path=MODULE/path
    if path.suffix=='.gz':
        with gzip.open(str(path),'rt') as stream:return json.load(stream)
    return json.loads(path.read_text())


def main():
    paths=dict(regression='results/provisioned-regression/summary.json',
        evaluation='results/provisioned-evaluation/summary.json',branches='results/provisioned-v4/branch-coverage.json')
    evidence={key:load(path) for key,path in paths.items()}
    assert all(v['passed'] for v in evidence.values())
    assert evidence['regression']['total_test_cases']==278
    assert evidence['evaluation']['runs']==96 and evidence['evaluation']['transactions']==192
    assert evidence['branches']['transactions']==160
    freeze=load('baselines/native-v3-freeze.json')
    for path,h in freeze['source_sha256'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==h,path
    for path,h in evidence['evaluation']['source_sha256'].items():
        assert hashlib.sha256((MODULE/path).read_bytes()).hexdigest()==h,path
    cases={}
    for name in ('mixed','mixed-fast-bsm','late-resources','ready-order','zero-equivalence','channel-noise'):
        report=load('results/provisioned-v4/'+name+'.json.gz')
        assert report['validation']['passed'] and report['cross_validation']['passed']
        cases[name]=dict(report='results/provisioned-v4/'+name+'.json.gz',sessions=report['metrics']['sessions'],
            max_density_matrix_error=report['cross_validation']['max_density_matrix_error'])
    error=max([evidence['evaluation']['max_density_matrix_error'],evidence['branches']['max_density_matrix_error']]+
              [r['max_density_matrix_error'] for r in cases.values()])
    assert error<=1e-12
    source_files=[p for folder in ('python','experiments','tests','tools') for p in (MODULE/folder).glob('*provisioned*.py')]
    source_files += [MODULE/'python/quantum_network_backend.py',MODULE/'examples/cosim-provisioned.cc',
                    ROOT/'scratch/cosim-provisioned/CMakeLists.txt',MODULE/'SPEC-PROVISIONED.md',
                    MODULE/'README-PROVISIONED.md']
    source_files += list((MODULE/'scenarios').glob('provisioned-*.json'))
    summary=dict(passed=True,architecture='provisioned-native-v4',total_test_cases=278,new_tests=20,
        evaluation_runs=96,evaluation_transactions=192,noiseless_branch_transactions=160,
        max_density_matrix_error=error,v3_sources_unchanged=True,v3_commit=freeze['commit'],
        q2ns_source_changes=False,ready_notification='ideal_zero_delay',quantum_loss_model='none',
        scope='Fixed A/R/B; t=0 pre-generated pairs delivered over native quantum channels; eligibility-gated shared R/B FIFO; native operations; actual result UDP.',
        evaluation_scope='Finite causality and correctness study; v3 P5-B/cost figures preserved separately.',
        artifacts={k:dict(path=p,sha256=hashlib.sha256((MODULE/p).read_bytes()).hexdigest()) for k,p in paths.items()},
        scenarios=cases,source_sha256={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(set(source_files))})
    (MODULE/'results/provisioned-validation-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    lines=['# QuCl v4 — Quantum-channel provisioning results','',
        'Actual NetSquid Network/Node/QuantumChannel delivery gates Q2NS BSM eligibility. Native R/B execution and actual ns-3 result packets are retained.', '',
        '**Assumptions:** EPR/input creation at t=0; lossless delivery; ideal zero-delay readiness knowledge at R; fixed topology and allocated memory positions. No heralding/ACK protocol is simulated.', '',
        '## Validation','',
        '- 20 provisioning tests + 258 existing tests = **278 PASS**.',
        '- Zero-delay/noise-off delivery reproduces v3 timings and states (also checked with memory noise enabled).',
        '- Five noiseless Teleport input states × 32 seeds = 160 transactions; all four branches covered for each input.',
        '- Independent channel/program reference checks delivery, readiness, BSM/gate and correction states.',
        '- Analytic channel depolarization and local-only T1 storage during transit are checked separately.',
        '- Resource/processor wait separation, ready-order FIFO, same-time ties, classical isolation, R/B mixed contention, observer invariance and negative cases pass.',
        '- Maximum density-matrix error: **{:.3g}**.'.format(error),'',
        '## New evaluation','',
        '4 RA/RB delay combinations × background off/on × depolarization 0/50 Hz × Swap/Teleport/mixed × seeds 7/11 = **96 runs, 192 transactions**. All runs pass packet FIFO, readiness/FIFO, ownership and independent state validation. Classical packet drops: 0.', '',
        'This is a finite correctness/causality sweep. It does not supply population-performance confidence intervals. Channel propagation need not strictly increase BSM start when an existing processor wait masks it. Fidelity monotonicity is not an acceptance condition.', '',
        '## Mixed scenario: resource wait and R wait','',
        'RA delay = 2 ms; RB delay = 1.2 ms; RB depolarization = 50 Hz; actual classical background traffic enabled. Teleport source/Alice stays at R. All durations below are ms.', '',
        '| Session | Protocol | Session start | Resources ready | Resource wait | R wait | BSM start | Result delay | B wait | Completion |',
        '|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    mixed=load('results/provisioned-v4/mixed.json.gz')
    for row in mixed['metrics']['sessions']:
        sid=row['session_id'];protocol=mixed['snapshot']['sessions'][str(sid)]['protocol']
        fields=('session_start_ns','resource_ready_ns','resource_wait_ns','quantum_wait_ns','bsm_start_ns',
                'result_delay_ns','correction_wait_ns','completion_ns')
        lines.append('| {} | {} | {} |'.format(sid,protocol,' | '.join('{:.3f}'.format(row[k]/1e6) for k in fields)))
    lines+=['','![Provisioned mixed execution](figures/fig8-provisioned-mixed.png)','',
        'The earlier-starting Swap session waits for RA delivery while a ready Teleport session can use R. Queue entry is based on eligibility, not blocked by an unready session.', '',
        '## Evidence and relation to v3','',
        '- [Validation summary](../results/provisioned-validation-summary.json)',
        '- [Evaluation summary and raw-report paths](../results/provisioned-evaluation/summary.json)',
        '- [Regression logs](../results/provisioned-regression/summary.json)',
        '- [Model/implementation contract](../SPEC-PROVISIONED.md)',
        '- [v3 freeze](../baselines/native-v3-freeze.json)','',
        '`RESULTS.md` and Figures 4–7 remain the published v3 native timed P5-B/cost results. They are not results for this provisioning model. This document and Figure 8 report fresh v4 runs.']
    (MODULE/'paper/PROVISIONING.md').write_text('\n'.join(lines)+'\n')
    print('v4: 278 tests, 96 runs / 192 transactions; maximum state error {:.3g}; PASS'.format(error))


if __name__=='__main__':main()
