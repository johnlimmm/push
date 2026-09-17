# P4 — 실제 classical FIFO와 native memory aging

P2의 단일 A–R–B swapping transaction에 유한 background UDP를 추가한다.
두 quantum 작업의 대기는 0으로 유지하고, 실제 ns-3 packet queue 대기만 분리해 검증한다.
범위와 판단 기준은 [SPEC-P4.md](SPEC-P4.md)에 있다.

## 검증 결과 (2026-09-16)

- P4 전용 **18개** 테스트 통과 (17.092 s).
- 기존 P0–P3 **58개** 회귀 테스트 통과 (106.590 s). 합계 **76개** 통과.
- 6개 부하율 × 3개 혼잡 방향 × noise off/on **36회 모두 통과**.
- 기본 4개 사례와 full sweep의 최대 reference 밀도행렬 오차: `5.551115123125783e-17`.
- 모든 정상 실행의 BSM/correction quantum wait와 control/background drop은 0.
- 32개 seed에서 네 BSM 분기 모두 검증. Noise off, 같은 시각 enqueue,
  추가 packet drain 이후 F_usable 보존, trace/state 변조 검출도 통과.
- Queue 용량 1의 의도적 실패 사례에서는 background 4개와 result 1개의 `TC_DROP`을 기록하고 거절했다.
- P3 보존 소스 해시 및 archive 해시 검사 통과.

| 기본 사례 | Command queue (ns) | Result queue (ns) | Session 완료 (ns) |
|---|---:|---:|---:|
| Zero | 0 | 0 | 3,498,080 |
| Command-only | 312,000 | 0 | 3,810,080 |
| Result-only | 0 | 2,361,920 | 5,860,000 |
| Both | 312,000 | 2,049,920 | 5,860,000 |

모든 packet의 APP/queue/PHY 관측 시각을 독립 FIFO 계산과 정수 ns 단위로 대조했다.
Result-only의 BSM 입력/frame 상태가 Zero와 같고 correction 시각만 늦어지는 것도 확인했다.

증거: [검증 요약](results/p4-validation-summary.json), [P4 테스트 로그](results/p4-test-suite.log),
[회귀 테스트 로그](results/p4-regression-suite.log), [양쪽 혼잡 결과](results/p4-both.json),
[sweep JSON](results/p4-load-sweep/summary.json), [sweep CSV](results/p4-load-sweep/summary.csv),
[의도적 overflow 실패 기록](results/p4-overflow-rejected.json).

## 실행

ns-3 루트 `/home/ns3/ns-3-dev`에서:

```bash
# 새 scratch 진입점을 처음 등록할 때 실행한다.
cmake -S . -B cmake-cache
./ns3 build cosim-p4

/home/ns3/qunet/bin/python contrib/cosim/python/run_p4.py \
  contrib/cosim/scenarios/p4-both.json \
  --output contrib/cosim/results/p4-both.json

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_p4.py -v

/home/ns3/qunet/bin/python contrib/cosim/python/run_p4_sweep.py \
  --output contrib/cosim/results/p4-load-sweep

# P0–P3 회귀 검증
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p 'test_p[0123].py' -v
```

기본 파일은 `p4-zero.json`, `p4-command-only.json`, `p4-result-only.json`, `p4-both.json`이다.
C++는 Python runner가 전달하는 IPC socket이 필요하므로 직접 실행하지 않는다.
P0–P3 CMake를 보존하기 위해 빌드 진입점은 `scratch/cosim-p4/CMakeLists.txt`에 둔다.

## 결과 읽기

- `validation`: 설정만으로 계산한 FIFO 일정과 actual packet/quantum 이벤트 검증.
- `cross_validation`: 실제 operation timestamps를 입력한 독립 NetSquid reference.
- `metrics.classical.command`, `.result`: 전체 Dc, queue/serialization/propagation 분해.
- `metrics.quantum_wait`: BSM/correction 모두 정확히 0이어야 한다.
- `metrics.links`: 전 패킷의 queue 길이·시간 적분, 전송 utilization, 송수신/drop 계수.
- `packet_events`: background/control APP TX/RX, queue enqueue/dequeue/drop, PHY TX 시작/끝/RX.
  `packet_bytes`는 APP에서는 payload, queue/PHY에서는 wire 크기다.
  `TC_DROP`은 device enqueue 이전의 drop이며 PPP를 제외한 payload+28 bytes다.
- `packets`: 패킷별 시각, 두 크기와 측정한 지연값. 독립 FIFO 예상값은 `validation.expected_timing.packets`에 있다.
- `events`: 기존 schema v1의 quantum/control 인과 로그. Background가 양자 요청을 만들지 않았는지 확인한다.
- `snapshot.checkpoints`: BSM 시작/완료 전 입력 상태, frame, correction 시작, usable 상태.

`session_completion_ns`는 correction 완료, `traffic_drain_completion_ns`는 마지막 packet RX,
`simulation_completion_ns`는 둘 중 늦은 시각이다. F_usable은 session 완료 순간의 값으로 고정한다.
Drop/quantum 대기/FIFO 불일치가 있으면 CLI는 실패 JSON을 저장하고 종료 코드 1을 반환한다.
구문·설정 오류 또는 참가자 프로세스 자체의 실패는 정상 실행 결과로 처리하지 않는다.

## metric 해석

두 링크 모두 `[0, traffic_drain_completion_ns]`를 관측 구간으로 사용한다.
Utilization은 실제 PHY serialization 시간 합 / 관측 구간이다.
Queue 평균은 packet 수의 시간 적분 / 관측 구간이며 전송 중인 패킷을 포함하지 않는다.
Queue peak는 callback 순간의 길이여서 즉시 dequeue되는 enqueue도 포함한다.

Sweep은 6개 wire offered load × command/result/both × noise off/on = 36회다.
Flow당 32개 패킷과 seed 7을 사용한다. 단일 seed의 조건부 fidelity와 reference의 정확한
분기 확률 가중 ensemble fidelity를 별도로 기록한다. 이 유한 실행 결과를 정상상태 부하 실험이나
반복 표본의 통계적 성능 추정으로 해석하지 않는다. 높은 부하에서도 control queue가 0일 수 있다.

T1/T2에서는 fidelity의 단조 감소를 일반 조건으로 강제하지 않는다. P4의 통과 기준은
정확한 저장시간, 무손실/무 quantum 대기, native reference와 상태 일치다.

## 보존과 다음 단계

P3는 commit `8ac3fe3c5`, tag `cosim-p3` 및 [보존 manifest](baselines/p3-freeze.json)에 보존했다.
P4는 P2Quantum/native T1T2NoiseModel/reference를 그대로 불러온다. P0–P3 소스는 변경하지 않는다.
현재 quantum processor 점유시간은 기존 atomic scheduler가 관리한다.

Q2NS `SwapApp`의 요청/완료와 논리 EPR mapping을 실제 연결하는 작업은 여전히 후속 필수 범위다.
P4 자체는 독립 cosim 참가자이며 Q2NS 직접 통합 완료를 의미하지 않는다.
P5에서 classical/quantum contention을 함께 넣고 단순화 모델의 예측 오차를 비교할 수 있다.
