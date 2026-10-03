#!/usr/bin/env python3
"""Validate native evaluation artifacts and record their provenance in one summary."""
import datetime
import hashlib
import json
from pathlib import Path

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


def read(path):
    return json.loads((MODULE/path).read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    inputs = dict(regression='results/native-timed/regression-summary.json',
        correctness='results/native-timed/summary.json', pilot='results/native-p5b-pilot/summary.json',
        expanded='results/native-p5b-expanded/summary.json', cost='results/native-paper-scaling/summary.json',
        timing='results/native-paper-scaling/timing.json', paper='paper/results-summary.json')
    data = {key:read(path) for key,path in inputs.items()}
    if not all(r['passed'] for r in data.values()):raise RuntimeError('failed experiment')
    if data['regression']['total_test_cases']!=258:raise RuntimeError('incomplete regression')
    for key in ('pilot','expanded','cost','timing','paper'):
        if data[key]['architecture']!='native-timed-v3':raise RuntimeError('mixed experiment architecture')
    for key in ('pilot','expanded','cost'):
        for name,value in data[key]['source_sha256'].items():
            if sha(MODULE/name)!=value:raise RuntimeError('experiment source changed: '+name)
    for name,value in data['paper']['evidence'].items():
        path=Path(name)
        if not path.is_absolute():path=ROOT/path
        if sha(path)!=value:raise RuntimeError('paper evidence changed')
    for key,cases in (('pilot',48),('expanded',384)):
        report=data[key]
        if (report['paired_cases']!=cases or report['execution_runs']!=3*cases or
                report['transactions_per_model']!=4*cases or report['calibration_runs']!=6):
            raise RuntimeError('incomplete P5-B execution')
        if report['plan']['fidelity_min']!=.5 or report['plan']['deadline_ns']!=5000000:
            raise RuntimeError('evaluation thresholds changed')
    if data['cost']['warmup_runs']!=12 or data['cost']['measured_runs']!=120:
        raise RuntimeError('incomplete cost study')
    if data['timing']['requests']!=500 or data['timing']['max_absolute_completion_error_ns']!=0:
        raise RuntimeError('native timing discrepancy')
    maximum=max(data[k]['max_density_matrix_error'] for k in ('correctness','pilot','expanded','cost'))
    if maximum>1e-12:raise RuntimeError('native reference mismatch')
    result=dict(passed=True,architecture='native-timed-v3',date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        total_test_cases=258,pilot_paired_cases=48,expanded_paired_cases=384,
        expanded_execution_runs=1152,expanded_calibration_runs=6,transactions_per_model=1536,
        cost_warmup_runs=12,cost_measured_runs=120,timing_requests=500,timing_max_error_ns=0,
        max_density_matrix_error=maximum,
        scope='Native timed gate chains; A/R/B local starts; pre-created resources; illustrative durations; periodic background phases.',
        atomic_evidence_preserved=['baselines/atomic-v2-paper.tar.gz','baselines/direct-start-v2-results.tar.gz'],
        artifacts={k:dict(path=p,sha256=sha(MODULE/p)) for k,p in inputs.items()},
        manuscript_note='Tables, figures and LaTeX replacement blocks updated. Original QuCl.pdf retained; full manuscript source unavailable.')
    output=MODULE/'results/native-paper-validation-summary.json'
    output.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print('Native paper evaluation: 258 tests, 384 expanded cases, 120 cost repetitions; PASS')


if __name__=='__main__':main()
