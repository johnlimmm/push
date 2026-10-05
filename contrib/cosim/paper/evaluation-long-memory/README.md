# Literature-profile evaluation package

Start with [RESULTS.md](RESULTS.md) for the Korean explanation and two figures.
[FIGURES.pdf](FIGURES.pdf) contains both plots. Vector PDFs and 400-dpi PNGs are
in `figures/`; every plotted number and interval is exported in `data/`.

## Paper integration

Use `evaluation.tex`, `physical-model.tex`, `table_validation.tex` and
`references.bib` with `graphicx` and `booktabs`. Merge the citation entries into
the paper's bibliography and adjust relative paths. These are section fragments,
not a standalone manuscript. The actual paper source/QuCl.pdf is not overwritten.
No LaTeX engine is installed here; figures and citation keys were checked, but
the combined manuscript has not been compiled.

The previous controlled-profile package is preserved in `../evaluation-controlled/`.
Do not combine its numbers with the new literature-profile captions.

## Reproduction (from ns-3 root)

```bash
./ns3 build cosim-chained cosim-provisioned
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_literature_evaluation.py \
  contrib/cosim/scenarios/literature-evaluation.json \
  --output-dir contrib/cosim/results/literature-evaluation-new
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/tests -p 'test_*.py' -v
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/experiments/tests -p 'test_*.py' -v
/tmp/qucl-native-plot-env/bin/python contrib/cosim/tools/render_literature_evaluation.py
```

The checked-in run uses `results/literature-evaluation-v1/`. For another run pass
`--source` to the renderer and update the two test logs it audits. Use NetSquid
1.1.7/Python 3.7.17 for execution and matplotlib 3.8.4/numpy for rendering (the
plotting virtualenv above is local, not distributed). Native participant binaries
are unchanged. The evaluation refuses an existing run directory; the renderer
replaces only its own generated literature package after source/report audits.

The two new runners attach native per-qubit gate noise through public processor
APIs. Frozen execution sources are unchanged. Independent reference programs have
their own circuits and noise setup in a separate process; they do not import the
production execution core. Each reference run resets the simulation; workers are
recycled after sixteen requests. A timeout interrupted the first invocation after
89 completed cells. The run resumed those validated new-profile reports after
hardening worker lifetime/stderr handling, without changing physics or circuits.
`summary.resumption` records reused/new counts and the two orchestration-source
hash changes. The failure and first log remain in
`results/literature-evaluation-interrupted/`. This is one resumed evaluation,
not two independent repetitions.

## Scope

Published nominal instruction/memory parameters; explicit QuCl gate-noise
placement. Finite four-session batches, ideal initialization/readout, lossless
quantum delivery. Six inputs × sixteen joint branches validate correctness;
the performance sweep uses +i. The swapping-only ablation is explicitly separate
from the end-to-end Swap→Teleport plot.

At nonzero load, intervals resample 16 traffic-phase clusters after averaging the
four transactions within each phase. The zero-load run is deterministic and has
no confidence interval. Fidelity expectations enumerate measurement outcomes;
there is no quantum-seed sampling uncertainty in those reported expectations.
Calibration uncertainty is not included in the intervals. `errors.csv` retains
the original fidelity/deadline audits, including cases with no observed failures.
