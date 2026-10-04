#!/usr/bin/env python3
"""Audit retained chain results, freeze provenance, and preserve raw evidence."""
import datetime
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import tarfile

MODULE=Path(__file__).resolve().parents[1];ROOT=MODULE.parents[1]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive-name',default='chained-v5-results')
    args=parser.parse_args()
    if Path(args.archive_name).name!=args.archive_name:raise ValueError('archive name must be a basename')
    archive=MODULE/'baselines'/(args.archive_name+'.tar.gz')
    if archive.exists():raise ValueError('result archive already exists')
    evaluation=json.loads((MODULE/'results/chained-evaluation/summary.json').read_text())
    regression=json.loads((MODULE/'results/chained-regression/summary.json').read_text())
    coverage=json.loads((MODULE/'results/chained-tests/branch-coverage.json').read_text())
    noise=json.loads((MODULE/'results/chained-tests/noise-inputs.json').read_text())
    frozen=json.loads((MODULE/'baselines/provisioned-v4-freeze.json').read_text())
    unchanged=all(digest(ROOT/p)==h for p,h in frozen['source_sha256'].items())
    assert evaluation['passed'] and regression['passed'] and coverage['passed'] and noise['passed'] and unchanged
    assert set(coverage['branches'])==set(noise['inputs'])=={'0','1','+','-','+i','-i'}
    assert coverage['transactions']==96 and noise['runs']==12
    max_error=0.;reports=0
    for entry in evaluation['reports']:
        path=MODULE/'results/chained-evaluation'/entry['report']
        assert digest(path)==entry['sha256']
        with gzip.open(str(path),'rt') as stream:r=json.load(stream)
        assert r['validation']['passed'] and r['cross_validation']['passed']
        assert r['q2ns_status']['native_qubit_count']==r['q2ns_status']['native_state_count']==0
        assert all(h['same_qubit_objects'] for h in r['snapshot']['handoffs'])
        assert not any('DROP' in e['event_type'] for e in r['ns3_events'])
        max_error=max(max_error,r['cross_validation']['max_density_matrix_error']);reports+=1
    test_reports=[]
    for path in sorted((MODULE/'results/chained-tests').glob('*.json.gz')):
        with gzip.open(str(path),'rt') as stream:r=json.load(stream)
        if 'rejected' in path.name:
            assert r['validation']['passed'] is False
            continue
        assert r['validation']['passed'] and r['cross_validation']['passed']
        max_error=max(max_error,r['cross_validation']['max_density_matrix_error'])
        test_reports.append(str(path.relative_to(ROOT)))
    patterns=['README-CHAINED.md','SPEC-CHAINED.md','python/chained_*.py','python/run_chained.py',
              'python/netsquid_reference_chained.py','examples/cosim-chained.cc','scenarios/chained-*.json',
              'tests/test_chained.py','experiments/run_chained_evaluation.py','tools/*chained*.py']
    sources=set()
    for pattern in patterns:sources.update(MODULE.glob(pattern))
    sources.add(ROOT/'scratch/cosim-chained/CMakeLists.txt')
    summary=dict(architecture='swapping-assisted-teleportation-v5',
        date=datetime.datetime.now(datetime.timezone.utc).isoformat(),passed=True,
        total_test_cases=regression['total_test_cases'],new_tests=regression['suites']['chained']['tests'],
        characterization_runs=reports,characterization_chains=evaluation['transactions'],
        branch_coverage=coverage,noise_input_validation=noise,
        max_density_matrix_error=max_error,frozen_v4_sources_unchanged=unchanged,
        rerun_scope=regression.get('rerun_scope','full regression'),
        characterization_evidence='Retained 48-run +i characterization; six-state validation rerun separately',
        topology='A(Alice)--R(repeater)--B(Bob)',
        quantum_operations='native R Swap BSM, native A Teleport BSM, shared native B corrections',
        pair_handoff='same A/B qubit objects and memory locations, single consumption, no replacement EPR',
        ready_notification=dict(elementary_delivery_at_R='ideal zero delay',swapped_pair_at_A='actual UDP B->R->A'),
        scope='Fixed lossless topology, ideal t=0 input/EPR preparation, native channels/gates/T1T2, no heralding or retry.',
        regression='chained-regression/summary.json',evaluation='chained-evaluation/summary.json',
        test_reports=test_reports,source_sha256={str(p.relative_to(ROOT)):digest(p) for p in sorted(sources)})
    (MODULE/'results/chained-validation-summary.json').write_text(json.dumps(summary,indent=2,sort_keys=True)+'\n')
    files=[]
    for folder in ('results/chained-tests','results/chained-evaluation','results/chained-regression','paper/chained-v5'):
        files.extend(p for p in (MODULE/folder).rglob('*') if p.is_file())
    files.append(MODULE/'results/chained-validation-summary.json')
    with tarfile.open(str(archive),'w:gz') as tar:
        for p in sorted(files):tar.add(str(p),arcname=str(p.relative_to(ROOT)))
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sorted(files)}
    with tarfile.open(str(archive),'r:gz') as tar:
        assert set(tar.getnames())==set(hashes)
        for p,h in hashes.items():assert hashlib.sha256(tar.extractfile(p).read()).hexdigest()==h
    manifest=dict(architecture=summary['architecture'],archive=str(archive.relative_to(ROOT)),
        archive_sha256=digest(archive),file_sha256=hashes,files=len(files),byte_reproduction_verified=True)
    archive.with_name(args.archive_name+'.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive.with_name(args.archive_name+'.sha256').write_text(manifest['archive_sha256']+'  '+manifest['archive']+'\n')
    print('Verified {} tests, {} runs, error {:.3g}; archived {} files ({:.2f} MiB)'.format(
        summary['total_test_cases'],reports,max_error,len(files),archive.stat().st_size/1024**2))


if __name__=='__main__':main()
