#!/usr/bin/env python3
"""Run direct-start paper validation and preserve the historical Hybrid v1 archive."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'tools'))
from verify_hybrid_v1 import verify, DEFAULT


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['timing', 'scaling'])
    parser.add_argument('--plan', type=Path, default=MODULE/'scenarios/hybrid-paper-validation.json')
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    if args.output_dir.exists():
        raise ValueError('choose a new output directory')
    verify(DEFAULT, archive_only=True)
    plan = json.loads(args.plan.read_text())
    if args.mode == 'timing':
        from paper_timing import evaluate
        result = evaluate(plan)
        args.output_dir.mkdir(parents=True)
    else:
        from paper_scaling import evaluate
        result = evaluate(plan, args.output_dir)
    result['plan_sha256'] = hashlib.sha256(args.plan.read_bytes()).hexdigest()
    result['experiment_source_sha256'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (Path(__file__), Path(__file__).with_name('paper_scaling.py'), Path(__file__).with_name('paper_timing.py'))}
    verify(DEFAULT, archive_only=True)
    result['historical_v1_archive_unchanged'] = True
    result['architecture'] = 'direct-session-start-v2'
    (args.output_dir/'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+'\n')
    print(args.mode+' PASS', flush=True)


if __name__ == '__main__':
    main()
