# QuCl Figures 3–5: literature gates and 20/10-ms memory

- **Fig. 3:** end-to-end Swap→Teleport added latency (bar chart).
- **Fig. 4:** final teleportation fidelity, equally averaged over six inputs (point/interval chart).
- **Fig. 5:** swapping-stage simplification error (bar chart).

[RESULTS.md](RESULTS.md) explains the results in Korean. [FIGURES.pdf](FIGURES.pdf)
contains all three plots. Individual vector PDFs and 400-dpi PNGs are in
`figures/`; all aggregates, input-resolved fidelity, raw scalar results and
calibration are in `data/`. Full trace/state reports remain under the experiment
directory named in `provenance.json`. Previous one-second T2 results are preserved
in `../evaluation-long-memory/`; do not reuse their numerical values for this profile.

The legend labels `0.5× interval`, `1× interval`, and `2× interval` refer to
workflow-start spacing relative to the fixed 27.405-μs BSM duration. Every
workflow executes a complete BSM. Bar colors and hatches identify each series;
fidelity uses the same colors with distinct marker shapes. Definitions and 95%
interval details are in the LaTeX captions, leaving the plots free of titles and
explanatory text.

## LaTeX integration

Use `evaluation.tex` and merge `references.bib`. Both tables are written directly
in this section; no separate table inputs are needed. Requires `graphicx` and
`booktabs`. The fragment sets the figure
counter to 2 before its first figure, so these are Figures 3, 4 and 5. Remove that
counter line if the containing manuscript already controls numbering. Relative
paths assume this directory. The section is not a standalone paper. No LaTeX
engine is installed; the generated PDFs and citation/path consistency are checked,
but the full manuscript is not compiled.

`evaluation.tex` is author-maintained. Rendering preserves an existing section
and copies the reviewed section into a new output directory when needed. If the
experiment changes, update the numerical claims in the section after checking
the generated CSVs; the renderer does not rewrite the paper.

## Reproduction from the ns-3 root

```bash
./ns3 build cosim-chained cosim-provisioned
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_memory_evaluation.py \
  contrib/cosim/scenarios/memory-evaluation.json \
  --output-dir contrib/cosim/results/memory-evaluation-new
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/tests -p 'test_*.py' -v
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/experiments/tests -p 'test_*.py' -v
/home/ns3/qunet/bin/python contrib/cosim/tools/audit_native_fidelity.py \
  --source contrib/cosim/results/memory-evaluation-new
/tmp/qucl-native-plot-env/bin/python contrib/cosim/tools/render_memory_evaluation.py \
  --source contrib/cosim/results/memory-evaluation-new
```

Execution uses NetSquid 1.1.7/Python 3.7; plotting uses a separate matplotlib
environment. The renderer audits source and report hashes and test logs before
generating output. For another run pass `--source` and refresh its test logs.
Completed run directories cannot be overwritten. Resume requires byte-identical
plans and execution-source hashes. Physical circuits, scheduling and noise are
unchanged. The two reference fidelity expressions now call NetSquid's public
`qapi.fidelity(..., squared=True)` API, as the production co-simulation already
does. The current figures recompute this metric on all saved output states;
this update is not represented as another network/quantum simulation run.
`data/native-fidelity-audit.json` records every final branch value and verifies
that the only source changes since the run are the two exact metric-expression
substitutions. All original report and source hashes are retained. A fresh run
already using the native API needs no source migration. Fixed-Dc uses virtual
transport; other models use actual ns-3 packets.

The run switched from serial execution to two independent condition workers
without changing the plan or physical sources. Completed new-profile reports
were retained and audited by the original runner's final `--resume` aggregation.
`parallel-provenance.json` records the orchestration code and retained-cell count.
The initial 196-case regression had two frozen-document hash failures caused by
a navigation notice added to the historical RESULTS.md. That notice was moved to
`paper/LATEST.md`; both checks then passed. Provenance retains the initial log and
the two-case recheck rather than representing them as one clean test invocation.

Each traffic condition is rerun as six separate four-session batches. All
six-state timing/decomposition signatures must match. The 16 joint measurement
branches are enumerated; then inputs and sessions are averaged inside each phase.
95% intervals resample the 16 independent loaded traffic phases, not quantum
branches or input states. Zero-load controls have one run per input and no CI.
Calibration has four disjoint phases per loaded condition; calibration uncertainty
is not included in these intervals. Memory parameters have published simulation
precedent, but uniform memories plus the separately sourced gate table form a
composite abstract model, not a calibrated device reproduction.
