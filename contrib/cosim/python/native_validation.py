"""Native callback provenance, individual gate times/states and independent reference."""
import json
from pathlib import Path
import subprocess
import sys
import numpy as np
from hybrid_validation import require, validate_report as validate_common


def validate_report(report, expected=None, network=True):
    result=validate_common(report, expected, network)
    durations=report['config']['native_instructions']
    keys={'CNOT':'cnot_ns','H':'h_ns','MEASURE_0':'measure_ns','MEASURE_1':'measure_ns',
          'X':'x_ns','IDLE_X':'x_ns','Z':'z_ns','IDLE_Z':'z_ns'}
    for request in report['snapshot']['requests']:
        sid=request['session_id'];op=request['operation']
        own=[r for r in report['native_instructions'] if r['session_id']==sid and r['operation']==op]
        bits=report['snapshot']['sessions'][str(sid)]['measurement_bits']
        names=['CNOT','H','MEASURE_0','MEASURE_1'] if op=='BSM' else [
            'X' if bits[1] else 'IDLE_X','Z' if bits[0] else 'IDLE_Z']
        require([r['instruction'] for r in own]==names,'native instruction sequence')
        previous=request['start_ns']
        for index,r in enumerate(own):
            require(r['index']==index and r['start_ns']==previous,'native instruction ordering')
            require(r['completion_ns']-r['start_ns']==durations[keys[r['instruction']]],'native instruction duration')
            previous=r['completion_ns']
        require(previous==request['completion_ns'],'native operation/program end')
        callbacks=[e for e in report['events'] if e['event_type']==op+'_COMPLETE' and e['session_id']==sid]
        require(len(callbacks)==1 and callbacks[0].get('completion_source')=='netsquid_program_done','native completion source')
    result['checks']+=['native_instruction_chain','native_program_done']
    return result


def cross_validate(report,references=None):
    cache={} if references is None else references;results={}
    for sid,session in report['snapshot']['sessions'].items():
        requests={r['operation']:r for r in report['snapshot']['requests'] if str(r['session_id'])==sid}
        spec=dict(protocol=session['protocol'],input_state=session['input_state'],
            memory_noise=report['config']['memory_noise'],native_instructions=report['config']['native_instructions'],
            bsm_start_ns=requests['BSM']['start_ns'],bsm_completion_ns=requests['BSM']['completion_ns'],
            correction_arrival_ns=requests['CORRECTION']['arrival_ns'],
            correction_start_ns=requests['CORRECTION']['start_ns'],correction_completion_ns=requests['CORRECTION']['completion_ns'])
        key=json.dumps(spec,sort_keys=True)
        if key not in cache:
            proc=subprocess.run([sys.executable,str(Path(__file__).with_name('netsquid_reference_native.py'))],
                input=key,stdout=subprocess.PIPE,stderr=subprocess.PIPE,universal_newlines=True,timeout=40)
            require(proc.returncode==0,'native reference subprocess: '+proc.stderr)
            cache[key]=json.loads(proc.stdout)
        ref=cache[key];require(ref['spec']==spec,'native reference specification')
        probabilities=[v['probability'] for v in ref['branches'].values()]
        require(len(probabilities)==4 and all(np.isfinite(p) and 0<=p<=1+1e-12 for p in probabilities)
                and abs(sum(probabilities)-1)<=1e-12,'native branch probabilities')
        bits=''.join(map(str,session['measurement_bits']));branch=ref['branches'][bits]
        require(branch['probability']>0,'native impossible branch')
        for b in ref['branches'].values():
            require(b['timing']=={k:spec[k] for k in ('bsm_start_ns','bsm_completion_ns','correction_arrival_ns',
                                                     'correction_start_ns','correction_completion_ns')},'native reference timing')
        errors={};ferrors={}
        def compare(label,a,b):
            da,db=a['density_matrix'],b['density_matrix']
            require(a['sim_time_ns']==b['sim_time_ns'] and da['qubit_order']==db['qubit_order'],'native state identity '+label)
            left=np.array(da['real'])+1j*np.array(da['imag']);right=np.array(db['real'])+1j*np.array(db['imag'])
            require(left.shape==right.shape and np.all(np.isfinite(left)) and np.all(np.isfinite(right)),'native state shape')
            error=float(np.max(np.abs(left-right)));errors[label]=error
            require(error<=1e-12,'native reference state '+label)
            if 'fidelity' in a:
                error=abs(a['fidelity']-b['fidelity']);ferrors[label]=error
                require(np.isfinite(error) and error<=1e-12,'native reference fidelity '+label)
        cp=session['checkpoints'];reference=branch['checkpoints']
        for name in reference['bsm_start']:compare('bsm_start.'+name,cp['bsm_start'][name],reference['bsm_start'][name])
        for name in ('frame','packet_arrival','correction_start','usable'):compare(name,cp[name],reference[name])
        actual=[r for r in report['native_instructions'] if str(r['session_id'])==sid]
        require(len(actual)==len(branch['instructions']),'reference instruction count')
        for a,b in zip(actual,branch['instructions']):
            require(all(a[k]==b[k] for k in ('operation','index','instruction','start_ns','completion_ns')),'reference instruction timestamps')
            # Before the first measurement, the state is unconditional. Between
            # measurements, the reference has projected only the observed prefix.
            if report['instruction_state_recording']:
                require(a['state'] is not None,'missing native instruction state')
                compare(a['operation']+'.'+a['instruction'],a['state'],b['state'])
        results[sid]=dict(passed=True,observed_branch=bits,checkpoint_errors=errors,
            max_density_matrix_error=max(errors.values()),max_fidelity_error=max(ferrors.values()),reference=ref)
    return dict(passed=True,sessions=results,max_density_matrix_error=max(v['max_density_matrix_error'] for v in results.values()))
