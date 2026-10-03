#!/usr/bin/env python3
"""Preserve and byte-verify v4 evidence, including reports ignored by Git."""
import hashlib
import json
from pathlib import Path
import tarfile

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


def digest(stream):
    checksum = hashlib.sha256()
    for block in iter(lambda: stream.read(1024 * 1024), b''):
        checksum.update(block)
    return checksum.hexdigest()


def main():
    summary_path = MODULE / 'results/provisioned-validation-summary.json'
    summary = json.loads(summary_path.read_text())
    if not summary['passed']:
        raise RuntimeError('v4 validation is incomplete')
    for name, expected in summary['source_sha256'].items():
        with (ROOT / name).open('rb') as stream:
            if digest(stream) != expected:
                raise RuntimeError('validated source changed: ' + name)

    archive = MODULE / 'baselines/provisioned-v4-results.tar.gz'
    manifest = MODULE / 'baselines/provisioned-v4-results.json'
    checksum = MODULE / 'baselines/provisioned-v4-results.sha256'
    if any(path.exists() for path in (archive, manifest, checksum)):
        raise ValueError('v4 evidence archive already exists; do not overwrite')
    files = [summary_path, MODULE / 'paper/PROVISIONING.md',
             MODULE / 'paper/figures/fig8-provisioned-mixed.pdf',
             MODULE / 'paper/figures/fig8-provisioned-mixed.png']
    for folder in ('results/provisioned-v4', 'results/provisioned-evaluation',
                   'results/provisioned-regression'):
        files.extend(path for path in (MODULE / folder).rglob('*') if path.is_file())

    hashes = {}
    with tarfile.open(str(archive), 'w:gz', compresslevel=6) as bundle:
        for path in sorted(set(files)):
            name = str(path.relative_to(ROOT))
            if path.is_symlink():
                raise ValueError('unexpected symlink: ' + name)
            with path.open('rb') as stream:
                hashes[name] = digest(stream)
            bundle.add(str(path), arcname=name)
    seen = set()
    with tarfile.open(str(archive), 'r|gz') as bundle:
        for entry in bundle:
            stream = bundle.extractfile(entry)
            if (stream is None or entry.name in seen or
                    digest(stream) != hashes.get(entry.name)):
                raise RuntimeError('archive reproduction mismatch: ' + entry.name)
            seen.add(entry.name)
    if seen != set(hashes):
        raise RuntimeError('archive entries do not match source evidence')
    with archive.open('rb') as stream:
        archive_hash = digest(stream)
    manifest.write_text(json.dumps(dict(
        architecture='provisioned-native-v4', archive=archive.name,
        archive_sha256=archive_hash, files=len(hashes), file_sha256=hashes,
        byte_reproduction_verified=True,
        scope='v4 correctness sweep, regression logs, raw reports and Figure 8; v3 paper evidence preserved separately.'
    ), indent=2, sort_keys=True) + '\n')
    checksum.write_text(archive_hash + '  ' + str(archive.relative_to(ROOT)) + '\n')
    print('v4 archive: {} files, {:.2f} MiB; byte verification PASS'.format(
        len(hashes), archive.stat().st_size / 1024**2))


if __name__ == '__main__':
    main()
