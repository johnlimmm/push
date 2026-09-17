#!/usr/bin/env python3
"""Verify frozen bytes and current v1 sources without extracting or running simulators."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import tarfile

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = ROOT / 'contrib/cosim/baselines/hybrid-v1-freeze.json'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def verify(manifest):
    data = json.loads(manifest.read_text())
    if Path(data['archive']).name != data['archive']:
        raise ValueError('archive must be a filename beside the manifest')
    archive = manifest.parent / data['archive']
    if digest(archive.read_bytes()) != data['archive_sha256']:
        raise ValueError('archive hash mismatch')
    expected = data['file_sha256']
    seen = set()
    with tarfile.open(str(archive), 'r:gz') as tar:
        for member in tar:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute() or '..' in path.parts
                    or member.name in seen or member.name not in expected):
                raise ValueError('invalid/duplicate/unexpected archive entry: ' + member.name)
            seen.add(member.name)
            if digest(tar.extractfile(member).read()) != expected[member.name]:
                raise ValueError('archived file hash mismatch: ' + member.name)
    if seen != set(expected):
        raise ValueError('archive entries do not match manifest')
    sources = 0
    for name, value in expected.items():
        if name.startswith('contrib/cosim/results/'):
            continue  # Reruns may replace local results; their original archived bytes were checked above.
        if digest((ROOT / name).read_bytes()) != value:
            raise ValueError('current source/configuration mismatch: ' + name)
        sources += 1
    for name, value in data['baseline_archives_sha256'].items():
        if digest((ROOT / name).read_bytes()) != value:
            raise ValueError('prior baseline archive mismatch: ' + name)
    print('Hybrid v1: {} archived files, {} current source/configuration files; PASS'.format(len(seen), sources))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, default=DEFAULT)
    args = parser.parse_args()
    verify(args.manifest)


if __name__ == '__main__':
    main()
