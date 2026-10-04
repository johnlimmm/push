"""Six Pauli eigenstates for chained validation; frozen v4 states stay intact."""
from hybrid_adapters import STATES as FROZEN_STATES

STATES = dict(FROZEN_STATES)
STATES['-i'] = FROZEN_STATES['+i'].conjugate()
