#!/usr/bin/env python3
"""Run native timing/cost study alone, after the P5-B study has finished."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'python'))
from native_paper_scaling import evaluate, save
from run_native_p5b import verify_frozen


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--plan', type=Path, default=MODULE/'scenarios/native-paper-validation.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    plan = json.loads(args.plan.read_text())
    verify_frozen()
    try:
        result = evaluate(plan, args.output_dir)
        result['plan_sha256'] = hashlib.sha256(args.plan.read_bytes()).hexdigest()
        files = list((MODULE/'python').glob('native_*.py')) + list((MODULE/'experiments').glob('*native*.py'))
        files.append(MODULE/'python/netsquid_reference_native.py')
        result['source_sha256'] = {str(p.relative_to(MODULE)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
        verify_frozen()
        save(args.output_dir/'summary.json', result)
    except Exception as error:
        save(args.output_dir/'failure.json', dict(passed=False,error=str(error)))
        raise
    print('Native cost/timing PASS', flush=True)


if __name__ == '__main__': main()
