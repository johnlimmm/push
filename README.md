# Hybrid Quantum–Classical Network Simulator

**Q2NS/ns-3의 실제 classical protocol·packet 실행과 NetSquid의 quantum state evolution을 연결하는 공동 시뮬레이터.**

이 저장소는 `johnlimmm`의 hybrid simulator 구현과 검증 결과를 담는다.
기존 **Hybrid v3 (native timed execution)**은 실제 Q2NS **SwapApp**과 **TeleportationApp**을 공통 실행 기반에 연결하고,
두 프로토콜의 혼합 실행에서 classical packet queue와 quantum processor queue가
실제 연산 시각 및 memory aging에 반영되는 것을 검증했다.

BSM과 correction 내부를 실제 NetSquid `QuantumProgram`으로 실행한다.
기존 v2 atomic 실행과 논문 평가 결과는 별도 기준점으로 유지한다.
새 실행 방법과 검증 결과는 [README-NATIVE](contrib/cosim/README-NATIVE.md)에 있다.

**v3 검증·평가: 전체 258개 PASS · 독립 native reference와 최대 density-matrix error 6.66×10⁻¹⁶.**

## 새 실행 경로: Hybrid v4 quantum-channel provisioning

**v4에서는 실제 NetSquid quantum-channel 도착이 자원 준비와 BSM 시작 가능 시각을 결정한다.**
Swap/Teleport의 준비 대기와 shared R FIFO 대기를 분리하고, 이후 native BSM → 실제 ns-3 UDP →
B FIFO/correction을 이어 실행한다. 무손실 전달과 지연 0의 readiness 통지를 명시적으로 가정한다.

**v4 검증: 전체 278개 PASS · 새 평가 96회/192 transaction · 최대 density-matrix error 4.44×10⁻¹⁶.**

[README-PROVISIONED](contrib/cosim/README-PROVISIONED.md) ·
[SPEC](contrib/cosim/SPEC-PROVISIONED.md) · [v4 결과](contrib/cosim/paper/PROVISIONING.md)

v4의 P5-B/실행 비용 평가 계약과 재현 방법은
[README-PROVISIONED-EVALUATION](contrib/cosim/README-PROVISIONED-EVALUATION.md)에 있다.
새 평가 표·그림은 [v4 논문 결과](contrib/cosim/paper/provisioned-v4/RESULTS.md)에 별도로 기록한다.
**v4 평가 완료: 회귀 291개 PASS · P5-B 384 paired cases · 비용 측정 120회 · timing error 0 ns.**

아래 native/P5-B 수치는 보존된 **v3** 평가다. v4 provisioning의 실행·검증 결과는 위 문서에 구분했다.

## 이 프로젝트에서 구현한 것

| 구현 | 역할 | 주요 코드 |
|---|---|---|
| `NativeHybridFederation` / `NativeExecutionCore` | native event calendar에 ns-3 경계를 등록하고 실제 program-done callback으로 완료 전달 | [native_core.py](contrib/cosim/python/native_core.py) |
| Native instruction chain | timed CNOT/H/measurement와 X/I/Z/I, idle·active storage aging | [native_programs.py](contrib/cosim/python/native_programs.py) |
| `HybridFederation` | ns-3와 NetSquid의 다음 이벤트 경계를 맞추고, 요청·완료의 인과 순서를 유지 | [hybrid_core.py](contrib/cosim/python/hybrid_core.py) |
| `HybridExecutionCore` | 정수 ns clock, shared R/B FIFO, session별 요청 식별, 자원 예약·해제 | [hybrid_core.py](contrib/cosim/python/hybrid_core.py) |
| `SwapAdapter` / `TeleportAdapter` | pair+pair→pair와 qubit+pair→qubit의 서로 다른 자원·연산 의미를 공통 core에 연결 | [hybrid_adapters.py](contrib/cosim/python/hybrid_adapters.py) |
| 실제 Q2NS 앱의 외부 실행 연결 | Q2NS가 protocol/UDP를 실행하고 NetSquid에 BSM·correction을 비동기로 요청 | [cosim-hybrid.cc](contrib/cosim/examples/cosim-hybrid.cc), [Q2NS patches](contrib/cosim/integrations/) |
| Native memory aging | 입력 qubit과 EPR을 NetSquid memory에 저장하고 실제 simulation time에 따라 T1/T2 noise 반영 | [adapters](contrib/cosim/python/hybrid_adapters.py) |
| 독립 검증 | packet FIFO·processor timing·자원 격리·causal log와 별도 NetSquid reference의 density matrix 비교 | [validation](contrib/cosim/python/hybrid_validation.py), [reference](contrib/cosim/python/netsquid_reference_hybrid.py) |
| 단순화 모델 비교 | Full Sync 대비 Fixed-Dc / No-Dq-R / Decoupled의 예측 오차 평가 | [P5-B 평가 코드](contrib/cosim/experiments/), [pilot 결과](contrib/cosim/README-P5B.md) |

ns-3, Q2NS, NetSquid 자체는 기존 프로젝트다. 이 저장소의 구현 범위는 그 사이의 실행·시간·자원 연결,
Q2NS 외부 실행 adapter, 시나리오 및 검증·평가 코드다.

## 실행 구조

```mermaid
flowchart TD
    S[Local session start at R] --> R[Q2NS SwapApp / TeleportationApp at R]
    R -->|Async BSM request| H[NativeExecutionCore: shared R FIFO]
    H --> N[NetSquid timed program: CNOT, H, measurements]
    N -->|Completion at simulation time| R
    R -->|Actual Q2NS UDP result / ns-3 queue| B[Q2NS app at B]
    B -->|Async correction request| Q[NativeExecutionCore: shared B FIFO]
    Q --> M[NetSquid timed program: X/I, Z/I]
    M -->|Correction completion| B
```

- **Q2NS/ns-3**: 앱의 protocol 진행, 실제 payload, UDP, packet queue, 전송·전파 지연.
- **공통 core/federation**: 시간 동기화, processor 배정, 자원 lifecycle, 완료 전달과 로그.
- **NetSquid**: 유일한 quantum-state 소유자. Q2NS 외부 session에는 중복 Qubit/QState를 만들지 않는다.

각 physical instruction은 지정된 duration 동안 native processor를 점유한다.
대기시간과 instruction 실행시간의 T1/T2 aging을 반영하고, 실제 program 완료가
다음 packet을 생성한다. 합계 duration을 같은 값으로 맞춰도 atomic 모델과 noisy state가
달라질 수 있으므로 두 모델은 각각 독립 reference로 검증한다.

## 현재 실행할 수 있는 시나리오

| 시나리오 | 내용 | 설정 |
|---|---|---|
| Native Teleportation | 입력 qubit + EPR, timed BSM, 실제 결과 packet, timed correction | [native-teleport.json](contrib/cosim/scenarios/native-teleport.json) |
| Native Mixed | Swap·Teleport가 같은 R/B processor를 공유하고 서로 대기시킴 | [native-mixed.json](contrib/cosim/scenarios/native-mixed.json) |
| Joint contention | 여러 Swap session의 quantum FIFO와 classical background traffic 결합 | [hybrid-swap-joint-result.json](contrib/cosim/scenarios/hybrid-swap-joint-result.json) |
| Simplification pilot | 네 실행/근사 모델을 동일 workload 조건에서 비교 | [native-p5b-pilot.json](contrib/cosim/scenarios/native-p5b-pilot.json) |

기본 Mixed 실행의 R 대기시간은 session 순서대로 **0 / 1.6 / 2.4 / 4.0 ms**다.
추가 fast-BSM 테스트에서는 B correction FIFO의 protocol 간 경합도 검증한다.

## Native 검증·평가

- **Python 159개 + 평가/timing/계측 16개 + Q2NS native 83개 = 258개 PASS**.
- 5개 Teleport 입력 상태 × 32 seeds에서 네 BSM branch를 확인했다.
- Native P5-B pilot 48조건과 확대 384조건을 같은 instruction/noise 설정으로 실행한다.
- 논문용 결과는 [P5-B 평가](contrib/cosim/README-P5B.md),
  [표·CI·그림](contrib/cosim/paper/RESULTS.md), [재현 절차](contrib/cosim/README-PAPER-VALIDATION.md)를 따른다.
- [전체 native 평가 요약](contrib/cosim/results/native-paper-validation-summary.json)
- 과거 atomic 수치는 [논문 산출물](contrib/cosim/baselines/atomic-v2-paper.tar.gz)과
  [실행 원자료](contrib/cosim/baselines/direct-start-v2-results.tar.gz)에 보존했다.

현재 topology는 **A/R/B**다. `session_start_ns`에 R의 Q2NS 앱이 BSM을 요청하며,
classical 통신은 실제 **R→B result UDP**다. Latency는 local session start부터 correction 완료까지다.

P0–P5-A/초기 Q2NS는 과거 command-path 구조의 regression fixture로 보존한다.
[Hybrid v1 release 기록](contrib/cosim/releases/hybrid-v1/)과
[v1 archive](contrib/cosim/baselines/hybrid-v1-freeze.tar.gz)는 이전 버전의 결과이며 현재 수치와 구분한다.

## 빠른 실행

검증 환경: **ns-3.47 / Python 3.7.17 / NetSquid 1.1.7 / NumPy 1.21.6**.
NetSquid가 설치된 Python 환경을 별도로 준비해야 한다. 이 저장소에 NetSquid를 재배포하지 않는다.

### 1. Q2NS 준비 — 새 checkout에서 한 번

저장소 루트에서 실행한다. 현재 개발 workspace에는 이미 적용되어 있으므로 재적용하지 않는다.

```bash
git clone https://github.com/QuantumInternet-it/q2ns.git contrib/q2ns
git -C contrib/q2ns checkout --detach f22ba28f437099ba3cf9956ca332ba5ce8bb14fd
git -C contrib/q2ns apply ../cosim/integrations/q2ns-swap-external.patch
git -C contrib/q2ns apply ../cosim/integrations/q2ns-teleport-external.patch
```

### 2. 빌드 및 Mixed 실행

```bash
./ns3 configure --enable-examples --enable-tests
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-hybrid -j 1

# 자신의 NetSquid 환경에 맞게 Python 경로를 지정한다.
COSIM_PYTHON=/home/ns3/qunet/bin/python
"$COSIM_PYTHON" contrib/cosim/python/run_native_hybrid.py \
  contrib/cosim/scenarios/native-mixed.json \
  --output /tmp/native-mixed.json
```

`run_native_hybrid.py`가 ns-3 participant를 시작하고 IPC와 native federation 실행을 관리한다.
Teleport 단독 실행은 설정을 `native-teleport.json`으로 바꾸면 된다.
Atomic 기준점은 기존 `run_hybrid.py`로 실행한다.
전체 회귀를 위한 추가 build target과 재현 절차는 [release 문서](contrib/cosim/RELEASE-HYBRID-V1.md)에 있다.

```bash
# 과거 v1 archive 검증 (현재 v2 source는 의도적으로 변경됨)
python3 contrib/cosim/tools/verify_hybrid_v1.py --archive-only

# 현재 구조를 포함한 전체 회귀
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_native_timed.py
/home/ns3/qunet/bin/python contrib/cosim/tools/summarize_native_timed.py
```

## 코드와 문서 읽는 순서

1. [README-NATIVE](contrib/cosim/README-NATIVE.md), [SPEC-NATIVE](contrib/cosim/SPEC-NATIVE.md): native 실행·noise·동기화 계약.
2. [run_native_hybrid.py](contrib/cosim/python/run_native_hybrid.py) → [native_core.py](contrib/cosim/python/native_core.py): 실제 federation 흐름.
3. [native_programs.py](contrib/cosim/python/native_programs.py) / [native_adapters.py](contrib/cosim/python/native_adapters.py): timed 연산과 protocol 자원 연결.
4. [reference](contrib/cosim/python/netsquid_reference_native.py) / [tests](contrib/cosim/tests/test_native_hybrid.py): 독립 native state/time 검증.
5. [README-HYBRID](contrib/cosim/README-HYBRID.md), [SPEC-HYBRID](contrib/cosim/SPEC-HYBRID.md): 보존된 atomic 기반의 시간·자원·adapter 계약.

`contrib/cosim/README.md` 및 이전 milestone 문서는 당시의 기준점을 기록한 문서다.
P0–P5-B의 구현·결과도 함께 보존하며, 진입점은 이 README, README-NATIVE(v3), README-PROVISIONED(v4)다.

## 지원 범위와 다음 단계

**v3 지원 범위:** 고정 A/R/B 배치, IPv4/UDP, t=0에 생성한 input/EPR,
직렬 timed BSM/correction, shared capacity-one R/B FIFO, native T1/T2 aging.
Gate duration은 설정 가능한 모델 값이며 하드웨어 실측값이 아니다.

**v4 추가 범위:** 실제 NetSquid Network/Node/QuantumChannel를 통한 EPR half 전달,
준비 완료 callback과 BSM eligibility, channel depolarization 및 이동/저장 noise 구분.

임의 topology, 물리적 photon source·heralded EPR generation, loss/retry, 실제 readiness ACK,
모든 Q2NS 예제의 무수정 실행은 아직 지원하지 않는다. 각 버전의 범위와 결과는 별도로 기록한다.

## 기반 프로젝트와 라이선스

- [ns-3](https://www.nsnam.org/): classical network simulator. 원본 설명은 [README-NS3.md](README-NS3.md)에 보존한다.
- [Q2NS](https://github.com/QuantumInternet-it/q2ns): quantum-network protocol 앱과 논리 자원 계층.
- [NetSquid](https://netsquid.org/): quantum state 및 native memory evolution.

ns-3 기반 소스를 함께 포함하며 원본의 라이선스와 저작자 표기를 유지한다.
이 저장소의 Git 이력은 프로젝트 게시용 단일 snapshot에서 시작한다.
게시 commit의 작성자가 포함된 upstream 소스 전체의 원저자라는 뜻은 아니다.
라이선스는 [LICENSE](LICENSE)를 참고한다.
