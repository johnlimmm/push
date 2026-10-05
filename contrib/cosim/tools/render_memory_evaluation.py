#!/usr/bin/env python3
"""Audit fresh literature-profile evidence and render Figures 3, 4 and 5.

Requires numpy/matplotlib; no simulator execution. Reads only the named completed
run. CSV exports and provenance accompany every plotted aggregate.
The authored evaluation.tex is preserved; numerical prose needs manual review.
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
from matplotlib.ticker import MaxNLocator, FormatStrFormatter
import numpy as np

MODULE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(MODULE/'experiments'))
from p5b_analysis import estimate

COLORS = ['#DCE7F1', '#F5E3D3', '#F0DEE6']
EDGES = ['#91A4B7', '#B8A18D', '#B39AA6']
HATCHES = ['///', '\\\\', '..']
MARKERS = ['o', 's', 'D']
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


def regression_result():
    initial=MODULE/'results/memory-regression-suite.log'
    if initial.read_text().rstrip().endswith('OK'):return test_result(initial)
    text=initial.read_text()
    count=re.search(r'Ran (\d+) tests? in ([\d.]+)s',text)
    failures=set(re.findall(r'^FAIL: (.+)$',text,re.M))
    expected={'test_frozen_v4_sources (test_chained.ChainedTests)',
              'test_20_v3_sources_preserved (test_provisioned.ProvisionedTests)'}
    require(count is not None and int(count[1])==196,'Unexpected regression coverage')
    require(failures==expected and text.rstrip().endswith('FAILED (failures=2)'),
            'Only the two documented frozen-document checks may be retried')
    retry_path=MODULE/'results/memory-freeze-recheck.log';retry=test_result(retry_path)
    passed=set(re.findall(r'^(test_\S+ \([^)]+\)) \.\.\. ok$',retry_path.read_text(),re.M))
    require(retry['tests']==2 and passed==expected,'Frozen-file retries did not pass')
    return dict(tests=196,seconds=float(count[2])+retry['seconds'],
        log=str(initial.relative_to(MODULE)),sha256=digest(initial),recheck=retry,
        note='194 initial passes plus the two frozen-document checks passing after removal of a navigation notice from the historical RESULTS.md. Execution code unchanged; original failed log retained.')


def audit(source):
    s = read(source/'summary.json'); p = s['plan']
    require(s['passed'], 'Run did not pass')
    require(p == read(source/'plan.json'), 'Plan mismatch')
    require(p == read(MODULE/'scenarios/memory-evaluation.json'), 'Renderer prose targets the registered literature plan')
    require(set(p['test_traffic_seeds']).isdisjoint(p['calibration_traffic_seeds']), 'Seed overlap')
    native=read(source/'native-fidelity-audit.json')
    require(native['passed'] and native['run_summary_sha256']==digest(source/'summary.json'),
            'Missing native API metric verification for this run')
    require(digest(MODULE/native['tool'])==native['tool_sha256'],'Native fidelity audit tool changed')
    require(native['max_fidelity_difference']<=1e-12 and native['max_expected_fidelity_difference']<=1e-12,
            'Native fidelity metric disagreement')
    require(set(native['source_changes'])<={'experiments/literature_reference_chained.py',
        'experiments/literature_reference_provisioned.py'},'Unexpected reference changes')
    for rel, sha in s['source_sha256'].items():
        current=digest(MODULE/rel)
        if rel not in native['source_changes']:
            require(current==sha, 'Execution source changed: '+rel)
            continue
        change=native['source_changes'][rel];text=(MODULE/rel).read_text()
        require(change['before']==sha and change['after']==current,'Reference source attestation mismatch')
        require(text.count(change['new_expression'])==1 and
            hashlib.sha256(text.replace(change['new_expression'],change['old_expression']).encode()).hexdigest()==sha,
            'Reference change exceeds the native fidelity expression')
    s['_native_fidelity']=native
    report_count = 0
    raw_chain_values={}
    for rel, sha in s['report_sha256'].items():
        file = source/rel
        require(digest(file) == sha, 'Report changed: '+rel)
        r = read(file)
        require(r['validation']['passed'], 'Invalid report: '+rel)
        if not rel.startswith('validation/coverage/'):
            require(r['config']['memory_noise']==p['memory_noise'], 'Wrong memory profile: '+rel)
            require(r['config']['native_instructions']==p['native_instructions'], 'Wrong gate times: '+rel)
            require(r['config']['gate_depolar_probability']==p['gate_depolar_probability'], 'Wrong gate noise: '+rel)
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
        if rel.startswith('chains/'):
            match=re.search(r'load-([\d.]+)-interval-(\d+)-phase-(\d+)',rel)
            require(match is not None,'Unknown report condition')
            load,interval,phase=float(match[1]),int(match[2]),int(match[3])
            states_by_id={c['chain_id']:c['input_state'] for c in r['config']['chains']}
            for m in r['metrics']['chains']:
                key=(load,interval,phase,m['chain_id'],states_by_id[m['chain_id']])
                require(key not in raw_chain_values,'Duplicate chain evidence')
                ref=r['cross_validation']['chains'][str(m['chain_id'])]['reference']
                require(len(ref['branches'])==16,'Incomplete quantum branch expectation')
                weight=sum(b['probability'] for b in ref['branches'].values())
                expect=sum(b['probability']*b['stages'][1]['checkpoints']['usable']['fidelity'] for b in ref['branches'].values())
                require(abs(weight-1)<1e-12 and abs(expect-ref['expected_fidelity'])<1e-12,'Bad branch-weighted fidelity')
                native_expect=native['values'][rel][str(m['chain_id'])]['expected_fidelity']
                require(abs(expect-native_expect)<1e-12,'Native API expectation differs from original report')
                raw_chain_values[key]=(m['latency_ns'],native_expect)
        report_count += 1
    val = s['validation']
    require(set(val['branches']) == {'0','1','+','-','+i','-i'}, 'Six input states')
    require(all(len(x) == 16 for x in val['branches'].values()), 'Joint branch coverage')
    with (source/'chains.csv').open() as f:
        rows = [{k: v if k == 'input_state' else float(v) for k,v in r.items()} for r in csv.DictReader(f)]
    require(len(rows) == s['chain_transactions'], 'Transaction count')
    require(s['input_timing_equivalence_passed'], 'Six-input timing equivalence')
    states=p['input_states']
    require(states==['0','1','+','-','+i','-i'], 'Six input-state performance coverage')
    for r in rows:
        key=(r['classical_load'],r['request_interval_ns'],r['traffic_seed'],r['chain_id'],r['input_state'])
        require(key in raw_chain_values,'Missing original six-input evidence')
        latency,fidelity=raw_chain_values[key]
        require(latency==r['latency_ns'] and abs(fidelity-r['expected_fidelity'])<1e-13,'CSV disagrees with original report')
        r['expected_fidelity']=fidelity
        require(sum(r[k] for k in DELAY_FIELDS) == r['latency_ns'], 'Latency decomposition')
        require(r['resource_wait_ns'] == 0, 'Resources not ready in controlled sweep')
    cells = []
    for load in p['classical_loads']:
        for interval in p['request_intervals_ns']:
            own = [r for r in rows if r['classical_load'] == load and r['request_interval_ns'] == interval]
            require(len(own) == len(states)*p['sessions']*(len(p['test_traffic_seeds']) if load else 1), 'Cell size')
            for phase in (p['test_traffic_seeds'] if load else p['test_traffic_seeds'][:1]):
                for sid in range(1,p['sessions']+1):
                    group=[r for r in own if r['traffic_seed']==phase and r['chain_id']==sid]
                    require(sorted(r['input_state'] for r in group)==sorted(states), 'Unbalanced six-state mean')
                    require(len({r['latency_ns'] for r in group})==1, 'Input-dependent latency')
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
    fidelity_by_key={(r['classical_load'],r['traffic_seed'],r['chain_id'],r['input_state'],r['request_interval_ns']):
                     r['expected_fidelity'] for r in rows}
    for key,value in fidelity_by_key.items():
        if key[-1]==half:
            require(abs(value-fidelity_by_key[key[:-1]+(full,)])<1e-12,
                    'Identical absolute timing and resource birth must preserve fidelity')
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
    for r in errors:
        if r['model']=='Decoupled':continue
        prefix='ablations/load-{}-interval-{}-phase-{}/'.format(
            float(r['classical_load']),int(r['request_interval_ns']),int(r['traffic_seed']))
        full=native['values'][prefix+'Full-Sync.json.gz'][r['session_id']]['expected_fidelity']
        predicted=native['values'][prefix+r['model']+'.json.gz'][r['session_id']]['expected_fidelity']
        delta=predicted-full
        require(abs(delta-float(r['delta_expected_fidelity']))<1e-12,'Native model fidelity bias differs')
        r['delta_expected_fidelity']=delta
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
            metric_rows=[dict(traffic_seed=int(r['traffic_seed']),delta_expected_fidelity=float(r['delta_expected_fidelity'])) for r in own]
            g['expected_fidelity_bias']=estimate(metric_rows,'delta_expected_fidelity',p['bootstrap_samples'])
            g['expected_fidelity_mae']=estimate(metric_rows,'delta_expected_fidelity',p['bootstrap_samples'],absolute=True)
    s['_native_errors']=errors
    require(report_count==native['counts']['reports'],'Native fidelity audit did not cover all original reports')
    return s, rows, cells, couplings, examples, report_count


def style():
    plt.rcParams.update({'font.family':'DejaVu Sans', 'font.size':10.5,
        'axes.labelsize':11, 'axes.spines.top':False, 'axes.spines.right':False,
        'axes.edgecolor':'#9099A2', 'axes.linewidth':.7, 'text.color':'#303942',
        'xtick.color':'#4C5862', 'ytick.color':'#4C5862', 'legend.frameon':False,
        'axes.axisbelow':True, 'pdf.fonttype':42, 'ps.fonttype':42,
        'savefig.facecolor':'white', 'hatch.linewidth':.65})


def figure_axes():
    fig, ax = plt.subplots(figsize=(5.4, 3.45))
    fig.subplots_adjust(left=.155, right=.98, bottom=.19, top=.83)
    ax.set_xlabel('Background load', labelpad=8)
    ax.grid(axis='y', color='#E7EAEE', linewidth=.65)
    ax.tick_params(axis='x', length=0, pad=7)
    ax.tick_params(axis='y', width=.6)
    return fig, ax


def legend(fig, ax):
    handles, labels = ax.get_legend_handles_labels()
    wrapped = {'No R contention': 'No R\ncontention',
               'Fixed classical delay': 'Fixed classical\ndelay',
               'Decoupled timing': 'Decoupled\ntiming'}
    labels = [wrapped.get(label, label) for label in labels]
    fig.legend(handles, labels, loc='upper center', bbox_to_anchor=(.56, .99),
               ncol=3, fontsize=10, handlelength=1.7, handleheight=1.15,
               columnspacing=1.2, handletextpad=.6)


def save_figure(fig, out, name, book):
    fig.savefig(out/'figures'/(name+'.pdf'))
    fig.savefig(out/'figures'/(name+'.png'), dpi=400)
    book.savefig(fig)
    plt.close(fig)


def bars(series, ylabel, loads, out, name, book):
    fig, ax = figure_axes()
    positions = np.arange(len(loads))*1.15; width = .245
    upper = max(v[2] if v[2] is not None else v[0] for _, values in series for v in values)
    height = upper*1.13 if upper else 1
    for i,(label,values) in enumerate(series):
        x = positions+(i-1)*width
        ys = [v[0] for v in values]
        ax.bar(x, ys, width*.90, label=label, color=COLORS[i], zorder=3,
               edgecolor=EDGES[i], linewidth=.8, hatch=HATCHES[i])
        for xp,(y,lo,hi) in zip(x,values):
            if lo is not None:
                ax.errorbar(xp,y,yerr=[[max(0,y-lo)],[max(0,hi-y)]],
                    fmt='none',ecolor='#414B55',capsize=3,elinewidth=.9,zorder=5)
            if abs(y) < 1e-9:
                ax.plot([xp-width*.45,xp+width*.45],[0,0],color=EDGES[i],
                        lw=1.6,zorder=6,clip_on=False)
    ax.set_ylim(0,height); ax.set_xticks(positions,[f'{l:.2f}' for l in loads])
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5, integer=True))
    ax.set_ylabel(ylabel,labelpad=8)
    legend(fig, ax)
    save_figure(fig, out, name, book)


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
            series.append((f'{ratio:g}× interval',values))
        bars(series,'Extra latency (μs)',loads,out,'fig3_chain_latency',book)
        fidelity_plot(s,cells,out,book)
        series=[]
        for model,label in zip(MODELS,LABELS):
            values=[]
            for load in loads:
                g=next(g for g in s['ablation_groups'] if g['classical_load']==load and
                       g['request_interval_ns']==p['request_intervals_ns'][0] and g['model']==model)
                e=g['latency_mae_ns'];lo,hi=e['ci95_cluster_bootstrap'] or [None,None]
                values.append((e['mean']/1000,None if lo is None else lo/1000,None if hi is None else hi/1000))
            series.append((label,values))
        bars(series,'Latency error (μs)',loads,out,'fig5_model_error',book)


def interval_text(e, scale=1, digits=2):
    m=e['mean']/scale;ci=e['ci95_cluster_bootstrap']
    return (f'{m:.{digits}f} [{ci[0]/scale:.{digits}f}, {ci[1]/scale:.{digits}f}]'
            if ci else f'{m:.{digits}f} (deterministic)')


def fidelity_plot(s,cells,out,book):
    """Absolute fidelity on an explicitly expanded axis, without misleading bars."""
    p=s['plan'];loads=p['classical_loads']
    fig,ax=figure_axes()
    bounds=[]
    for i,(interval,ratio) in enumerate(zip(p['request_intervals_ns'],p['interval_factors'])):
        own=[next(c for c in cells if c['load']==load and c['interval_ns']==interval) for load in loads]
        ys=[c['expected_fidelity'] for c in own]
        lo=[c['expected_fidelity_low'] if c['expected_fidelity_low'] is not None else c['expected_fidelity'] for c in own]
        hi=[c['expected_fidelity_high'] if c['expected_fidelity_high'] is not None else c['expected_fidelity'] for c in own]
        bounds+=lo+hi
        # Categorical groups match Fig. 3. The 0.5×/1× means can be identical;
        # adjacent markers keep both visible without implying distinct fidelity.
        x=np.arange(len(loads))*1.15+(i-1)*.23
        ax.plot(x,ys,color=EDGES[i],marker=MARKERS[i],ms=7.5,linestyle='none',
                markerfacecolor=COLORS[i],markeredgewidth=1.1,zorder=4,
                label=f'{ratio:g}× interval')
        ax.errorbar(x[1:],ys[1:],yerr=[np.maximum(0,np.array(ys[1:])-lo[1:]),np.maximum(0,np.array(hi[1:])-ys[1:])],
                    fmt='none',ecolor=EDGES[i],capsize=3.5,lw=1,zorder=3)
    span=max(bounds)-min(bounds);pad=max(span*.18,.0005)
    ax.set_ylim(max(0,min(bounds)-pad),min(1,max(bounds)+pad))
    ax.set_xlim(-.5,3.95);ax.set_xticks(np.arange(len(loads))*1.15,[f'{x:.2f}' for x in loads])
    ax.set_ylabel('Fidelity',labelpad=8)
    ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
    ax.yaxis.set_major_formatter(FormatStrFormatter('%.3f'))
    legend(fig, ax)
    save_figure(fig, out, 'fig4_teleport_fidelity', book)


def preserve_manuscript(out):
    """Keep the authored section; seed new packages from the reviewed copy.

    Numerical prose is reviewed manually when the experimental results change.
    Tables belong in this section, not in generated LaTeX fragments.
    """
    target = out/'evaluation.tex'
    if target.exists():
        return
    source = MODULE/'paper/evaluation/evaluation.tex'
    require(source.is_file(), 'Authored evaluation.tex missing')
    shutil.copy2(source, target)


def documents(s,cells,couplings,examples,tests,out,source):
    p=s['plan'];v=s['validation'];short=p['request_intervals_ns'][0]
    grouped={(g['classical_load'],g['model']):g for g in s['ablation_groups'] if g['request_interval_ns']==short}
    baseline=cells[0]['baseline_latency_ns']/1000
    total_tests=sum(t['tests'] for t in tests.values())
    lines=['# QuCl — 20/10 ms memory 재평가: Fig. 3–5','',
        '**새 문헌의 gate 시간 + 기존 T1=20 ms·T2=10 ms로 모두 새로 실행했다.**',
        '이전 T1=10 h·T2=1 s 결과는 [evaluation-long-memory](../evaluation-long-memory/RESULTS.md)에 보존했다.','',
        '## 설정과 출처','',
        '| 항목 | 설정 | 근거 |','|---|---|---|',
        '| CNOT / H / 측정 | 20 μs / 5 ns / 3.7 μs | Liao Table 3; Iqbal Table 3 |',
        '| X / Z | 각각 5 ns | Iqbal Table 3 |',
        '| Memory T1 / T2 | **20 ms / 10 ms** | Bugalho Fig. 3a의 사용 선례; 모든 memory에 균일 적용은 QuCl 가정 |',
        '| Gate depolarization | p=0.01 유지 | Iqbal Section 4; 각 operand에 독립 적용 |',
        '| BSM / correction | 27.405 μs / 10 ns | 직렬 회로와 고정 correction slot의 합 |',
        '| 시작 간격 | 13.703 / 27.405 / 54.810 μs | BSM 실행시간 기준 0.5× / 1× / 2× 간격 |',
        '| Background load | 0 / 0.25 / 0.50 / 0.75 | R→B, 100 Mb/s, 100 μs/hop |','',
        '문헌: [Liao 2022](https://doi.org/10.1038/s41598-022-08901-x), '
        '[Iqbal 2023](https://doi.org/10.3390/s23187891), '
        '[Bugalho 2023](https://doi.org/10.1038/s41534-023-00773-x). '
        '각 항목의 출처가 있는 **조합형 추상 모델**이며 한 장비의 재현이 아니다. '
        'Gate noise의 적용 위치, ideal source/readout, lossless/noiseless quantum transit은 [evaluation.tex](evaluation.tex)에 명시했다.','',
        '**0.5×·1×·2×는 workflow 시작 간격**이다. 기준 BSM 실행시간은 27.405 μs이고, '
        '모든 workflow에서 BSM은 온전히 실행된다. 0.5× 간격에서 R 대기가 생기며, '
        '이 실험의 1×·2× 간격에서는 R 대기가 없다.','',
        '입력과 EPR 생성은 t=0, quantum delivery는 0.8/1.2 ms, 첫 시작은 2 ms다. '
        '모든 입력 상태마다 별도 4-session batch를 실행했다. '
        '따라서 여섯 입력 때문에 하나의 batch에 24개 session을 넣거나 contention을 바꾸지 않았다. '
        '입력 qubit은 t=0부터 memory에 있고, 전송 중인 EPR half는 quantum channel 모델을 따른다.','',
        '## 새 실행 및 검증','',
        f'- {s["paired_cases"]}개 workload 조건 × 6개 입력 = **{s["chain_runs"]} chain runs / {s["chain_transactions"]} transactions**.',
        f'- Swapping Full/No-Dq-R/Fixed-Dc를 모두 재실행: 모델별 **{s["transactions_per_ablation_model"]} transactions**.',
        f'- 합계 **{s["evaluation_runs"]} evaluation runs**, 별도 calibration **{s["calibration_runs"]} runs**.',
        f'- Noiseless **{v["noiseless_transactions"]} chains**, 6개 입력 × 16개 joint branch; noisy 추가 **{v["noisy_runs"]} runs**.',
        f'- 최대 density-matrix error **{s["max_density_matrix_error"]:.2e}**; 회귀 **{total_tests}개 항목 검증 완료**.',
        '- 전체 회귀의 최초 2개 보존 검사는 이전 문서에 추가된 안내 링크 때문에 실패했다. 보존 문서를 원복하고 두 검사를 재실행해 통과했다. 원본 실패 로그와 재검사 로그를 provenance에 함께 기록했다.',
        '- 여섯 입력 사이의 latency/decomposition 동일성, 실제 swapped-pair handoff, native Q2NS state/qubit=0, packet drop=0을 검사했다.','',
        '### Fidelity API 통일','',
        'Co-simulation과 두 reference 모두 **NetSquid `qapi.fidelity(..., squared=True)`**를 사용한다. '
        '기존 보고서의 최종 density matrix를 native API에 입력해 모든 평가 분기의 fidelity를 다시 계산하고 Fig. 4의 집계를 갱신했다. '
        '이는 저장된 상태의 metric 재계산이며 network/quantum evolution을 새로 실행한 것은 아니다. '
        '원본 시각·상태·보고서와 생성 당시의 source hash는 보존했다.','',
        f'- Native API로 대조한 출력 상태 **{s["_native_fidelity"]["counts"]["output_states"]:,}개**; 최대 차이 **{s["_native_fidelity"]["max_fidelity_difference"]:.2e}**.',
        f'- Native API 변경 후 평가 회귀 **{tests["experiments"]["tests"]}개 PASS**. 물리 모델·실행 코드는 fidelity API 호출 두 곳 외에는 바뀌지 않았다.',
        '- [Native metric 검증 및 분기별 값](data/native-fidelity-audit.json)에 변경 전후 해시와 계산 결과를 기록했다.','',
        '## Fig. 3 — Swap→Teleport 완료시간','',
        '![Fig. 3](figures/fig3_chain_latency.png)','',
        f'공통 무부하·비경합 기준 **{baseline:.3f} μs**를 뺀 추가 완료시간이다. '
        '측정 구간은 local session start부터 최종 Bob output usable까지다. 아래 표는 절대 latency다.','',
        '| Background load | 0.5× 간격 (μs) | 1× 간격 (μs) | 2× 간격 (μs) |','|---:|---:|---:|---:|']
    for load in p['classical_loads']:
        own=[next(c for c in cells if c['load']==load and c['interval_ns']==i) for i in p['request_intervals_ns']]
        lines.append('| {:.2f} | {} |'.format(load,' | '.join(f'{c["latency_ns"]/1000:.3f}' for c in own)))
    lines += ['', '0.5× 간격과 1× 간격에서는 R의 직렬 완료 일정이 같다. 평균 latency 차이 20.553 μs는 요청 시작시점과 FIFO 대기 차이다. '
        '뒤쪽 packet 생성시각을 실제로 바꾸는 개입은 Fig. 5의 No-R 비교다.','',
        '## Fig. 4 — 최종 Teleportation 충실도','',
        '![Fig. 4](figures/fig4_teleport_fidelity.png)','',
        '**Bob의 출력 상태와 최초 입력 상태의 squared fidelity**를 평가했다. '
        '각 `0, 1, +, −, +i, −i` 입력에서 16개 joint branch를 확률 가중하고, '
        '여섯 상태와 네 session을 phase 안에서 동일 가중 평균했다. '
        '그래프는 절대 fidelity이며 세 조건의 차이를 읽을 수 있도록 Y축 범위를 명시적으로 확대했다.','',
        '| Background load | 0.5× 간격 | 1× 간격 | 2× 간격 |','|---:|---:|---:|---:|']
    for load in p['classical_loads']:
        own=[next(c for c in cells if c['load']==load and c['interval_ns']==i) for i in p['request_intervals_ns']]
        lines.append('| {:.2f} | {} |'.format(load,' | '.join(f'{c["expected_fidelity"]:.6f}' for c in own)))
    age_cases=[next(c for c in cells if c['load']==0 and c['interval_ns']==i) for i in p['request_intervals_ns'][1:]]
    lines += ['', '**동일 latency에서도 fidelity는 다를 수 있다.** 무부하의 1×·2× 간격 조건은 모두 '
        f'평균 latency {age_cases[0]["latency_ns"]/1000:.3f} μs지만, 평균 fidelity는 각각 '
        f'{age_cases[0]["expected_fidelity"]:.6f}, {age_cases[1]["expected_fidelity"]:.6f}다. '
        '모든 자원을 t=0에 만들기 때문에 2× 간격 조건의 뒤쪽 session은 시작 전에 이미 더 오래 저장된 상태를 사용한다. '
        '요청 이후 latency만으로 최종 quantum quality를 판단할 수 없다는 예다.']
    lines += ['', '0.5× 간격과 1× 간격은 절대 완료 일정과 자원 생성시각이 같아 fidelity도 수치 오차 내에서 같다. '
        '간격을 늘리면 queue wait와 t=0 이후의 자원 저장시간이 함께 달라진다. '
        '따라서 이 그림에서 간격 간 차이를 quantum queue만의 효과로 해석하지 않는다. '
        '부하 비교는 같은 간격에서 수행한다. 입력별 결과와 95% CI는 CSV에 보존했다.','',
        '## Fig. 5 — 단순화 모델 예측 오차','',
        '![Fig. 5](figures/fig5_model_error.png)','',
        '**Swapping 구간의 paired ablation**이다. 전체 Swap→Teleport chain 모델 비교와 구분한다. '
        '간격은 13.703 μs다. No-Dq-R은 R capacity만 제거하고 변경된 시각에 실제 packet을 다시 생성한다. '
        'Fixed-Dc는 별도 calibration 평균 result delay와 quantum FIFO를 사용한다. '
        'Decoupled는 No-R result delay와 독립 FIFO wait를 합성하며 fidelity는 정의하지 않는다.','',
        '| Load | No R contention MAE (μs) | Fixed-Dc MAE (μs) | Decoupled MAE (μs) |','|---:|---:|---:|---:|']
    for load in p['classical_loads']:
        lines.append('| {:.2f} | {} |'.format(load,' | '.join(interval_text(grouped[load,m]['latency_mae_ns'],1000) for m in MODELS)))
    lines += ['', '### Swapping Bell-state fidelity bias (model − Full Sync)','',
              '| Load | No R contention | Fixed-Dc |','|---:|---:|---:|']
    for load in p['classical_loads']:
        lines.append('| {:.2f} | {} |'.format(load,' | '.join(interval_text(grouped[load,m]['expected_fidelity_bias'],digits=6) for m in MODELS[:2])))
    if examples:
        e=examples[0]
        lines += ['', f'실제 trace 예: load={e["load"]}, phase seed={int(e["traffic_seed"])}, session={int(e["session_id"])}에서 '
            f'R 대기 {e["R_wait_ns"]/1000:.3f} μs를 제거해도 result 전달 지연이 {e["delta_result_ns"]/1000:.3f} μs 증가해 '
            f'latency는 {e["full_latency_ns"]/1000:.3f} μs로 같다. 평균 효과가 아니라 인과관계를 보여주는 사례다.']
    noise_by_delay={delay:[x for x in v['noisy_cases'] if x['access_delay_ns']==delay] for delay in (100000,500000)}
    noise_means={delay:sum(x['expected_fidelity'] for x in values)/len(values) for delay,values in noise_by_delay.items()}
    lines += ['', '### 별도 memory-aging 검증','',
        '단일 chain의 A–R propagation만 100→500 μs로 바꾼 6입력 검증에서 '
        f'최종 평균 fidelity는 **{noise_means[100000]:.6f} → {noise_means[500000]:.6f}**였다. '
        '완료시간은 576.110→1376.110 μs다. Readiness와 teleport result가 각각 A–R을 지나 추가 시간은 800 μs이며, '
        '두 조건의 state는 모두 독립 reference와 일치한다. 이는 별도 지연 개입 검증이며 Fig. 4의 load sweep 데이터와 섞지 않는다.',
        '', '## 통계와 해석 범위','',
        '- Loaded cell마다 독립 traffic phase 16개. 무부하 phase는 의미가 없어 1회이며 CI를 그리지 않는다.',
        '- 여섯 입력과 네 session을 phase 안에서 평균한 뒤 phase를 10,000회 bootstrap했다. 입력 6개를 독립 traffic 표본으로 세지 않는다.',
        '- Fidelity는 joint branch 확률 가중 기대값이다. Quantum seed 반복 평균이 아니다.',
        '- Calibration phase 4개/loaded condition은 test와 분리했다. CI는 고정된 calibration에 조건부다.',
        '- T1/T2 변경으로 시간 차이가 커졌다고 주장하지 않는다. 고정 duration/고정 packet size 구조에서 memory는 state만 바꿀 수 있다.',
        '- Fmin=0.5, deadline=5 ms는 감사용 기준으로 유지했다. Fidelity가 더 낮다고 곧바로 service failure 주장으로 바꾸지 않는다.',
        '- 유한 4-session batch·고정 topology·균일 memory의 결과이며 단일 장비 calibration이나 정상상태 성능 결과가 아니다.',
        '',f'원본: [새 summary](../../results/{source.name}/summary.json). '
        '입력별 원시값과 집계값: [data/](data/). 재현 방법: [README](README.md).']
    (out/'RESULTS.md').write_text('\n'.join(lines)+'\n')
    preserve_manuscript(out)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source',type=Path,default=MODULE/'results/memory-evaluation-v1')
    parser.add_argument('--output',type=Path,default=MODULE/'paper/evaluation')
    args=parser.parse_args();source=args.source.resolve();out=args.output.resolve()
    s,rows,cells,couplings,examples,count=audit(source)
    tests=dict(regression=regression_result(),
               experiments=test_result(MODULE/'results/native-fidelity-experiment-tests.log'))
    if out.exists() and not (out/'MEMORY-PROFILE').exists():
        require((out/'LITERATURE-PROFILE').exists(),'Expected previous literature package')
        archive=out.with_name(out.name+'-long-memory')
        require(not archive.exists(),'Archive exists; choose a new output')
        out.rename(archive);out.mkdir(parents=True)
        shutil.copy2(archive/'references.bib',out/'references.bib')
    else:out.mkdir(parents=True,exist_ok=True)
    bib=out/'references.bib'
    require(bib.exists(),'Verified literature bibliography missing')
    if 'bugalho2023resource' not in bib.read_text():
        with bib.open('a') as f:
            f.write('''
@article{bugalho2023resource,
  author = {Bugalho, Lu{\\'i}s and Cruzeiro, Emmanuel Zambrini and Chen, Kevin C. and Dai, Wenhan and Englund, Dirk and Omar, Yasser},
  title = {Resource-efficient simulation of noisy quantum circuits and application to network-enabled QRAM optimization},
  journal = {npj Quantum Information},
  volume = {9},
  pages = {105},
  year = {2023},
  doi = {10.1038/s41534-023-00773-x},
  url = {https://doi.org/10.1038/s41534-023-00773-x}
}
''')
    for directory in ['data','figures']:(out/directory).mkdir(exist_ok=True)
    (out/'MEMORY-PROFILE').write_text(s['profile']+'\n')
    write_csv(out/'data/chain_cells.csv',cells)
    write_csv(out/'data/result_phase_coupling.csv',couplings)
    write_csv(out/'data/six_state_noise.csv',s['validation']['noisy_cases'])
    input_cells=[]
    for c in cells:
        for state in s['plan']['input_states']:
            own=[r for r in rows if r['classical_load']==c['load'] and r['request_interval_ns']==c['interval_ns'] and r['input_state']==state]
            e=estimate(own,'expected_fidelity',s['plan']['bootstrap_samples']);ci=e['ci95_cluster_bootstrap'] or [None,None]
            input_cells.append(dict(load=c['load'],interval_ns=c['interval_ns'],input_state=state,
                expected_fidelity=e['mean'],ci_low=ci[0],ci_high=ci[1],traffic_phases=e['traffic_clusters']))
    write_csv(out/'data/fidelity_by_input.csv',input_cells)
    ablation=[]
    for g in s['ablation_groups']:
        e=g['latency_mae_ns'];ci=e['ci95_cluster_bootstrap'] or [None,None]
        b=g['expected_fidelity_bias'];bc=(b['ci95_cluster_bootstrap'] or [None,None]) if b else [None,None]
        ablation.append(dict(load=g['classical_load'],interval_us=g['request_interval_ns']/1000,model=g['model'],
            latency_mae_us=e['mean']/1000,latency_ci_low_us=None if ci[0] is None else ci[0]/1000,
            latency_ci_high_us=None if ci[1] is None else ci[1]/1000,
            fidelity_bias=None if b is None else b['mean'],fidelity_ci_low=bc[0],fidelity_ci_high=bc[1]))
    write_csv(out/'data/ablation_cells.csv',ablation)
    for filename in ['chains.csv','errors.csv','calibration.json','plan.json']:
        shutil.copy2(source/filename,out/'data'/filename)
    # Preserve source CSVs. The figure artifact receives the native-API means.
    native_rows={(r['classical_load'],r['request_interval_ns'],r['traffic_seed'],r['chain_id'],r['input_state']):
                 r['expected_fidelity'] for r in rows}
    with (source/'chains.csv').open() as f:export_rows=list(csv.DictReader(f))
    for r in export_rows:
        r['expected_fidelity']=native_rows[(float(r['classical_load']),int(r['request_interval_ns']),
            int(r['traffic_seed']),int(r['chain_id']),r['input_state'])]
    write_csv(out/'data/chains.csv',export_rows)
    write_csv(out/'data/errors.csv',s['_native_errors'])
    shutil.copy2(source/'native-fidelity-audit.json',out/'data/native-fidelity-audit.json')
    plots(s,cells,out);documents(s,cells,couplings,examples,tests,out,source)
    (out/'README.md').write_text('''# QuCl Figures 3–5: literature gates and 20/10-ms memory

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
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_memory_evaluation.py \\
  contrib/cosim/scenarios/memory-evaluation.json \\
  --output-dir contrib/cosim/results/memory-evaluation-new
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/tests -p 'test_*.py' -v
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/experiments/tests -p 'test_*.py' -v
/home/ns3/qunet/bin/python contrib/cosim/tools/audit_native_fidelity.py \\
  --source contrib/cosim/results/memory-evaluation-new
/tmp/qucl-native-plot-env/bin/python contrib/cosim/tools/render_memory_evaluation.py \\
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
''')
    prov=dict(profile=s['profile'],run=str(source.relative_to(MODULE)),
        run_summary_sha256=digest(source/'summary.json'),plan_sha256=digest(source/'plan.json'),
        raw_reports_audited=count,source_hashes_unchanged=not s['_native_fidelity']['source_changes'],
        state_evolution_sources_unchanged=True,tests=tests,
        native_fidelity_recomputation={k:v for k,v in s['_native_fidelity'].items() if k!='values'},
        renderer=str(Path(__file__).relative_to(MODULE)),renderer_sha256=digest(Path(__file__)),
        figures=['fig3_chain_latency','fig4_teleport_fidelity','fig5_model_error'],
        latex_compiled=False,manuscript_mode='author-maintained; inline tables',
        scope=s['scope'],resumption=s['resumption'])
    parallel=source/'parallel-provenance.json'
    if parallel.exists():
        prov['parallel_execution']=read(parallel)
        require(digest(MODULE/prov['parallel_execution']['orchestrator'])==
                prov['parallel_execution']['orchestrator_sha256'],'Parallel orchestrator changed')
        for entry in prov['parallel_execution'].get('invocations',[]):
            script=source/entry['source_archive'] if 'source_archive' in entry else MODULE/entry['orchestrator']
            require(digest(script)==entry['orchestrator_sha256'],'Historical orchestration source mismatch')
    prov['simulation_environment']=json.loads(subprocess.check_output([
        '/home/ns3/qunet/bin/python','-c',
        'import json,sys,netsquid,numpy; print(json.dumps(dict(python=sys.version, executable=sys.executable, netsquid=netsquid.__version__, numpy=numpy.__version__)))'],text=True))
    prov['render_environment']=dict(python=sys.version,matplotlib=matplotlib.__version__,numpy=np.__version__)
    binary_dir=MODULE.parents[1]/'build/contrib/cosim/examples'
    prov['participant_sha256']={str(f.relative_to(MODULE.parents[1])):digest(f)
        for f in [binary_dir/'ns3.47-cosim-chained-default',binary_dir/'ns3.47-cosim-provisioned-default']}
    prov['generated_sha256']={str(f.relative_to(out)):digest(f) for f in out.rglob('*') if f.is_file() and f.name!='provenance.json'}
    (out/'provenance.json').write_text(json.dumps(prov,indent=2,sort_keys=True)+'\n')
    target=MODULE/'paper/qucl-evaluation-figures.zip'
    archive=target.with_name('qucl-evaluation-long-memory.zip')
    if target.exists() and not archive.exists():target.rename(archive)
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for f in sorted(out.rglob('*')):
            if f.is_file():z.write(f,'evaluation/'+str(f.relative_to(out)))
    print(json.dumps(dict(profile=s['profile'],raw_reports_audited=count,figures=prov['figures'],tests=tests),indent=2))


if __name__=='__main__':main()
