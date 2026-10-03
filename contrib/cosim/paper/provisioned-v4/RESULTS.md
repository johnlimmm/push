# QuCl provisioned-native v4 — validation and evaluation results

**Architecture: A/R/B; actual NetSquid quantum-channel delivery; resource-ready gating; native timed gates; actual R→B result UDP. All evaluation and cost results were freshly executed with v4.**

Latency is correction completion minus local session_start_ns. Classical load applies only to the R→B result link.

All intervals below are 95% percentile bootstrap intervals. Runtime intervals resample repeated runs; P5-B intervals resample traffic-phase clusters.

## Provisioning and comparison contract

EPRs are prepared at R at t=0. QuantumChannel R→A delay is 0.8 ms; R→B delay is 1.2 ms; channel depolarization is 0 Hz. Native memory T1/T2 stays enabled. Lossless delivery and ideal zero-delay readiness knowledge at R are assumed.

All state-bearing models run the same native channels and retain resource wait. Full-Sync retains R FIFO and actual result packets. No-Dq-R removes only R execution capacity constraints, using separate native processors attached to R. Fixed-Dc replaces only result transport with a calibrated constant delay; it retains channels and R/B FIFO. Decoupled adds eligible R FIFO waiting to No-Dq-R result delays without regenerating packet phases, and predicts no state.

Session 1 starts at 1 ms and waits 0.2 ms for resources. The 0.8-ms case therefore has R waits 0/1.0/1.8/2.6 ms in Full-Sync. Deadline remains 5 ms from local session start and includes resource wait.

These parameters are recorded in the evaluation plan before the sweep; thresholds and traffic/quantum seed lists retain the prior study settings. Channel-noise/delay sensitivity is validated in the separate 96-run provisioning study.

## Native timing

- 12 actual mixed-protocol workloads / 500 R/B requests: maximum start, completion and waiting error **0 ns** against the independent resource-ready/FIFO oracle.
- Native program-done callbacks drive Q2NS completion and actual packet generation. Gate/checkpoint states are cross-validated against a separately implemented native NetSquid circuit.
- Serial CNOT/H/M/M = 0.6/0.2/0.4/0.4 ms. X-or-I and Z-or-I slots are 25 us each in P5-B and 250 us each in the cost study.
- Idle and active storage use native T1/T2; ideal gates act at instruction completion. Durations are illustrative, not hardware calibration.

## Expanded P5-B

384 paired cases; 1152 simulation runs plus 6 calibration runs; 1536 transactions per model. Maximum reference density-matrix error: 4.44e-16.

| Request interval (ms) | Load | Model | Latency MAE (ms), mean [CI] | Expected fidelity bias, mean [CI] |
|---:|---:|---|---:|---:|
| 0.8 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 0.8 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | No-Dq-R | 1.350 [1.350, 1.350] | 0.0643 [0.0643, 0.0643] |
| 2.0 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Decoupled | 0.152 [0.120, 0.187] | not defined |
| 0.8 | 0.35 | Fixed-Dc | 0.141 [0.111, 0.172] | 0.0040 [0.0030, 0.0051] |
| 0.8 | 0.35 | No-Dq-R | 1.319 [1.296, 1.345] | 0.0623 [0.0615, 0.0632] |
| 2.0 | 0.35 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.35 | Fixed-Dc | 0.169 [0.141, 0.196] | 0.0046 [0.0036, 0.0056] |
| 2.0 | 0.35 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | 0.244 [0.213, 0.276] | not defined |
| 0.8 | 0.7 | Fixed-Dc | 0.261 [0.249, 0.274] | -0.0041 [-0.0051, -0.0031] |
| 0.8 | 0.7 | No-Dq-R | 1.334 [1.297, 1.369] | 0.0606 [0.0594, 0.0617] |
| 2.0 | 0.7 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.7 | Fixed-Dc | 0.263 [0.248, 0.278] | -0.0037 [-0.0046, -0.0028] |
| 2.0 | 0.7 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |

## Feasibility (pre-specified thresholds retained)

F_min=0.5; deadline=5 ms from local session start at R. Rates are fractions of all paired transactions in the cell, not conditional false-positive rates.

| Interval (ms) | Load | Model | False service feasible [CI] | False service infeasible [CI] | False deadline feasible [CI] |
|---:|---:|---|---:|---:|---:|
| 0.8 | 0.0 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | No-Dq-R | 0.3750 [0.3750, 0.3750] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Decoupled | not defined | not defined | 0.0156 [0.0000, 0.0391] |
| 0.8 | 0.35 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0312 [0.0078, 0.0625] |
| 0.8 | 0.35 | No-Dq-R | 0.3477 [0.3281, 0.3633] | 0.0000 [0.0000, 0.0000] | 0.0312 [0.0078, 0.0625] |
| 2.0 | 0.35 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | not defined | not defined | 0.0234 [0.0000, 0.0547] |
| 0.8 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0469 [0.0156, 0.0859] |
| 0.8 | 0.7 | No-Dq-R | 0.3477 [0.3281, 0.3633] | 0.0000 [0.0000, 0.0000] | 0.0469 [0.0156, 0.0859] |
| 2.0 | 0.7 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |

Zero observed errors (including a zero-width empirical bootstrap interval) do not establish zero population error. These estimates are conditional on fixed calibration from two traffic seeds and periodic background traffic with randomized start phase.

## Simulation cost

| Sessions | Load | Total (s), mean [CI] | Per transaction (ms), mean [CI] | Rounds | Unique times | IPC lines (both ways) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0 | 0.087 [0.081, 0.094] | 86.9 [81.1, 93.7] | 10 | 7 | 58 |
| 1 | 0.7 | 0.133 [0.104, 0.167] | 132.5 [104.0, 166.8] | 25 | 22 | 123 |
| 4 | 0.0 | 0.180 [0.148, 0.217] | 45.0 [37.0, 54.2] | 31 | 22 | 179 |
| 4 | 0.7 | 0.265 [0.209, 0.331] | 66.3 [52.4, 82.8] | 64 | 55 | 322 |
| 8 | 0.0 | 0.253 [0.239, 0.270] | 31.7 [29.9, 33.7] | 59 | 42 | 341 |
| 8 | 0.7 | 0.461 [0.362, 0.585] | 57.7 [45.3, 73.1] | 116 | 99 | 588 |
| 16 | 0.0 | 0.698 [0.522, 0.902] | 43.6 [32.6, 56.4] | 115 | 82 | 665 |
| 16 | 0.7 | 0.685 [0.586, 0.806] | 42.8 [36.6, 50.4] | 220 | 187 | 1120 |
| 32 | 0.0 | 0.922 [0.864, 0.980] | 28.8 [27.0, 30.6] | 227 | 162 | 1313 |
| 32 | 0.7 | 1.253 [1.108, 1.433] | 39.2 [34.6, 44.8] | 431 | 366 | 2197 |
| 64 | 0.0 | 2.178 [1.962, 2.406] | 34.0 [30.6, 37.6] | 451 | 322 | 2609 |
| 64 | 0.7 | 2.805 [2.361, 3.340] | 43.8 [36.9, 52.2] | 850 | 721 | 4338 |

At zero background load, traffic phase is inactive and some metrics are deterministic across seeds. Collapsed intervals there do not represent additional workload diversity.

Runtime includes setup, ns-3 startup, all native instruction state probes, in-memory traces/snapshot and traffic drain; independent reference validation, build/import and disk I/O are excluded. It is not an isolated measurement of IPC overhead.

Environment: {"actual_quantum_channel_provisioning": true, "cpu": "Intel(R) Core(TM) Ultra 7 155H", "cpu_affinity": [0, 1], "instrumentation": "Two IPC line/byte counters per direction; normal production trace logging enabled.", "native_instruction_state_probes": true, "netsquid": "1.1.7", "numpy": "1.21.6", "platform": "Linux-6.8.0-138-generic-x86_64-with-Ubuntu-22.04-jammy", "python": "3.7.17 (default, Jun  6 2023, 20:10:09) \n[GCC 11.3.0]", "python_executable": "/home/ns3/qunet/bin/python"}
