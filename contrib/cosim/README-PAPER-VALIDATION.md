# QuCl paper — timing fidelity, simulation cost, expanded P5-B

Controller 경로를 제거한 **direct-session-start-v2**로 전체 검증·평가를 다시 실행했다.
노드는 A/R/B이며 latency 기준은 R의 local session start다. Classical load는 R→B에만 적용한다. 실험 계획은 실행 전에
[`hybrid-paper-validation.json`](scenarios/hybrid-paper-validation.json)과
[`p5b-paper-expanded.json`](scenarios/p5b-paper-expanded.json)에 고정했다.

## 산출물

현재 실행 원자료: `results/direct-start-timing`, `direct-start-scaling`,
`direct-start-p5b-pilot`, `direct-start-p5b-expanded`. 이전 `paper-*-20260921*`는 이전 구조의 결과다.
[새 전체 검증 요약](results/direct-start-validation-summary.json)을 기준으로 읽는다.

- [원고 교정 메모와 측정 방법](paper/REVISION-NOTES.md)
- [실험 수치·95% CI 표](paper/RESULTS.md)
- [요약 JSON](paper/results-summary.json)
- [VI-E LaTeX 삽입문](paper/validation-insert.tex)
- [VI-A/VI-D 확대 결과 교체문](paper/abstraction-results-insert.tex)
- [VI-A 설정 표·지표 정의](paper/setup-and-metrics.tex)
- [Fig. 4 — latency MAE](paper/figures/fig4-latency-mae.pdf)
- [Fig. 5 — expected-fidelity bias](paper/figures/fig5-expected-fidelity.pdf)
- [Fig. 6 — contention control](paper/figures/fig6-mechanism-control.pdf)
- [Fig. 7 — timing / cost](paper/figures/fig7-timing-cost.pdf)
- [전체 실행시간·round/IPC 비용](paper/figures/simulation-cost-details.pdf)
- [Timing 원자료 CSV](paper/timing.csv), [runtime 반복 원자료 CSV](paper/scaling.csv)

원본 `/home/ns3/QuCl.pdf`는 변경하지 않았다. `.tex/.bib` 원본이 없으므로 기존 PDF에 그림을
억지로 덧붙이거나 참고문헌을 임의로 복원하지 않았다. 삽입문·그림을 원고 소스에 반영한 후
참고문헌, figure 번호와 페이지 수를 다시 확인해야 한다.

## 원자료 복원

Git에는 현재 구조의 검증 요약, 대표 실행, 평가 CSV와 논문 표·그림을 포함한다.
전체 실행 trace와 calibration 원자료는
[압축본](baselines/direct-start-v2-results.tar.gz)에 보존했다.
[manifest](baselines/direct-start-v2-results.json)에 파일별 SHA-256을 기록했다.
새 checkout의 ns-3 루트에서 다음 명령으로 압축본을 확인하고 원래 경로에 복원할 수 있다.

```bash
sha256sum -c contrib/cosim/baselines/direct-start-v2-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/direct-start-v2-results.tar.gz
```

Git에 이미 포함된 파일은 `--skip-old-files`가 보존한다.
압축본은 현재 구조의 재실행 결과만 포함하며, 이전 v1 결과와 구분한다.

## 실행

ns-3 루트에서 실행한다. 변경 후 빌드한 `cosim-hybrid` 바이너리와 NetSquid 1.1.7이 필요하다.
완료 결과를 덮어쓰지 않도록 새로운 출력 경로를 사용한다.

```bash
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/experiments/tests -v

/home/ns3/qunet/bin/python contrib/cosim/experiments/run_paper_validation.py timing \
  --output-dir contrib/cosim/results/paper-timing-new

/home/ns3/qunet/bin/python contrib/cosim/experiments/run_p5b.py \
  contrib/cosim/scenarios/p5b-paper-expanded.json \
  --output-dir contrib/cosim/results/paper-expanded-new

# Runtime benchmark는 위 실험이 끝난 후 단독으로 실행한다.
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_paper_validation.py scaling \
  --output-dir contrib/cosim/results/paper-scaling-new

/home/ns3/qunet/bin/python contrib/cosim/tools/verify_hybrid_v1.py --archive-only
```

전체 회귀는 아래로 실행한다. 과거 P0–P5-A/Q2NS suite와 새 Hybrid/P5-B, timing/계측,
Q2NS native suite를 함께 재실행한다. 과거 archive의 hash 보존과 현재 source 동일성은 구분한다.

```bash
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_direct_start.py
```

그림은 NetSquid와 분리한 Python 환경에서 생성한다. 사용한 plotting dependency는
matplotlib 3.8.4 / NumPy 1.26.4다.

```bash
python3 -m venv /tmp/qucl-paper-plot-env
/tmp/qucl-paper-plot-env/bin/pip install matplotlib==3.8.4 numpy==1.26.4
/tmp/qucl-paper-plot-env/bin/python contrib/cosim/experiments/render_paper_results.py \
  --timing contrib/cosim/results/paper-timing-new/summary.json \
  --scaling contrib/cosim/results/paper-scaling-new/summary.json \
  --expanded contrib/cosim/results/paper-expanded-new/summary.json \
  --output-dir contrib/cosim/paper
```

## 해석의 범위

- Timing은 native **physical instruction 완료 이벤트**와 비교한다. 독립 FIFO의 tie policy는
  명시적으로 맞춘다. 모든 quantum state/noise의 gate-level 동등성이나 장비 duration의 현실성을
  검증하는 실험은 아니다. Production runtime에 native timed QuantumProgram을 도입하지 않는다.
- Cost는 trace logging과 traffic drain을 포함하는 실제 finite-batch 실행 비용이다. Reference
  subprocess/결과 저장 비용은 분리하며, IPC 자체만의 overhead라고 해석하지 않는다.
- Scaling은 고정 topology에서 session 수를 늘린다. 64 sessions를 64 nodes로 표현하지 않는다.
- P5-B는 32개 독립 background phase seed를 사용한다. Quantum 반복·세션은 cluster 안에서
  평균낸다. Calibration/test 분리와 F_min/deadline을 유지하며 feasibility 결과를 선택적으로 숨기지 않는다.
- Bootstrap CI는 사전에 고정한 workload family와 calibration에 조건화되어 있다. 결과가 0인
  metric의 degenerate empirical CI를 일반적인 error probability=0의 증거로 쓰지 않는다.

## 구현 파일

- `experiments/paper_timing.py`: native dispatcher, production core fixture, 실제 trace 재생.
- `experiments/paper_scaling.py`: 같은 HybridFederation/Core/adapter를 사용한 구간별 계측과 검증.
- `experiments/run_paper_validation.py`: 과거 archive 검사, 현재 구조의 실험 실행, provenance.
- `experiments/render_paper_results.py`: PDF/PNG 그림, CSV, 수치 표 및 VI-E 삽입문.
- `experiments/tests/test_paper_validation.py`: 1 ns 오류·FIFO 순서 오류 검출, identity duration,
  동시 도착 정책, 계측 runner와 production report 동등성.

큰 raw trace는 `results/`에 있고, `paper/`의 표·그림·요약은 원본 summary hash를 기록한다.
