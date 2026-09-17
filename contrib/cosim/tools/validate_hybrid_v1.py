#!/usr/bin/env python3
"""Run the existing Python/native suites and record release evidence (no new tests)."""
import datetime
import json
from pathlib import Path
import re
import subprocess
import sys
import time

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]
RESULTS = MODULE / 'results'
NATIVE_SUITES = {
    'q2ns-analysis': 4, 'q2ns-netcontroller': 8, 'q2ns-qchannel': 14,
    'q2ns-qnode': 7, 'q2ns-qstate-interface': 4, 'q2ns-qstate-registry': 35,
    'q2ns-swap-external': 4, 'q2ns-teleport-external': 7,
}


def run(command, log):
    start = time.monotonic()
    with (RESULTS / log).open('w') as stream:
        completed = subprocess.run(command, cwd=str(ROOT), stdout=stream, stderr=subprocess.STDOUT)
    return dict(command=command, log=log, returncode=completed.returncode,
                elapsed_seconds=round(time.monotonic() - start, 3))


def main():
    RESULTS.mkdir(exist_ok=True)
    python = run([sys.executable, '-m', 'unittest', 'discover', '-s', 'contrib/cosim/tests', '-v'],
                 'hybrid-v1-python-tests.log')
    match = re.search(r'Ran (\d+) tests in [\d.]+s\s+OK\s*$',
                      (RESULTS / python['log']).read_text())
    python['tests'] = int(match.group(1)) if match else None
    python['passed'] = python['returncode'] == 0 and python['tests'] == 136
    print('Python: ' + ('PASS' if python['passed'] else 'FAIL'), flush=True)
    native = {}
    for suite, expected in NATIVE_SUITES.items():
        result = run(['build/utils/ns3.47-test-runner-default', '--suite=' + suite, '--verbose'],
                     'hybrid-v1-' + suite + '.log')
        text = (RESULTS / result['log']).read_text()
        result['test_cases'] = len(re.findall(r'^  PASS ', text, re.MULTILINE))
        result['passed'] = (result['returncode'] == 0 and result['test_cases'] == expected
                            and text.startswith('PASS ' + suite + ' ') and 'FAIL' not in text)
        native[suite] = result
        print(suite + ': ' + ('PASS' if result['passed'] else 'FAIL'), flush=True)
    summary = dict(milestone='Hybrid v1 release verification',
                   date=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                   python=python, native=native,
                   native_test_cases=sum(r['test_cases'] for r in native.values()),
                   passed=python['passed'] and all(r['passed'] for r in native.values()))
    summary['total_test_cases'] = (python['tests'] or 0) + summary['native_test_cases']
    (RESULTS / 'hybrid-v1-release-checks.json').write_text(
        json.dumps(summary, indent=2, sort_keys=True) + '\n')
    if not summary['passed']:
        raise SystemExit('Release verification failed; inspect the saved logs.')
    print('Hybrid v1: {} test cases PASS'.format(summary['total_test_cases']))


if __name__ == '__main__':
    main()
