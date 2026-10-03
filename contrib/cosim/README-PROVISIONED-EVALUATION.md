# Hybrid v4 — P5-B와 실행 비용 평가

실제 NetSquid quantum-channel 전달과 resource-ready gating을 포함한 v4 평가다.
v3의 구현·평가 수치는 [기존 결과](paper/RESULTS.md)에 보존한다.
새 표·그림·본문 삽입문은 [v4 결과](paper/provisioned-v4/RESULTS.md)에 생성한다.

## 완료 결과

- 전체 회귀 **291개 PASS**: 기존 278개 + 새 evaluation 검증 13개.
- **384 paired cases**, simulation 1,152회 + 별도 calibration 6회, 모델별 1,536 transactions.
- P5-B 독립 reference 대비 최대 density-matrix error **4.44×10⁻¹⁶**.
- 비용 평가 **12 warmups + 120 repetitions PASS**. 비용 평가까지 포함한 최대 상태 오차 **9.99×10⁻¹⁶**.
- 12개 mixed workload의 500 R/B requests에서 ready/FIFO oracle 대비 timing error **0 ns**.
- 64 sessions 평균 실행시간: load 0에서 **2.18 s [1.96, 2.41]**,
  load 0.7에서 **2.81 s [2.36, 3.34]**. 대괄호는 95% 반복 bootstrap interval이다.

요청 간격 0.8 ms에서 Full-Sync 대비 latency MAE는 다음과 같다. 단위는 ms다.

| R→B offered load | Fixed-Dc | No-Dq-R | Decoupled |
|---|---:|---:|---:|
| 0 | 0 | 1.350 | 0 |
| 0.35 | 0.141 | 1.319 | 0.152 |
| 0.7 | 0.261 | 1.334 | 0.244 |

No-Dq-R의 기대 fidelity bias는 각각 **+0.0643 / +0.0623 / +0.0606**이다.
2 ms 간격에서는 R wait가 없고 No-Dq-R/Decoupled latency 오차가 0이다.
Fixed-Dc fidelity bias는 load 0.35에서 양수, 0.7에서 음수여서 모든 단순화가 항상 낙관적이라고 해석하지 않는다.

동일한 F_min/deadline에서 0.8 ms 조건의 No-Dq-R false service-feasible fraction은
**37.5% / 34.8% / 34.8%**였다. 분모는 각 cell의 모든 paired transactions이며,
동일 quantum seed에 기반한 표본 비교다. 통계 범위와 전체 CI는 아래 계약과 결과 문서에 명시한다.

## 사전에 고정한 조건

- EPR/input 생성: t=0. Quantum link R→A 0.8 ms, R→B 1.2 ms.
- Channel depolarization: 0 Hz. Native memory T1=20 ms, T2=10 ms와 timed gate chain은 그대로 유지한다.
- Classical result link: 10 Mb/s, propagation 0.2 ms; Swap payload 80 bytes와 wire overhead 30 bytes.
- 무손실 전달, R의 준비 완료 지식은 지연 0으로 가정한다. ACK/heralding은 모델링하지 않는다.
- P5-B: Swap 4 sessions, 시작 간격 0.8/2 ms, result background offered load 0/0.35/0.7.
- Traffic seeds 32개 × quantum seeds 2개 = 384 paired cases; 모델별 1,536 transactions.
- Calibration은 test와 겹치지 않는 기존 2개 traffic seed를 부하별로 사용한다.
- BSM CNOT/H/M/M: 0.6/0.2/0.4/0.4 ms. Correction X-or-I/Z-or-I: 각각 25 μs.
- F_min=0.5, deadline=5 ms는 그대로 유지하며 **원래 local session start**부터 측정한다.
- 비용 평가: mixed Swap/Teleport 1/4/8/16/32/64 sessions, 부하 0/0.7, 조건당 warmup 1회와 반복 10회.
  비용 평가의 correction slots는 각각 250 μs이며, P5-B의 25 μs와 구분한다.

준비 대기는 모든 모델에서 latency에 포함된다. 첫 session은 1 ms에 시작하고
1.2 ms에 자원이 준비되므로 0.2 ms를 기다린다.
Channel delay/noise를 바꾼 검증은 [별도 provisioning 평가](paper/PROVISIONING.md)에 있다.
이번 P5-B는 위 고정된 quantum-link 조건에서 classical/quantum 실행 단순화 오차를 비교한다.

## Baseline 정의

| 모델 | 유지하는 동작 | 단순화 |
|---|---|---|
| Full-Sync | 실제 quantum channel, 준비 대기, R/B FIFO, native gates, 실제 result UDP | 없음 |
| Fixed-Dc | 실제 quantum channel, 준비 대기, R/B FIFO, native gates | BSM 완료 후 result 전달만 별도 calibration 평균 지연으로 대체 |
| No-Dq-R | 실제 quantum channel, 준비 대기, native gates, 실제 result UDP, B FIFO | R execution capacity만 session별 processor replica로 완화 |
| Decoupled | 준비 시각과 eligible R FIFO 계산 | No-Dq-R의 result delay에 R wait를 합성하며 packet 생성 시각은 재계산하지 않음 |

No-Dq-R의 모든 replica는 실제 NetSquid R node의 component이고, qubit의 논리 memory position과
noise model은 유지한다. BSM은 native program-done callback으로 완료한다.
Fixed-Dc의 classical transport는 가상 지연 이벤트이며 실제 ns-3 packet 실행으로 표현하지 않는다.
Decoupled는 latency/deadline만 예측하며 quantum state/service feasibility는 정의하지 않는다.

```text
eligible = max(session_start, resources_ready)
resource_wait = eligible - session_start
processor_wait = BSM_start - eligible
latency = correction_complete - session_start
```

모든 state-bearing 모델은 자체 operation timestamps와 quantum-link 설정으로 독립 reference를 실행한다.
모델 내부의 reference 오차와 Full-Sync 대비 모델 간 예측 오차를 구분한다.
P5-B에서 packet drop 또는 B wait가 생기면 정상 결과로 받아들이지 않는다.

## 통계와 비용 측정

P5-B interval은 session/quantum 반복을 traffic seed 내에서 평균한 뒤,
traffic-phase cluster를 10,000회 재표집한 percentile bootstrap 95% interval이다.
Calibration 2개 seed를 고정한 조건부 결과이며, calibration 추정 불확실성은 포함하지 않는다.
부하 0에서는 traffic seed가 workload 다양성을 추가하지 않는다.
Service 판정은 paired sampled outcome을 사용하며 같은 quantum seed가 동일 BSM branch를 보장하지 않는다.
기대 fidelity와 success probability는 reference의 네 branch를 Born 확률로 가중한다.

비용 측정은 다른 실험이 끝난 뒤 CPU affinity 0/1에서 단독 실행한다.
실제 channel 생성/전달, ns-3 startup, IPC, native gate/state 기록, snapshot, 전체 traffic drain을 포함한다.
Python import/build, 독립 reference 검증, 디스크 쓰기는 제외한다.
반복 CI는 호스트 실행시간 변동이며 workload CI 또는 고립된 IPC overhead가 아니다.
각 조건의 반복 trace hash 일치를 검사한다.

## 실행 및 산출물

ns-3 루트에서 실행한다. 출력 경로는 새 경로를 사용한다.
새 checkout에서는 먼저 [v4 실행 문서](README-PROVISIONED.md)에 따라 바이너리·Q2NS 환경을 준비하고
v4 correctness 압축본을 복원한다. 평가 runner는 그 검증 summary의 소스 해시를 확인한다.

```bash
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/experiments/tests -p test_provisioned_evaluation.py -v

taskset -c 0,1 /home/ns3/qunet/bin/python contrib/cosim/experiments/run_provisioned_p5b.py \
  contrib/cosim/scenarios/provisioned-p5b-expanded.json \
  --output-dir contrib/cosim/results/provisioned-p5b-new

# 위 실험이 끝난 뒤 비용 측정을 실행한다.
taskset -c 0,1 /home/ns3/qunet/bin/python contrib/cosim/experiments/run_provisioned_paper.py \
  --plan contrib/cosim/scenarios/provisioned-paper-validation.json \
  --output-dir contrib/cosim/results/provisioned-cost-new
```

- [평가 plan](scenarios/provisioned-p5b-expanded.json) / [비용 plan](scenarios/provisioned-paper-validation.json)
- [P5-B summary](results/provisioned-p5b-expanded/summary.json): CI, model errors, calibration provenance.
- [비용 summary](results/provisioned-paper-scaling/summary.json): 시간 분해, IPC/round/channel counters, 환경.
- [전체 회귀](results/provisioned-paper-regression/summary.json): P0–v4 및 evaluation tests와 native Q2NS suites.
- [종합 검증](results/provisioned-paper-validation-summary.json)
- [논문용 결과](paper/provisioned-v4/RESULTS.md): 새 Figure 4–7, CSV, LaTeX 삽입문.

원자료는 `.json.gz`로 저장한다. v3와 이전 v4 correctness의 소스·증거는 보존한다.
원본 논문 PDF를 직접 고치지 않으며 새 구조에 맞는 결과·삽입문을 제공한다.

## 원자료 보존

전체 원자료·로그·표·그림은 [평가 압축본](baselines/provisioned-v4-paper-results.tar.gz)과
[파일 해시 manifest](baselines/provisioned-v4-paper-results.json)에 보존한다.
검증 및 복원은 ns-3 루트에서 실행한다. 기존 파일은 덮어쓰지 않는다.

```bash
sha256sum -c contrib/cosim/baselines/provisioned-v4-paper-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/provisioned-v4-paper-results.tar.gz
```
