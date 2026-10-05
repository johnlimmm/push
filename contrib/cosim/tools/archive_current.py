#!/usr/bin/env python3
"""Preserve current and previous literature evaluation evidence in checked archives.

Run after validate_current.py. Archives contain original report bytes and logs;
chunking keeps each archive below GitHub's per-file limit. No simulation runs.
"""
import argparse
import hashlib
import json
from pathlib import Path
import tarfile

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--regression-dir', type=Path, required=True)
    parser.add_argument('--prefix', default='literature-memory-evidence')
    args = parser.parse_args()
    if Path(args.prefix).name != args.prefix:
        raise ValueError('prefix must be a basename')
    regression = args.regression_dir.resolve()
    status = json.loads((regression / 'summary.json').read_text())
    if not status['passed'] or not status['published_evidence_preserved']:
        raise ValueError('requires a passing current regression')
    folders = [MODULE / 'results/memory-evaluation-v1',
               MODULE / 'results/literature-evaluation-v1', regression]
    files = set()
    for folder in folders:
        files.update(p for p in folder.rglob('*') if p.is_file())
    # Historical tests cited by each evaluation package remain reproducible.
    for name in ['evaluation', 'evaluation-long-memory']:
        provenance = json.loads((MODULE / 'paper' / name / 'provenance.json').read_text())
        def log_entries(value):
            if isinstance(value, dict):
                if 'log' in value and 'sha256' in value:
                    path = MODULE / value['log']
                    if digest(path) != value['sha256']:
                        raise ValueError('changed historical log: ' + str(path))
                    files.add(path)
                for entry in value.values():
                    log_entries(entry)
            elif isinstance(value, list):
                for entry in value:
                    log_entries(entry)
        log_entries(provenance.get('tests', {}))
    for name in ['memory-evaluation-v1', 'literature-evaluation-v1']:
        folder = MODULE / 'results' / name
        summary = json.loads((folder / 'summary.json').read_text())
        if not summary['passed']:
            raise ValueError('failed evaluation: ' + name)
        for rel, expected in summary['report_sha256'].items():
            if digest(folder / rel) != expected:
                raise ValueError('changed raw report: ' + rel)
    chunks = [[]]
    size = 0
    for path in sorted(files):
        if size + path.stat().st_size > 40 * 1024**2 and chunks[-1]:
            chunks.append([])
            size = 0
        chunks[-1].append(path)
        size += path.stat().st_size
    manifest_path = MODULE / 'baselines' / (args.prefix + '.json')
    archives = [manifest_path.with_name(args.prefix + '-{:02d}.tar.gz'.format(i + 1))
                for i in range(len(chunks))]
    if manifest_path.exists() or any(p.exists() for p in archives):
        raise ValueError('archive destination exists')
    hashes = {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}
    entries = []
    for archive, paths in zip(archives, chunks):
        with tarfile.open(str(archive), 'w:gz') as tar:
            for path in paths:
                tar.add(str(path), arcname=str(path.relative_to(ROOT)))
        with tarfile.open(str(archive), 'r:gz') as tar:
            for name in tar.getnames():
                if hashlib.sha256(tar.extractfile(name).read()).hexdigest() != hashes[name]:
                    raise ValueError('archive byte mismatch: ' + name)
        entries.append(dict(path=str(archive.relative_to(ROOT)), sha256=digest(archive),
                            files=len(paths), bytes=archive.stat().st_size))
        print('{}: {} files, {:.2f} MiB, verified'.format(
            archive.name, len(paths), archive.stat().st_size / 1024**2), flush=True)
    manifest = dict(scope='Literature and memory evaluations plus current regression',
                    byte_reproduction_verified=True, archives=entries,
                    file_sha256=hashes, files=len(hashes),
                    regression=str((regression / 'summary.json').relative_to(ROOT)))
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    manifest_path.with_suffix('.sha256').write_text(''.join(
        e['sha256'] + '  ' + e['path'] + '\n' for e in entries))


if __name__ == '__main__':
    main()
