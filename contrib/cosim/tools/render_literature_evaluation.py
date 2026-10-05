#!/usr/bin/env python3
"""Audit fresh literature-profile evidence and render two comparable bar figures.

Requires numpy/matplotlib; no simulator execution. Reads only the named completed
run. CSV exports and provenance accompany every plotted aggregate.
"""
import argparse
import csv
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import zipfile

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pdf import PdfPages
import numpy as np

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'experiments'))
from p5b_analysis import estimate

COLORS = ['#2166AC', '#D46B35', '#208574']
MODELS = ['No-Dq-R', 'Fixed-Dc', 'Decoupled']
LABELS = ['No R contention', 'Fixed classical delay', 'Decoupled timing']
DELAY_FIELDS = ['resource_wait_ns', 'swap_R_wait_ns', 'swap_bsm_ns',
                'swap_packet_ns', 'swap_B_wait_ns', 'swap_correction_ns',
                'ready_packet_ns', 'teleport_A_wait_ns', 'teleport_bsm_ns',
                'teleport_packet_ns', 'teleport_B_wait_ns', 'teleport_correction_ns']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    with (gzip.open(path, 'rt') if path.suffix == '.gz' else path.open()) as f:
        return json.load(f)


def write_csv(path, rows):
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader(); writer.writerows(rows)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def test_result(path):
    text = path.read_text()
    count = re.search(r'Ran (\d+) tests? in ([\d.]+)s', text)
    require(count is not None and text.rstrip().endswith('OK'), 'Test suite incomplete/failed: '+str(path))
    return dict(tests=int(count[1]), seconds=float(count[2]), log=str(path.relative_to(MODULE)), sha256=digest(path))


def audit(source):
    s = read(source/'summary.json'); p = s['plan']
    require(s['passed'], 'Run did not pass')
    require(p == read(source/'plan.json'), 'Plan mismatch')
    require(p == read(MODULE/'scenarios/literature-evaluation.json'), 'Renderer prose targets the registered literature plan')
    require(set(p['test_traffic_seeds']).isdisjoint(p['calibration_traffic_seeds']), 'Seed overlap')
    for rel, sha in s['source_sha256'].items():
        require(digest(MODULE/rel) == sha, 'Execution source changed: '+rel)
    report_count = 0
    for rel, sha in s['report_sha256'].items():
        file = source/rel
        require(digest(file) == sha, 'Report changed: '+rel)
        r = read(file)
        require(r['validation']['passed'], 'Invalid report: '+rel)
        if 'cross_validation' in r:
            require(r['cross_validation']['passed'], 'Reference mismatch: '+rel)
        if r.get('q2ns_status') is not None:
            status = r['q2ns_status']
            require(status['native_qubit_count'] == status['native_state_count'] == 0, 'Duplicate state ownership')
        else:
            require(rel.endswith('/Fixed-Dc.json.gz'), 'Missing native application status')
        require(not any('DROP' in e['event_type'] for e in r.get('ns3_events', [])), 'Packet loss')
        if 'handoffs' in r['snapshot']:
            require(all(h['same_qubit_objects'] for h in r['snapshot']['handoffs']), 'Pair not reused')
        report_count += 1
    val = s['validation']
    require(set(val['branches']) == {'0','1','+','-','+i','-i'}, 'Six input states')
    require(all(len(x) == 16 for x in val['branches'].values()), 'Joint branch coverage')
    with (source/'chains.csv').open() as f:
        rows = [{k: float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    require(len(rows) == s['chain_transactions'], 'Transaction count')
    for r in rows:
        require(sum(r[k] for k in DELAY_FIELDS) == r['latency_ns'], 'Latency decomposition')
        require(r['resource_wait_ns'] == 0, 'Resources not ready in controlled sweep')
    cells = []
    for load in p['classical_loads']:
        for interval in p['request_intervals_ns']:
            own = [r for r in rows if r['classical_load'] == load and r['request_interval_ns'] == interval]
            require(len(own) == p['sessions']*(len(p['test_traffic_seeds']) if load else 1), 'Cell size')
            result = dict(load=load, interval_ns=interval, transactions=len(own))
            for key in ['latency_ns', 'expected_fidelity']+DELAY_FIELDS:
                e = estimate(own, key, p['bootstrap_samples'])
                lo, hi = e['ci95_cluster_bootstrap'] or [None, None]
                result.update({key:e['mean'], key+'_low':lo, key+'_high':hi})
            cells.append(result)
    baseline=next(c['latency_ns'] for c in cells if c['load']==0 and
                  c['interval_ns']==p['request_intervals_ns'][-1])
    for c in cells:
        c['baseline_latency_ns']=baseline
        for suffix in ['', '_low', '_high']:
            value=c['latency_ns'+suffix]
            c['extra_latency_ns'+suffix]=None if value is None else value-baseline
    half,full=p['request_intervals_ns'][:2]
    completion_by_key={(r['classical_load'],r['traffic_seed'],r['chain_id'],r['request_interval_ns']):
        r['latency_ns']+p['first_start_ns']+(r['chain_id']-1)*r['request_interval_ns'] for r in rows}
    for key,value in completion_by_key.items():
        if key[-1]==half:
            require(value==completion_by_key[key[:-1]+(full,)], 'Half/full service completion identity')
    couplings = []; examples = []
    for file in sorted((source/'ablations').glob('*/comparison.json')):
        c = read(file); models = c['models']
        for full, nodq, dec in zip(models['Full-Sync'], models['No-Dq-R'], models['Decoupled']):
            change = nodq['result_delay_ns'] - full['result_delay_ns']
            err = dec['transaction_latency_ns'] - full['transaction_latency_ns']
            require(change == err, 'Decoupled error must match changed result-path delay')
            row = dict(load=c['classical_load'], interval_ns=c['request_interval_ns'],
                traffic_seed=c['traffic_seed'], session_id=full['session_id'],
                R_wait_ns=full['quantum_wait_ns'], full_result_ns=full['result_delay_ns'],
                nodq_result_ns=nodq['result_delay_ns'], delta_result_ns=change,
                full_latency_ns=full['transaction_latency_ns'], nodq_latency_ns=nodq['transaction_latency_ns'])
            couplings.append(row)
            if row['R_wait_ns'] > 0 and row['full_latency_ns'] == row['nodq_latency_ns']:
                examples.append(row)
    with (source/'errors.csv').open() as f: errors=list(csv.DictReader(f))
    for g in s['ablation_groups']:
        own=[r for r in errors if r['model']==g['model'] and
             float(r['classical_load'])==g['classical_load'] and
             int(r['request_interval_ns'])==g['request_interval_ns']]
        require(len(own)==g['transactions'],'Ablation cell count')
        mae=np.mean([abs(int(r['delta_latency_ns'])) for r in own])
        require(abs(mae-g['latency_mae_ns']['mean'])<1e-8,'Ablation aggregate mismatch')
        if g['expected_fidelity_bias'] is not None:
            bias=np.mean([float(r['delta_expected_fidelity']) for r in own])
            require(abs(bias-g['expected_fidelity_bias']['mean'])<1e-14,'Fidelity aggregate mismatch')
    return s, rows, cells, couplings, examples, report_count


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10,
        'axes.labelsize':10, 'axes.spines.top':False, 'axes.spines.right':False,
        'axes.edgecolor':'#8B96A1', 'axes.linewidth':.6, 'text.color':'#253441',
        'xtick.color':'#52606A', 'ytick.color':'#52606A', 'legend.frameon':False,
        'axes.axisbelow':True, 'pdf.fonttype':42, 'ps.fonttype':42,
        'savefig.facecolor':'white', 'hatch.linewidth':.55})


def bars(series, title, subtitle, ylabel, loads, out, name, book):
    fig, ax = plt.subplots(figsize=(7.2, 3.9))
    fig.subplots_adjust(left=.105, right=.985, bottom=.19, top=.69)
    fig.text(.105, .95, title, fontsize=14, weight='bold', ha='left')
    fig.text(.105, .884, subtitle, fontsize=9, color='#586875', ha='left')
    positions = np.arange(len(loads))*1.15; width = .245
    upper = max(v[2] if v[2] is not None else v[0] for _, values in series for v in values)
    height = upper*1.24 if upper else 1
    for i,(label,values) in enumerate(series):
        x = positions+(i-1)*width
        ys = [v[0] for v in values]
        ax.bar(x, ys, width*.88, label=label, color=COLORS[i], zorder=3,
               edgecolor='white', linewidth=.6, hatch=['','//','..'][i])
        for xp,(y,lo,hi) in zip(x,values):
            if lo is not None:
                ax.errorbar(xp,y,yerr=[[max(0,y-lo)],[max(0,hi-y)]],
                    fmt='none',ecolor='#384650',capsize=2.5,elinewidth=.8,zorder=5)
            top = hi if hi is not None else y
            if abs(y) < 1e-9:
                ax.plot([xp-.045,xp+.045],[0,0],color=COLORS[i],lw=2,zorder=6,clip_on=False)
            ax.text(xp,top+height*.026,'0' if abs(y)<1e-9 else f'{y:.1f}',
                ha='center',va='bottom',fontsize=9,color=COLORS[i],weight='medium')
    ax.set_ylim(0,height); ax.set_xticks(positions,[f'{l:.2f}' for l in loads])
    ax.set_xlabel('Background offered load on R→B (fraction)',labelpad=9)
    ax.set_ylabel(ylabel,labelpad=7); ax.grid(axis='y',color='#E4E9ED',lw=.65)
    ax.tick_params(axis='x',length=0,pad=7); ax.tick_params(axis='y',width=.5)
    handles,labels=ax.get_legend_handles_labels()
    fig.legend(handles,labels,loc='upper left',bbox_to_anchor=(.09,.832),ncol=3,
               fontsize=8.6,handlelength=1.4,columnspacing=1.5)
    fig.text(.105,.035,'95% traffic-phase bootstrap intervals · 16 phases per loaded cell · zero load: one deterministic run',
             fontsize=8,color='#657480')
    fig.savefig(out/'figures'/(name+'.pdf'))
    fig.savefig(out/'figures'/(name+'.png'),dpi=400)
    book.savefig(fig); plt.close(fig)


def plots(s,cells,out):
    style();p=s['plan'];loads=p['classical_loads']
    with PdfPages(out/'FIGURES.pdf') as book:
        series=[]
        for interval,ratio in zip(p['request_intervals_ns'],p['interval_factors']):
            values=[]
            for load in loads:
                r=next(c for c in cells if c['load']==load and c['interval_ns']==interval)
                values.append(tuple(r[k]/1000 if r[k] is not None else None
                                    for k in ['extra_latency_ns','extra_latency_ns_low','extra_latency_ns_high']))
            series.append((f'{interval/1000:.3f} μs ({ratio:g} × BSM)',values))
        baseline=cells[0]['baseline_latency_ns']/1000
        bars(series,'Swap → Teleport: added completion time',
             f'Full Sync · common unloaded reference: {baseline:.3f} μs · four-session batches',
             'Additional end-to-end latency (μs)',loads,out,'fig1_chain_latency',book)
        series=[]
        for model,label in zip(MODELS,LABELS):
            values=[]
            for load in loads:
                g=next(g for g in s['ablation_groups'] if g['classical_load']==load and
                       g['request_interval_ns']==p['request_intervals_ns'][0] and g['model']==model)
                e=g['latency_mae_ns'];lo,hi=e['ci95_cluster_bootstrap'] or [None,None]
                values.append((e['mean']/1000,None if lo is None else lo/1000,None if hi is None else hi/1000))
            series.append((label,values))
        bars(series,'What simplification misses',
             'Swapping ablation · error against Full Sync · starts every 13.703 μs (½ BSM)',
             'Mean absolute latency error (μs)',loads,out,'fig2_model_error',book)


def interval_text(e, scale=1, digits=2):
    m=e['mean']/scale;ci=e['ci95_cluster_bootstrap']
    return (f'{m:.{digits}f} [{ci[0]/scale:.{digits}f}, {ci[1]/scale:.{digits}f}]'
            if ci else f'{m:.{digits}f} (deterministic)')


def physical_tex():
    return r'''% Requires booktabs and references.bib. All figures use this profile.
\paragraph{Literature-parameterized physical model.}
We adopt the nominal instruction times reported by Liao et al.\ in
\emph{Benchmarking of quantum protocols}~\cite{liao2022benchmarking}
(Table~3), and the matching H/X/Z, memory and gate-noise parameters
used by Iqbal et al.\ in \emph{Investigating Imperfect Cloning for
Extending Quantum Communication Capabilities}~\cite{iqbal2023cloning}
(Table~3 and Section~4).
\begin{table}[t]
\centering
\caption{Adopted nominal processor profile. Times and noise parameters are
from~\cite{iqbal2023cloning}; instruction times also appear
in~\cite{liao2022benchmarking}. Derived circuit durations are QuCl choices.}
\label{tab:qucl-physical-profile}
\small
\begin{tabular}{@{}lr@{}}
\toprule
Parameter & Value \\
\midrule
CNOT & 20~$\mu$s \\
H / X / Z & 5~ns each \\
Single measurement & 3.7~$\mu$s \\
Memory $T_1$, $T_2$ & 10~h, 1~s \\
Gate depolarization parameter $p$ & 0.01 \\
\midrule
Serial CNOT--H--M--M & 27.405~$\mu$s \\
Two correction slots & 10~ns \\
\bottomrule
\end{tabular}
\end{table}

NetSquid executes the timed instructions and applies native T1/T2 storage
noise. We explicitly implement the quoted gate parameter as independent
per-participating-qubit depolarization,
$\mathcal{D}_p(\rho)=(1-p)\rho+pI/2$, before each actual CNOT, H, X or Z,
after storage noise for the instruction's duration. The channel extends
locally to entangled qubits. Ideal measurements and unused identity
correction slots receive storage noise only. Both correction slots
reserve 5~ns regardless of the measured branch.
This noise placement and the serial measurement schedule are explicit
QuCl modeling choices, not an assertion that the cited simulator uses
the same channel placement. Initialization and readout are ideal;
quantum transit is lossless and noiseless. The profile is a published
nominal abstraction, not a calibrated physical NV device or a complete
reproduction of the cited experiments.
'''


def documents(s,cells,couplings,examples,tests,out,source):
    p=s['plan'];v=s['validation'];short=p['request_intervals_ns'][0]
    selected=[g for g in s['ablation_groups'] if g['request_interval_ns']==short]
    by={(g['classical_load'],g['model']):g for g in selected}
    name=dict(zip(MODELS,LABELS))
    analysis_rows=[]
    for g in s['ablation_groups']:
        e=g['latency_mae_ns'];ci=e['ci95_cluster_bootstrap'] or [None,None]
        b=g['expected_fidelity_bias'];bc=b['ci95_cluster_bootstrap'] if b else None
        analysis_rows.append(dict(load=g['classical_load'],interval_us=g['request_interval_ns']/1000,
            model=g['model'],transactions=g['transactions'],phases=e['traffic_clusters'],
            latency_mae_us=e['mean']/1000,latency_ci_low_us=None if ci[0] is None else ci[0]/1000,
            latency_ci_high_us=None if ci[1] is None else ci[1]/1000,
            expected_fidelity_bias=None if b is None else b['mean'],
            fidelity_ci_low=None if bc is None else bc[0],fidelity_ci_high=None if bc is None else bc[1]))
    write_csv(out/'data/ablation_cells.csv',analysis_rows)
    lines=['# QuCl — 문헌 기반 profile 재평가','',
        '**현재 결과는 Liao–Iqbal profile로 새로 실행했다. 기존 1.6 ms 결과와 분리한다.**','',
        '## 설정과 근거','',
        '| 항목 | 새 설정 | 근거 |','|---|---|---|',
        '| CNOT / H / 개별 측정 | 20 μs / 5 ns / 3.7 μs | Liao Table 3; Iqbal Table 3 |',
        '| X / Z | 각각 5 ns | Iqbal Table 3 |',
        '| Memory T1 / T2 | 10 h / 1 s | Iqbal Section 4 |',
        '| Gate depolarization p | 0.01 | Iqbal Section 4; 적용 위치는 아래 명시 |',
        '| BSM / correction | 27.405 μs / 10 ns | 직렬 회로·고정 슬롯의 합 |',
        '| 요청 간격 | 13.703 / 27.405 / 54.810 μs | BSM의 ½ / 1 / 2배; 반올림 +0.5 ns |',
        '| R–B background load | 0 / 0.25 / 0.50 / 0.75 | 동일 간격의 부하 sweep |',
        '| Classical link | 100 Mb/s, hop당 100 μs | controlled network 가정 |','',
        '문헌: [Liao et al., *Benchmarking of quantum protocols* (2022)](https://doi.org/10.1038/s41598-022-08901-x), '
        '[Iqbal et al., *Investigating Imperfect Cloning for Extending Quantum Communication Capabilities* (2023)](https://doi.org/10.3390/s23187891). '
        '논문용 citation은 [references.bib](references.bib), 적용 설명은 [physical-model.tex](physical-model.tex)에 있다.','',
        'Native T1/T2와 함께 CNOT/H/X/Z의 각 operand에 p=0.01 depolarization을 적용했다. '
        '적용 순서는 active memory noise → gate depolarization → ideal gate다. '
        'Measurement와 실행하지 않는 correction identity slot에는 storage noise만 적용했다. '
        '이 noise 위치, 직렬 측정, 이상적인 초기화/readout, 무손실·무잡음 quantum transit은 명시적인 QuCl 가정이다. '
        '**문헌 기반 nominal processor이며 실제 NV 장비 재현을 주장하지 않는다.**','',
        'EPR과 입력 qubit은 t=0에 생성하고 native quantum delivery는 0.8/1.2 ms다. '
        '첫 session은 2 ms에 시작하여 resource-ready 지연을 통제했다. '
        '4개 session의 뒤쪽 요청은 t=0부터 더 오래 저장된 상태를 사용한다. '
        'Chain 성능 sweep의 입력은 `|+i⟩`이며, 6개 입력 상태의 correctness 검증과 구분한다. '
        '100 Mb/s에서 swap result의 serialization은 8.8 μs이므로 가장 짧은 요청 간격보다 짧다. '
        '1000-byte background packet은 1030 wire bytes이며 serialization 82.4 μs/설정 부하로 주기를 정했다. '
        '부하는 background offered load이며 protocol packet까지 포함한 총 이용률이 아니다.','',
        '## 실행·검증','',
        f'- {s["paired_cases"]}개 조건: chain {s["chain_runs"]}회 + swapping 모델 3종, 총 **{s["evaluation_runs"]}회 재실행**. Calibration {s["calibration_runs"]}회 별도.',
        f'- Chain {s["chain_transactions"]} transactions; swapping 모델별 {s["transactions_per_ablation_model"]} transactions.',
        f'- Noiseless {v["noiseless_runs"]}회 / {v["noiseless_transactions"]} chains: 6개 입력 × 16개 joint branch 모두 확인. 최소 fidelity {v["minimum_noiseless_fidelity"]:.16f}.',
        f'- 6개 noisy input × 2개 A–R delay = {v["noisy_runs"]}회 별도 검증. 전체 최대 density-matrix error **{s["max_density_matrix_error"]:.2e}**.',
        f'- 기존 회귀 {tests["regression"]["tests"]}개 + 평가 도구 {tests["experiments"]["tests"]}개 = **{sum(t["tests"] for t in tests.values())} tests PASS**.',
        '- 실제 ns-3 실행의 packet drop=0, Q2NS native qubit/state=0, chained 실행의 swapped pair 실제 객체 handoff를 검사했다. Fixed-Dc는 virtual transport다. 실행 소스와 원본 report 해시도 대조했다.','',
        '## 그래프 1 — Swap→Teleport의 추가 완료시간','',
        '[PDF](figures/fig1_chain_latency.pdf) · [PNG](figures/fig1_chain_latency.png)','',
        '![End-to-end latency](figures/fig1_chain_latency.png)','',
        '**같은 load에서 세 막대는 요청 간격만 다르다.** '
        f'Y축은 공통 무부하·비경합 완료시간 {cells[0]["baseline_latency_ns"]/1000:.3f} μs보다 추가된 시간이다. '
        '모든 막대에 같은 기준을 사용하고 축은 0에서 시작한다. 아래 표에는 절대 완료시간을 함께 제시한다. '
        'Swap R BSM → R–B result → B correction → B–R–A readiness → Teleport A BSM → A–R–B result → B correction 전체를 포함한다. '
        '측정 기준은 local session start부터 최종 teleported qubit usable까지다.','',
        '| Load | 13.703 μs 간격 | 27.405 μs 간격 | 54.810 μs 간격 |',
        '|---:|---:|---:|---:|']
    for load in p['classical_loads']:
        vals=[]
        for interval in p['request_intervals_ns']:
            c=next(c for c in cells if c['load']==load and c['interval_ns']==interval)
            vals.append(f'{c["latency_ns"]/1000:.1f}')
        lines.append('| '+str(load)+' | '+' | '.join(vals)+' |')
    lines += ['', '단위 μs. 95% 구간과 각 대기시간 성분은 [chain_cells.csv](data/chain_cells.csv).', '',
        '½T와 1T 간격에서는 R의 직렬 완료 일정이 같다. 두 조건의 평균 latency 차이 20.553 μs는 '
        '서로 다른 요청 시작시점에 따른 FIFO 대기시간을 반영한다. 실제 packet 생성시각 변화의 영향은 아래 No-R paired ablation에서 확인한다.', '',
        '## 그래프 2 — 무엇을 단순화하면 오차가 생기는가','',
        '[PDF](figures/fig2_model_error.pdf) · [PNG](figures/fig2_model_error.png)','',
        '![Model error](figures/fig2_model_error.png)','',
        '**Swapping을 분리한 paired ablation이며 chain 전체의 모델 비교가 아니다.** '
        '요청 간격은 13.703 μs로 고정한다. No R contention은 R capacity 제약을 제거한 시각에 실제 packet을 다시 생성한다. '
        'Fixed classical delay는 별도 calibration 평균 result delay를 사용하고 R FIFO는 유지한다. '
        'Decoupled timing은 No-R의 result delay와 resource-eligible R FIFO wait를 합성하며 fidelity는 정의하지 않는다.','',
        '| Load | No R contention | Fixed classical delay | Decoupled timing |',
        '|---:|---:|---:|---:|']
    for load in p['classical_loads']:
        lines.append('| '+str(load)+' | '+' | '.join(interval_text(by[(load,m)]['latency_mae_ns'],1000,2) for m in MODELS)+' |')
    lines += ['', 'Latency MAE, μs [95% interval]. Zero load는 결정론적 1회 결과다.', '',
        '### 기대 fidelity 차이도 함께 확인','',
        '| Load | No R contention − Full | Fixed delay − Full |','|---:|---:|---:|']
    for load in p['classical_loads']:
        lines.append('| '+str(load)+' | '+' | '.join(interval_text(by[(load,m)]['expected_fidelity_bias'],1,6) for m in MODELS[:2])+' |')
    lines += ['', '이 표의 fidelity는 swapping output과 목표 Bell state의 fidelity이며, 각 timing에서 네 측정 분기의 확률 가중 기대값이다. '
        '같은 seed의 단일 branch 차이를 평균 fidelity 효과로 해석하지 않는다. '
        '긴 T2와 μs 단위 연산에서는 추가 대기로 인한 fidelity 변화가 이전 illustrative profile보다 작을 수 있다. '
        '서로 다른 물리 모델의 수치를 시스템 개선율로 비교하지 않는다.','',
        '### Cross-domain timing의 직접 확인','',
        f'{len(couplings)}개 paired transaction에서 `Decoupled latency error = No-R result delay − Full result delay`를 확인했다. '
        '따라서 quantum wait를 제거하면 뒤쪽 packet이 다른 background queue 구간을 만나며, 그 지연을 독립적으로 재사용할 수 없다.']
    if examples:
        e=max(examples,key=lambda r:r['R_wait_ns'])
        lines += ['',f'예: load={e["load"]}, 간격={e["interval_ns"]/1000:.3f} μs, phase seed={e["traffic_seed"]}, session={e["session_id"]}. '
            f'Full의 R wait는 {e["R_wait_ns"]/1000:.3f} μs지만 Full과 No-R latency는 모두 {e["full_latency_ns"]/1000:.3f} μs다. '
            f'No-R의 result delay가 정확히 {e["delta_result_ns"]/1000:.3f} μs 늘어나 상쇄했다. '
            '이 사례는 대표 평균이 아닌 인과관계 확인용 trace다.']
    phase_states=[r for r in v['noisy_cases'] if r['input_state']=='+i']
    phase_states.sort(key=lambda r:r['access_delay_ns'])
    lines += ['', '### 저장시간과 quantum state의 연결', '',
        f'단일 chain의 A–R propagation을 100→500 μs로 늘린 검증에서는 완료시간이 '
        f'{phase_states[0]["latency_ns"]/1000:.3f}→{phase_states[1]["latency_ns"]/1000:.3f} μs로 늘고, '
        f'`|+i⟩`의 기대 fidelity는 {phase_states[0]["expected_fidelity"]:.6f}→{phase_states[1]["expected_fidelity"]:.6f}로 변했다. '
        'A–R을 readiness와 teleport result가 각각 지나므로 추가 시간은 800 μs다. '
        '두 상태 모두 독립 reference와 비교했다. 6개 입력의 수치는 [six_state_noise.csv](data/six_state_noise.csv)에 있다.']
    lines += ['', '## 해석 범위','',
        '- Loaded cell마다 독립 traffic phase 16개. 한 phase의 4개 session을 먼저 평균내고 phase를 10,000회 bootstrap했다.',
        '- Quantum fidelity는 16개(chain) 또는 4개(swap) 분기를 정확히 열거했다. Quantum seed 반복을 독립 traffic 표본으로 세지 않는다.',
        '- Calibration은 load별 별도 phase 4개(무부하 1개), 요청 간격 20×BSM이다. 모든 calibration transaction은 background traffic 종료 전에 완료한다. CI는 이 calibration에 조건부다.',
        '- 요청 간격=BSM 조건은 정확히 정렬된 결정론적 경계 조건이다. 일반 확률 도착의 안정성/이용률 주장이 아니다.',
        '- 모든 실행은 4-session finite batch이며 steady-state throughput, 장비 fidelity 또는 임의 network로 일반화하지 않는다.',
        '- F_min=0.5, deadline=5 ms는 보존한 audit 기준이다. 이번 profile의 주요 결과는 latency 및 모델 오차이며 서비스 실패 일반화에 사용하지 않는다.',
        '',f'원본: [{source.name}/summary.json](../../results/{source.name}/summary.json). '
        '모든 aggregate: [data/](data/). 재현법: [README](README.md).']
    (out/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    (out/'physical-model.tex').write_text(physical_tex())
    short_mae={m:[by[(load,m)]['latency_mae_ns']['mean']/1000 for load in p['classical_loads']] for m in MODELS}
    tex = r'''% Requires graphicx, booktabs, references.bib; paths assume this directory.
\section{Experimental Validation and Analysis}
\label{sec:eval}
We evaluate a literature-parameterized nominal processor with two linked
protocols: swapping at R creates an A--B pair, and teleportation at A
consumes that same pair. Q2NS retains the classical protocol and real
packet path; NetSquid owns the quantum state and timed instruction chain.
\input{physical-model.tex}

\subsection{Controlled Workload}
Each batch contains four sessions; the chain sweep teleports $|+i\rangle$.
All quantum resources are created at
$t=0$; lossless native delivery to A/B takes 0.8/1.2~ms. The first session
starts locally at 2~ms, after delivery. Later requests therefore also
have greater storage age. We use regular start intervals of 13.703,
27.405 and 54.810~$\mu$s: one half (rounded up by 0.5~ns), one and two
times the circuit service time. The exact service-time boundary is a
deterministic control, not a stationary queueing claim.

Classical hops run at 100~Mb/s with 100~$\mu$s propagation. A swap result
serializes in 8.8~$\mu$s, below the smallest request interval. Periodic
background packets on R--B have 1000-byte payloads (1030 wire bytes).
Their period is serialization time divided by offered load, swept over
0, 0.25, 0.50 and 0.75; only their initial phase is randomized. Protocol
traffic is additional to this background load. These network choices are
controlled workload assumptions, not parameters taken from the gate papers.

We use 16 test phases per loaded cell and a single zero-load run, where
phase has no effect. Fidelity is evaluated by exact measurement-branch
enumeration (16 joint branches for a chain, four for swapping). We average
the four transactions within a phase before 10,000-replicate percentile
bootstrap resampling; bars show 95\% intervals. Swapping ablations use the
same starts and background phase. Fixed classical delay is calibrated
from four disjoint phases per loaded condition and one zero-load run,
using 20 service times between requests. All calibration transactions
complete while background traffic is active. Intervals are conditional
on that fixed calibration.

\subsection{Execution Correctness}
\input{table_validation.tex}
The six inputs $\{|0\rangle,|1\rangle,|+\rangle,|-\rangle,
|+i\rangle,|-i\rangle\}$ cover all 16 joint swap/teleport outcomes.
Noiseless output fidelity equals one within numerical precision.
Independent NetSquid-only circuits reproduce the native instruction
and checkpoint states using the observed operation times. Additional
noisy cases exercise both 100- and 500-$\mu$s A--R propagation. We verify
physical qubit continuity at the pair handoff, absence of duplicate
Q2NS state, zero packet drops and the complete latency decomposition.

\subsection{End-to-End Execution}
\begin{figure*}[t]
\centering
\includegraphics[width=.96\textwidth]{figures/fig1_chain_latency.pdf}
\caption{Additional Full Sync swapping-assisted teleportation latency
above the common unloaded, noncontending reference (576.110~$\mu$s).
Absolute latency is measured from local session start to usable output.
Each group holds network load fixed and
compares the three start intervals. Error bars resample traffic phases;
the zero-load result is deterministic.}
\label{fig:qucl-chain}
\end{figure*}
Figure~\ref{fig:qucl-chain} includes the R swapping queue, result delivery,
B correction, B--R--A readiness, A teleportation queue, A--R--B result
delivery and final B correction. The operation timing and generated
packets are recomputed for every condition.
For half- versus full-service start intervals, the R completion sequence
is identical: the 20.553-$\mu$s difference in mean latency follows from
the different request origins and FIFO waiting. The paired No-R ablation
below specifically changes packet-generation times to test downstream
timing dependence.

\subsection{Simplification Error}
\begin{figure*}[t]
\centering
\includegraphics[width=.96\textwidth]{figures/fig2_model_error.pdf}
\caption{Mean absolute latency error against Full Sync for the swapping
ablation at a 13.703-$\mu$s start interval. These are paired protocol-stage
comparisons, not a counterfactual model of the complete chain.}
\label{fig:qucl-models}
\end{figure*}
No R contention removes the R execution-capacity constraint and generates
real packets at the resulting completion times. Fixed classical delay
preserves the R queue but uses its separately calibrated result delay.
Decoupled timing combines No-R result delays with the resource-eligible
FIFO wait. It makes latency predictions only.
'''
    tex += '\nAt background load 0.75, the latency MAEs for No R contention, '
    tex += 'Fixed classical delay and Decoupled timing are '
    tex += ', '.join(f'{short_mae[m][-1]:.2f}' for m in MODELS)
    tex += r'~$\mu$s, respectively (Fig.~\ref{fig:qucl-models}). '
    tex += r'At zero load, Fixed and Decoupled are exact, while removing R contention yields a 20.553-$\mu$s MAE.'+'\n'
    tex += r'''
For every paired transaction, the Decoupled latency error equals the
change in result-path delay between No-R and Full Sync. Removing quantum
waiting shifts packet generation relative to background traffic; hence
independently reusing a measured classical delay need not preserve
completion timing. This is a conditional causal counterfactual, not a
claim that load and fidelity must be monotone.

The adopted one-second $T_2$ and microsecond-scale gates also make the
incremental storage-noise effect smaller than under our earlier
illustrative profile. We report branch-weighted fidelity biases in the
artifact and do not interpret differences between physical profiles as
simulator improvements. The retained $F_{\min}=0.5$, 5-ms deadline is an
audit threshold, not a tuned service-failure endpoint.

\paragraph{Scope.}
These results characterize finite four-session batches with randomized
periodic traffic phase, fixed resource-delivery times and a nominal
processor. They do not establish calibrated hardware performance,
steady-state queueing, arbitrary topology scaling, or calibration-free
error bounds. Zero observed errors do not establish zero population error.
'''
    tex=tex.replace('576.110~',f'{cells[0]["baseline_latency_ns"]/1000:.3f}~')
    (out/'evaluation.tex').write_text(tex)
    table = r'''\begin{table}[t]
\centering
\caption{Fresh validation and evaluation under the literature profile.}
\label{tab:qucl-validation}
\small
\begin{tabular}{@{}lr@{}}
\toprule
Check & Result \\
\midrule
'''
    table += f'Input states $\\times$ joint branches & 6 $\\times$ 16 \\\\\n'
    table += f'Noiseless chains & {v["noiseless_transactions"]} \\\\\n'
    table += f'Additional noisy cases & {v["noisy_runs"]} \\\\\n'
    table += f'Evaluation / calibration runs & {s["evaluation_runs"]} / {s["calibration_runs"]} \\\\\n'
    mantissa,exponent=f'{s["max_density_matrix_error"]:.2e}'.split('e')
    table += f'Max. density-matrix error & ${mantissa}\\times 10^{{{int(exponent)}}}$ \\\\\n'
    table += f'Regression / evaluation tests & {tests["regression"]["tests"]} / {tests["experiments"]["tests"]} \\\\\n'
    table += r'''\bottomrule
\end{tabular}
\end{table}
'''
    (out/'table_validation.tex').write_text(table)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=MODULE/'results/literature-evaluation-v1')
    parser.add_argument('--output',type=Path,default=MODULE/'paper/evaluation')
    args=parser.parse_args();source=args.source.resolve();out=args.output.resolve()
    s,rows,cells,couplings,examples,count=audit(source)
    tests=dict(regression=test_result(MODULE/'results/literature-regression-suite.log'),
               experiments=test_result(MODULE/'results/literature-experiment-tests.log'))
    # Preserve the old controlled package, including its citations and raw CSVs.
    if out.exists() and not (out/'LITERATURE-PROFILE').exists():
        archive=out.with_name(out.name+'-controlled')
        require(not archive.exists(),'Historical archive already exists; choose a new output directory')
        out.rename(archive)
        out.mkdir(parents=True)
        shutil.copy2(archive/'references.bib',out/'references.bib')
    else:
        out.mkdir(parents=True,exist_ok=True)
    require((out/'references.bib').exists(),'Copy the verified references.bib to output first')
    for directory in ['data','figures']:(out/directory).mkdir(exist_ok=True)
    (out/'LITERATURE-PROFILE').write_text(s['profile']+'\n')
    write_csv(out/'data/chain_cells.csv',cells)
    write_csv(out/'data/result_phase_coupling.csv',couplings)
    write_csv(out/'data/six_state_noise.csv',s['validation']['noisy_cases'])
    for filename in ['chains.csv','errors.csv','calibration.json','plan.json']:
        shutil.copy2(source/filename,out/'data'/filename)
    plots(s,cells,out)
    documents(s,cells,couplings,examples,tests,out,source)
    (out/'README.md').write_text('''# Literature-profile evaluation package

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
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_literature_evaluation.py \\
  contrib/cosim/scenarios/literature-evaluation.json \\
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
''')
    prov=dict(profile=s['profile'],run=str(source.relative_to(MODULE)),
        run_summary_sha256=digest(source/'summary.json'),plan_sha256=digest(source/'plan.json'),
        raw_reports_audited=count,source_hashes_unchanged=True,tests=tests,
        renderer=str(Path(__file__).relative_to(MODULE)),renderer_sha256=digest(Path(__file__)),
        figures=['fig1_chain_latency','fig2_model_error'],
        latex_compiled=False,scope=s['scope'],resumption=s['resumption'])
    prov['simulation_environment']=json.loads(subprocess.check_output([
        '/home/ns3/qunet/bin/python','-c',
        'import json,sys,netsquid,numpy; print(json.dumps(dict(python=sys.version, executable=sys.executable, netsquid=netsquid.__version__, numpy=numpy.__version__)))'],text=True))
    prov['render_environment']=dict(python=sys.version,matplotlib=matplotlib.__version__,numpy=np.__version__)
    prov['participant_sha256']={str(f.relative_to(MODULE.parents[1])):digest(f)
        for f in (MODULE.parents[1]/'build/contrib/cosim').rglob('*')
        if f.is_file() and f.name in ['ns3.47-cosim-chained-default','ns3.47-cosim-provisioned-default']}
    prov['generated_sha256']={str(f.relative_to(out)):digest(f) for f in out.rglob('*') if f.is_file() and f.name!='provenance.json'}
    (out/'provenance.json').write_text(json.dumps(prov,indent=2,sort_keys=True)+'\n')
    target=MODULE/'paper/qucl-evaluation-figures.zip'
    if target.exists() and not (target.with_name('qucl-evaluation-controlled.zip')).exists():
        target.rename(target.with_name('qucl-evaluation-controlled.zip'))
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file():z.write(f,'evaluation/'+str(f.relative_to(out)))
    print(json.dumps(prov,indent=2))


if __name__=='__main__':main()
