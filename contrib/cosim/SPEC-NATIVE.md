# Native timed hybrid execution (v3)

## Scope and ownership

- Same A/R/B placement, Q2NS SwapApp/TeleportationApp, IPv4/UDP result packet,
  session-start API, shared capacity-one R/B FIFO, and pre-created input/EPR.
- `NativeExecutionCore` derives from `HybridExecutionCore`: request identity,
  resource registration/reservation, physical positions and protocol handles
  retain the same contract. Both native protocols use this one core instance.
- NetSquid alone owns quantum state, physical instruction execution and time.
  Q2NS native state/qubit counts remain zero.
- The atomic runner and its experiment definitions remain available as the v2
  baseline. The parent commit and source hashes are in
  `baselines/native-timed-parent.json`. One shared C++ startup fix is explicitly
  recorded: finish Q2NS's zero-time activation before registering user starts.

## Configured native circuit

`native_instructions` contains positive integer nanosecond durations:

| Key | Default | Use |
|---|---:|---|
| `cnot_ns` | 600000 | CNOT(input0, input1) |
| `h_ns` | 200000 | H(input0) |
| `measure_ns` | 400000 | Each sequential Z measurement |
| `x_ns` | 250000 | X or identity correction slot |
| `z_ns` | 250000 | Z or identity correction slot |

These are illustrative modeling choices, not hardware calibration. BSM totals
1.6 ms; correction totals 0.5 ms. Totals are derived from these instructions.
Explicit atomic total fields, if provided, must match the sums.

The R program is `CNOT -> H -> MEASURE_0 -> MEASURE_1`, each executed with
`physical=True` in a `QuantumProgram`. Its measurement outputs are `(m1,m2)`.
The B program is `X if m2 else I -> Z if m1 else I`. Identity slots have the
same durations as the corresponding correction slots, including branch 00.
Instructions and programs are serial, not parallel or preemptive.

The processor's idle memory noise is native `T1T2NoiseModel`. NetSquid 1.1.7
does not apply that idle model over an active physical instruction's time on
its targets. Therefore each physical instruction also has the same T1/T2
storage model as `quantum_noise_model`, with `apply_q_noise_after=False`.
This counts waiting and active storage time once each, applies the ideal gate
at instruction completion, and adds no separate calibrated gate error.
Untargeted positions continue to use native idle memory noise.

## Event calendar and completion

The native backend uses NetSquid's actual event calendar. Each reported ns-3
next-event time is registered as a native bridge wakeup. A native program-done
callback records its actual simulation time and registers a same-time wakeup.
No externally predicted operation-end timer releases a processor or creates a
result packet. Config-derived timing sums are used only by the independent
validation oracle and for input overflow checks.

At a bridge wakeup at t:

1. Process existing ns-3 events at t and import their causal traces.
2. Submit the resulting Q2NS requests to the common FIFO/resource contract.
3. Dispatch idle R/B processors using native `execute_program`.
4. Inject queued native completions into Q2NS at t.
5. Register the participant's updated next-event time on the native calendar.

Q2NS result creation after a BSM completion stays at that same timestamp.
Background already scheduled at t precedes newly injected result sends. A
correction request requires actual result reception at B; the processor is
released only by its program-done callback. Equal-time session arrivals retain
ns-3/config order. Intermediate native events can run without an IPC round.

The atomic loop's strict global `COMMIT -> INPUT` order at ties is not asserted
for native internal events. Same-time processor completion and request arrival
may be handled in either native order; FIFO queuing plus callback-only release
produces the specified request starts in both cases. No time epsilon,
clock rollback, private engine API, or artificial completion timestamp is used.

Program failure is fatal. Final clocks, event calendar, request queues and
completion delivery must all drain. Arbitrary quantum channels, dynamic EPR,
mid-program external control and retry/cancellation remain outside this scope.

## Observations and independent reference

Each gate has native start/completion traces and an optional density-matrix
checkpoint. State observations run as zero-duration diagnostic instructions on
the program's positions; they respect native busy-memory access. They add no
gate duration. A dedicated test removes these diagnostic instructions and
checks that final states/timing are unchanged within numerical precision.

`netsquid_reference_native.py` imports none of the production core, adapters or
programs. It builds an independent timed circuit and enumerates all four BSM
branches using projected measurements with Born probabilities. It receives the
observed operation starts/packet arrival, the instruction model and memory
noise. Its native program completion times, intermediate conditional states,
frame, packet-arrival, correction-start and usable states are compared against
the co-simulation. Conditional checkpoints use only the measured prefix, not
future measurement outcomes. Branch probabilities must sum to one.

The noiseless test covers five teleport inputs and all four branches. Noisy
checks include active-time T1 decay against its analytic exponential, internal
gate-duration changes, late packets, mixed R/B contention, same-time starts,
observer invariance, malformed traces and drops. Atomic-vs-native state
differences are recorded as model differences, not required to be zero.
