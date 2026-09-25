"""Evaluation-only R capacity relaxation; same hybrid federation and native Q2NS packets."""
from run_hybrid import HybridManager, HybridValidationFailure


class NoDqManager(HybridManager):
    def __init__(self,scenario,binary=None):
        super().__init__(scenario,binary,no_dq=True)

    def run(self,references=None):
        report=super().run(references)
        if any(m['correction_wait_ns'] for m in report['metrics']['sessions']):
            raise HybridValidationFailure(report,RuntimeError('P5-B requires B wait=0'))
        return report
