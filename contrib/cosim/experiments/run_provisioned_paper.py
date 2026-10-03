#!/usr/bin/env python3
"""Run native timing/cost study alone, after the P5-B study has finished."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))
from provisioned_paper_scaling import evaluate, save
from run_provisioned_p5b import verify_frozen, source_hashes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=MODULE/'scenarios/provisioned-paper-validation.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    verify_frozen()
    sources=source_hashes()
    try:
        result = evaluate(plan, args.output_dir)
        result['plan_sha256'] = hashlib.sha256(args.plan.read_bytes()).hexdigest()
        if source_hashes()!=sources: raise RuntimeError('evaluation sources changed during cost run')
        result['source_sha256'] = sources
        verify_frozen()
        save(args.output_dir/'summary.json', result)
    except Exception as error:
        save(args.output_dir/'failure.json', dict(passed=False,error=str(error)))
        raise
    print('Provisioned cost/timing PASS', flush=True)


if __name__ == '__main__': main()
