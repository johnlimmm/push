# v5 — Swapping-assisted A→B teleportation

## Purpose and compatibility

A is Alice, B is Bob, R is the repeater. A chain first creates a usable A–B pair
through R's SwapApp, then consumes that exact pair in A's TeleportationApp.
The v4 R→B mixed-protocol contention workload remains a frozen regression baseline;
it tested independent protocols sharing R, whereas v5 tests resource composition.
The v4 source manifest is `baselines/provisioned-v4-freeze.json`.

No existing Q2NS source changes are needed. Both real Q2NS applications retain
native result packet creation, payload decoding, external requests, and completion
callbacks. `ChainedCore` extends the same `NativeExecutionCore` / resource FIFO
contract. The existing `ProvisionedFederation` event loop is reused without changes.

## Nodes, resources, and physical execution

- NetSquid owns every quantum state. Q2NS native state/qubit counts must remain zero.
- A, R, B each have a capacity-one native timed `QuantumProcessor`.
  Swap BSM uses R, teleport BSM uses A, both corrections share B.
- There is one input qubit at A and two elementary EPR pairs per chain.
  Input and EPR creation are t=0; input aging starts immediately.
- R stores both local EPR halves. The remote halves travel on the actual native
  R→A / R→B quantum channels and enter destination memory only on port delivery.
- Default quantum-link delays: R→A 0.8 ms, R→B 1.2 ms. Channel depolarization is
  configurable; no loss, heralding, source physics, or retry is modeled.
- Native T1/T2 memory/instruction noise and native CNOT/H/measurement/X/Z programs
  are unchanged. Default BSM is 1.6 ms and correction is 0.5 ms at both stages.
- Separate memory positions per chain; finite memory capacity is not evaluated.

The elementary-pair readiness knowledge at R retains v4's **ideal zero-delay**
notification assumption. The *downstream swapped-pair readiness knowledge at A*
is carried by a new actual ns-3 UDP packet and is never delivered by that shortcut.

## Ordered protocol

```text
local chain start at R + elementary pairs delivered
 -> R SwapApp BSM request -> R FIFO -> native swap BSM
 -> existing SwapApp R→B UDP result (80-byte default application payload)
 -> B SwapApp receives -> B FIFO -> native swap correction
 -> actual A–B pair ownership transfer, same qubit objects, no quantum operation
 -> B→R→A UDP PAIR_READY (16-byte application payload)
 -> A TeleportationApp resources ready + its local start requested
 -> A FIFO -> native teleport BSM on input and A's swapped-pair half
 -> existing TeleportationApp A→R→B UDP result (2-byte application payload)
 -> B TeleportationApp receives -> B FIFO -> native teleport correction
 -> final B qubit compared with the original input target
```

Local session-start events for both stages use the chain's configured start time.
TeleportationApp holds its request until its resource-ready notification arrives.
The first implementation deliberately completes swap correction before issuing the
ready packet. It does not use early teleportation with deferred Pauli-frame merging.
No separate Controller, command packet, or direct A–B quantum channel is added.

## Classical network

Two bidirectional IPv4 point-to-point links, A–R and R–B, with IP forwarding at R.
Defaults: 10 Mb/s and 0.2 ms propagation per link/direction. Actual native UDP
payloads survive both hops. ReadyHeader contains the downstream session ID and
logical swap-output handle; observation PacketTags do not contribute wire bytes.
Wire overhead is 30 bytes per hop (PPP+IPv4+UDP). Actual queue, PHY and application
traces are recorded on every hop. Each direction has its own capacity and FIFO.
Background traffic is confined to R→B, uses a separate port, and creates no quantum
request. Any packet drop fails correctness validation. QueueDisc is removed and
PointToPointNetDevice uses a DropTail queue, as in the baseline.

Readiness is trusted simulation control, not an authenticated or reliable transport.
Duplicate ready receptions are idempotent; loss/retransmission is outside scope.

## Resource and identity contract

User configuration contains `chains`, not independent sessions. Every chain has a
unique `chain_id`, start time and input state. Internal stage IDs are unique across
the run and are explicitly linked by `parent_session_id`.

```text
Swap elementary pairs: PROVISIONING -> AVAILABLE -> RESERVED -> IN_USE -> CONSUMED
Swap A–B output: FRAME_PENDING -> RESERVED -> IN_USE -> USABLE -> TRANSFERRED
Teleport EPR:    AVAILABLE (origin = swap/output) -> RESERVED -> IN_USE -> CONSUMED
Teleport input: AVAILABLE -> RESERVED -> IN_USE -> CONSUMED
Teleport output at B: FRAME_PENDING -> RESERVED -> IN_USE -> USABLE
```

Handoff occurs only after native swap correction completion and clears the previous
owner. The transfer records its source/destination identities and keeps the same
A/B memory locations and actual qubit objects. It does not pop/reinsert/reset those
qubits or prepare a replacement Bell pair. Pair identity is checked again at the
teleport BSM request; Bob's surviving identity is checked at final completion.
Only one consumer per swapped pair is supported.

## Metrics and acceptance

Primary latency is final teleport correction completion minus the original local
chain start. Resource wait, R swap wait, two native BSM durations, two correction
durations, both result-packet delays, ready-packet delay, A wait and both B waits
are reported separately and must sum exactly to end-to-end latency.

Record the swap-usable pair state, teleport input/EPR state at BSM start, each
native instruction checkpoint, both packet arrivals and corrections, and final B
state. Swap's usable snapshot remains a historical checkpoint after handoff.
Input fidelity at teleport BSM is relative to its original t=0 target.

Validation requires:

1. Actual five control-packet hops per chain, with correct endpoints, payloads,
   serialization, propagation, and native Q2NS request/completion timestamps.
2. Independent FIFO recurrence per directed link and per processor. The FIFO oracle
   consumes observed enqueue/arrival ordering, while separate causal checks tie
   arrivals to packet forwarding and native operation completions. It is not
   described as a fully independent network simulation from configuration alone.
3. Exclusive state ownership, original pair identity/provenance and single use.
4. No teleport request before the actual B→R→A readiness packet arrives; no correction
   before its measured-bit result packet arrives.
5. An independent NetSquid-only two-stage circuit matches checkpoint and final
   density matrices using the same observed stage timestamps and physical parameters.
   It imports no production core, adapter or quantum program. The reference performs
   conditional measurement projection; enumeration covers all 16 joint branches.
6. Noiseless inputs 0, 1, +, -, +i, -i each cover all 16 joint branches with fidelity≈1
   (96 transactions). Native T1/T2 is also checked for all six inputs at A–R delays
   0.2 and 1 ms: 12 runs, observed checkpoint-state comparison and enumeration of
   all 16 reference branches per run. The two Y eigenstates must have opposite
   imaginary-coherence signs at teleport BSM start.
7. Existing P0–v4/P5-B/native Q2NS regression remains unchanged and passing.

## Analysis contract

`scenarios/chained-evaluation.json` fixes a finite 48-run design before evaluation:
3 A–R delays × 2 chain-start intervals × 2 R→B offered loads × 4 traffic phases.
Each run has four chains. Quantum seed is fixed; final expected fidelity is computed
by exact Born-probability weighting of the independent reference's 16 joint branches
at that chain's timing. This is not a 16-seed sample mean.

The six-input branch test separately uses seeds selected for **coverage**, not
performance inference. Noiseless coverage results must not be presented as random
performance samples. Analysis is finite periodic-background characterization with
four phases; no hardware fidelity, population success-rate, throughput scaling,
or universal monotonicity claim is made. The previous P5-B baselines are not
silently reinterpreted as evaluations of this new composed application.
