# P5-A — Classical / quantum joint contention

**상태: P5-A correctness PASS.** P4는 commit `db2960572`, tag `cosim-p4`로 보존했다.
P3의 공유 R FIFO와 P4의 실제 packet FIFO를 결합했으며 기존 P0–P4 소스는 변경하지 않았다.
P5-B 비교 평가 및 Q2NS 직접 연결은 후속 작업이다.

## 검증 결과

- P5-A 18개 테스트 + P0–P4 회귀 76개 = **94개 PASS**.
- 결정론적 3개 시나리오와 각 noise-off 실행 PASS.
- joint-both에서 32 seeds × 4 sessions = 128 transactions, BSM 네 분기 모두 확인.
- 위 기본/noise-off/분기 검증의 최대 density-matrix error: `3.3306690738754696e-16`.
- 정상 실행에서 B correction wait=0, control/background drop=0.
- 동일 시각 completion/request/background, session-local ID 재사용, 큰 session ID,
  background 격리, traffic drain 이후 F_usable 보존, 잘못된 trace/state 검출 확인.
- B 대기와 packet overflow는 의도적 실패로 검출하고 원본 결과를 보존했다.

근거: [검증 요약](results/p5-validation-summary.json),
[P5-A 테스트 로그](results/p5-test-suite.log), [회귀 로그](results/p5-regression-suite.log).
요약은 현재 검증 실행의 기록이다. 테스트를 재실행하면 시나리오 결과와 분기/격리 검증 기록이 갱신된다.

### session별 관측 대기시간

단위는 ms이며 각 배열은 session 1, 2, 3, 4 순서다.

| 시나리오 | command queue | R wait | result queue | 마지막 session 완료 |
|---|---|---|---|---|
| quantum-only | 0, 0, 0, 0 | 0, 0.8, 1.6, 2.4 | 0, 0, 0, 0 | 8.298080 |
| joint-result | 0, 0, 0, 0 | 0, 0.8, 1.6, 2.4 | 0.713920 × 4 | 9.012000 |
| joint-both | 0.312, 0, 0, 0 | 0, 1.112, 1.912, 2.712 | 0.401920 × 4 | 9.012000 |

모든 packet의 APP/queue/PHY 시각과 R/B 연산시각은 설정만으로 계산한 독립 FIFO 일정과 일치한다.
각 session의 실제 operation timestamps를 독립 NetSquid-only reference에 입력해
BSM 입력/frame/correction-start/usable density matrix와 fidelity를 비교했다.

### R 대기가 실제 result queue를 바꾸는 사례

동일한 session 2 command 시각과 background traffic에서 경쟁 session 유무를 비교했다.

| 관측값 | session 2 단독 | 4 session 공유 R |
|---|---|---|
| command 도착 | 1.910080 ms | 1.910080 ms |
| R 대기 | 0 | 0.800000 ms |
| result 생성 | 3.510080 ms | 4.310080 ms |
| result queue 대기 | 0 | 0.713920 ms |
| correction 완료 | 4.298080 ms | 5.812000 ms |

이 사례에서 경쟁 session 추가는 R 대기뿐 아니라 뒤쪽 result queue 대기도 바꾼다.
결과: [격리 비교](results/p5-phase-witness.json), [단독 실행](results/p5-isolated-session-2.json).
이는 P5-A의 인과관계 검증이며 P5-B의 No-Dq-R baseline 전체를 구현한 것은 아니다.

## 실행

ns-3 루트에서 실행한다. NetSquid가 설치된 Python 환경을 사용한다.

```bash
./ns3 configure
./ns3 build cosim-p5
/home/ns3/qunet/bin/python contrib/cosim/python/run_p5.py \
  contrib/cosim/scenarios/p5-joint-both.json \
  --output contrib/cosim/results/p5-joint-both.json

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_p5.py -v
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p 'test_p[0-4].py' -v
```

설정은 [SPEC-P5](SPEC-P5.md) 및 [joint-both scenario](scenarios/p5-joint-both.json)를 참고한다.
`expected_queueing`의 `positive`는 해당 종류에 적어도 하나의 양의 대기가 있어야 한다는 의미다.
기존 queue 규약은 [SPEC-P4](SPEC-P4.md), quantum atomic 모델은 [SPEC-P3](SPEC-P3.md)와 같다.

## 파일과 결과 해석

- [cosim-p5.cc](examples/cosim-p5.cc): session별 실제 UDP 송수신, background 분리, packet FIFO/PHY trace.
- [run_p5.py](python/run_p5.py): P0 federation 순서 유지, 기존 `P3Quantum` 재사용, JSON/실패 결과 보존.
- [p5_config.py](python/p5_config.py): 설정 검증과 독립 command FIFO → R FIFO → result FIFO → B FIFO 계산.
- [p5_validation.py](python/p5_validation.py): packet/quantum 시간, 자원, session 격리, 상태 reference 검증.
- [test_p5.py](tests/test_p5.py): 실제 simulator 경로 및 negative tests.

`metrics.sessions`는 session별 Dc, R/B 대기, 완료시각과 fidelity를 담는다.
`metrics.processor`는 R 통계, `metrics.links`는 classical FIFO 통계다.
R utilization의 구간은 첫 command 도착부터 마지막 BSM 완료까지이며,
링크 utilization의 구간은 t=0부터 마지막 packet 수신까지다. 서로 다른 관측 구간을 혼용하지 않는다.

`batch_completion_ns`와 `traffic_drain_completion_ns`를 구분한다.
각 `snapshot.sessions[sid].ab_pair.fidelity`는 그 session의 correction 완료시각 값이다.
뒤쪽 background drain 때문에 F_usable을 다시 계산하지 않는다.

본 결과는 유한 workload의 correctness 증거다. 부하의 통계적 성능 경향이나 단순화 오차 크기는
아직 주장하지 않는다. NetSquid는 quantum state/native memory noise를 담당하고,
FIFO 및 atomic operation duration은 기존 scheduler가 담당한다.
현재 참가자는 독립 cosim이며 Q2NS `SwapApp` 직접 통합 완료를 의미하지 않는다.
