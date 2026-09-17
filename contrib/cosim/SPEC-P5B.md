# P5-B — 단순화 모델의 예측 오차 평가

## 비교 계약

Full Sync는 동일 물리 모델 내 상세 causal execution 기준이다.
Q2NS `SwapApp`의 실제 UDP 경로와 NetSquid native T1/T2 상태를 사용한다.
실제 하드웨어의 정답이나 성능을 뜻하지 않는다.

기존 P0–P5-A/Q2NS 소스는 `baselines/q2ns-freeze.tar.gz`와 SHA-256 목록으로 보존했다.
baseline은 별도 `experiments/`에 둔다. Q2NS C++ 참가자와 native noise 코드를 변경하지 않는다.

| 모델 | 실행 의미 |
|---|---|
| Full-Sync | 실제 Q2NS/ns-3 packet queue + 공유 R FIFO + native memory aging |
| Fixed-Dc | calibration의 command/result 고정 지연을 적용하고 P3 quantum FIFO/NetSquid 재실행 |
| No-Dq-R | session별 가상 실행 슬롯으로 R wait만 제거. 같은 native memory, BSM duration, B FIFO 유지. Q2NS/ns-3 packet을 새 완료시각에 실제 재전송 |
| Decoupled | C-run=No-Dq-R 실측 Dc, Q-run=무부하 command delay를 더한 도착시각의 R FIFO wait를 합성 |

No-Dq-R의 가상 슬롯은 R의 무제한 실행 capacity 근사이며 물리 장치를 추가한 것이 아니다.
메모리 위치는 유지하고 atomic BSM은 해당 완료시각에 기존 native 명령으로 수행한다.
같은 시각은 session 등록 순서로 처리한다. Fixed-Dc는 packet simulator를 생략한 baseline이며
synthetic event를 실제 packet/SwapApp trace라고 기록하지 않는다.

Decoupled의 session i 예측은 아래 하나로 고정한다.

`L_i = Dc_cmd_i(C) + W_R_i(Q) + BSM_duration + Dc_result_i(C) + correction_duration`

Q-run 도착은 `command_TX + 무부하 command serialization + propagation`이다.
R wait 때문에 C-run의 result 생성시각이나 queue phase를 바꾸지 않는다.
Decoupled는 latency/deadline만 예측한다. fidelity/service feasibility는 null이다.

## Calibration과 공통 입력

- traffic seed와 quantum seed를 분리한다. traffic seed는 유한 주기 background의 시작 phase만 변경한다.
- 같은 test case의 모든 모델은 command 일정, background 일정, t=0 EPR, noise, duration을 공유한다.
  Fixed-Dc는 그 background 조건에 해당하는 calibration 상수로 classical network를 대체한다.
- classical load별 별도 calibration traffic seeds에서 Q2NS Full Sync로 command/result delay를 측정한다.
  calibration request interval은 고정 2 ms다. test 실행 전에 두 평균을 저장·해시한다.
- 평균은 가장 가까운 정수 ns로 반올림하며 정확히 절반이면 위로 반올림한다.
- calibration/test traffic seed 중복을 거절한다. test 결과를 calibration에 다시 넣지 않는다.
- 실제 workload 설정·해시, traffic/quantum seed, calibration hash를 매 결과에 기록한다.

## 초기 sweep

`scenarios/p5b-pilot.json`:

- 두 링크의 background offered load: 0 / 0.35 / 0.7.
- request interval: 0.8 / 2 ms; session 4개.
- calibration traffic seed: 100/101; test: 200/201/202/203.
- quantum seed: 7/11. 24개 workload × 2회 = 48개 paired case.
- BSM 1.6 ms, correction **50 μs**를 모든 모델에 동일 적용.
- F_min=0.5, deadline=command TX 이후 5 ms.

기존 P5-A의 correction 0.5 ms에서 No-Dq-R result packet이 몰리면 B queue가 생길 수 있다.
이번 workload는 최소 result serialization 88 μs보다 correction을 짧게 설정해 이를 배제한다.
B duration을 0으로 생략하지 않는다. 모든 모델에 B wait=0을 검사하고 위반 시 전체 평가를 실패시킨다.
control/background drop도 허용하지 않는다. 실패 조건을 정상 통계에서 조용히 제외하지 않는다.

background payload는 1000 bytes, 주기는 wire serialization/offered load를 정수 ns로 반올림한다.
명시된 load는 background의 주기 내 부하이며 control을 포함한 총 부하나 정상상태 utilization이 아니다.
유한 traffic 종료시각은 입력 설정만으로 정하며 session 완료와 drain 완료를 구분한다.

## 지표와 통계

- `L = correction_complete - command_TX`; EPR은 여전히 모든 session에서 t=0 생성이다.
- `delta_latency = L_baseline - L_full`, `delta_fidelity = F_baseline - F_full`.
- 실현된 BSM branch의 fidelity와 독립 reference의 확률 가중 `expected_fidelity`를 함께 기록한다.
- 성공은 correction 완료 AND F≥F_min AND L≤deadline이다.
  기대 성공확률은 **분기마다 threshold를 적용한 뒤 확률을 합산**한다.
  기대 fidelity에 threshold를 적용하여 성공확률을 대신하지 않는다.
- false feasible/infeasible은 동일 workload·quantum seed의 표본 판정 비교다.
  같은 seed라도 모델 간 BSM bit가 반드시 같다는 가정은 하지 않는다.
  branch 확률까지 포함한 성공확률 오차도 별도로 보고한다.
- Decoupled에는 deadline 오판만 보고하며 양자 서비스 성공률을 부여하지 않는다.
- throughput/goodput의 관측 창은 첫 command TX부터 마지막 correction 완료까지의 유한 batch다.
- 95% percentile bootstrap은 **traffic seed 단위 cluster**를 재표집한다.
  session/quantum 반복을 같은 cluster 안에서 먼저 평균내어 독립 표본수를 과장하지 않는다.

현재 4개 test traffic seed의 interval은 작은 pilot의 기술 통계다.
논문용 통계적 성능 주장에는 더 많은 workload seed와 실험 범위를 사전에 정해 실행해야 한다.

## 검증

- No-Dq-R: 독립 command/result packet FIFO, R wait=0, duration 유지, 실제 Q2NS 완료 callback,
  session/resource/clock/queue/packet trace 검증 및 독립 quantum state reference.
- Fixed-Dc: 독립 fixed-delay FIFO 식과 실제 P3 dispatch 비교, 자원 lifecycle/quantum state reference.
- Full-Sync: 기존 Q2NS/P5 validation 그대로 적용.
- 모든 reference는 같은 operation timestamp/noise만 받아 별도 subprocess에서 Bell projection으로 계산한다.
  같은 시각·물리 설정의 분기 표만 재사용하고 매 실행의 실제 상태와 다시 대조한다.
- 단순화 baseline이 Full과 다르게 예측하는 것은 오류 지표다. baseline 자체가 정의된 실행 규약이나
  독립 reference를 어기면 구현 실패로 처리한다.
