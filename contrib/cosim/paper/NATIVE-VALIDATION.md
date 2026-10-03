# Native timed execution — validation results

NetSquid-native `QuantumProgram` backend; atomic v2 evidence is preserved in [its paper archive](../baselines/atomic-v2-paper.tar.gz).

## Correctness

- 258 tests PASS: 159 Python (including 19 new native tests), 16 evaluation/timing/instrumentation, 83 Q2NS native cases.
- Five noiseless Teleport inputs × 32 seeds = 160 transactions; all four BSM branches for each input.
- Maximum intermediate/checkpoint density-matrix error against the independent native reference: **4.44e-16**.
- Configured gate durations, native operation ends and actual packet-generation timestamps agree exactly (0 ns error).
- Mixed Swap/Teleport R/B FIFO, result queueing, equal-time arrivals, active/idle T1 accounting and observer invariance pass.

## Teleport native instruction trace

This example starts locally at R at 1 ms. All values below are simulated milliseconds.

| Instruction | Start | Complete |
|---|---:|---:|
| CNOT | 1.0000 | 1.6000 |
| H | 1.6000 | 1.8000 |
| MEASURE_0 | 1.8000 | 2.2000 |
| MEASURE_1 | 2.2000 | 2.6000 |
| X | 2.8256 | 3.0756 |
| IDLE_Z | 3.0756 | 3.3256 |

The native BSM callback generates the actual UDP result at 2.6000 ms; B receives it at 2.8256 ms and begins correction.

## Model distinction

For the single Teleport example, matching total BSM/correction durations preserves atomic-vs-native operation timing.
The branch-probability-weighted final density matrices nevertheless differ by **0.008699** (maximum element difference).
This reflects different noise/gate ordering. It is not a failure of either model against its own reference.

Default CNOT/H/each-measurement durations are 0.6/0.2/0.4 ms; X/I and Z/I slots are each 0.25 ms.
These parameters are illustrative, not hardware calibration. Storage T1/T2 is applied before each ideal gate at instruction completion.
Native P5-B simplification and simulation-cost results are reported in [RESULTS.md](RESULTS.md).

Evidence: [summary](../results/native-timed/summary.json), [regression](../results/native-timed/regression-summary.json),
[Teleport trace](../results/native-timed/teleport.json), [Mixed trace](../results/native-timed/mixed.json).
