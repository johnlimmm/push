# P5-B — Direct-start 실행 구조의 단순화 오차

## 실행 기준

현재 기준은 `direct-session-start-v2`다. R의 Q2NS SwapApp이 `session_start_ns`에
external BSM을 요청한다. Controller, C–R 링크, command packet/queue는 없다.
Full Sync와 No-Dq-R은 `cosim-hybrid`의 실제 Q2NS UDP result 경로를 사용한다.
모든 실행 모델은 `HybridExecutionCore`, `HybridFederation`, 동일 adapter와 native T1/T2 aging을 쓴다.

Full Sync는 지정한 물리 모델 내 상세 실행 기준이며 실제 하드웨어 정답을 뜻하지 않는다.
이전 command-path 구현과 수치는 `baselines/hybrid-v1-freeze.*` 및 이전 결과 디렉터리에 보존한다.
새 결과에 그 수치를 재사용하지 않는다.

| 모델 | 실행 의미 |
|---|---|
| Full-Sync | Local session start → shared R FIFO → BSM → 실제 R→B UDP → B FIFO → correction |
| Fixed-Dc | 동일 local start/R FIFO; BSM 완료 후 calibration 평균 R→B 지연으로 correction 도착 예약 |
| No-Dq-R | R 실행 capacity를 session 수로 늘림. 실제 BSM 완료시각에 Q2NS result를 생성·재전송. B FIFO 유지 |
| Decoupled | No-Dq-R의 실측 result delay + local session 시작시각으로 독립 계산한 R FIFO wait |

No-Dq-R의 capacity는 평가용 근사다. 물리 memory 위치/자원 ownership, BSM duration을 유지한다.
같은 시각은 설정 목록 순서다. Fixed-Dc는 packet simulator를 생략하며 가상 도착 이벤트의
source는 `fixed-delay`다. 실제 ns-3/Q2NS packet이 실행됐다고 기록하지 않는다.

## Latency와 baseline 식

`L_i = t_correction_complete,i - t_session_start,i`

Full Sync에서는 다음 분해를 검사한다.

`L_i = W_R,i + T_BSM + D_result,i + W_B,i + T_correction`

`D_result = t_RESULT_RX - t_RESULT_TX = queue + serialization + propagation`.
새 설정·metric·calibration에는 command delay 항이 없다.

Fixed-Dc는 calibration에서 얻은 `result_ns` 하나만 받는다. 같은 session start에 R FIFO를
재실행하고 BSM 완료시각 + `result_ns`에 correction을 접수한다.

Decoupled는 아래 식만 예측한다.

`L_i = W_R,i(Q) + T_BSM + D_result,i(C) + T_correction`

Q-run의 도착은 정확히 local `session_start_ns`다. C-run은 No-Dq-R의 실제 ns-3 실행이다.
합성 시 R 대기로 이동한 결과 생성시각에 packet을 다시 전송하지 않으므로 queue phase 의존성을
생략한다. Latency/deadline만 정의하고 fidelity/service feasibility는 null로 둔다.

## Calibration과 workload

- R→B background load 0 / 0.35 / 0.7, request interval 0.8 / 2 ms, 4 Swap sessions.
- 모든 모델에서 BSM 1.6 ms, correction 50 μs, T1=20 ms/T2=10 ms, EPR 생성 t=0.
- Result link 10 Mb/s, propagation 0.2 ms; result payload 80 bytes, background payload 1000 bytes.
- IPv4/UDP/PPP overhead 30 bytes. Background 주기는 wire serialization / offered load를 정수 ns로 반올림.
- Traffic seed는 주기 background의 시작 phase만 바꾼다. 첫 난수는 유일한 result flow에 사용한다.
- Calibration traffic seeds 100/101, request interval 2 ms. Test 전에 각 load의 result 지연 평균을 계산한다.
- 가장 가까운 정수 ns, half-up 반올림. Calibration/test seed 중복은 거절한다.
- Pilot test seeds 200–203: 48 paired cases, 144 model executions + 6 calibration runs.
- Expanded test seeds 1000–1031: 384 paired cases, 1152 executions + 6 calibration runs.
- Quantum seeds 7/11. 각 case의 session 일정, background 일정, EPR, noise, duration을 공유한다.
- F_min=0.5, deadline=**local session start 이후 5 ms**. 결과에 맞춰 threshold를 바꾸지 않는다.
- 정상 실행은 control/background drop=0, 모든 모델의 B wait=0을 요구한다.
  B wait가 생기면 전체 평가가 실패한다. Mixed protocol 검증의 B contention 허용과 구분한다.

이 평가의 50 μs correction은 Swap result 최소 직렬화 88 μs보다 짧다.
Teleport 2-byte packet의 직렬화는 25.6 μs이므로 이 조건을 Teleport mixed evaluation에 일반화하지 않는다.
P5-B workload는 Swap이며, 별도의 Hybrid mixed 검증에서는 B FIFO 대기도 허용한다.

## 통계와 해석

- Signed latency/fidelity bias와 latency MAE를 구분한다.
- 실현된 branch fidelity와 reference 네 branch의 확률 가중 E[F]를 각각 기록한다.
- Service feasibility는 correction 완료, F≥F_min, L≤deadline의 결합이다.
  기대 성공확률은 branch별 threshold 판정 후 확률을 합산한다.
- 같은 seed가 모델 간 같은 BSM branch를 보장한다고 가정하지 않는다.
- False feasible/infeasible의 분모는 cell 전체 paired transactions이며 conditional false-positive rate가 아니다.
- Deadline-only 오판은 fidelity를 포함한 service 오판과 별도로 보고한다.
- Batch throughput/goodput의 관측 창은 첫 local session start부터 마지막 correction 완료까지다.
- 95% percentile bootstrap은 traffic seed cluster를 재표집한다. Session/quantum 반복은 cluster 안에서 평균낸다.
- CI는 고정 calibration과 periodic phase workload에 조건화된다. Calibration 두 seed의 불확실성을 포함하지 않는다.
- 무부하에서는 traffic phase가 비활성이다. 0건/zero-width CI는 모집단 오차가 0임을 증명하지 않는다.

## 검증

독립 설정 기반 R FIFO / result packet FIFO / B FIFO와 실제 trace를 대조한다.
No-Dq-R은 R wait=0과 새 완료시각에서의 실제 재전송을 검사한다.
Fixed-Dc는 독립 constant-delay 일정과 실제 shared core의 dispatch/자원 lifecycle을 검사한다.
별도 NetSquid subprocess는 각 모델의 실제 operation/packet-arrival timestamp를 받아
native memory + Bell projection으로 모든 branch state를 계산한다.
검증 cache에는 완전한 reference spec(protocol, 생성시각, noise, 각 operation/도착시각)을 key로 쓴다.
각 run의 실제 density matrix와 다시 비교하며 다른 구조의 결과 파일을 읽어 대체하지 않는다.
