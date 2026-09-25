#!/usr/bin/env python3
"""Render paper-ready PDF/PNG figures, tables and a manuscript insert from evidence.

Run with a separate plotting Python (matplotlib); NetSquid is not imported here.
"""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def interval(metric, scale=1):
    mean = metric['mean']/scale
    ci = metric.get('ci95_cluster_bootstrap', metric.get('ci95_repetition_bootstrap'))
    return mean, ci[0]/scale, ci[1]/scale


def display(metric, scale=1, digits=3):
    mean, lo, hi = interval(metric, scale)
    return ('{:.%df} [{:.%df}, {:.%df}]' % (digits, digits, digits)).format(mean, lo, hi)


def errors(metrics, scale=1):
    values = np.array([interval(m, scale) for m in metrics])
    # Percentile bootstrap intervals may very slightly exclude a point estimate.
    return values[:, 0], np.maximum(0, np.vstack((values[:, 0]-values[:, 1], values[:, 2]-values[:, 0])))


def save_figure(fig, directory, name):
    fig.tight_layout(pad=0.8)
    fig.savefig(directory/(name+'.pdf'), bbox_inches='tight')
    fig.savefig(directory/(name+'.png'), dpi=220, bbox_inches='tight')
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--timing', type=Path, required=True)
    parser.add_argument('--scaling', type=Path, required=True)
    parser.add_argument('--expanded', type=Path, required=True)
    parser.add_argument('--manuscript', type=Path)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    timing, cost, expanded = [read(p) for p in (args.timing, args.scaling, args.expanded)]
    if not all(r['passed'] and r.get('architecture')=='direct-session-start-v2' for r in (timing, cost, expanded)):
        raise ValueError('only validated results may be rendered')
    output = args.output_dir
    figures = output/'figures'
    figures.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({'font.family': 'DejaVu Serif', 'font.size': 9,
                         'axes.labelsize': 9, 'legend.fontsize': 8,
                         'pdf.fonttype': 42, 'ps.fonttype': 42})
    models = ['Fixed-Dc', 'No-Dq-R', 'Decoupled']
    colors = ['#8064a2', '#297ba8', '#c76e42']
    def group(model, load, spacing=800000):
        return next(g for g in expanded['groups'] if g['model'] == model and
                    g['classical_load'] == load and g['request_interval_ns'] == spacing)
    loads = expanded['plan']['classical_loads']
    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    for model, color, marker in zip(models, colors, ['s', 'o', '^']):
        y, err = errors([group(model, load)['latency_mae_ns'] for load in loads], 1e6)
        ax.errorbar(loads, y, yerr=err, label=model, color=color, marker=marker, capsize=3)
    ax.set(xlabel='R–B background offered load', ylabel='Latency MAE relative to QuCl (ms)', ylim=(-.02, None), xticks=loads)
    ax.grid(axis='y', alpha=.2); ax.legend(loc='upper center', ncol=3, bbox_to_anchor=(.5, 1.22), frameon=False)
    save_figure(fig, figures, 'fig4-latency-mae')

    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    y, err = errors([group('No-Dq-R', load)['expected_fidelity_bias'] for load in loads])
    ax.errorbar(loads, y, yerr=err, color=colors[1], marker='o', capsize=3)
    ax.set(xlabel='R–B background offered load', ylabel='Expected-fidelity bias\n(No-Dq-R minus QuCl)',
           xticks=loads, ylim=(0, 1.15*max(y+err[1])))
    ax.grid(axis='y', alpha=.2)
    save_figure(fig, figures, 'fig5-expected-fidelity')

    fig, ax = plt.subplots(figsize=(4.5, 2.8))
    spacings = expanded['plan']['request_intervals_ns']
    x = np.arange(len(spacings)); width = .24
    for i, (model, color) in enumerate(zip(models, colors)):
        y, err = errors([group(model, .7, spacing)['latency_mae_ns'] for spacing in spacings], 1e6)
        ax.bar(x+(i-1)*width, y, width, yerr=err, color=color, label=model, capsize=3)
    ax.set(xticks=x, xticklabels=['0.8 ms\nR contention', '2.0 ms\nNo R contention'],
           ylabel='Latency MAE relative to QuCl (ms)', ylim=(0, None))
    ax.grid(axis='y', alpha=.2); ax.legend(loc='upper center', ncol=3, bbox_to_anchor=(.5, 1.22), frameon=False)
    save_figure(fig, figures, 'fig6-mechanism-control')

    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.7))
    qucl = [r['completion_ns']/1e6 for c in timing['cases'] for r in c['qucl']]
    native = [r['completion_ns']/1e6 for c in timing['cases'] for r in c['native']]
    limit = max(qucl+native)
    axes[0].plot([0, limit], [0, limit], '--', color='gray', lw=.8)
    axes[0].scatter(native, qucl, s=5, alpha=.25, color=colors[1])
    axes[0].set(xlabel='Native completion time (ms)', ylabel='QuCl completion time (ms)', title='(a) Atomic timing equivalence')
    axes[0].text(.04, .95, '{} requests\nMaximum error: {} ns'.format(timing['requests'], timing['max_absolute_completion_error_ns']),
                 transform=axes[0].transAxes, va='top', fontsize=8)
    for load, color in zip(cost['plan']['scaling_loads'], [colors[1], colors[2]]):
        groups = sorted([g for g in cost['groups'] if g['classical_load'] == load], key=lambda g: g['sessions'])
        y, err = errors([g['simulation_seconds_per_transaction'] for g in groups], .001)
        axes[1].errorbar([g['sessions'] for g in groups], y, yerr=err, color=color, marker='o', capsize=3,
                         label='Load '+str(load))
    axes[1].set(xlabel='Number of sessions', ylabel='Runtime per transaction (ms)', title='(b) Finite-batch simulation cost')
    axes[1].set_xscale('log', base=2)
    axes[1].set_xticks(cost['plan']['session_counts'], labels=cost['plan']['session_counts'])
    axes[1].grid(axis='y', alpha=.2); axes[1].legend(frameon=False)
    save_figure(fig, figures, 'fig7-timing-cost')

    fig, axes = plt.subplots(1, 2, figsize=(7.1, 2.7))
    for load, color in zip(cost['plan']['scaling_loads'], [colors[1], colors[2]]):
        groups = sorted([g for g in cost['groups'] if g['classical_load'] == load], key=lambda g: g['sessions'])
        n = [g['sessions'] for g in groups]
        y, err = errors([g['simulation_seconds'] for g in groups])
        axes[0].errorbar(n, y, yerr=err, color=color, marker='o', capsize=3, label='Load '+str(load))
        axes[1].plot(n, [g['counters']['synchronization_rounds'] for g in groups], color=color, marker='o', label='Rounds, load '+str(load))
        axes[1].plot(n, [g['counters']['ipc_tx_lines']+g['counters']['ipc_rx_lines'] for g in groups], color=color, marker='^', ls='--', label='IPC lines, load '+str(load))
    for ax in axes:
        ax.set_xscale('log', base=2)
        ax.set_xticks(cost['plan']['session_counts'], labels=cost['plan']['session_counts'])
        ax.set_xlabel('Number of sessions'); ax.grid(axis='y', alpha=.2); ax.legend(frameon=False, fontsize=7)
    axes[0].set_ylabel('Total simulation runtime (s)'); axes[1].set_ylabel('Count per simulation')
    save_figure(fig, figures, 'simulation-cost-details')

    table = ['# QuCl direct-session-start v2 — validation results', '',
        '**Architecture: A/R/B; local session start at R; only native R→B result packets. All results below were rerun for this structure.**', '',
        'Latency is correction completion minus local session_start_ns. Classical load applies only to the R→B result link.', '',
        'All intervals below are 95% percentile bootstrap intervals. Runtime intervals resample repeated runs; P5-B intervals resample traffic-phase clusters.', '',
        '## Native timing', '',
        '- {} synthetic workloads / {} requests: maximum start, completion and waiting error **0 ns**.'.format(timing['case_count'], timing['requests']),
        '- {} R/B requests from 12 actual mixed-protocol runs: maximum timing error **{} ns**.'.format(cost['native_timing_replay_requests'], cost['native_timing_replay_max_error_ns']),
        '- Capacity-one FIFO and explicit input-order tie policy; timing equivalence, not gate-level state or hardware validation.', '',
        '## Expanded P5-B', '',
        '{} paired cases; {} simulation runs plus {} calibration runs; {} transactions per model. Maximum reference density-matrix error: {:.3g}.'.format(
            expanded['paired_cases'], expanded['execution_runs'], expanded['calibration_runs'], expanded['transactions_per_model'], expanded['max_density_matrix_error']), '',
        '| Request interval (ms) | Load | Model | Latency MAE (ms), mean [CI] | Expected fidelity bias, mean [CI] |',
        '|---:|---:|---|---:|---:|']
    for g in expanded['groups']:
        table.append('| {} | {} | {} | {} | {} |'.format(g['request_interval_ns']/1e6, g['classical_load'], g['model'],
            display(g['latency_mae_ns'], 1e6), display(g['expected_fidelity_bias'], digits=4) if g['expected_fidelity_bias'] else 'not defined'))
    table += ['', '## Feasibility (pre-specified thresholds retained)', '',
              'F_min=0.5; deadline=5 ms from local session start at R. Rates are fractions of all paired transactions in the cell, not conditional false-positive rates.', '',
              '| Interval (ms) | Load | Model | False service feasible [CI] | False service infeasible [CI] | False deadline feasible [CI] |',
              '|---:|---:|---|---:|---:|---:|']
    for g in expanded['groups']:
        table.append('| {} | {} | {} | {} | {} | {} |'.format(g['request_interval_ns']/1e6, g['classical_load'], g['model'],
            display(g['false_feasible_rate'], digits=4) if g['false_feasible_rate'] else 'not defined',
            display(g['false_infeasible_rate'], digits=4) if g['false_infeasible_rate'] else 'not defined',
            display(g['false_deadline_feasible_rate'], digits=4)))
    table += ['', 'Zero observed errors (including a zero-width empirical bootstrap interval) do not establish zero population error. These estimates are conditional on fixed calibration from two traffic seeds and periodic background traffic with randomized start phase.', '',
              '## Simulation cost', '', '| Sessions | Load | Total (s), mean [CI] | Per transaction (ms), mean [CI] | Rounds | Unique times | IPC lines (both ways) |',
              '|---:|---:|---:|---:|---:|---:|---:|']
    for g in cost['groups']:
        c = g['counters']
        table.append('| {} | {} | {} | {} | {} | {} | {} |'.format(g['sessions'], g['classical_load'],
            display(g['simulation_seconds']), display(g['simulation_seconds_per_transaction'], .001, digits=1),
            c['synchronization_rounds'], c['distinct_boundary_timestamps'], c['ipc_tx_lines']+c['ipc_rx_lines']))
    table += ['', 'At zero background load, traffic phase is inactive and some metrics are deterministic across seeds. Collapsed intervals there do not represent additional workload diversity.', '',
              'Runtime includes setup, ns-3 startup, normal in-memory traces/snapshot and traffic drain; independent reference validation, build/import and disk I/O are excluded. It is not an isolated measurement of IPC overhead.', '',
              'Environment: '+json.dumps(cost['environment'], ensure_ascii=False), '']
    (output/'RESULTS.md').write_text('\n'.join(table))

    with (output/'scaling.csv').open('w', newline='') as stream:
        fields = ['sessions', 'classical_load', 'repetition', 'core_initialization_seconds', 'participant_startup_seconds',
                  'federation_seconds', 'participant_finish_seconds', 'simulation_seconds', 'offline_validation_seconds',
                  'simulation_seconds_per_transaction', 'federation_seconds_per_transaction']+list(cost['rows'][0]['counters'])
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for r in cost['rows']:
            flat = dict(r, **r['counters']); writer.writerow({k: flat[k] for k in fields})
    with (output/'timing.csv').open('w', newline='') as stream:
        fields = ['family', 'pattern', 'sessions', 'session_id', 'arrival_ns', 'qucl_start_ns', 'native_start_ns',
                  'qucl_completion_ns', 'native_completion_ns', 'qucl_waiting_ns', 'native_waiting_ns']
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        for case in timing['cases']:
            for a, b in zip(case['qucl'], case['native']):
                row = {k: case[k] for k in ('family', 'pattern', 'sessions')}
                row.update(session_id=a['session_id'], arrival_ns=a['arrival_ns'])
                for key in ('start_ns', 'completion_ns', 'waiting_ns'):
                    row['qucl_'+key], row['native_'+key] = a[key], b[key]
                writer.writerow(row)

    insert = r'''% Insert after VI-D. Requires graphicx. Copy figures/ next to the manuscript.
\subsection{Timing Fidelity and Simulation Cost}
We validate the operation-level scheduler against a separately implemented
capacity-one FIFO dispatcher driving NetSquid 1.1.7 timed
\texttt{QuantumProcessor} instructions. Both paths receive the same arrivals
and configured durations. The native path dispatches its next request only on
the processor's program-completion event; it does not reuse QuCl's scheduling
code or computed completion timestamps. Equal-time arrivals are submitted as
a batch in input order. The comparison includes idle, saturated, simultaneous,
bursty, and completion-boundary arrivals (including offsets of $\pm1$ ns),
BSMs of 1.6 ms, corrections of 0.5 and 0.05 ms, and variable-duration correction
workloads. Across 120 workloads and 2,500 requests, the maximum absolute
start, completion, and waiting-time differences are all 0 ns. Replaying 500
R/B requests from 12 actual mixed-protocol runs also gives 0 ns maximum error.
This establishes timing equivalence for the specified atomic FIFO model;
it does not validate physical device durations or gate-level noisy evolution.

For simulation cost, we execute finite mixed Swap--Teleport batches of
1, 4, 8, 16, 32, and 64 sessions with a request interval of 0.8 ms, at
R--B background offered loads of 0 and 0.70. Each condition has one warmup
and ten measured repetitions in shuffled order. All runs retain native memory
noise, production event logging, and the full background-traffic drain.
Runtime includes state initialization, ns-3 startup/configuration, federation,
and shutdown, but excludes build/import time, offline independent-reference
validation, and result-file writing. All repeated traces are identical within
each condition and pass packet, resource, clock, and quantum-state validation.
The error bars in Fig.~\ref{fig:timing-cost}(b) are 95\% bootstrap intervals
over runtime repetitions, not over network workloads. These measurements
characterize finite-batch cost on a fixed topology, rather than isolated IPC
overhead or arbitrary-topology scalability.

\begin{figure*}[t]
\centering
\includegraphics[width=\textwidth]{figures/fig7-timing-cost.pdf}
\caption{Additional validation. (a) Atomic completion timing against an
independent dispatcher using native timed instructions. (b) Mean simulation
runtime per completed transaction, with 95\% repetition-bootstrap intervals.
Offline reference validation and file writing are excluded.}
\label{fig:timing-cost}
\end{figure*}
'''
    assert timing['case_count'] == 120 and timing['requests'] == 2500
    assert cost['native_timing_replay_requests'] == 500 and cost['native_timing_replay_max_error_ns'] == 0
    largest = [next(g for g in cost['groups'] if g['sessions'] == 64 and g['classical_load'] == load)
               for load in cost['plan']['scaling_loads']]
    observed_cost = ('At 64 sessions, mean total simulation runtimes are '+
        ' and '.join(display(g['simulation_seconds'], digits=2) for g in largest)+
        ' s at offered loads 0 and 0.70, respectively. The corresponding synchronization-round counts are '+
        ' and '.join(str(g['counters']['synchronization_rounds']) for g in largest)+
        ', and bidirectional IPC line counts are '+
        ' and '.join(str(g['counters']['ipc_tx_lines']+g['counters']['ipc_rx_lines']) for g in largest)+
        '. Counts include setup and the complete traffic drain.\n\n')
    insert = insert.replace(r'\begin{figure*}', observed_cost+r'\begin{figure*}')
    (output/'validation-insert.tex').write_text(insert)
    # A separate replacement block prevents mixing pilot point estimates with
    # expanded confidence intervals when updating the existing VI-D section.
    expanded_text = [r'% Replace pilot counts/point estimates in VI-A and VI-D; use direct-session-start-v2 model definitions.',
        r'All sessions start locally at R; latency is measured from local session activation to correction completion. Only R--B result delivery contributes classical delay.', '',
        r'The expanded finite-batch study uses 32 independent traffic-phase seeds,',
        r'two quantum seeds, three offered loads, and two request intervals, yielding',
        r'384 paired cases and 1,536 transactions per model. Calibration remains',
        r'fixed from two disjoint traffic seeds. We report 95\% percentile-bootstrap',
        r'intervals from 10,000 resamples of traffic-seed clusters; session and quantum',
        r'repetitions are averaged within each cluster. These intervals are conditional',
        r'on the fixed calibration and the specified periodic-traffic workload family.', '',
        r'\begin{table*}[t]', r'\centering', r'\caption{Latency MAE (ms), mean [95\% CI], at a 0.8-ms request interval.}',
        r'\begin{tabular}{lccc}', r'\hline', r'Model & Load 0 & Load 0.35 & Load 0.70 \\', r'\hline']
    for model in models:
        expanded_text.append(model+' & '+' & '.join(display(group(model, load)['latency_mae_ns'], 1e6) for load in loads)+r' \\')
    expanded_text += [r'\hline', r'\end{tabular}', r'\end{table*}', '',
        'At a 0.8-ms request interval, the expected-fidelity biases of No-Dq-R are '+
        ', '.join(display(group('No-Dq-R', load)['expected_fidelity_bias'], digits=4) for load in loads)+
        ', respectively. These are probability-weighted branch expectations, not single observed-branch fidelities.', '',
        'At a 2-ms interval, the Fixed-Dc latency MAEs are '+
        ' and '.join(display(group('Fixed-Dc', load, 2000000)['latency_mae_ns'], 1e6) for load in loads[1:])+
        ' ms at loads 0.35 and 0.70. No-Dq-R and Decoupled have zero latency error in these noncontending finite workloads.', '']
    service_max = max(g[k]['mean'] for g in expanded['groups'] for k in ('false_feasible_rate', 'false_infeasible_rate') if g[k])
    if service_max == 0:
        expanded_text.append(r'With the pre-specified $F_{\min}=0.5$ and 5-ms deadline, no sampled service-feasibility misclassification is observed. This does not establish a zero population error rate.')
    else:
        expanded_text.append('With the unchanged $F_{\\min}=0.5$ and 5-ms deadline measured from local session start, No-Dq-R has false service-feasible fractions '+
            ', '.join(display(group('No-Dq-R', load)['false_feasible_rate'], digits=4) for load in loads)+
            ' at a 0.8-ms interval. These are finite-workload, paired sampled classifications; they are not hardware success probabilities. The zero-load traffic phase is inactive, so its degenerate interval does not establish population certainty.')
    expanded_text += ['', r'\begin{table*}[t]', r'\centering',
        r'\caption{Service-feasibility misclassification fractions, mean [95\% CI]. Latency is measured from local session start.}',
        r'\begin{tabular}{lllcc}',r'\hline',r'Interval (ms) & Load & Model & False feasible & False infeasible \\',r'\hline']
    for g in expanded['groups']:
        if g['false_feasible_rate'] is not None:
            expanded_text.append('{} & {} & {} & {} & {} '.format(g['request_interval_ns']/1e6,g['classical_load'],g['model'],
                display(g['false_feasible_rate'],digits=4),display(g['false_infeasible_rate'],digits=4))+r'\\')
    expanded_text += [r'\hline',r'\end{tabular}',r'\end{table*}','']
    expanded_text.append(r'Deadline-only false-feasible rates are reported separately below; they must not be interpreted as service-feasibility errors. Rates use all paired transactions in each cell as the denominator.')
    expanded_text += ['', r'\begin{table*}[t]', r'\centering', r'\caption{Deadline-only false-feasible fraction, mean [95\% CI], at 0.8 ms.}',
        r'\begin{tabular}{lcc}', r'\hline', r'Model & Load 0.35 & Load 0.70 \\', r'\hline']
    for model in models:
        expanded_text.append(model+' & '+' & '.join(display(group(model, load)['false_deadline_feasible_rate'], digits=4) for load in loads[1:])+r' \\')
    expanded_text += [r'\hline', r'\end{tabular}', r'\end{table*}', '']
    (output/'abstraction-results-insert.tex').write_text('\n'.join(expanded_text))
    summary = dict(architecture='direct-session-start-v2',created_at_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(), passed=True,
        evidence={str(p): sha(p) for p in (args.timing, args.scaling, args.expanded)},
        native_timing=dict(cases=timing['case_count'], synthetic_requests=timing['requests'],
            trace_replay_requests=cost['native_timing_replay_requests'], max_error_ns=0),
        scaling={k: cost[k] for k in ('measured_runs', 'warmup_runs', 'groups', 'environment', 'max_density_matrix_error')},
        expanded_p5b={k: expanded[k] for k in ('paired_cases', 'execution_runs', 'calibration_runs',
            'transactions_per_model', 'max_density_matrix_error', 'plan', 'groups')},
        plots=dict(matplotlib=matplotlib.__version__, numpy=np.__version__),
        manuscript='QuCl.pdf reviewed; original PDF not modified; LaTeX/BibTeX source not available.',
        manuscript_sha256=sha(args.manuscript) if args.manuscript else None)
    (output/'results-summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True)+'\n')
    print('Paper figures and tables generated in '+str(output))


if __name__ == '__main__':
    main()
