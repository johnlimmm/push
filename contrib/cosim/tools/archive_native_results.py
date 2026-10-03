#!/usr/bin/env python3
"""Preserve and verify native evidence, including large reports ignored by Git."""
import hashlib
import json
from pathlib import Path
import tarfile

MODULE = Path(__file__).resolve().parents[1]
ROOT = MODULE.parents[1]


def digest_stream(stream):
    h = hashlib.sha256()
    for chunk in iter(lambda:stream.read(1024*1024), b''):h.update(chunk)
    return h.hexdigest()


def main():
    summary = json.loads((MODULE/'results/native-paper-validation-summary.json').read_text())
    if not summary['passed']:raise RuntimeError('native evaluation incomplete')
    archive = MODULE/'baselines/native-timed-v3-results.tar.gz'
    if archive.exists():raise ValueError('native result archive already exists; do not overwrite')
    files = []
    for folder in ('results/native-timed','results/native-p5b-pilot','results/native-p5b-expanded',
                   'results/native-paper-scaling','results/native-paper-logs','paper'):
        files += [p for p in (MODULE/folder).rglob('*') if p.is_file() and 'atomic-regression' not in p.parts]
    files.append(MODULE/'results/native-paper-validation-summary.json')
    hashes = {}
    with tarfile.open(str(archive), 'w:gz', compresslevel=6) as tar:
        for p in sorted(set(files)):
            name = str(p.relative_to(ROOT))
            with p.open('rb') as stream:hashes[name] = digest_stream(stream)
            tar.add(str(p), arcname=name)
    seen = set()
    with tarfile.open(str(archive), 'r|gz') as tar:
        for entry in tar:
            stream = tar.extractfile(entry)
            if stream is None or digest_stream(stream)!=hashes[entry.name]:
                raise RuntimeError('archive reproduction mismatch: '+entry.name)
            seen.add(entry.name)
    if seen!=set(hashes):raise RuntimeError('archive entry mismatch')
    with archive.open('rb') as stream:archive_hash=digest_stream(stream)
    manifest=dict(architecture='native-timed-v3',archive=archive.name,archive_sha256=archive_hash,
        files=len(hashes),file_sha256=hashes,byte_reproduction_verified=True,
        scope='Native correctness, pilot/expanded P5-B, isolated cost repetitions, paper tables/figures and logs.')
    archive.with_suffix('').with_suffix('.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive.with_suffix('').with_suffix('.sha256').write_text(archive_hash+'  '+str(archive.relative_to(ROOT))+'\n')
    print('Native archive: {} files, {:.1f} MiB, byte verification PASS'.format(len(hashes),archive.stat().st_size/1024**2))


if __name__=='__main__':main()
