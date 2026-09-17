# P5-A — Joint contention correctness

P4 보존: `cosim-p4`, commit `db2960572`. 코드·결과·기존 테스트 로그는
`baselines/p4-freeze.tar.gz`에 보존하며 `p4-freeze.json`으로 SHA-256을 검사한다.

## 목표와 범위

P3의 다중 session / 공유 R FIFO와 P4의 실제 ns-3 packet FIFO를 결합한다.
검증 대상은 **packet 대기 → R 대기 → BSM 완료 → 실제 result packet 대기 → memory aging**이다.
Full Sync의 결합 실행을 검증하는 단계이며 단순화 모델의 성능 비교는 후속 P5-B다.

- Controller → R, R → B의 IPv4/UDP point-to-point 경로를 유지한다.
- 1..64 session, session마다 AR/RB EPR을 t=0에 생성한다.
- R processor 하나, FIFO, 고정 BSM duration. B processor 하나, 고정 correction duration.
- NetSquid native `T1T2NoiseModel`, density-matrix formalism을 재사용한다.
- 실행시간과 점유는 기존 atomic scheduler가 관리한다. BSM/correction의 이상적 연산은
  완료 시각에 적용한다. NetSquid timed QuantumProgram이나 gate noise는 추가하지 않는다.
- 모든 정상 실행에서 control/background drop=0, B correction wait=0이어야 한다.
  B 대기가 생기는 workload는 결과를 보존하고 validation 실패로 처리한다.
- Q2NS 직접 연결은 후속 필수 항목이다. P5-A를 Q2NS 통합 완료로 표현하지 않는다.

## 실행 계약

Federation은 P0의 순서를 유지한다:

1. quantum completion commit
2. 해당 시각 ns-3 event 배출
3. 수신 packet에서 발생한 quantum 입력 반영
4. R/B FIFO dispatch
5. 완료 결과를 ns-3에 주입하고 같은 timestamp의 다음 round에서 packet 생성

다음 boundary는 ns-3 next event와 quantum safe horizon의 최솟값이다.
양쪽 clock은 정확한 integer nanosecond여야 한다.
`P3Quantum`을 그대로 사용하며 session마다 simulator를 reset하지 않는다.

## 식별자와 패킷

외부 자원은 `(session_id, pair_id)` / 요청은 `(session_id, request_id)`로 식별한다.
각 session의 pair 1/2/3, request 1/2는 재사용 가능하며 native memory position은 분리한다.
설정 목록의 0-based 순번 i에 command packet ID `2*i+1`, result ID `2*i+2`를 부여한다.
background ID는 command `1000+i`, result `100000+i`, session ID는 0이다.
UDP port는 control=9000, background=9001이다. background는 quantum 요청을 만들지 않는다.

packet 크기, DropTail capacity, queue/PHY trace는 P4와 같다.
background 송신 event는 command보다 먼저 등록한다. 같은 송신시각이면 background가 먼저,
command끼리는 설정 목록 순서다. result는 quantum completion 이후 주입하므로 같은 시각에
이미 등록된 background 송신 뒤에 온다. PHY serialization은 양수다.

## 독립 timing 계산

ns-3/quantum 관측 trace를 기준값으로 사용하지 않는다. 설정만으로 다음을 계산한다.

1. 모든 command/background 송신을 command-link FIFO에 배치한다.
2. command 실제 예상 도착 순서로 R FIFO를 계산한다.
   `BSM_start = max(COMMAND_RX, previous_BSM_end)`.
3. 이 BSM 완료시각들에 result packet을 생성해 result/background FIFO를 계산한다.
4. result 도착 순서로 B FIFO를 계산하고 대기가 0인지 검증한다.

각 packet의 APP TX/RX, Queue Enqueue/Dequeue, PHY TX begin/end/RX를 모두 대조한다.
`Dc = queue_wait + serialization + propagation`을 확인한다.
R의 각 dispatch 후 waiting/running session, queue 적분=대기시간 합도 확인한다.
`expected_queueing`의 command/result/R 값은 `zero`, `positive`, `any`다.
`positive`는 해당 종류에서 적어도 하나의 control 요청이 양의 대기를 가져야 한다.

## 최소 시나리오

공통: session 4개, command TX=1.0/1.8/2.6/3.4 ms, BSM=1.6 ms, correction=0.5 ms.
command link=100 Mbps/0.1 ms, result link=10 Mbps/0.2 ms.

| 시나리오 | command background | result background | 목적 |
|---|---|---|---|
| quantum-only | 없음 | 없음 | P3와 동일 실행 확인 |
| joint-result | 없음 | 2.6 ms부터 1.6 ms 간격 4개 | R 대기와 result packet 대기의 결합 |
| joint-both | 0.9 ms부터 0.02 ms 간격 5개 | joint-result와 동일 | 두 classical 링크와 R 대기의 결합 |

background payload는 1000 bytes다. 본 시나리오는 유한 결정론적 검증이며 통계적 성능 주장이 아니다.
추가 isolation 검증에서는 session 2를 같은 command 시각·같은 background로 단독 실행한다.
R 대기가 있는 다중 session 실행과 비교하여 result 생성시각 및 queue 대기가 달라짐을 확인한다.
이 비교는 P5-B No-Dq-R 모델 전체의 구현이나 평가를 대신하지 않는다.

## 상태·로그·완료 기준

- 모든 session은 AR/RB `CONSUMED`, AB `USABLE`, correction 정확히 1회.
- P3의 arrival, BSM-start, BSM-end-input, frame, correction-start, usable checkpoint를 유지한다.
- session별 실제 네 operation timestamps와 같은 memory model을 독립 NetSquid-only
  subprocess에 전달한다. 관측 BSM branch에 조건부인 각 checkpoint density matrix와 fidelity를
  `1e-12` 이내에서 비교한다. quantum 상태나 co-sim 계산 결과를 reference 입력으로 주지 않는다.
- 시간·자원·로그 검증을 fidelity와 독립 수행한다. fidelity 단조성은 통과 조건이 아니다.
- `events`: 기존 v1 transaction log. `packet_events`: background/queue/PHY 포함.
- `metrics.sessions`: command/result queue 및 Dc, R/B wait, 완료시각, checkpoint fidelity.
- `metrics.processor`: R FIFO queue 길이/적분, 대기시간, utilization.
- `metrics.links`: 실제 classical queue 길이/적분, utilization, packet/drop 수.
- `batch_completion_ns`: 마지막 session correction 완료.
- `traffic_drain_completion_ns`: 마지막 실제 packet 수신.
- `simulation_completion_ns`: 두 완료시각의 최댓값. 각 F_usable은 session 완료시각의 값을 보존한다.

## 후속 작업

P5-A PASS 이후 Q2NS SwapApp의 최소 요청/완료 연결을 확인하고 P5-B를 진행한다.
P5-B는 Full Sync / Fixed-Dc / No-Dq-R / Decoupled를 비교한다.
실제 변경된 결과 생성시각으로 packet 일정을 다시 실행해야 하는 모델을 로그 후처리로 대신하지 않는다.
Decoupled의 Q-run 도착시각 정의, 공통 입력 일정, calibration/평가 분리와 통계 기준은 P5-B에서 고정한다.
