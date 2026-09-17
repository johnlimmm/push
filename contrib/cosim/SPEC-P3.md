# P3 — Quantum Contention with Native Memory Aging

## 검증 결과 (2026-09-16)

- P3 전용 **16개 테스트 통과** (54.490 s).
- 기존 P0/P1/P2 **42개 회귀 테스트 통과** (51.939 s). 총 **58개 통과**.
- 도착 간격 5조건 × noise off/on: **10 batches, 40 transactions 모두 통과**.
- 기본 run과 sweep의 최대 밀도행렬 오차: `1.6653345369377348e-16`.
- 기본 Dq: 0 / 1.2 / 2.4 / 3.6 ms. 최대 queue=3, 평균 queue=1.125, 관측 구간 utilization=1.
- 모든 정상 시나리오의 command/result packet 송신 대기와 B correction 대기=0.
- P0/P1/P2 보존 소스 해시 검증 통과. 기존 코드 변경 없음.

증거: [검증 요약](results/p3-validation-summary.json), [P3 테스트](results/p3-test-suite.log),
[기존 회귀 테스트](results/p3-regression-suite.log), [기본 결과](results/p3-quantum-contention.json),
[sweep CSV](results/p3-arrival-sweep/summary.csv).

## 1. 목표와 보존 기준

**여러 session이 공유 R processor에서 기다린 시간이 native quantum memory aging에 반영되는지 검증한다.**
P2 보존 commit은 `b900f8e99`, tag는 `cosim-p2`다.
`baselines/p2-freeze.tar.gz`와 JSON manifest에 코드, 명세, 실행 결과와 해시를 함께 보존했다.
P0/P1/P2 소스·테스트·명세·기존 CMake 파일은 변경하지 않는다.

P3는 유한 개 session의 correctness 검증이다. 정상상태 throughput, 하드웨어 성능,
논문용 확률 추정·deadline 성능을 주장하지 않는다.

## 2. 고정 범위

- Controller(0), A(1), R(2), B(3)와 실제 IPv4/UDP/P2P 링크 두 개를 유지한다.
- 하나의 Python/NetSquid 엔진, 하나의 공유 R QuantumProcessor, 하나의 공유 B QuantumProcessor.
- A/B는 각각 N개 memory position, R은 2N개 position. 서로 다른 session이 같은 position을 점유하지 않는다.
- 모든 입력 EPR은 t=0에 생성한다. session별로 AR/RB 두 쌍, local pair ID는 1/2, AB는 3이다.
- Request ID는 session마다 BSM=1, correction=2다. pair key는 `(session_id, pair_id)`, request key는 `(session_id, request_id)`다.
- P0의 정수 ID FIFO를 재사용하기 위해 내부에서만 session별 ID를 충돌 없는 정수로 매핑한다. 외부 packet/log에는 local ID를 유지한다.
- 1..64개 session을 지원한다. 입력은 session ID와 command 송신시각의 목록이다.
- EPR 재생성, 만료, admission control, background traffic, packet loss, gate noise, timed QuantumProgram은 추가하지 않는다.
- NetSquid native `T1T2NoiseModel`과 DM formalism을 유지한다. 기본 T1=20 ms, T2=10 ms.
- BSM 1.6 ms, correction 0.5 ms. 고정 duration의 끝에서 이상적 연산을 한 번 적용한다.
- R의 FIFO waiting만 허용한다. 실제 classical 송신 queue나 B correction queue가 생기는 설정은 P3 validation에서 거절한다.

R/B 실행시간과 busy 상태는 기존 atomic scheduler가 관리한다. 보고하는 utilization은
이 모델의 점유 구간에서 계산하며 native `QuantumProcessor.busy`의 gate-level 통계가 아니다.

## 3. 최소 4-session 시나리오

명령 송신시각: 1.0 / 1.4 / 1.8 / 2.2 ms. Session ID: 1 / 2 / 3 / 4.
P2와 같은 link rate/delay 및 payload를 사용한다.
Command serialization=10,080 ns, propagation=100,000 ns.
Result serialization=88,000 ns, propagation=200,000 ns.

| Session | Command RX (ns) | BSM start (ns) | BSM end (ns) | Dq (ns) | Correction end (ns) |
|---|---:|---:|---:|---:|---:|
| 1 | 1,110,080 | 1,110,080 | 2,710,080 | 0 | 3,498,080 |
| 2 | 1,510,080 | 2,710,080 | 4,310,080 | 1,200,000 | 5,098,080 |
| 3 | 1,910,080 | 4,310,080 | 5,910,080 | 2,400,000 | 6,698,080 |
| 4 | 2,310,080 | 5,910,080 | 7,510,080 | 3,600,000 | 8,298,080 |

도착 순서에서 `start_i = max(arrival_i, end_(i-1))`, `end_i = start_i + BSM_duration`.
`Dq_i = start_i - arrival_i`다. Request ID나 session ID로 정렬하지 않는다.

같은 시각에 완료와 새 도착이 있으면 완료를 먼저 commit하고 모든 입력을 접수한 뒤
기존 FIFO의 가장 오래된 요청을 배정한다. 새 요청이 이미 대기 중인 요청을 추월하지 않는다.

## 4. Federation과 자원 수명

각 boundary는 P0/P1/P2와 같은 순서를 사용한다.

1. Quantum completion commit
2. 해당 시각 ns-3 이벤트 모두 처리
3. 실제 UDP 수신이 만든 외부 입력 모두 접수
4. R/B FIFO dispatch
5. BSM completion을 R 앱에 주입; 같은 시각의 다음 round에서 실제 결과 UDP 송신

다음 boundary는 quantum completion horizon과 ns-3 next event의 최솟값이다.
정수 ns, 두 시계 일치, 미래 native event 부재 검사를 유지하며 epsilon을 사용하지 않는다.

입력 자원은 session별 `AVAILABLE → RESERVED → IN_USE → CONSUMED`,
출력은 `FRAME_PENDING → CORRECTING → USABLE`이다.
예약된 큐빗도 memory에 남아 실제 시간만큼 aging한다. BSM duration 동안 네 큐빗이 저장되고,
R의 두 큐빗은 BSM 완료에 소모된다. A/B의 원래 큐빗과 position은 보정 완료까지 유지한다.
AB 등록은 물리 큐빗 재생성이 아니다.

BSM·correction duplicate는 같은 session 안에서 멱등적으로 처리한다. 잘못된 local 자원 ID,
없는 session, 아직 AB가 없는 session의 correction은 거절한다. 최초 correction은 수신한 측정 비트를
그대로 사용하며, 이미 수신한 결과와 다른 재시도는 RESULT_MISMATCH로 거절한다.
P3의 duplicate/mismatch 검사는 양자 어댑터 수준이다. 실제 UDP replay 회귀는 기존 P1에 유지한다.

## 5. 관측과 metric 정의

공통 event envelope v1을 유지한다. 모든 이벤트의 session_id는 실제 session이며 event ID와 sequence는
전체 batch에서 고유하다. causal parent는 같은 session의 앞선 이벤트여야 한다.
Correction 이벤트의 `input_pair_ids=[3]`, `output_pair_id=3`, `details.ancestor_pair_ids=[1,2]`를 유지한다.

Session별 `snapshot.sessions[session_id].checkpoints`:

- `arrival.AR/RB`: 실제 R 요청 도착 직후의 입력 상태
- `bsm_start.AR/RB`: FIFO 대기 후 실제 연산 시작 직전의 입력 상태
- `bsm_end_inputs.AR/RB`: BSM 완료의 이상적 회로 직전 상태
- `frame`: BSM 측정 직후 조건부 Bell frame 상태
- `correction_start`: 결과 패킷이 B에 도착하여 보정을 시작할 때의 상태
- `usable`: 해당 session의 실제 correction 완료 시점 상태

F_usable은 각 session의 보정 완료 시각에 저장한다. 전체 batch 종료 시각에 다시 평가하여
과거의 F_usable을 덮어쓰지 않는다. `batch_completion_ns`는 마지막 session의 종료시각이며
일찍 완료된 session의 F_usable 평가시각과 다르다. USABLE은 품질/얽힘 임계값을 보장하지 않는다.

### 시간·queue·utilization

- `age_on_arrival_ns = request.arrival_ns - created_ns` (현재 created_ns=0)
- `quantum_wait_ns = BSM_start - request.arrival_ns`
- `age_at_bsm_start_ns = BSM_start - created_ns`
- `command_queue_ns`, `result_queue_ns`: 실제 `PHY_TX - APP_TX`; 모두 0이어야 한다.
- `correction_wait_ns = correction_start - RESULT_RX`; 0이어야 한다.
- `transaction_latency_ns = correction_completion - COMMAND_TX`
- Queue sample은 매 dispatch 직후 기록하며 실행 중 요청을 제외한다.
- 관측 구간 W는 `[첫 R 요청 도착, 마지막 R BSM 완료)`다.
- `busy_ns = sum(BSM_end - BSM_start)`, `utilization = busy_ns / |W|`
- `queue_area_ns = integral_W Q(t) dt = sum(Dq_i)`; 이 등식을 별도 검사한다.
- `time_average_queue_length = queue_area_ns / |W|`
- `max_queue_length`: dispatch 후 안정된 queue sample의 최대 길이. 순간 QUEUED→RUNNING 전이는 피크에 세지 않는다.

기본값: busy=6.4 ms, utilization=1, max_queue_length=3, queue_area=7.2 ms, 평균 queue length=1.125,
평균 Dq=1.8 ms. 유한 batch에서 utilization=1은 모델의 해당 구간에서 빈 시간이 없다는 뜻이다.
평균·비율은 실수일 수 있으며, simulation timestamp는 정확한 정수 ns다.

## 6. 독립 quantum reference와 무대기 비교

각 session의 실제 BSM/correction 시작·완료시각을 기존 독립 `netsquid_reference_p2.py` subprocess에 입력한다.
Reference는 co-sim 상태·측정 비트를 입력받지 않고 native memory와 timer로 네 BSM 분기를 계산한다.
P3는 관측된 분기의 bsm_start, bsm_end_inputs, frame, correction_start, usable 상태를 비교한다.
P2와 동일하게 밀도행렬 원소 최대 오차와 fidelity 오차는 1e-12 이하여야 한다.

추가로 같은 session의 t=0 EPR과 동일한 R 도착시각에서 **R 대기 Dq만 0으로 제거한** 독립 reference를 계산한다.
네 operation timestamp에서 Dq를 뺀다. Classical serialization/delay와 연산 duration은 유지한다.
이것은 추가 ns-3 실행이나 여러 dedicated processor의 실제 동작이라고 주장하지 않는 반사실적 reference다.
이 reference의 BSM 시작 전 상태는 co-sim의 arrival 관측과 일치해야 한다.

- `sessions[sid].reference.ensemble.fidelity`: 실제 waiting을 포함한 정확한 분기 가중 기대 fidelity
- `no_wait_baselines[sid].reference.ensemble.fidelity`: 같은 도착·생성시각에서 R 대기를 제거한 기대 fidelity
- `ensemble_fidelity_delta`: 실제 기대 fidelity − 무대기 기대 fidelity

동일 seed의 서로 다른 BSM 분기를 같은 표본으로 취급하지 않는다. 비교에는 조건부 상태 또는 정확한 분기 가중 기대값을 쓴다.
T1/T2에서는 F_usable의 단조 감소를 합격 기준으로 강제하지 않는다. 추가 저장시간과 reference 상태 일치가 기준이다.

## 7. Arrival interval sweep

4 sessions, command 시작 1 ms, 간격 0.2 / 0.4 / 0.8 / 1.6 / 3.2 ms.
각 간격에서 noise off/on을 실행해 총 10 batches, 40 transactions를 검증한다.
모든 개별 run은 실제 packet 경로, R FIFO, classical/B 무대기와 session별 reference를 통과해야 한다.
Noise off에서는 각 AB가 Phi+로 복원되고 noise on/off의 packet/operation timing은 같아야 한다.

간격을 바꾸면 t=0 생성과 요청 도착 사이의 age도 달라진다. 따라서 간격별 F 변화 전체를 Dq에 귀속하지 않는다.
CSV에는 도착 시 age, Dq, BSM 시작 age, 조건부 fidelity, 실제/무대기 기대 fidelity를 각각 기록한다.

## 8. 검증 계획

- 기본 4-session timing, queue integral, utilization, 실제 packet 무대기
- Noise off의 Bell 복원 및 P3 timing 불변, 단일 session의 P2 재현
- 동일 timestamp 완료/새 도착에서 기존 대기 요청 우선
- 설정 목록 순서와 큰 session ID에 무관한 FIFO, session-local ID 재사용
- Sparse arrival의 queue=0, utilization<1
- 여러 seed/session에서 네 측정 분기와 독립 조건부 reference 비교
- 동일 session의 duplicate·mismatch·잘못된 자원 ID, 없는/준비되지 않은 session 격리
- Shared native memory 위치와 원래 A/B 큐빗 객체 보존
- 경계/peek 분할 시 quantum 결과 불변
- Queue aging을 의도적으로 누락하면 reference 실패
- Classical 또는 correction 경합이 섞이면 P3 scope 검증 실패
- 자원 위치, causal parent, queue sample, metric, timestamp, 전이 로그 변조 검출
- P0/P1/P2 42개 회귀 테스트와 P2 보존 파일 해시 유지

## 9. 파일과 빌드

- `examples/cosim-p3.cc`: P1 UDP 참가자를 fork한 multi-session 실제 ns-3 경로
- `python/p3_config.py`: 설정과 trace 독립 시간식
- `python/p3_quantum.py`: 하나의 P0 scheduler, 공유 native memory/processor, session별 상태
- `python/p3_validation.py`: 시간·자원·로그·metric 검증 및 독립 reference 비교
- `python/run_p3.py`: IPC와 P3 federation 실행기
- `python/run_p3_sweep.py`: 유한 batch 도착 간격 sweep과 CSV
- `tests/test_p3.py`: 통합/자원/aging 회귀 검사

기존 CMake 파일은 보존 해시 검사 대상이다. `scratch/cosim-p3/CMakeLists.txt`에 별도 빌드 진입점을 추가해
P3 소스만 기존 ns-3 라이브러리에 링크한다. 생성 binary는 `build/contrib/cosim/examples/*cosim-p3*`다.
