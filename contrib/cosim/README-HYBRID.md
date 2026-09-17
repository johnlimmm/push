# Multi-Protocol Hybrid Execution — Swap + Teleportation

**상태: 두 실제 Q2NS 앱의 공통 core 실행 및 혼합 실행 검증 완료.**
`SwapAdapter`와 `TeleportAdapter`가 동일 `HybridExecutionCore`, `HybridFederation`,
NetSquid R/B processor와 resource registry를 사용한다.
기존 P5-B pilot은 완료된 기준점이며 [freeze manifest](baselines/p5b-freeze.json)와 archive로 보존했다.
이번 구현의 보존·재현 절차와 후속 경계는 [Hybrid v1 release](RELEASE-HYBRID-V1.md)에 정리했다.

## 현재 위치

P0–P5-A → Q2NS SwapApp 연동 → P5-B 비교 평가 pilot → **공통 core + Teleportation + Mixed**.
기존 [README-Q2NS](README-Q2NS.md)의 “다음 단계는 P5-B”는 freeze 시점의 안내다.
P5-B는 [README-P5B](README-P5B.md)에서 완료 결과를 확인할 수 있다. 현재 구현 범위는 이 문서와
[SPEC-HYBRID](SPEC-HYBRID.md)를 기준으로 한다. 기존 freeze 파일은 재작성하지 않았다.

## 실제 실행 구조

```text
Controller ── ns-3 UDP command ──> R (Teleport의 Alice 역할)
                                  │
                      ┌───────────┴─────────────┐
                      │ Q2NS SwapApp            │
                      │ Q2NS TeleportationApp   │
                      └───────────┬─────────────┘
                                  │ async BSM request
                      HybridExecutionCore: 공통 R FIFO
                                  │ NetSquid 실제 BSM
                                  ▼
                      각 Q2NS 앱에 완료 통지
                                  │ 실제 Q2NS UDP result
                                  ▼
                          B의 해당 Q2NS 앱
                                  │ async correction request
                      HybridExecutionCore: 공통 B FIFO
                                  │ NetSquid X/Z correction
                                  ▼
                         Q2NS correction 완료 trace
```

Q2NS 앱이 준비 조건·packet 수신·protocol 진행을 판단하고, NetSquid만 quantum state를 소유한다.
Swap은 pair + pair → pair, Teleport는 input qubit + pair → qubit이다.
공통 core는 resource handle과 실제 memory position을 예약하며 protocol의 pair 의미를 가정하지 않는다.
같은 processor를 공유하는 session도 서로 다른 position을 사용한다.

Teleport 입력 상태와 EPR은 t=0에 NetSquid에서 생성하며 각각 생성시각을 기록한다.
입력 qubit을 포함해 memory에 있는 모든 생존 qubit에 native T1/T2 aging이 적용된다.
첫 범위의 BSM/correction은 fixed-duration atomic 연산이다. NetSquid timed QuantumProgram은 아니다.
Teleport 결과는 기존 앱의 2-byte payload이고 Swap은 기존 80-byte payload(기본값)를 유지한다.

## 검증 결과

- 신규 Python 통합 테스트 **14개**, 기존 P0–P5-B/Q2NS 회귀 **122개**: **136개 PASS**.
- Q2NS 기존 native **76개** + Teleport 외부/native 경로 **7개**: **83개 PASS**.
- 총 **219개 test cases PASS**. [검증 요약](results/hybrid-validation-summary.json)
- 32 seeds × 5 입력 상태 = **160 teleport transactions**에서 각 상태별 `00/01/10/11` 모두 확인.
  Noiseless fidelity≈1. [분기 검증](results/hybrid-branch-coverage.json)
- 기존 Swap 세 시나리오의 packet/request timing은 정확히 일치한다.
  기존 quantum checkpoint와의 최대 오차는 **8.33×10⁻¹⁷**.
  [동등성 검증](results/hybrid-swap-equivalence.json)
- 별도 NetSquid subprocess의 native memory + Bell projection reference와 비교한다.
  기본 단독/혼합/Swap 재실행 및 fast-BSM 결과의 최대 상태 오차는 검증 요약에 기록한다.
- ready-first / ctrl-first, 중복 요청·완료·packet, invalid bit/session, stopped app의 late result,
  callback 내부 stop을 검사한다. 기존 native teleportation도 동작한다.
- mixed R FIFO와 추가 fast-BSM 사례의 **B FIFO + 실제 결과 packet queueing**까지 확인했다.
- 모든 정상 run에서 native Q2NS state/qubit=0, packet drop=0.
  의도적 overflow는 실패 report로 보존한다.

기본 mixed 실행([설정](scenarios/hybrid-mixed.json), [결과](results/hybrid-mixed.json)):

| Session | Protocol | R wait (ms) | Correction 완료 (ms) |
|---|---|---:|---:|
| 1 | Swap | 0 | 4.212000 |
| 2 | Teleport (+i) | 1.589920 | 5.749600 |
| 3 | Swap | 2.400000 | 7.412000 |
| 4 | Teleport (−) | 3.989920 | 8.949600 |

R의 동일 FIFO에서 도착순으로 실행된다. Swap session 하나를 제거했을 때 Teleport 대기가 줄어드는
것도 테스트한다. 서로 다른 output fidelity는 각 protocol의 기준 상태에 대한 값이므로 직접 우열 비교하지 않는다.

## 실행

ns-3 루트에서:

```bash
./ns3 configure
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-hybrid q2ns-test -j 1

/home/ns3/qunet/bin/python contrib/cosim/python/run_hybrid.py \
  contrib/cosim/scenarios/hybrid-teleport.json \
  --output contrib/cosim/results/hybrid-teleport.json

/home/ns3/qunet/bin/python contrib/cosim/python/run_hybrid.py \
  contrib/cosim/scenarios/hybrid-mixed.json \
  --output contrib/cosim/results/hybrid-mixed.json

# 기존 swapping 시나리오도 같은 실행기로 처리한다. protocol 생략 시 swap이다.
/home/ns3/qunet/bin/python contrib/cosim/python/run_hybrid.py \
  contrib/cosim/scenarios/p5-joint-both.json \
  --output contrib/cosim/results/hybrid-swap-joint-both.json

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_hybrid.py -v
build/utils/ns3.47-test-runner-default --suite=q2ns-teleport-external --verbose
```

새 환경의 전체 회귀에는 P0–P5/Q2NS participant와 test-runner 바이너리도 필요하다.
CLI는 명시한 output을 기록한다. 정상 조건에서 validation/reference가 실패하거나 packet drop이
발생하면 실패 사유와 원본 report를 남기고 nonzero 종료한다.

## 주요 파일

- [hybrid_core.py](python/hybrid_core.py): 두 adapter가 실제로 공유하는 clock/FIFO/resource/federation.
- [hybrid_adapters.py](python/hybrid_adapters.py): Swap/Teleport의 자원 구성과 상태 해석.
- [cosim-hybrid.cc](examples/cosim-hybrid.cc): 실제 Q2NS 앱과 UDP/queue/PHY, 완료 통지.
- [run_hybrid.py](python/run_hybrid.py): 공통 실행 진입점.
- [hybrid_validation.py](python/hybrid_validation.py): 독립 FIFO·native app·state/reference 검증.
- [독립 reference](python/netsquid_reference_hybrid.py): 별도 과정에서 네 Bell branch 계산.
- [통합 테스트](tests/test_hybrid.py), [Python 로그](results/hybrid-test-suite.log),
  [기존 회귀 로그](results/hybrid-regression-suite.log), [native 로그](results/hybrid-all-native-test-suite.log).

Q2NS는 별도 저장소다. 새 변경은 [Teleport patch](integrations/q2ns-teleport-external.patch)와
[base/hash manifest](integrations/q2ns-teleport-external.json)로 보존했고 원본 commit에서 재현했다.
새 checkout에는 기존 [Swap patch](integrations/q2ns-swap-external.patch)도 필요하다.
현재 workspace에는 둘 다 적용되어 있으므로 다시 적용하지 않는다.

## 한계와 후속 범위

검증된 것은 고정 배치·IPv4/UDP·pre-created EPR·두 atomic protocol의 공통 실행이다.
Teleport helper/기존 예제를 무수정으로 실행하거나 임의 topology·dynamic EPR·quantum channel을
지원하는 상태는 아니다. 다섯 입력 상태, 최대 64 sessions, 실행 전체에서 유일한 session ID를 사용한다.
다음 구현 범위는 고정 topology에서 **E1: Scheduled EPR Provisioning**이다.
자원 준비 대기와 processor 대기를 분리하고, 실제 상태 생성시각부터 aging을 검증한다.
E1 이후 configurable placement/topology, native quantum channel/generation 순으로 확장한다.
E1은 아직 구현되지 않았으며 이번 v1의 검증 범위에 포함되지 않는다.
