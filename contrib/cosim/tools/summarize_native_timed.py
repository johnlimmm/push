#!/usr/bin/env python3
"""Summarize native reports and successful regression logs; retain atomic results."""
import datetime
import hashlib
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]
OUT = MODULE / 'results/native-timed'


def read(name):
    return json.loads((OUT / (name + '.json')).read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    regression = read('regression-summary')
    if not regression['passed'] or regression['total_test_cases'] != 258:
        raise RuntimeError('full native/atomic regression has not passed')
    log = (OUT / regression['suites']['python']['log']).read_text()
    if log.count('(test_native_hybrid.NativeHybridTests) ... ok') != 19:
        raise RuntimeError('native test coverage missing from regression log')
    coverage = read('branch-coverage')
    if not coverage['passed'] or any(set(v) != {'00', '01', '10', '11'}
                                     for v in coverage['branches'].values()):
        raise RuntimeError('incomplete native branch coverage')
    parent = json.loads((MODULE / 'baselines/native-timed-parent.json').read_text())
    for name, expected in parent['source_sha256'].items():
        if name in parent['compatibility_fixes']:
            expected = parent['compatibility_fixes'][name]['current_sha256']
        if digest(ROOT / name) != expected:
            raise RuntimeError('atomic baseline changed: ' + name)
    if digest(MODULE / 'baselines' / parent['results_archive']) != parent['results_archive_sha256']:
        raise RuntimeError('atomic results archive changed')

    names = ['teleport', 'mixed', 'mixed-fast-bsm', 'different-gate-partition',
             'delayed-result', 'boundary-arrivals', 'without-state-probes']
    scenarios = {}
    maximum = coverage['max_density_matrix_error']
    for name in names:
        report = read(name)
        if (report['architecture'] != 'native-timed-v3' or not report['validation']['passed']
                or not report['cross_validation']['passed']):
            raise RuntimeError('native scenario failed: ' + name)
        maximum = max(maximum, report['cross_validation']['max_density_matrix_error'])
        scenarios[name] = dict(
            report=name + '.json', passed=True, native_instructions=len(report['native_instructions']),
            max_density_matrix_error=report['cross_validation']['max_density_matrix_error'],
            q2ns_status=report['q2ns_status'], sessions=report['metrics']['sessions'])
    overflow = read('overflow-rejected')
    if overflow['validation']['passed'] or 'packet drop' not in overflow['validation']['error']:
        raise RuntimeError('expected drop failure missing')

    sources = [ROOT / 'README.md', MODULE / 'README-NATIVE.md', MODULE / 'SPEC-NATIVE.md',
               MODULE / 'examples/cosim-hybrid.cc', MODULE / 'python/run_native_hybrid.py',
               MODULE / 'python/netsquid_reference_native.py', MODULE / 'tests/test_native_hybrid.py',
               MODULE / 'tools/validate_native_timed.py', Path(__file__).resolve()]
    sources += sorted((MODULE / 'python').glob('native_*.py'))
    sources += sorted((MODULE / 'scenarios').glob('native-*.json'))
    summary = dict(
        date=datetime.datetime.now(datetime.timezone.utc).isoformat(), passed=True,
        milestone='NetSquid-native timed instruction chains', architecture='native-timed-v3',
        scope='Fixed A/R/B; pre-created resources; serial native gates; shared capacity-one R/B; UDP result path.',
        regression='regression-summary.json', total_test_cases=258, new_native_tests=19,
        max_density_matrix_error=maximum, branch_coverage=coverage, scenarios=scenarios,
        completion_source='netsquid_program_done', native_timing_error_ns=0,
        atomic_comparison=read('atomic-comparison'),
        overflow_negative_test=dict(expected_failure=True, report='overflow-rejected.json'),
        atomic_parent_commit=parent['parent_commit'],
        atomic_sources_verified=True, shared_startup_fix=parent['compatibility_fixes'],
        atomic_results_archive_unchanged=True,
        model_note='Native T1/T2 applies to idle and active storage once each; ideal gates act at instruction completion. Durations are illustrative.',
        evaluation_note='Native P5-B and cost results are reported separately in paper/RESULTS.md; atomic evidence is archived.',
        source_sha256={str(p.relative_to(ROOT)): digest(p) for p in sources})
    (OUT / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')

    tele = read('teleport')
    rows = ['# Native timed execution — validation results', '',
            'NetSquid-native `QuantumProgram` backend; atomic v2 evidence is preserved in [its paper archive](../baselines/atomic-v2-paper.tar.gz).', '',
            '## Correctness', '',
            '- 258 tests PASS: 159 Python (including 19 new native tests), 16 evaluation/timing/instrumentation, 83 Q2NS native cases.',
            '- Five noiseless Teleport inputs × 32 seeds = 160 transactions; all four BSM branches for each input.',
            '- Maximum intermediate/checkpoint density-matrix error against the independent native reference: **{:.3g}**.'.format(maximum),
            '- Configured gate durations, native operation ends and actual packet-generation timestamps agree exactly (0 ns error).',
            '- Mixed Swap/Teleport R/B FIFO, result queueing, equal-time arrivals, active/idle T1 accounting and observer invariance pass.', '',
            '## Teleport native instruction trace', '',
            'This example starts locally at R at 1 ms. All values below are simulated milliseconds.', '',
            '| Instruction | Start | Complete |', '|---|---:|---:|']
    for row in tele['native_instructions']:
        rows.append('| {} | {:.4f} | {:.4f} |'.format(row['instruction'], row['start_ns']/1e6,
                                                    row['completion_ns']/1e6))
    metric = tele['metrics']['sessions'][0]
    rows += ['', 'The native BSM callback generates the actual UDP result at {:.4f} ms; B receives it at {:.4f} ms and begins correction.'.format(
        metric['bsm_completion_ns']/1e6, metric['correction_start_ns']/1e6), '',
        '## Model distinction', '',
        'For the single Teleport example, matching total BSM/correction durations preserves atomic-vs-native operation timing.',
        'The branch-probability-weighted final density matrices nevertheless differ by **{:.6f}** (maximum element difference).'.format(
            summary['atomic_comparison']['branch_weighted_density_matrix_difference']),
        'This reflects different noise/gate ordering. It is not a failure of either model against its own reference.', '',
        'Default CNOT/H/each-measurement durations are 0.6/0.2/0.4 ms; X/I and Z/I slots are each 0.25 ms.',
        'These parameters are illustrative, not hardware calibration. Storage T1/T2 is applied before each ideal gate at instruction completion.',
        'Native P5-B simplification and simulation-cost results are reported in [RESULTS.md](RESULTS.md).', '',
        'Evidence: [summary](../results/native-timed/summary.json), [regression](../results/native-timed/regression-summary.json),',
        '[Teleport trace](../results/native-timed/teleport.json), [Mixed trace](../results/native-timed/mixed.json).', '']
    (MODULE / 'paper/NATIVE-VALIDATION.md').write_text('\n'.join(rows))
    print('Native timed: 258 tests PASS; maximum density-matrix error {:.3g}'.format(maximum))


if __name__ == '__main__':
    main()
