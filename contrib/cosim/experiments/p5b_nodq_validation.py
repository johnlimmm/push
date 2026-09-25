"""No-Dq-R uses the common hybrid validator with an independent relaxed-R oracle."""
from hybrid_validation import validate_report as validate_hybrid


def validate_report(report):
    if report.get('model')!='No-Dq-R':raise RuntimeError('expected No-Dq-R model')
    checked=validate_hybrid(report)
    if any(t['correction_wait_ns'] for t in checked['expected_timing']['sessions'].values()):
        raise RuntimeError('P5-B requires B wait=0')
    return checked
