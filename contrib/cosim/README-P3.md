# P3 — 공유 QuantumProcessor의 FIFO 대기와 memory aging

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

P2의 native T1/T2 모델을 유지하고 여러 session의 요청이 하나의 R processor를 공유한다.
구현/검증 범위와 metric 정의는 [SPEC-P3.md](SPEC-P3.md)에 있다.

## 실행

ns-3 루트 `/home/ns3/ns-3-dev`에서:

```bash
# 새 scratch 빌드 진입점을 처음 등록할 때만 실행한다. 기존 설정을 유지한다.
cmake -S . -B cmake-cache
./ns3 build cosim-p3

/home/ns3/qunet/bin/python contrib/cosim/python/run_p3.py \
  contrib/cosim/scenarios/p3-quantum-contention.json \
  --output contrib/cosim/results/p3-quantum-contention.json

/home/ns3/qunet/bin/python contrib/cosim/python/run_p3_sweep.py \
  contrib/cosim/scenarios/p3-arrival-sweep.json \
  --output-dir contrib/cosim/results/p3-arrival-sweep

/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/tests -v
```

기존 P0/P1/P2 코드와 CMake는 보존했다. P3 빌드 진입점은 `scratch/cosim-p3/CMakeLists.txt`다.
새 checkout에서도 이 파일을 포함해야 한다. C++ 실행 파일을 직접 실행하지 않고 Python runner로 시작한다.

## 결과 읽기

- `metrics.sessions`: session별 도착 age, Dq, BSM-start age, packet/correction 대기, F_usable, 완료시각
- `metrics.processor`: 관측 구간, R busy 시간, utilization, 평균/최대 queue length, queue integral
- `snapshot.sessions`: session별 local 자원/요청 ID와 native 상태 관측
- `cross_validation.sessions`: 실제 operation 시각에 대한 독립 네 분기 reference와 조건부 상태 비교
- `cross_validation.no_wait_baselines`: 동일 생성·도착시각에서 R 대기만 제거한 독립 reference
- `queue_samples`: 각 boundary의 dispatch 후 대기 session 목록과 실행 session
- `events`: session ID와 인과관계가 있는 공통 v1 로그

기본 예상 대기시간은 0 / 1.2 / 2.4 / 3.6 ms, queue 최대 길이는 3이다.
Packet 송신 대기와 B correction 대기는 0이어야 한다. 그런 경합이 생기는 설정은 P3 검증이 거절한다.

F_usable은 session별 보정 완료 시각의 값이다. 전체 batch 종료시각의 상태로 다시 계산하지 않는다.
무대기 reference는 실제 추가 ns-3 실행이 아닌 시간 조건을 고정한 비교 기준이다.
T1/T2 fidelity의 단조 감소를 강제하지 않으며, 정확한 저장시간과 reference 상태 일치를 검증한다.

## P2 보존

- commit `b900f8e99`, tag `cosim-p2`
- [manifest](baselines/p2-freeze.json), [코드·결과 archive](baselines/p2-freeze.tar.gz)
