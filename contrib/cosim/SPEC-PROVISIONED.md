# v4 — Quantum-channel resource provisioning

## Scope

Fixed A/R/B placement; lossless delivery of EPR halves created at R at t=0;
native NetSquid `Network`, `Node`, `QuantumChannel`, existing memories/processors,
and timed BSM/correction. Source preparation is ideal and instantaneous.
Teleportation's input and Alice processor remain at R. All sessions share one
capacity-one R processor and one capacity-one B processor with separate positions.
Positions are allocated per session; memory-capacity contention is not modeled.

Classical traffic remains exclusively on the actual ns-3 R→B UDP result link.
There is no Controller, command path, photon source physics, generation retry,
heralding protocol, quantum loss, dynamic topology, or quantum-link bandwidth
allocation. Native channels allow concurrent transmissions. Unsupported loss
configuration is rejected rather than treated as successful delivery.

The v3 commit and source hashes are in `baselines/native-v3-freeze.json`.
No existing v3 production, evaluation, paper artifact, or Q2NS source is modified.
v4 is a separate runner and participant with the existing core/instructions reused.

## Component ownership and storage

`QuantumNetworkBackend` places the same A `QuantumMemory`, R `QuantumProcessor`
and B `QuantumProcessor` instances under actual NetSquid Nodes. It connects R→A
and R→B with native one-way `QuantumChannel` components. All quantum states stay
in NetSquid. Q2NS contains logical handles only.

At t=0, a Bell pair is prepared at R. Its local half enters its R memory position;
its remote half is sent through the R node's channel port. The destination node's
input handler receives that same qubit object and puts it in destination memory.
No remote-half copy is made, and no half occupies both source and destination memory.
The receive callback, not an analytic timer in QuCl, sets the actual ready timestamp.

| Qubit | Storage/noise interval |
|---|---|
| R EPR half | Native T1/T2 from creation at 0 through waiting and native gates |
| Teleport input | Native T1/T2 from creation at 0 through its native BSM |
| Traveling remote half | Native channel depolarization during transit; no destination memory T1/T2 |
| Delivered remote half | Native destination T1/T2 from memory placement onward |

`quantum_links.RA/RB.delay_ns` is a nonnegative integer. `depolar_rate_hz` selects
native `DepolarNoiseModel(time_independent=False)` with a nonnegative rate in Hz.
Zero rate disables channel noise; zero delay and zero rate reproduce v3 states
and timings. With memory noise disabled, the fidelity of a delivered Bell pair is
`1 - 3/4 * (1 - exp(-rate_hz * delay_ns / 1e9))`; a dedicated test checks this law.
Native gate durations and ideal-gate/noise ordering retain the v3 model.

## Readiness policy and its assumption

This protocol policy requires complete delivery of input EPR resources before
requesting BSM. It is a modeling policy, not a physical requirement to delay all
local Bell measurements until a remote half arrives.

The simulator provides **ideal zero-delay knowledge of resource readiness** to R.
A remote port delivery is not a simulated herald or ACK. This approximation is
explicit in every network snapshot. Modeling a real acknowledgement would require
an actual ns-3 return path and a separate readiness-knowledge timestamp.

Pair lifecycle:

```
PROVISIONING → AVAILABLE → RESERVED → IN_USE → CONSUMED
                                                  ↘ output FRAME_PENDING → USABLE
```

All input handles must be AVAILABLE before a session-level `RESOURCES_READY` event.
Swap waits for RA and RB; Teleport waits for RB plus its input at R.
That event schedules a bridge wakeup on the existing native event calendar.
The bridge delivers `RESOURCE_READY` through IPC at the same simulated timestamp.

Q2NS readiness implementation:

- `TeleportationApp` uses its existing `NotifyExternalResourcesReady` and pending
  start request. Both source and sink receive notification.
- `SwapApp` is final and remains unchanged. A small `SwapResourceGate` in the v4
  participant retains session-start/readiness flags, then invokes the existing
  `RequestExternalBsm` once. The existing SwapApp still owns BSM completion,
  packet creation, payload parsing and correction callbacks.

The session's original start is recorded even if it is not yet eligible:

```
eligible = max(session_start, resource_ready)
resource_wait = eligible - session_start
R_processor_wait = BSM_start - eligible
latency = correction_complete - session_start
```

Only eligible requests enter the R FIFO. Unready sessions do not block eligible
ones. At the same timestamp, existing ns-3 start events for already-ready sessions
precede newly delivered readiness notifications. Each batch retains config order.
For the configured t=0 sends, the oracle sorts by `(eligible, ready >= start, slot)`.
The B FIFO continues to use actual result arrival order. Readiness is not BSM
completion, and it never generates the result packet by itself.

## Required invariants and reference

- A delivery occurs exactly once per logical pair, to its assigned node/position.
- Creation and delivery timestamps are distinct; BSM starts no earlier than all
  required resource-ready timestamps and session start.
- Duplicate or unknown readiness IPC is rejected. The BSM request is emitted once.
- Native program completion creates the real UDP result; correction requires
  actual packet receipt and B FIFO dispatch. Q2NS quantum state/qubit counts stay 0.
- Final channel deliveries, IPC notifications, native programs, packets and clocks
  drain completely. Packet drops fail correctness validation.

The timing oracle is computed from configuration only: channel delay, eligibility,
R FIFO, independent classical packet FIFO, B FIFO. It does not read production
trace timestamps to manufacture expected readiness or requests.

`netsquid_reference_provisioned.py` constructs a separate native quantum network
and programs without importing the production backend/core/adapters. It receives
the same link/noise model and observed operation timestamps, independently handles
delivery and memory placement, and enumerates all four Born-weighted branches.
Delivery states, resources-ready inputs, BSM inputs, each instruction state,
frame, packet-arrival and correction checkpoints are compared at matching times.

Additional checks include noiseless five-input/four-branch teleportation, analytic
channel depolarization, analytic local-half-only T1 decay during transit, v3 zero
delay equivalence, readiness reordering, delay masked by R wait, observer invariance,
mixed R/B contention, classical isolation, malformed evidence and overflow rejection.

## Evaluation interpretation

The provisioning sweep is a finite correctness/causality evaluation. It varies
four RA/RB delay combinations, background off/on, channel depolarization 0/50 Hz,
Swap/Teleport/mixed workloads and seeds 7/11. It does not establish population
performance or monotonic fidelity. Readiness delay can be hidden by processor wait;
changing arrival phase can also change classical queueing.

The published v3 P5-B comparison and cost figures remain v3 evidence. Their
Fixed-Dc/No-Dq-R/Decoupled numbers are not relabeled as v4 results. v4 results and
figures are recorded separately in `paper/PROVISIONING.md`.
