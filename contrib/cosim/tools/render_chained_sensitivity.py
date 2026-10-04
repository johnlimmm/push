#!/usr/bin/env python3
"""Render the finite quantum-delay experiment without statistical extrapolation."""
import csv
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np

MODULE=Path(__file__).resolve().parents[1]
RESULTS=MODULE/'results/chained-quantum-delay-sensitivity'
OUT=MODULE/'paper/chained-v5'


def main():
    s=json.loads((RESULTS/'summary.json').read_text())
    if not s['passed']:raise ValueError('experiment failed')
    groups=s['groups'];plan=s['plan'];OUT.mkdir(parents=True,exist_ok=True)
    plt.rcParams.update({'font.size':9,'pdf.fonttype':42,'ps.fonttype':42})
    fig,axes=plt.subplots(1,2,figsize=(10,4.2))
    x=np.arange(len(groups));bottom=np.zeros(len(groups))
    components=[('Resource readiness',('resource_wait_ns',),'#9a9a9a'),
        ('R BSM queue',('swap_R_wait_ns',),'#2878b5'),
        ('A BSM queue',('teleport_A_wait_ns',),'#69a8d0'),
        ('B correction queues',('swap_B_wait_ns','teleport_B_wait_ns'),'#d95f02'),
        ('Packet queues',('total_control_queue_ns',),'#f3b16e')]
    for label,keys,color in components:
        y=np.array([sum(g['means'][k] for k in keys)/1e6 for g in groups])
        axes[0].bar(x,y,bottom=bottom,label=label,color=color,width=.72);bottom+=y
    axes[0].set(xticks=x,xticklabels=['{}x\nload {}'.format(g['scale'],g['result_load']) for g in groups],
        ylabel='Mean variable delay (ms)',title='(a) Readiness, processor and packet waiting')
    axes[0].legend(fontsize=7,loc='upper left');axes[0].set_ylim(0,max(bottom)*1.5)
    for load,color,marker in [(0,'#2878b5','o'),(.7,'#d95f02','s')]:
        own=[g for g in groups if g['result_load']==load]
        axes[1].plot([g['scale'] for g in own],[g['means']['expected_output_fidelity'] for g in own],
                     marker=marker,color=color,label='load '+str(load))
    axes[1].set(xlabel='Quantum delivery timescale (RA:RB fixed)',ylabel='Mean expected output fidelity',
        xticks=[q['scale'] for q in plan['quantum_delays']],title='(b) Branch-weighted final state quality')
    axes[1].legend(fontsize=8)
    for ax in axes:ax.grid(axis='y',alpha=.2);ax.set_axisbelow(True)
    fig.tight_layout()
    for ext in ('pdf','png'):fig.savefig(OUT/('quantum-delay-sensitivity.'+ext),dpi=180)
    plt.close(fig)
    lines=['# Quantum-resource delivery timescale sensitivity','',
        '**Controlled execution-coupling study: fixed-ratio sensitivity, not hardware calibration or a population estimate.**','',
        '## Design fixed before execution','',
        '- Quantum RA/RB delivery delays: (0.4, 0.6), (0.8, 1.2), (1.6, 2.4) ms.',
        '- Classical A–R delay 1 ms, R–B delay 0.2 ms, both 10 Mb/s; no synthetic command path.',
        '- Four chains at 0.8 ms intervals, first start at 1 ms; input +i and elementary EPRs created at t=0.',
        '- Native BSM/correction 1.6/0.5 ms per stage; memory T1/T2 20/10 ms.',
        '- R→B periodic background offered load 0 or 0.7; 60 packets of 1,000-byte payload when enabled.',
        '- Four paired traffic phases (101–104), quantum seed 7; all 16 joint reference branches enumerated for each chain.',
        '- 24 new runs / 96 chains. The four zero-load phases repeat the same condition: only 15 distinct scale/load/phase conditions.',
        '- Acceptance is causal/FIFO/resource/native-state correctness. No monotonicity or preferred direction of performance change is required.','',
        '## Verification','',
        '- All runs passed existing packet, resource, native-instruction and independent state-reference checks.',
        '- Maximum density-matrix difference: {:.3g}.'.format(s['max_density_matrix_error']),
        '- All {} baseline 1x runs exactly reproduce the original v5 snapshot, packet events, instruction traces, metrics and reference output.'.format(s['baseline_1x_reproduced_runs']),
        '- Paired end-to-end latency differences equal the sum of changes in resource wait, R/A/B processor wait and packet queueing, exactly in integer ns.',
        '- Production implementation and prior evidence were left unchanged; source hashes were checked before and after execution.','',
        '## Results','',
        '| Quantum scale | Background load | Mean latency (ms) | Mean expected output fidelity | Mean R wait (ms) | Mean A wait (ms) | Mean B wait (ms) | Mean packet queue (ms) |',
        '|---:|---:|---:|---:|---:|---:|---:|---:|']
    for g in groups:
        m=g['means']
        lines.append('| {} | {} | {:.3f} | {:.4f} | {:.3f} | {:.3f} | {:.3f} | {:.3f} |'.format(
            g['scale'],g['result_load'],m['latency_ns']/1e6,m['expected_output_fidelity'],
            m['swap_R_wait_ns']/1e6,m['teleport_A_wait_ns']/1e6,
            (m['swap_B_wait_ns']+m['teleport_B_wait_ns'])/1e6,m['total_control_queue_ns']/1e6))
    lines+=['','![Delivery timescale sensitivity](quantum-delay-sensitivity.png)','',
        'Panel (a) excludes fixed native execution and uncontended packet transit, whose sum is 7.0128 ms per chain.',
        'The remaining bars sum to mean latency minus that fixed term. Panel (b) averages the branch-weighted fidelity across four chains and four traffic phases.',
        'There are no confidence intervals; repeated zero-load phases do not provide independent evidence.','',
        '## Paired change from the 1x quantum delays','',
        '| Scale | Load | Mean change in latency (ms) | Mean change in packet queues (ms) | Chains with changed packet queue |',
        '|---:|---:|---:|---:|---:|']
    with (RESULTS/'paired-vs-1x.csv').open() as stream:paired=list(csv.DictReader(stream))
    for g in groups:
        if g['scale']==1:continue
        own=[r for r in paired if float(r['scale'])==g['scale'] and float(r['result_load'])==g['result_load']]
        lines.append('| {} | {} | {:+.3f} | {:+.3f} | {}/{} |'.format(g['scale'],g['result_load'],
            sum(float(r['delta_latency_ns']) for r in own)/len(own)/1e6,
            sum(float(r['delta_total_control_queue_ns']) for r in own)/len(own)/1e6,
            sum(int(r['delta_total_control_queue_ns'])!=0 for r in own),len(own)))
    by={(g['scale'],g['result_load']):g['means'] for g in groups}
    fast,base,slow=by[.5,.7],by[1,.7],by[2,.7]
    lines+=['','## Main observations','',
        '- At load 0.7, halving delivery times reduces mean latency by {:.3f} ms; mean packet queueing accounts for {:.3f} ms of that reduction. The remaining change includes readiness and processor waits.'.format(
            (base['latency_ns']-fast['latency_ns'])/1e6,(base['total_control_queue_ns']-fast['total_control_queue_ns'])/1e6),
        '- Doubling delivery times increases mean latency by {:.3f} ms while mean packet queueing decreases by {:.3f} ms. Quantum delay does not map to an independent additive packet-delay term.'.format(
            (slow['latency_ns']-base['latency_ns'])/1e6,(base['total_control_queue_ns']-slow['total_control_queue_ns'])/1e6),
        '- All three loaded scales exhibit waiting at A and B in addition to R. The downstream interaction is present across the three tested delivery timescales.',
        '- Without background traffic, the 0.5x and 1x cases differ in latency by 0.2 ms but have the same expected fidelity to numerical precision. Readiness and memory placement change together; latency alone does not determine accumulated memory noise.','',
        '## Interpretation boundaries','',
        '- Initial resource wait of the first chain is 0, 0.2 and 1.4 ms respectively. This exercises readiness before start and readiness after start.',
        '- Load 0 means no background traffic. Protocol packets and the shared B processor can still contend.',
        '- A 4 ms start interval in the original characterization is a lower offered-rate condition, not proof of zero downstream contention. R and A have distinct processors; their BSM durations should not be added to derive a universal contention threshold.',
        '- Increasing quantum delivery delay also changes remote-memory placement time: quantum transit has no memory T1/T2 and channel depolarization is zero here. This experiment changes readiness and storage history together, not only a scheduler delay.',
        '- Resource-delivery knowledge at R remains ideal and instantaneous; this is not a heralded entanglement-generation model.',
        '- The RA:RB ratio remains 2:3. No robustness claim is made for other asymmetries, noise models, topologies or arrival processes.',
        '- The 48-run main characterization remains valid as finite evidence; v4 ablations remain a separate controlled swapping workload and do not quantify approximation errors for this v5 chain.',
        '- Parameter explanations describe what the existing settings exercise; they should not be presented as newly discovered evidence of hardware realism or as a retrospective claim of preregistered selection.','',
        '## Reproduction','',
        'From the ns-3 root, use a fresh output directory:','',
        '```bash',
        '/home/ns3/qunet/bin/python contrib/cosim/experiments/run_chained_sensitivity.py \\',
        '  contrib/cosim/scenarios/chained-quantum-delay-sensitivity.json \\',
        '  --output-dir contrib/cosim/results/chained-quantum-delay-sensitivity-new',
        '```','',
        'Raw reports, actual packet-generation timestamps, queue decomposition and paired changes are in',
        '`results/chained-quantum-delay-sensitivity/`; each compressed report has a SHA-256 digest in `summary.json`.',
        'The [result archive](../../baselines/chained-v5-quantum-delay-sensitivity-results.tar.gz) and',
        '[file hashes](../../baselines/chained-v5-quantum-delay-sensitivity-results.json) preserve the successful run evidence and this figure.','']
    (OUT/'SENSITIVITY.md').write_text('\n'.join(lines))


if __name__=='__main__':main()
