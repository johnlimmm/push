#!/usr/bin/env python3
"""Publication artifact for actual mixed resource/processor/packet timing."""
import gzip
import json
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

MODULE=Path(__file__).resolve().parents[1]


def main():
    with gzip.open(str(MODULE/'results/provisioned-v4/mixed.json.gz'),'rt') as stream:report=json.load(stream)
    assert report['validation']['passed'] and report['cross_validation']['passed']
    rows=report['metrics']['sessions']
    segments=[('Resource wait','#b9bec6'),('R FIFO wait','#e6ae45'),('Native BSM','#477cb4'),
              ('Result packet','#9571bb'),('B FIFO wait','#dd8047'),('Native correction','#469578')]
    fig,ax=plt.subplots(figsize=(8.1,3.6));labels=[]
    for i,row in enumerate(rows):
        end_bsm=row['bsm_completion_ns'];arrival=end_bsm+row['result_delay_ns']
        boundaries=[row['session_start_ns'],row['eligible_ns'],row['bsm_start_ns'],end_bsm,arrival,
                    row['correction_start_ns'],row['completion_ns']]
        for j,((label,color),a,b) in enumerate(zip(segments,boundaries,boundaries[1:])):
            ax.barh(i,(b-a)/1e6,left=a/1e6,height=.46,color=color,label=label if i==0 else None)
        ax.plot(row['resource_ready_ns']/1e6,i,marker='D',ms=5,mfc='white',mec='black',
                linestyle='none',label='Resources ready' if i==0 else None)
        ax.plot(row['session_start_ns']/1e6,i,marker='|',ms=13,color='black',linestyle='none',
                label='Session start' if i==0 else None)
        protocol=report['snapshot']['sessions'][str(row['session_id'])]['protocol']
        labels.append('S{} {}'.format(row['session_id'],protocol.capitalize()))
    ax.set_yticks(range(len(rows)),labels);ax.invert_yaxis()
    ax.set_xlabel('Simulation time (ms)');ax.set_xlim(left=0)
    ax.set_title('Native quantum delivery → shared execution → actual result packets',fontsize=11)
    ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,-.22),ncol=4,frameon=False,fontsize=8)
    fig.subplots_adjust(left=.15,right=.98,top=.85,bottom=.30)
    dest=MODULE/'paper/figures/fig8-provisioned-mixed'
    fig.savefig(str(dest)+'.pdf',bbox_inches='tight')
    fig.savefig(str(dest)+'.png',dpi=180,bbox_inches='tight')
    print('Rendered actual v4 mixed timeline')


if __name__=='__main__':main()
