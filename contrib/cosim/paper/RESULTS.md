# QuCl direct-session-start v2 — validation results

**Architecture: A/R/B; local session start at R; only native R→B result packets. All results below were rerun for this structure.**

Latency is correction completion minus local session_start_ns. Classical load applies only to the R→B result link.

All intervals below are 95% percentile bootstrap intervals. Runtime intervals resample repeated runs; P5-B intervals resample traffic-phase clusters.

## Native timing

- 120 synthetic workloads / 2500 requests: maximum start, completion and waiting error **0 ns**.
- 500 R/B requests from 12 actual mixed-protocol runs: maximum timing error **0 ns**.
- Capacity-one FIFO and explicit input-order tie policy; timing equivalence, not gate-level state or hardware validation.

## Expanded P5-B

384 paired cases; 1152 simulation runs plus 6 calibration runs; 1536 transactions per model. Maximum reference density-matrix error: 2.78e-16.

| Request interval (ms) | Load | Model | Latency MAE (ms), mean [CI] | Expected fidelity bias, mean [CI] |
|---:|---:|---|---:|---:|
| 0.8 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 0.8 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.0 | No-Dq-R | 1.200 [1.200, 1.200] | 0.0435 [0.0435, 0.0435] |
| 2.0 | 0.0 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.0 | Fixed-Dc | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.0 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.35 | Decoupled | 0.117 [0.073, 0.165] | not defined |
| 0.8 | 0.35 | Fixed-Dc | 0.174 [0.144, 0.206] | 0.0040 [0.0031, 0.0049] |
| 0.8 | 0.35 | No-Dq-R | 1.188 [1.185, 1.191] | 0.0423 [0.0419, 0.0426] |
| 2.0 | 0.35 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.35 | Fixed-Dc | 0.184 [0.151, 0.216] | 0.0042 [0.0031, 0.0053] |
| 2.0 | 0.35 | No-Dq-R | 0.000 [0.000, 0.000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | 0.223 [0.189, 0.260] | not defined |
| 0.8 | 0.7 | Fixed-Dc | 0.242 [0.227, 0.258] | 0.0017 [0.0008, 0.0026] |
| 0.8 | 0.7 | No-Dq-R | 1.188 [1.174, 1.208] | 0.0409 [0.0403, 0.0415] |
| 2.0 | 0.7 | Decoupled | 0.000 [0.000, 0.000] | not defined |
| 2.0 | 0.7 | Fixed-Dc | 0.240 [0.227, 0.253] | 0.0018 [0.0010, 0.0026] |
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
| 0.8 | 0.35 | No-Dq-R | 0.1875 [0.1484, 0.2266] | 0.0000 [0.0000, 0.0000] | 0.0156 [0.0000, 0.0391] |
| 2.0 | 0.35 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.35 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 0.8 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0234 [0.0000, 0.0547] |
| 0.8 | 0.7 | No-Dq-R | 0.0938 [0.0547, 0.1328] | 0.0000 [0.0000, 0.0000] | 0.0234 [0.0000, 0.0547] |
| 2.0 | 0.7 | Decoupled | not defined | not defined | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | Fixed-Dc | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |
| 2.0 | 0.7 | No-Dq-R | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] | 0.0000 [0.0000, 0.0000] |

Zero observed errors (including a zero-width empirical bootstrap interval) do not establish zero population error. These estimates are conditional on fixed calibration from two traffic seeds and periodic background traffic with randomized start phase.

## Simulation cost

| Sessions | Load | Total (s), mean [CI] | Per transaction (ms), mean [CI] | Rounds | Unique times | IPC lines (both ways) |
|---:|---:|---:|---:|---:|---:|---:|
| 1 | 0.0 | 0.063 [0.050, 0.082] | 63.3 [49.9, 82.1] | 8 | 6 | 49 |
| 1 | 0.7 | 0.090 [0.063, 0.127] | 89.9 [63.4, 127.0] | 20 | 18 | 101 |
| 4 | 0.0 | 0.113 [0.090, 0.147] | 28.1 [22.4, 36.7] | 28 | 20 | 161 |
| 4 | 0.7 | 0.153 [0.123, 0.196] | 38.4 [30.8, 48.9] | 58 | 50 | 291 |
| 8 | 0.0 | 0.201 [0.163, 0.245] | 25.2 [20.3, 30.6] | 54 | 38 | 309 |
| 8 | 0.7 | 0.229 [0.199, 0.278] | 28.6 [24.8, 34.7] | 111 | 95 | 556 |
| 16 | 0.0 | 0.337 [0.287, 0.391] | 21.1 [18.0, 24.4] | 106 | 74 | 605 |
| 16 | 0.7 | 0.425 [0.376, 0.486] | 26.5 [23.5, 30.4] | 211 | 179 | 1060 |
| 32 | 0.0 | 0.617 [0.539, 0.716] | 19.3 [16.9, 22.4] | 210 | 146 | 1197 |
| 32 | 0.7 | 0.796 [0.713, 0.886] | 24.9 [22.3, 27.7] | 414 | 350 | 2081 |
| 64 | 0.0 | 1.173 [1.000, 1.397] | 18.3 [15.6, 21.8] | 418 | 290 | 2381 |
| 64 | 0.7 | 1.503 [1.414, 1.607] | 23.5 [22.1, 25.1] | 817 | 689 | 4110 |

At zero background load, traffic phase is inactive and some metrics are deterministic across seeds. Collapsed intervals there do not represent additional workload diversity.

Runtime includes setup, ns-3 startup, normal in-memory traces/snapshot and traffic drain; independent reference validation, build/import and disk I/O are excluded. It is not an isolated measurement of IPC overhead.

Environment: {"cpu": "Intel(R) Core(TM) Ultra 7 155H", "cpu_affinity": [0, 1], "instrumentation": "Two IPC line/byte counters per direction; normal production trace logging enabled.", "netsquid": "1.1.7", "numpy": "1.21.6", "platform": "Linux-6.8.0-138-generic-x86_64-with-Ubuntu-22.04-jammy", "python": "3.7.17 (default, Jun  6 2023, 20:10:09) \n[GCC 11.3.0]", "python_executable": "/home/ns3/qunet/bin/python"}
