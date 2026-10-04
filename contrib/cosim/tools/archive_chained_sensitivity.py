#!/usr/bin/env python3
"""Verify and preserve the quantum-delivery sensitivity evidence."""
import hashlib
import json
from pathlib import Path
import tarfile

MODULE=Path(__file__).resolve().parents[1];ROOT=MODULE.parents[1]
RESULTS=MODULE/'results/chained-quantum-delay-sensitivity'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    summary=json.loads((RESULTS/'summary.json').read_text())
    assert summary['passed'] and summary['runs']==24 and summary['transactions']==96
    assert summary['baseline_1x_reproduced_runs']==8 and summary['paired_latency_decomposition_passed']
    for row in summary['reports']:assert digest(RESULTS/row['report'])==row['sha256']
    for name,h in summary['provenance']['source_sha256'].items():assert digest(ROOT/name)==h,name
    files=set(p for p in RESULTS.rglob('*') if p.is_file())
    for name in ('SENSITIVITY.md','quantum-delay-sensitivity.png','quantum-delay-sensitivity.pdf'):
        files.add(MODULE/'paper/chained-v5'/name)
    for name in ('scenarios/chained-quantum-delay-sensitivity.json','experiments/run_chained_sensitivity.py',
                 'tools/render_chained_sensitivity.py','tools/archive_chained_sensitivity.py'):
        files.add(MODULE/name)
    stem='chained-v5-quantum-delay-sensitivity-results'
    archive=MODULE/'baselines'/(stem+'.tar.gz')
    if archive.exists():raise ValueError('archive already exists')
    hashes={str(p.relative_to(ROOT)):digest(p) for p in sorted(files)}
    with tarfile.open(str(archive),'w:gz') as stream:
        for name in hashes:stream.add(str(ROOT/name),arcname=name)
    with tarfile.open(str(archive),'r:gz') as stream:
        assert set(stream.getnames())==set(hashes)
        for name,h in hashes.items():assert hashlib.sha256(stream.extractfile(name).read()).hexdigest()==h
    manifest=dict(archive=str(archive.relative_to(ROOT)),archive_sha256=digest(archive),
        files=len(files),file_sha256=hashes,byte_reproduction_verified=True,
        scope='24 successful sensitivity runs; fixed 2:3 quantum delay ratio; all previous v5 sources unchanged')
    archive.with_name(stem+'.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    archive.with_name(stem+'.sha256').write_text(manifest['archive_sha256']+'  '+manifest['archive']+'\n')
    print('Verified {} files; {:.2f} MiB archive'.format(len(files),archive.stat().st_size/1024**2))


if __name__=='__main__':main()
