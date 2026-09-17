"""모델 비교: 확률 가중 fidelity와 표본 판정 오차를 분리한다."""
import random
from collections import defaultdict


def model_rows(report, fmin, deadline):
    rows=[]
    for metric in report['metrics']['sessions']:
        sid=str(metric['session_id']); row=dict(metric)
        ref=report['cross_validation']['sessions'][sid]['reference']
        row['expected_fidelity']=ref['ensemble']['fidelity']
        row['deadline_ok']=row['transaction_latency_ns']<=deadline
        row['feasible']=row['deadline_ok'] and row['usable_fidelity']>=fmin
        row['success_probability']=sum(b['probability'] for b in ref['branches'].values()
            if b['probability']>0 and b['usable']['fidelity']>=fmin) if row['deadline_ok'] else 0.0
        row['measurement_bits']=report['snapshot']['sessions'][sid]['correction']['measurement_bits']
        rows.append(row)
    return rows


def compare(full, predicted, metadata, deadline):
    truth={r['session_id']:r for r in full}; result=[]
    for row in predicted:
        base=truth[row['session_id']]; actual=row['usable_fidelity'] is not None
        deadline_ok=row['transaction_latency_ns']<=deadline
        result.append(dict(metadata,session_id=row['session_id'],
            delta_latency_ns=row['transaction_latency_ns']-base['transaction_latency_ns'],
            delta_fidelity=row['usable_fidelity']-base['usable_fidelity'] if actual else None,
            delta_expected_fidelity=row['expected_fidelity']-base['expected_fidelity'] if actual else None,
            delta_success_probability=row['success_probability']-base['success_probability'] if actual else None,
            false_feasible=int(row['feasible'] and not base['feasible']) if actual else None,
            false_infeasible=int(not row['feasible'] and base['feasible']) if actual else None,
            false_deadline_feasible=int(deadline_ok and not base['deadline_ok']),
            false_deadline_infeasible=int(not deadline_ok and base['deadline_ok'])))
    return result


def estimate(rows, field, bootstrap_samples, absolute=False):
    # 같은 traffic seed의 session/quantum 반복은 하나의 cluster로 평균낸다.
    # seed를 여러 번 돌렸다고 독립 workload 표본수가 증가했다고 세지 않는다.
    clusters=defaultdict(list)
    for row in rows:
        if row[field] is not None:
            clusters[row['traffic_seed']].append(abs(row[field]) if absolute else row[field])
    if not clusters:return None
    means=[sum(v)/len(v) for _,v in sorted(clusters.items())]
    mean=sum(means)/len(means)
    interval=None
    if len(means)>=2:
        rng=random.Random(7301)
        samples=sorted(sum(rng.choice(means) for _ in means)/len(means) for _ in range(bootstrap_samples))
        interval=[samples[int(.025*(len(samples)-1))],samples[int(.975*(len(samples)-1))]]
    return dict(mean=mean,traffic_clusters=len(means),ci95_cluster_bootstrap=interval)


def summarize(errors, samples):
    grouped=defaultdict(list)
    for row in errors:grouped[(row['classical_load'],row['request_interval_ns'],row['model'])].append(row)
    output=[]
    for (load,spacing,model),rows in sorted(grouped.items()):
        output.append(dict(classical_load=load,request_interval_ns=spacing,model=model,transactions=len(rows),
            latency_bias_ns=estimate(rows,'delta_latency_ns',samples),
            latency_mae_ns=estimate(rows,'delta_latency_ns',samples,True),
            fidelity_bias=estimate(rows,'delta_fidelity',samples),
            expected_fidelity_bias=estimate(rows,'delta_expected_fidelity',samples),
            expected_fidelity_mae=estimate(rows,'delta_expected_fidelity',samples,True),
            success_probability_mae=estimate(rows,'delta_success_probability',samples,True),
            false_feasible_rate=estimate(rows,'false_feasible',samples),
            false_infeasible_rate=estimate(rows,'false_infeasible',samples),
            false_deadline_feasible_rate=estimate(rows,'false_deadline_feasible',samples),
            false_deadline_infeasible_rate=estimate(rows,'false_deadline_infeasible',samples)))
    return output
