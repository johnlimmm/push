# QuCl paper — native timed execution 평가

현재 논문용 실행 기준은 **native-timed-v3**다. A/R/B에서 session이 R에 직접 도착하고,
NetSquid의 실제 `QuantumProgram` 완료가 Q2NS R→B result packet 생성을 구동한다.
Full Sync, No-Dq-R, Fixed-Dc 모두 같은 timed gate chain과 idle/active T1/T2를 사용한다.

## 실험 계획

- [P5-B 확대 계획](scenarios/native-p5b-paper-expanded.json): 기존과 같은 384 paired cases,
  1,152 model executions + calibration 6회. 모델별 1,536 transactions.
- Test traffic seeds 1000–1031, calibration 100/101, quantum seeds 7/11을 유지한다.
  Loads 0/0.35/0.7, request intervals 0.8/2 ms, F_min=0.5, deadline=5 ms를 유지한다.
- [비용 측정 계획](scenarios/native-paper-validation.json): 1/4/8/16/32/64 sessions × load 0/0.7,
  각 cell warmup 1회 + 10회 반복. 총 12 warmups와 120 measured runs.
- P5-B는 Swap이며 B wait=0을 요구한다. 비용 측정은 Swap/Teleport 교대이며 B FIFO도 검증한다.
- CNOT/H/M0/M1은 0.6/0.2/0.4/0.4 ms. Correction X/I와 Z/I 슬롯은 P5-B에서 각 25 μs,
  비용 측정에서 각 250 μs다. 합계 시간과 workload는 atomic v2와 맞추되 quantum state는 다시 계산한다.
- P5-B CI는 traffic-seed cluster bootstrap, 비용 CI는 같은 workload의 runtime 반복 bootstrap이다.
  둘 모두 95% percentile interval이며 비용 측정은 다른 실험이 끝난 뒤 단독으로 수행한다.

## 현재 산출물

- [수치·95% CI 표](paper/RESULTS.md), [요약·입력 해시](paper/results-summary.json)
- [Fig. 4 latency MAE](paper/figures/fig4-latency-mae.pdf),
  [Fig. 5 expected-fidelity bias](paper/figures/fig5-expected-fidelity.pdf),
  [Fig. 6 contention control](paper/figures/fig6-mechanism-control.pdf),
  [Fig. 7 native timing / cost](paper/figures/fig7-timing-cost.pdf)
- [설정·지표 LaTeX](paper/setup-and-metrics.tex), [VI-D 교체문](paper/abstraction-results-insert.tex),
  [VI-E 교체문](paper/validation-insert.tex), [원고 수정 메모](paper/REVISION-NOTES.md)
- [Native correctness](paper/NATIVE-VALIDATION.md), [전체 회귀](results/native-timed/regression-summary.json)
- [Pilot](results/native-p5b-pilot/summary.json), [Expanded](results/native-p5b-expanded/summary.json),
  [비용 측정](results/native-paper-scaling/summary.json), [실제 timing](results/native-paper-scaling/timing.json)

`/home/ns3/QuCl.pdf`의 전체 `.tex/.bib` 원본은 workspace에서 찾지 못했다.
원본 PDF는 유지하고, 반영할 문장·표·그림·LaTeX를 갱신한다. 최종 PDF의 참고문헌,
figure 번호와 page budget은 원본 manuscript 소스에서 반영·확인해야 한다.

## 재실행

ns-3 루트에서 NetSquid 환경의 Python으로 실행한다. 완료된 출력 경로는 다시 사용하지 않는다.
기존 `run_p5b.py`/`paper_scaling.py`는 atomic 재현용이다.

```bash
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_native_timed.py

/home/ns3/qunet/bin/python contrib/cosim/experiments/run_native_p5b.py \
  contrib/cosim/scenarios/native-p5b-paper-expanded.json \
  --output-dir contrib/cosim/results/native-expanded-new

# 다른 실험이 끝난 뒤 단독 실행
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_native_paper.py \
  --output-dir contrib/cosim/results/native-scaling-new

# matplotlib 3.8.4 / NumPy 1.26.4 별도 plotting 환경
/tmp/qucl-native-plot-env/bin/python contrib/cosim/experiments/render_native_paper_results.py \
  --timing contrib/cosim/results/native-scaling-new/timing.json \
  --scaling contrib/cosim/results/native-scaling-new/summary.json \
  --expanded contrib/cosim/results/native-expanded-new/summary.json \
  --manuscript /home/ns3/QuCl.pdf --output-dir contrib/cosim/paper
```

## 측정·해석의 범위

Native circuit의 start/completion/wait를 독립 analytic FIFO와 대조한다. 각 모델의
중간 gate와 checkpoint state는 별도로 구현한 native NetSquid circuit과 비교한다.
이전 atomic scheduler의 120 synthetic workloads/2,500 requests는 과거 증거로 보존하며
새 native 평가의 표본 수에 더하지 않는다. 장비 parameter를 검증하는 실험은 아니다.

비용에는 core/state 초기화, ns-3 시작·설정, native federation, **모든 instruction state probe**,
기존 로그·snapshot, traffic drain과 종료를 포함한다. Python import/build/config normalization,
사후 reference 검증과 파일 쓰기는 제외한다. IPC만 분리한 overhead나 노드 수 scalability가 아니다.

No-Dq-R은 session별 R 실행 엔진으로 동시성을 늘리되 qubit state를 복제하지 않는다.
Fixed-Dc는 가상 result 도착 이벤트를 쓴다. 두 근사를 Full Sync와 같은 native 물리 모델에서 비교한다.
Decoupled는 latency/deadline만 예측하며 fidelity/service feasibility는 정의하지 않는다.

Bootstrap CI는 calibration 두 seed를 고정하고 periodic background phase family에 조건화한다.
같은 quantum seed가 모델 간 같은 branch를 보장하지 않는다. 무부하의 zero-width CI나 오판 0건은
모집단 확률을 확정하지 않는다. 관측 fidelity와 branch 확률 가중 E[F], deadline-only와 service 오판을 구분한다.

## 과거 결과 보존

- [Atomic v2 논문 산출물](baselines/atomic-v2-paper.tar.gz) · [파일별 해시](baselines/atomic-v2-paper.json)
- [Atomic v2 실행 원자료](baselines/direct-start-v2-results.tar.gz) · [manifest](baselines/direct-start-v2-results.json)
- [Native 이전 source 기준점](baselines/native-timed-parent.json)

Native 전체 원자료는 [압축본](baselines/native-timed-v3-results.tar.gz)과
[파일별 SHA-256 manifest](baselines/native-timed-v3-results.json)에 보존한다.
모든 entry를 다시 읽어 원본 파일과 byte 단위로 일치하는지 확인했다.
새 checkout에서 결과를 복원하려면 다음 명령을 사용한다.

```bash
sha256sum -c contrib/cosim/baselines/native-timed-v3-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/native-timed-v3-results.tar.gz
```

예전 raw data를 복원하려면 ns-3 루트에서 아래 명령을 쓴다. 현재 paper 파일 위에
atomic paper archive를 풀지 않는다. 별도 디렉터리에서 열어 비교한다.

```bash
sha256sum -c contrib/cosim/baselines/direct-start-v2-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/direct-start-v2-results.tar.gz
```
