#!/usr/bin/env python3
"""Audit retained v4/v5 evidence and build the manuscript evaluation figure pack.

No simulator execution or modification. Requires Python 3, numpy and matplotlib.
Run from any directory; every plotted number is exported to data/*.csv.
"""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.patches import Patch
from matplotlib.ticker import MultipleLocator
import numpy as np

MODULE = Path(__file__).resolve().parents[1]
BLUE, ORANGE, TEAL, PURPLE, GRAY = '#2364A0', '#C65B29', '#218577', '#8065A8', '#9EA8B2'
MODEL = {'No-Dq-R': ('No R contention', BLUE, 'o'),
         'Fixed-Dc': ('Fixed classical delay', ORANGE, 's'),
         'Decoupled': ('Decoupled timing', TEAL, '^')}
MS = 1e6


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


class Evidence:
    def __init__(self):
        self.hashes = {}

    def path(self, relative):
        path = MODULE / relative
        self.hashes[relative] = digest(path)
        return path

    def json(self, relative):
        path = self.path(relative)
        if path.suffix == '.gz':
            with gzip.open(path, 'rt') as stream:
                return json.load(stream)
        return json.loads(path.read_text())

    def csv(self, relative):
        with self.path(relative).open() as stream:
            return list(csv.DictReader(stream))


def write_csv(path, rows):
    with path.open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def matching(rows, **keys):
    return [r for r in rows if all(float(r[k]) == v for k, v in keys.items())]


def mean(rows, key):
    return float(np.mean([float(r[key]) for r in rows]))


def close(a, b, message):
    require(np.isclose(a, b, atol=1e-10, rtol=1e-12), message)


def prepare(ev, out):
    chain = ev.json('results/chained-evaluation/summary.json')
    sensitivity = ev.json('results/chained-quantum-delay-sensitivity/summary.json')
    ablation = ev.json('results/provisioned-p5b-expanded/summary.json')
    coverage = ev.json('results/chained-tests/branch-coverage.json')
    noise = ev.json('results/chained-tests/noise-inputs.json')
    chain_validation = ev.json('results/chained-validation-summary.json')
    prior_validation = ev.json('results/provisioned-paper-validation-summary.json')
    require(all(s['passed'] for s in [chain, sensitivity, ablation, coverage,
                                     noise, chain_validation, prior_validation]), 'Failed source evidence')
    require(chain['architecture'] == sensitivity['architecture'] ==
            'swapping-assisted-teleportation-v5', 'Wrong chain architecture')
    require(ablation['architecture'] == 'provisioned-native-v4', 'Wrong ablation architecture')
    # Hash and inspect every raw report in the two plotted v5 sweeps.
    raw_count = 0
    for summary, folder in [(chain, 'chained-evaluation'),
                            (sensitivity, 'chained-quantum-delay-sensitivity')]:
        max_error = 0
        for entry in summary['reports']:
            relative = 'results/' + folder + '/' + entry['report']
            raw = ev.json(relative)
            require(ev.hashes[relative] == entry['sha256'], 'Raw report hash mismatch: ' + relative)
            require(raw['validation']['passed'] and raw['cross_validation']['passed'], relative)
            require(all(h['same_qubit_objects'] for h in raw['snapshot']['handoffs']), 'Pair continuity')
            require(raw['q2ns_status']['native_qubit_count'] ==
                    raw['q2ns_status']['native_state_count'] == 0, 'Duplicate state ownership')
            require(not any('DROP' in e['event_type'] for e in raw['ns3_events']), 'Packet drop')
            max_error = max(max_error, raw['cross_validation']['max_density_matrix_error'])
            raw_count += 1
        require(max_error == summary['max_density_matrix_error'], 'State error aggregation')
        require(len(summary['reports']) == summary['runs'], 'Raw run count')

    rows = ev.csv('results/chained-evaluation/chains.csv')
    require(len(rows) == chain['transactions'] == 192, 'Chain transaction count')
    aggregates = []
    for g in chain['groups']:
        keys = {k: g[k] for k in ['access_delay_ns', 'request_interval_ns', 'result_load']}
        own = matching(rows, **keys)
        require(len(own) == 16 and len({r['traffic_seed'] for r in own}) == 4, 'Chain cell count')
        for key, value in g['means'].items():
            close(mean(own, key), value, 'Chain mean ' + key)
        vals = [int(r['latency_ns']) for r in own]
        require([min(vals), max(vals)] == g['ranges']['latency_ns'], 'Chain observed range')
        aggregates.append(dict(access_delay_ms=g['access_delay_ns']/MS,
            interval_ms=g['request_interval_ns']/MS, load=g['result_load'], executions=len(own),
            latency_mean_ms=mean(own, 'latency_ns')/MS, latency_min_ms=min(vals)/MS,
            latency_max_ms=max(vals)/MS, expected_output_fidelity=mean(own, 'expected_output_fidelity')))
    write_csv(out/'data/chain_cells.csv', aggregates)
    write_csv(out/'data/chain_executions.csv', rows)

    errors = ev.csv('results/provisioned-p5b-expanded/errors.csv')
    require(len(errors) == 3 * ablation['transactions_per_model'] == 4608, 'Ablation count')
    require(ablation['calibration_test_disjoint'], 'Calibration/test leakage')
    require(ablation['plan']['correction_duration_ns'] == 50000, 'Ablation correction duration')
    cells = []
    for g in ablation['groups']:
        own = [r for r in matching(errors, classical_load=g['classical_load'],
                                 request_interval_ns=g['request_interval_ns']) if r['model'] == g['model']]
        require(len(own) == g['transactions'] == 256, 'Ablation cell count')
        clusters = {}
        for r in own:
            clusters.setdefault(r['traffic_seed'], []).append(r)
        require(len(clusters) == 32 and all(len(v) == 8 for v in clusters.values()), 'Traffic clusters')
        mae = np.mean([np.mean([abs(int(r['delta_latency_ns'])) for r in rr]) for rr in clusters.values()])
        close(mae, g['latency_mae_ns']['mean'], 'Ablation latency mean')
        bias = g['expected_fidelity_bias']
        if bias is not None:
            close(mean(own, 'delta_expected_fidelity'), bias['mean'], 'Ablation fidelity mean')
        ci = g['latency_mae_ns']['ci95_cluster_bootstrap']
        row = dict(model=g['model'], paper_label=MODEL[g['model']][0], interval_ms=g['request_interval_ns']/MS,
            load=g['classical_load'], traffic_clusters=32, transactions=256,
            latency_mae_ms=mae/MS, latency_ci_low_ms=ci[0]/MS, latency_ci_high_ms=ci[1]/MS,
            expected_fidelity_bias=None, fidelity_ci_low=None, fidelity_ci_high=None)
        if bias is not None:
            row.update(expected_fidelity_bias=bias['mean'], fidelity_ci_low=bias['ci95_cluster_bootstrap'][0],
                       fidelity_ci_high=bias['ci95_cluster_bootstrap'][1])
        cells.append(row)
    write_csv(out/'data/ablation_cells.csv', cells)

    sens_rows = ev.csv('results/chained-quantum-delay-sensitivity/chains.csv')
    paired = ev.csv('results/chained-quantum-delay-sensitivity/paired-vs-1x.csv')
    require(len(sens_rows) == 96 and len(paired) == 96, 'Sensitivity count (including 1x self-pairs)')
    components = ['resource_wait_ns', 'swap_R_wait_ns', 'teleport_A_wait_ns',
                  'swap_B_wait_ns', 'teleport_B_wait_ns', 'total_control_queue_ns']
    for row in sens_rows:
        require(int(row['latency_ns']) == 7012800 + sum(int(row[k]) for k in components), 'Latency decomposition')
    for row in paired:
        require(int(row['delta_latency_ns']) == sum(int(row['delta_'+k]) for k in components), 'Paired decomposition')
    for g in sensitivity['groups']:
        own = matching(sens_rows, scale=g['scale'], result_load=g['result_load'])
        for key, value in g['means'].items():
            close(mean(own, key), value, 'Sensitivity mean ' + key)
    write_csv(out/'data/sensitivity_executions.csv', sens_rows)
    write_csv(out/'data/sensitivity_paired.csv', paired)
    sens_cells = [dict(scale=g['scale'], load=g['result_load'], **g['means']) for g in sensitivity['groups']]
    write_csv(out/'data/sensitivity_cells.csv', sens_cells)
    require(coverage['transactions'] == 96 and all(len(v) == 16 for v in coverage['branches'].values()), 'Branch coverage')
    require(set(coverage['branches']) == set(noise['inputs']) == {'0','1','+','-','+i','-i'}, 'Six-state coverage')
    write_csv(out/'data/six_state_noise.csv', noise['cases'])
    timing = ev.csv('paper/provisioned-v4/timing.csv')
    require(len(timing) == 500, 'Timing sample size')
    require(all(int(r['native_'+k]) == int(r['oracle_'+k]) for r in timing
                for k in ['start_ns','completion_ns','waiting_ns']), 'Timing mismatch')
    write_csv(out/'data/native_timing.csv', timing)
    burst = ev.json('results/chained-tests/burst.json.gz')
    require(burst['validation']['passed'] and burst['cross_validation']['passed'], 'Burst validation')
    return dict(chain=chain, ablation=ablation, coverage=coverage, noise=noise, sensitivity=sensitivity,
                chain_cells=aggregates, ablation_cells=cells, burst=burst, raw_reports_audited=raw_count)


def style():
    plt.rcParams.update({
        'font.family':'DejaVu Sans', 'font.size':8, 'axes.labelsize':8,
        'axes.titlesize':9, 'axes.titleweight':'bold', 'axes.titlelocation':'left',
        'axes.spines.top':False, 'axes.spines.right':False,
        'axes.edgecolor':'#74808C', 'axes.linewidth':.6, 'text.color':'#202C38',
        'axes.labelcolor':'#202C38', 'xtick.color':'#45515C', 'ytick.color':'#45515C',
        'xtick.labelsize':7.5, 'ytick.labelsize':7.5, 'legend.fontsize':7.2,
        'lines.linewidth':1.4, 'lines.markersize':4.5, 'patch.linewidth':.6,
        'pdf.fonttype':42, 'ps.fonttype':42, 'savefig.facecolor':'white',
        'legend.frameon':False, 'axes.axisbelow':True, 'mathtext.fontset':'dejavusans',
    })


def grid(ax):
    ax.grid(axis='y', color='#E4E8ED', linewidth=.55)
    ax.tick_params(length=3, width=.6)


def save(fig, directory, name, book):
    fig.savefig(directory/(name+'.pdf'))
    fig.savefig(directory/(name+'.png'), dpi=450)
    book.savefig(fig)
    plt.close(fig)


def label_bars(ax, positions, values, lows, highs, fmt, color, pad):
    """Place labels beyond the uncertainty whiskers, including negative bars."""
    for x, y, lo, hi in zip(positions, values, lows, highs):
        zero = abs(y) < 1e-12
        if zero:
            ax.plot([x-.045, x+.045], [0, 0], color=color, lw=1.4, zorder=4)
        top = hi if y >= 0 else lo
        ax.text(x, top + (pad if y >= 0 else -pad), '0' if zero else fmt.format(y),
                ha='center', va='bottom' if y >= 0 else 'top',
                fontsize=7.5, color=color, fontweight='medium')


def plot_latency(data):
    # One shared axis: the four execution conditions are directly adjacent.
    fig, ax = plt.subplots(figsize=(7.2, 3.65))
    fig.subplots_adjust(left=.09, right=.98, bottom=.17, top=.76)
    x=np.arange(3)*1.28; width=.22
    variants=[(.8,0,BLUE,''), (.8,.7,BLUE,'////'),
              (4,0,ORANGE,''), (4,.7,ORANGE,'////')]
    handles=[]
    for i,(interval,load,color,hatch) in enumerate(variants):
        rows=sorted([r for r in data['chain_cells'] if r['interval_ms']==interval and r['load']==load],
                    key=lambda r:r['access_delay_ms'])
        y=np.array([r['latency_mean_ms'] for r in rows])
        lo=np.array([r['latency_min_ms'] for r in rows]); hi=np.array([r['latency_max_ms'] for r in rows])
        pos=x+(i-1.5)*width
        face=color if load==0 else ('#E5EFF8' if interval==.8 else '#F9E8DD')
        ax.bar(pos,y,width*.88,color=face,edgecolor=color,hatch=hatch,linewidth=.75,
               yerr=[y-lo,hi-y],error_kw=dict(ecolor='#4E5B68',elinewidth=.7,capsize=2,capthick=.7))
        label_bars(ax,pos,y,lo,hi,'{:.2f}',color,.30)
        handles.append(Patch(facecolor=face,edgecolor=color,hatch=hatch,
                       label='{:g} ms interval  |  load {:g}'.format(interval,load)))
    ax.set(xticks=x,xticklabels=['0.2','1','5'],ylabel='End-to-end latency (ms)',
           xlabel='A–R propagation delay (ms)',ylim=(0,21.5),xlim=(x[0]-.64,x[-1]+.64))
    ax.yaxis.set_major_locator(MultipleLocator(5));grid(ax)
    fig.suptitle('End-to-end latency across execution conditions',x=.09,ha='left',y=.985,fontsize=11,fontweight='bold')
    fig.legend(handles=handles,loc='upper center',bbox_to_anchor=(.53,.923),ncol=2,
               fontsize=8,columnspacing=3,handlelength=1.8)
    return fig


def plot_ablation(data):
    # Both models' fidelity bias uses ONE zero-centred axis; no inset or rescaling.
    fig,axes=plt.subplots(1,2,figsize=(7.2,3.65))
    fig.subplots_adjust(left=.09,right=.985,bottom=.17,top=.76,wspace=.37)
    x=np.arange(3);colors={k:v[1] for k,v in MODEL.items()}
    def own(model):
        return sorted([r for r in data['ablation_cells'] if r['model']==model and r['interval_ms']==.8],key=lambda r:r['load'])
    for i,model in enumerate(MODEL):
        rows=own(model);y=np.array([r['latency_mae_ms'] for r in rows])
        lo=np.array([r['latency_ci_low_ms'] for r in rows]);hi=np.array([r['latency_ci_high_ms'] for r in rows])
        pos=x+(i-1)*.29
        axes[0].bar(pos,y,.22,color=colors[model],edgecolor='white',linewidth=.6,
                    yerr=[y-lo,hi-y],error_kw=dict(ecolor='#45515C',elinewidth=.8,capsize=2,capthick=.8))
        label_bars(axes[0],pos,y,lo,hi,'{:.2f}',colors[model],.025)
    axes[0].set(ylabel='Latency MAE (ms)',ylim=(0,1.62))
    axes[0].yaxis.set_major_locator(MultipleLocator(.4))
    axes[0].set_title('(a) Latency error',pad=10,fontsize=9)
    for i,model in enumerate(['No-Dq-R','Fixed-Dc']):
        rows=own(model);y=100*np.array([r['expected_fidelity_bias'] for r in rows])
        lo=100*np.array([r['fidelity_ci_low'] for r in rows]);hi=100*np.array([r['fidelity_ci_high'] for r in rows])
        pos=x+(i-.5)*.30
        axes[1].bar(pos,y,.265,color=colors[model],edgecolor='white',linewidth=.6,
                    yerr=[y-lo,hi-y],error_kw=dict(ecolor='#45515C',elinewidth=.8,capsize=2,capthick=.8))
        label_bars(axes[1],pos,y,lo,hi,'{:+.2f}',colors[model],.12)
    axes[1].axhline(0,color='#5E6B77',lw=.8)
    axes[1].set(ylabel='Fidelity bias (percentage points)',ylim=(-1.1,7.75))
    axes[1].set_yticks([0,2,4,6]);axes[1].set_title('(b) Fidelity bias',pad=10,fontsize=9)
    for ax in axes:
        ax.set(xticks=x,xticklabels=['0','0.35','0.70'],xlabel='R→B background offered load',xlim=(-.50,2.50))
        grid(ax)
    fig.suptitle('Prediction error relative to Full Coupling',x=.09,ha='left',y=.985,fontsize=11,fontweight='bold')
    fig.legend(handles=[Patch(facecolor=v[1],label=v[0]) for v in MODEL.values()],
               loc='upper center',bbox_to_anchor=(.54,.925),ncol=3,fontsize=8,columnspacing=1.8)
    return fig


def write_results(data, out):
    def ab(model, load, interval=.8):
        return next(r for r in data['ablation_cells'] if r['model']==model and r['load']==load and r['interval_ms']==interval)
    def ch(delay):
        return next(r for r in data['chain_cells'] if r['access_delay_ms']==delay and r['load']==0 and r['interval_ms']==.8)
    def se(scale, load=.7):
        return next(g['means'] for g in data['sensitivity']['groups'] if g['scale']==scale and g['result_load']==load)
    fast,base,slow=se(.5),se(1),se(2)
    numbers={
        'ChainLowLatency':'{:.3f}'.format(ch(.2)['latency_mean_ms']),
        'ChainMidLatency':'{:.3f}'.format(ch(1)['latency_mean_ms']),
        'ChainHighLatency':'{:.3f}'.format(ch(5)['latency_mean_ms']),
        'NoQueueMAEZero':'{:.3f}'.format(ab('No-Dq-R',0)['latency_mae_ms']),
        'NoQueueMAEHigh':'{:.3f}'.format(ab('No-Dq-R',.7)['latency_mae_ms']),
        'FixedMAEHigh':'{:.3f}'.format(ab('Fixed-Dc',.7)['latency_mae_ms']),
        'DecoupledMAEHigh':'{:.3f}'.format(ab('Decoupled',.7)['latency_mae_ms']),
        'NoQueueBiasZero':'{:.4f}'.format(ab('No-Dq-R',0)['expected_fidelity_bias']),
        'NoQueueBiasMid':'{:.4f}'.format(ab('No-Dq-R',.35)['expected_fidelity_bias']),
        'NoQueueBiasHigh':'{:.4f}'.format(ab('No-Dq-R',.7)['expected_fidelity_bias']),
        'FixedBiasMid':'{:+.4f}'.format(ab('Fixed-Dc',.35)['expected_fidelity_bias']),
        'FixedBiasHigh':'{:+.4f}'.format(ab('Fixed-Dc',.7)['expected_fidelity_bias']),
        'FastLatencyReduction':'{:.3f}'.format((base['latency_ns']-fast['latency_ns'])/MS),
        'FastQueueReduction':'{:.3f}'.format((base['total_control_queue_ns']-fast['total_control_queue_ns'])/MS),
        'SlowLatencyIncrease':'{:.3f}'.format((slow['latency_ns']-base['latency_ns'])/MS),
        'SlowQueueReduction':'{:.3f}'.format((base['total_control_queue_ns']-slow['total_control_queue_ns'])/MS),
    }
    def sci_tex(value):
        mantissa,exponent=('{:.2e}'.format(value)).split('e')
        return mantissa+r'\times 10^{'+str(int(exponent))+'}'
    numbers.update(NoiselessError=sci_tex(data['coverage']['max_density_matrix_error']),
        NoiseError=sci_tex(data['noise']['max_density_matrix_error']),
        ChainError=sci_tex(data['chain']['max_density_matrix_error']),
        SensitivityError=sci_tex(data['sensitivity']['max_density_matrix_error']))
    (out/'numbers.tex').write_text('% Generated from audited evidence; do not edit by hand.\n'+
        '\n'.join(r'\newcommand{\qucl'+k+'}{'+v+'}' for k,v in numbers.items())+'\n')
    (out/'table_validation.tex').write_text(r'''% Requires booktabs. Input after numbers.tex.
\begin{table}[t]
\centering
\caption{Validation evidence. State errors are maximum absolute density-matrix entry differences against the independent reference at matched operation times. The timing row is a separate v4 mixed-protocol regression.}
\label{tab:qucl-validation}
\small
\begin{tabular}{@{}ll@{}}
\toprule
Check / sample & Result \\
\midrule
Noiseless: 6 inputs $\times$ 16 branches & $F_{\min}\simeq 1$ \\
\quad 96 composed executions & $\epsilon_\rho=\quclNoiselessError$ \\
Noisy: 6 inputs $\times$ 2 delays & $\epsilon_\rho=\quclNoiseError$ \\
Chained sweep: 48 runs / 192 chains & $\epsilon_\rho=\quclChainError$ \\
Pair continuity / packet gating & Pass \\
FIFO: 500 requests / 12 workloads & $\epsilon_t=0$ ns \\
\bottomrule
\end{tabular}
\end{table}
''')
    lines=['# QuCl 평가 — 그림 두 장과 검증 표 하나','',
        '**[두 페이지 PDF 열기](FIGURES.pdf)** · [LaTeX 원고](evaluation.tex) · [전체 수치 CSV](data/)',
        '기존 검증 완료 데이터를 다시 집계한 결과이며, 이번 변경은 표현과 구성의 수정입니다.','',
        '## 파라미터 출처와 현재 결과의 범위','',
        '[문헌 설명·비교 표](physical-model.tex)와 [BibTeX](references.bib)를 원고 setup에 포함했습니다.',
        'Liao (2022) Table 3와 Iqbal (2023) Table 3/Section 4의 문헌 profile은 CNOT 20 μs, H/X/Z 5 ns, 측정 3.7 μs, T1=10 h, T2=1 s입니다.',
        '이 profile의 직렬 BSM 시간은 27.405 μs로 유도됩니다. **아래 결과는 기존 1.6 ms controlled profile의 결과이며, 문헌 profile로 재실험한 결과가 아닙니다.**',
        '논문 제목·DOI와 인용 위치는 [README](README.md#문헌-기반-파라미터와-인용)에 정리했습니다.','',
        '## 검증은 표 하나로','',
        '| 항목 | 결과 |','|---|---|',
        '| Noiseless: 6 inputs × 16 joint branches | 96 chains; min F ≈ 1; max ρ error {:.3g} |'.format(data['coverage']['max_density_matrix_error']),
        '| Native T1/T2: 6 inputs × 2 delays | 12 runs; max ρ error {:.3g} |'.format(data['noise']['max_density_matrix_error']),
        '| 연쇄 실행 sweep | 48 runs / 192 chains; max ρ error {:.3g} |'.format(data['chain']['max_density_matrix_error']),
        '| 자원·인과관계 | 같은 qubit 인계, 단일 소비, packet 수신 후 연산 시작 PASS |',
        '| 별도 v4 FIFO 검증 | 500 requests / 12 workloads; timing error 0 ns |','',
        '## 그림 1 — 같은 조건을 바로 옆에서 비교','',
        '![조건별 end-to-end latency](figures/fig3_end_to_end_latency.png)','',
        '**색 = 시작 간격, 빗금 = background load 0.7.** 각 A–R delay에서 네 조건을 같은 축에 나란히 배치했습니다.',
        '막대와 숫자는 평균, 오차막대는 4 chain positions × 4 phases의 관측 min–max입니다. 신뢰구간이 아닙니다.',
        '시작 간격 0.8 ms / load 0에서 평균 latency는 **'+numbers['ChainLowLatency']+' → '+numbers['ChainMidLatency']+' → '+numbers['ChainHighLatency']+' ms**입니다.',
        '모든 자원은 t=0 생성이므로 시작 간격 비교에는 contention과 저장 age 변화가 함께 들어갑니다. Load 0의 phase 반복은 동일 조건입니다.','',
        '## 그림 2 — 어떤 단순화가 얼마나 틀리는가','',
        '![모델별 예측 오차](figures/fig5_6_execution_abstraction.png)','',
        '**같은 load의 모델들을 나란히 비교합니다.** 왼쪽은 latency MAE, 오른쪽은 같은 0 기준축의 signed fidelity bias입니다.',
        '오른쪽 단위는 percentage points, 즉 **100 × ΔE[F]**입니다. 상대적인 퍼센트 변화율이 아닙니다. Decoupled는 state를 예측하지 않아 오른쪽에서 제외합니다.',
        '오차막대는 32 traffic-phase clusters의 95% bootstrap CI입니다. 두 calibration phase의 추정 불확실성은 포함하지 않습니다.','',
        '| Load 0.7, interval 0.8 ms | Latency MAE (ms) | Fidelity bias (pp) |',
        '|---|---:|---:|']
    for model in MODEL:
        r=ab(model,.7)
        fidelity='not defined' if r['expected_fidelity_bias'] is None else '{:+.2f}'.format(100*r['expected_fidelity_bias'])
        lines.append('| {} | {:.3f} | {} |'.format(MODEL[model][0],r['latency_mae_ms'],fidelity))
    lines+=['',
        '**핵심:** R 대기를 없애면 약 1.33 ms의 시간 오차와 +6.06 pp의 fidelity bias가 생깁니다. Fixed classical delay도 정확하지 않으며 bias는 부하에 따라 +/−로 바뀝니다.',
        'R wait가 없는 2 ms interval에서는 No R Contention의 관측 시간·fidelity 오차가 0입니다. 이 대조 조건은 본문 한 문장과 CSV로 남겼습니다.','',
        '### 두 실험의 범위','',
        '- 그림 1: v5 Swap → A-to-B Teleport, correction 500 μs.',
        '- 그림 2: 별도 v4 provisioned Swap, correction 50 μs로 B 경합 배제. 384 paired cases / model당 1,536 transactions. Target은 A–B Bell pair.',
        '- 따라서 그림 2의 오차를 그림 1의 전체 workflow에 대한 오차로 해석하지 않습니다.','',
        '### 민감도는 그림을 늘리지 않고 한 문단으로','',
        '별도 24-run quantum-delivery sweep에서 load 0.7일 때 전달시간을 절반으로 줄이면 latency −'+numbers['FastLatencyReduction']+' ms, packet queue −'+numbers['FastQueueReduction']+' ms였습니다. 두 배로 늘리면 latency +'+numbers['SlowLatencyIncrease']+' ms이나 packet queue는 −'+numbers['SlowQueueReduction']+' ms였습니다. 총지연은 각 항의 합이지만, quantum completion이 packet 생성시각을 바꾸므로 각 항을 독립적으로 예측할 수 없습니다.',
        '이 비교는 RA:RB 비율 고정이며 readiness와 remote-memory placement가 함께 바뀝니다. 상세 조건·수치는 [sensitivity CSV](data/sensitivity_cells.csv)에 있습니다.','',
        '## 검산·재현','',
        '72개 raw report, v4 오차 4,608행, timing 500행을 대조했습니다. 원본 해시와 집계 검산은 [provenance.json](provenance.json), 재생성 명령은 [README](README.md)에 있습니다.',
        '모든 입력/원본 데이터는 보존했습니다. 추가 시뮬레이션 실행은 하지 않았습니다.','']
    (out/'RESULTS.md').write_text('\n'.join(lines))


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-dir',type=Path,default=MODULE/'paper/evaluation-controlled')
    args=parser.parse_args();out=args.output_dir.resolve()
    require(not (out/'LITERATURE-PROFILE').exists(), 'Use the literature renderer for this output directory')
    (out/'figures').mkdir(parents=True,exist_ok=True);(out/'data').mkdir(exist_ok=True)
    ev=Evidence();data=prepare(ev,out);style()
    with PdfPages(out/'FIGURES.pdf',metadata={'Title':'QuCl | Controlled execution-coupling evaluation'}) as book:
        save(plot_latency(data),out/'figures','fig3_end_to_end_latency',book)
        save(plot_ablation(data),out/'figures','fig5_6_execution_abstraction',book)
    # Keep the paper's compact numeric validation table next to the figure data.
    table=[dict(scope='v5 noiseless state',sample='6 inputs x 16 joint branches',measure='max density-matrix error',value=data['coverage']['max_density_matrix_error']),
           dict(scope='v5 noiseless state',sample='96 chains',measure='minimum fidelity',value=data['coverage']['min_output_fidelity']),
           dict(scope='v5 noisy six-state',sample='12 runs',measure='max density-matrix error',value=data['noise']['max_density_matrix_error']),
           dict(scope='v5 characterization',sample='48 runs / 192 chains',measure='max density-matrix error',value=data['chain']['max_density_matrix_error']),
           dict(scope='v5 delivery sensitivity',sample='24 runs / 96 chains',measure='max density-matrix error',value=data['sensitivity']['max_density_matrix_error']),
           dict(scope='v4 FIFO timing regression',sample='500 R/B requests / 12 workloads',measure='max start/completion/wait error (ns)',value=0)]
    write_csv(out/'data/validation.csv',table)
    write_results(data,out)
    manifest=dict(passed=True,action='Recomputed plot aggregates and audited retained evidence; no new simulation runs',
        raw_v5_reports_audited=data['raw_reports_audited'],raw_v4_error_rows_checked=4608,
        v4_timing_rows_checked=500,chain_executions=192,sensitivity_executions=96,
        sample_interpretation={'chain':'16 executions/cell: four chain positions x four phases; min/max, not CI',
          'ablation':'256 transactions/cell; 32 traffic clusters, two quantum seeds, four sessions; retained 95% bootstrap CI',
          'sensitivity':'Finite paired conditions; zero-load phases duplicate; no CI'},
        source_sha256=ev.hashes,renderer_sha256=digest(Path(__file__)),
        environment={'matplotlib':matplotlib.__version__,'numpy':np.__version__},
        editable_manuscript_sha256={name:digest(out/name) for name in
            ['README.md','evaluation.tex','physical-model.tex','references.bib'] if (out/name).exists()},
        generated_sha256={str(p.relative_to(out)):digest(p) for p in
            sorted(list((out/'figures').glob('*'))+list((out/'data').glob('*'))+
                   [out/'FIGURES.pdf',out/'numbers.tex',out/'table_validation.tex',out/'RESULTS.md'])})
    require(all(digest(MODULE/p)==h for p,h in ev.hashes.items()),'Source changed during rendering')
    (out/'provenance.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n')
    print('PASS: audited {} raw v5 reports, 4608 ablation errors and 500 timing rows; two grouped-bar PDF/PNG figures + data exported to {}'.format(data['raw_reports_audited'],out))


if __name__=='__main__':
    main()
