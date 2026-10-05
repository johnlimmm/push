#!/usr/bin/env python3
"""Run all current Python/Q2NS suites while preserving published result fixtures."""
import argparse
import datetime
import gzip
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

from validate_hybrid_v1 import NATIVE_SUITES

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    out = args.output_dir.resolve()
    out.mkdir(parents=True, exist_ok=False)
    names = subprocess.check_output(
        ['git', 'ls-files', '-z', 'contrib/cosim/results'], cwd=str(ROOT)
    ).decode().split('\0')
    original = {name: (ROOT / name).read_bytes() for name in names
                if name and (ROOT / name).is_file()}
    suites = {}

    def run(command, name, native_count=None):
        path = out / (name + '.log')
        start = time.monotonic()
        with path.open('w') as stream:
            process = subprocess.run(command, cwd=str(ROOT), stdout=stream,
                                     stderr=subprocess.STDOUT)
        log = path.read_text()
        if native_count is None:
            match = re.search(r'Ran (\d+) tests? in [\d.]+s\s+OK\s*$', log)
            count = int(match.group(1)) if match else 0
            passed = process.returncode == 0 and count > 0
        else:
            count = len(re.findall(r'^  PASS ', log, re.MULTILINE))
            passed = (process.returncode == 0 and count == native_count
                      and log.startswith('PASS ' + name + ' ') and 'FAIL' not in log)
        suites[name] = dict(command=command, tests=count, passed=passed,
                            returncode=process.returncode,
                            elapsed_seconds=round(time.monotonic() - start, 3),
                            log=path.name, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        print('{}: {} ({} cases)'.format(name, 'PASS' if passed else 'FAIL', count), flush=True)

    try:
        for folder, name in [('tests', 'core'), ('experiments/tests', 'experiments')]:
            run([sys.executable, '-m', 'unittest', 'discover', '-s',
                 'contrib/cosim/' + folder, '-p', 'test_*.py', '-v'], name)
        for name, count in NATIVE_SUITES.items():
            run(['build/utils/ns3.47-test-runner-default', '--suite=' + name,
                 '--verbose'], name, count)
    finally:
        for name, data in original.items():
            current = ROOT / name
            if current.exists() and current.read_bytes() != data:
                copy = out / 'replayed-published' / current.relative_to(MODULE / 'results')
                copy = copy.with_name(copy.name + '.gz')
                copy.parent.mkdir(parents=True, exist_ok=True)
                with gzip.open(str(copy), 'wb') as stream:
                    stream.write(current.read_bytes())
            current.parent.mkdir(parents=True, exist_ok=True)
            current.write_bytes(data)
    result = dict(date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  scope='Fresh full Python and Q2NS regression; no evaluation sweep rerun.',
                  base_commit=subprocess.check_output(['git', 'rev-parse', 'HEAD'],
                                                      cwd=str(ROOT)).decode().strip(),
                  suites=suites, total_test_cases=sum(v['tests'] for v in suites.values()),
                  published_evidence_preserved=all((ROOT / n).read_bytes() == b
                                                   for n, b in original.items()),
                  passed=all(v['passed'] for v in suites.values()))
    (out / 'summary.json').write_text(json.dumps(result, indent=2, sort_keys=True) + '\n')
    if not result['passed']:
        raise SystemExit('Regression failed; inspect logs in ' + str(out))


if __name__ == '__main__':
    main()
