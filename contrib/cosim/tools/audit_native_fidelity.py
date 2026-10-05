#!/usr/bin/env python3
"""Recompute saved reference output fidelities with NetSquid's public API.

This is metric recomputation from preserved NetSquid density matrices, not a
new physical/network simulation. Original reports and their provenance remain
unchanged. Only the two explicit fidelity-expression substitutions are allowed
relative to the generating sources; timing/state evolution must be identical.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import numpy as np
import netsquid as ns
from netsquid.qubits import qubitapi as qapi

MODULE=Path(__file__).resolve().parents[1]
REPLACEMENTS={
    'experiments/literature_reference_chained.py':(
        "float(np.real(ref.conj()@dm@ref))", "float(qapi.fidelity(qs,ref,squared=True))"),
    'experiments/literature_reference_provisioned.py':(
        "float(np.real(ref.conj()@rho@ref))", "float(qapi.fidelity(qubits,ref,squared=True))")}
STATES={'0':[1,0],'1':[0,1],'+':[1,1],'-':[1,-1],'+i':[1,1j],'-i':[1,-1j]}


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def read(path):
    with (gzip.open(path,'rt') if path.suffix=='.gz' else path.open()) as f:return json.load(f)


def source_changes(summary):
    changes={}
    for name,expected in summary['source_sha256'].items():
        path=MODULE/name;current=sha(path)
        if current==expected:continue
        if name not in REPLACEMENTS:raise ValueError('Unrelated execution source changed: '+name)
        old,new=REPLACEMENTS[name];text=path.read_text()
        if text.count(new)!=1 or hashlib.sha256(text.replace(new,old).encode()).hexdigest()!=expected:
            raise ValueError('Change exceeds the native fidelity substitution: '+name)
        changes[name]=dict(before=expected,after=current,old_expression=old,new_expression=new)
    for name,(_,new) in REPLACEMENTS.items():
        if (MODULE/name).read_text().count(new)!=1:
            raise ValueError('Both reference calculators must use the native API')
    return changes


def run(source):
    summary=read(source/'summary.json');changes=source_changes(summary)
    ns.sim_reset();ns.set_qstate_formalism(ns.QFormalism.DM)
    scratch={1:qapi.create_qubits(1),2:qapi.create_qubits(2)}
    counts=dict(reports=0,output_states=0,branch_expectations=0)
    largest=0.;largest_mean=0.;values={}
    def fidelity(state,target):
        nonlocal largest
        dm=state['density_matrix'];rho=np.array(dm['real'])+1j*np.array(dm['imag'])
        qubits=scratch[len(dm['qubit_order'])]
        qapi.assign_qstate(qubits,rho)
        value=float(qapi.fidelity(qubits,target,squared=True))
        error=abs(value-state['fidelity'])
        if not np.isfinite(value) or error>1e-12:raise ValueError('Native fidelity disagreement: '+str(error))
        counts['output_states']+=1;largest=max(largest,error)
        return value
    def target(state):
        v=np.array(STATES[state],complex);return v/np.linalg.norm(v)
    bell=np.array([1,0,0,1],complex)/np.sqrt(2)
    for rel,digest in sorted(summary['report_sha256'].items()):
        path=source/rel
        if sha(path)!=digest:raise ValueError('Original report changed: '+rel)
        report=read(path);counts['reports']+=1
        cv=report.get('cross_validation')
        if cv is None:continue
        own={}
        chained='chains' in cv
        entries=cv['chains'] if chained else cv['sessions']
        for sid,entry in entries.items():
            ref=entry['reference']
            if chained:
                state=next(c['input_state'] for c in report['config']['chains'] if str(c['chain_id'])==sid)
                goal=target(state)
            else:
                spec=ref['spec'];goal=bell if spec['protocol']=='swap' else target(spec['input_state'])
            branches=ref.get('branches')
            if branches is None:branches={'observed':ref['observed']}
            finals={};mean=0.;weight=0.
            for bits,branch in branches.items():
                if chained:
                    fidelity(branch['stages'][0]['checkpoints']['usable'],bell)
                    value=fidelity(branch['stages'][1]['checkpoints']['usable'],goal)
                else:value=fidelity(branch['checkpoints']['usable'],goal)
                finals[bits]=value;mean+=branch['probability']*value;weight+=branch['probability']
            item=dict(branch_fidelity=finals)
            if 'branches' in ref:
                if abs(weight-1)>1e-12:raise ValueError('Incomplete branch weights')
                original=ref.get('expected_fidelity')
                if original is None:
                    original=sum(b['probability']*b['checkpoints']['usable']['fidelity'] for b in branches.values())
                error=abs(mean-original)
                if error>1e-12:raise ValueError('Native expected fidelity disagreement')
                counts['branch_expectations']+=1;largest_mean=max(largest_mean,error)
                item['expected_fidelity']=mean
            own[sid]=item
        values[rel]=own
        if counts['reports']%100==0:print('Audited {} reports / {} states'.format(counts['reports'],counts['output_states']),flush=True)
    result=dict(passed=True,method='netsquid.qubits.qubitapi.fidelity(qubits, target, squared=True)',
        scope='Metric recomputation on preserved output density matrices; no new network/quantum evolution run.',
        netsquid_version=ns.__version__,run_summary_sha256=sha(source/'summary.json'),
        source_changes=changes,state_evolution_sources_unchanged=True,counts=counts,
        max_fidelity_difference=largest,max_expected_fidelity_difference=largest_mean,
        values=values,tool=str(Path(__file__).resolve().relative_to(MODULE)),tool_sha256=sha(Path(__file__)))
    out=source/'native-fidelity-audit.json'
    out.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='values'},indent=2))
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--source',type=Path,default=MODULE/'results/memory-evaluation-v1')
    run(p.parse_args().source.resolve())
