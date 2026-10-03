# QuCl native-timed v3 — validation and evaluation results

**Architecture: A/R/B; local session start; NetSquid timed gate chains; actual R→B result UDP. All evaluation and cost results were rerun with this native backend.**

Latency is correction completion minus local session_start_ns. Classical load applies only to the R→B result link.

All intervals below are 95% percentile bootstrap intervals. Runtime intervals resample repeated runs; P5-B intervals resample traffic-phase clusters.

## Native timing

- 12 actual mixed-protocol workloads / 500 R/B requests: maximum start, completion and waiting error **0 ns** against the independent FIFO oracle.
- Native program-done callbacks drive Q2NS completion and actual packet generation. Gate/checkpoint states are cross-validated against a separately implemented native NetSquid circuit.
- Serial CNOT/H/M/M = 0.6/0.2/0.4/0.4 ms. X-or-I and Z-or-I slots are 25 us each in P5-B and 250 us each in the cost study.
- Idle and active storage use native T1/T2; ideal gates act at instruction completion. Durations are illustrative, not hardware calibration.

## Expanded P5-B

384 paired cases; 1152 simulation runs plus 6 calibration runs; 1536 transactions per model. Maximum reference density-matrix error: 3.89e-16.

| Request interval (ms) | Load | Model | Latency MAE (ms), mean [CI] | Expected fidelity bias, mean [CI] |
|---:|---:|---|---:|---:|
| 0.8 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 0.8 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | No-Dq-R | 1.200 [1.200, 1.200] | 0.0486 [0.0486, 0.0486] |
| 2.0 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Decoupled | 0.117 [0.073, 0.165] | not defined |
| 0.8 | 0.35 | Fixed-Dc | 0.174 [0.144, 0.206] | 0.0045 [0.0035, 0.0055] |
| 0.8 | 0.35 | No-Dq-R | 1.188 [1.185, 1.191] | 0.0472 [0.0467, 0.0476] |
| 2.0 | 0.35 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.35 | Fixed-Dc | 0.184 [0.151, 0.216] | 0.0048 [0.0035, 0.0060] |
| 2.0 | 0.35 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | 0.223 [0.189, 0.260] | not defined |
| 0.8 | 0.7 | Fixed-Dc | 0.242 [0.227, 0.258] | 0.0020 [0.0009, 0.0029] |
| 0.8 | 0.7 | No-Dq-R | 1.188 [1.174, 1.208] | 0.0456 [0.0449, 0.0462] |
| 2.0 | 0.7 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.7 | Fixed-Dc | 0.240 [0.227, 0.253] | 0.0020 [0.0011, 0.0029] |
| 2.0 | 0.7 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |

## Feasibility (pre-specified thresholds retained)

F_min=0.5; deadline=5 ms from local session start at R. Rates are fractions of all paired transactions in the cell, not conditional false-positive rates.

| Interval (ms) | Load | Model | False service feasible [CI] | False service infeasible [CI] | False deadline feasible [CI] |
|---:|---:|---|---:|---:|---:|
| 0.8 | 0.0 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | No-Dq-R | 0.2500 [0.2500, 0.2500] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0156 [0.0000, 0.0391] |
| 0.8 | 0.35 | No-Dq-R | 0.2344 [0.2109, 0.2500] | 0.0000 [0.0000, 0.0000] | 0.0156 [0.0000, 0.0391] |
| 2.0 | 0.35 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0234 [0.0000, 0.0547] |
| 0.8 | 0.7 | No-Dq-R | 0.1875 [0.1484, 0.2188] | 0.0000 [0.0000, 0.0000] | 0.0234 [0.0000, 0.0547] |
| 2.0 | 0.7 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |

Zero observed errors (including a zero-width empirical bootstrap interval) do not establish zero population error. These estimates are conditional on fixed calibration from two traffic seeds and periodic background traffic with randomized start phase.

## Simulation cost

| Sessions | Load | Total (s), mean [CI] | Per transaction (ms), mean [CI] | Rounds | Unique times | IPC lines (both ways) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0 | 0.113 [0.090, 0.141] | 113.2 [89.9, 141.5] | 8 | 6 | 49 |
| 1 | 0.7 | 0.134 [0.102, 0.171] | 134.1 [102.2, 170.6] | 20 | 18 | 101 |
| 4 | 0.0 | 0.194 [0.173, 0.215] | 48.6 [43.4, 53.8] | 29 | 20 | 163 |
| 4 | 0.7 | 0.280 [0.217, 0.345] | 70.0 [54.2, 86.3] | 59 | 50 | 293 |
| 8 | 0.0 | 0.333 [0.280, 0.410] | 41.6 [35.0, 51.3] | 57 | 38 | 315 |
| 8 | 0.7 | 0.374 [0.325, 0.432] | 46.7 [40.6, 54.0] | 114 | 95 | 562 |
| 16 | 0.0 | 0.805 [0.653, 0.967] | 50.3 [40.8, 60.4] | 113 | 74 | 619 |
| 16 | 0.7 | 0.707 [0.622, 0.812] | 44.2 [38.9, 50.8] | 218 | 179 | 1074 |
| 32 | 0.0 | 1.303 [1.087, 1.526] | 40.7 [34.0, 47.7] | 225 | 146 | 1227 |
| 32 | 0.7 | 1.773 [1.352, 2.290] | 55.4 [42.2, 71.6] | 429 | 350 | 2111 |
| 64 | 0.0 | 2.318 [2.091, 2.576] | 36.2 [32.7, 40.3] | 449 | 290 | 2443 |
| 64 | 0.7 | 3.535 [3.159, 3.875] | 55.2 [49.4, 60.5] | 848 | 689 | 4172 |

At zero background load, traffic phase is inactive and some metrics are deterministic across seeds. Collapsed intervals there do not represent additional workload diversity.

Runtime includes setup, ns-3 startup, all native instruction state probes, in-memory traces/snapshot and traffic drain; independent reference validation, build/import and disk I/O are excluded. It is not an isolated measurement of IPC overhead.

Environment: {"cpu": "Intel(R) Core(TM) Ultra 7 155H", "cpu_affinity": [0, 1], "instrumentation": "Two IPC line/byte counters per direction; normal production trace logging enabled.", "native_instruction_state_probes": true, "netsquid": "1.1.7", "numpy": "1.21.6", "platform": "Linux-6.8.0-138-generic-x86_64-with-Ubuntu-22.04-jammy", "python": "3.7.17 (default, Jun  6 2023, 20:10:09) \n[GCC 11.3.0]", "python_executable": "/home/ns3/qunet/bin/python"}
