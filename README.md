# QuCl — Hybrid Quantum–Classical Network Simulator

**Q2NS/ns-3의 실제 protocol·packet 실행과 NetSquid의 quantum state·timed operation을 연결한다.**
현재 종단 간 시나리오는 **R에서 swapping → 생성된 A–B 얽힘을 사용해 A에서 B로 teleportation**이다.
두 protocol은 공통 시간 동기화와 quantum 실행 기반을 사용하며, 같은 qubit의 상태와 저장 이력을 이어간다.

[현재 구현과 실행](contrib/cosim/README-CHAINED.md) ·
[실행 계약](contrib/cosim/SPEC-CHAINED.md) ·
[최신 평가·그림](contrib/cosim/paper/evaluation/RESULTS.md) ·
[논문 평가절](contrib/cosim/paper/evaluation/evaluation.tex)

## 현재 실행 구조

A는 Alice, R은 repeater, B는 Bob이다. 별도 Controller 노드나 첫 연산을 위한 synthetic command packet은 없다.

```text
NetSquid: A–R / R–B EPR 전달 → memory 배치
                         ↓
R의 local session start + 자원 준비
 → R FIFO → native swapping BSM
 → 실제 Q2NS R→B UDP 결과 → B FIFO → native correction
 → 실제 B→R→A 준비 완료 UDP
 → A FIFO → native teleportation BSM (기존 A–B pair 소비)
 → 실제 Q2NS A→R→B UDP 결과 → B FIFO → native correction
 → B의 최종 상태 및 fidelity
```

양자 연산 완료시각이 다음 packet의 생성시각을 결정하고, packet 도착이 다음 양자 연산을 허용한다.
Processor 대기와 network queueing은 실제 실행시각 및 memory aging에 함께 반영된다.
여러 workflow는 A/R/B processor와 classical links를 공유한다. B correction FIFO에는 두 protocol의 요청이 들어간다.

| 계층 | 담당하는 것 | 구현 |
|---|---|---|
| Q2NS/ns-3 | SwapApp·TeleportationApp, 실제 payload/UDP, queueing·전파, 준비 완료 통신 | [cosim-chained.cc](contrib/cosim/examples/cosim-chained.cc), [Q2NS patches](contrib/cosim/integrations/) |
| 공통 실행·동기화 | native event 경계, FIFO, 요청·완료 전달, protocol별 자원 lifecycle | [native_core.py](contrib/cosim/python/native_core.py), [chained_core.py](contrib/cosim/python/chained_core.py) |
| NetSquid components | node/channel 전달, memory, timed CNOT/H/measurement/correction, T1/T2 | [quantum_network_backend.py](contrib/cosim/python/quantum_network_backend.py), [native_programs.py](contrib/cosim/python/native_programs.py) |
| 검증 | packet·processor FIFO, qubit handoff, 독립 circuit의 state/time 비교 | [chained_validation.py](contrib/cosim/python/chained_validation.py), [tests](contrib/cosim/tests/) |
| 평가 | 문헌 기반 파라미터, 여섯 입력, Full Sync 및 단순화 모델 비교 | [평가 runner](contrib/cosim/experiments/run_memory_evaluation.py), [설정](contrib/cosim/scenarios/memory-evaluation.json) |

NetSquid가 quantum state를 단독 소유한다. 외부 실행 session에 Q2NS의 별도 Qubit/QState를 만들지 않는다.
Swapping 출력은 동일한 A/B qubit 객체로 teleportation에 전달되며, 새 EPR로 교체하지 않는다.
연산 내부는 NetSquid `QuantumProgram`/`PhysicalInstruction`으로 실행하고 실제 완료 callback을 사용한다.
Fidelity도 NetSquid의 `fidelity(..., squared=True)`로 계산한다. 분기 확률 가중과 통계 집계는 평가 코드에서 수행한다.

## 빠른 실행

검증 환경: **ns-3.47 / NetSquid 1.1.7 / Python 3.7.17 / NumPy 1.21.6**.
NetSquid 설치 환경은 별도로 준비한다. 이 저장소에 NetSquid를 재배포하지 않는다.

새 checkout에서는 ns-3 루트에서 Q2NS를 준비한다. 기존 개발 workspace에는 이미 patch가 적용되어 있다.

```bash
git clone https://github.com/QuantumInternet-it/q2ns.git contrib/q2ns
git -C contrib/q2ns checkout --detach f22ba28f437099ba3cf9956ca332ba5ce8bb14fd
git -C contrib/q2ns apply ../cosim/integrations/q2ns-swap-external.patch
git -C contrib/q2ns apply ../cosim/integrations/q2ns-teleport-external.patch

./ns3 configure --enable-examples --enable-tests
./ns3 build cosim-chained cosim-provisioned -j 1

# 자신의 NetSquid Python 경로로 지정한다.
COSIM_PYTHON=/home/ns3/qunet/bin/python
"$COSIM_PYTHON" contrib/cosim/python/run_chained.py \
  contrib/cosim/scenarios/chained-single.json \
  --output contrib/cosim/results/chained-single-new.json.gz --enumerate-branches
```

이 명령은 기본 chain 예제를 실행한다. **최신 논문 파라미터를 사용한 전체 평가는 별도 설정·runner로 실행한다.**

```bash
"$COSIM_PYTHON" contrib/cosim/experiments/run_memory_evaluation.py \
  contrib/cosim/scenarios/memory-evaluation.json \
  --output-dir contrib/cosim/results/memory-evaluation-new
```

완료된 평가 디렉터리는 덮어쓰지 않는다. 그림 생성·원자료 복원·전체 회귀는
[현재 작업 정리](contrib/cosim/CURRENT.md)를 따른다.

## 검증과 최신 평가

- 이번 게시 준비에서 **Python 구현 196개 + 평가 44개 + Q2NS native 83개 = 323개**를 새로 실행해 모두 통과했다.
- 실제 packet FIFO와 native processor FIFO, 요청·완료 인과관계, 자원 단일 소비를 검증한다.
- 여섯 입력 `0, 1, +, -, +i, -i`와 두 BSM의 16개 joint outcome을 검증한다.
- Native instruction 및 protocol checkpoint에서 별도 NetSquid circuit과 상태를 비교한다.
- 현재 문헌 파라미터 평가: **147개 workload 조건, chain 882회와 swapping 비교 441회, 별도 calibration 13회**.
- 최대 reference density-matrix error는 **9.99×10⁻¹⁶**다.

최신 [평가 패키지](contrib/cosim/paper/evaluation/)에는 원고, Fig. 3–5, CSV, 출처·해시가 있다.
게이트·측정 시간과 T1/T2의 출처 및 적용 가정은 [물리 모델](contrib/cosim/paper/PHYSICAL-MODEL.md)에 정리했다.
여러 문헌의 파라미터를 결합한 추상 모델이며 특정 장치의 보정된 재현 모델은 아니다.

## 지원 범위

**현재 지원:** 고정 A/R/B topology, IPv4/UDP, t=0 input/EPR 생성과 native quantum-channel 전달,
native timed BSM/correction, processor FIFO, T1/T2 aging, Swap→Teleport 자원 전달,
혼잡 및 단순화 오차 평가. 기존 독립 Swap/Teleport 혼합 실행도 회귀 기준으로 유지한다.

**현재 범위 밖:** 임의 topology와 routing, 확률적 photon generation/heralding, loss/retry,
모든 Q2NS 예제의 무수정 실행. Elementary EPR delivery의 준비 통지는 R에 지연 0으로 가정하며,
swapping 이후 A에 전달하는 준비 통지는 실제 UDP로 실행한다.

## 이전 기준점

기존 구현·결과는 회귀와 비교를 위해 보존한다. 과거 문서의 수치는 최신 논문 평가와 구분한다.

| 단계 | 보존 내용 |
|---|---|
| P0–P5 / Q2NS / Hybrid v1 | 동기화, aging, classical·quantum 경합, adapter 및 atomic 실행 검증: [기록](contrib/cosim/releases/hybrid-v1/) |
| Native v3 | timed instruction chain과 native event 동기화: [문서](contrib/cosim/README-NATIVE.md) |
| Provisioned v4 | native channel 전달과 resource readiness: [문서](contrib/cosim/README-PROVISIONED.md) |
| Chained v5 | 실제 swapped pair로 A→B teleportation: [문서](contrib/cosim/README-CHAINED.md) |
| 이전 평가 | [controlled](contrib/cosim/paper/evaluation-controlled/), [long-memory](contrib/cosim/paper/evaluation-long-memory/), [현재 평가 안내](contrib/cosim/paper/LATEST.md) |

모듈의 초기 [README](contrib/cosim/README.md)와 [v3 RESULTS](contrib/cosim/paper/RESULTS.md)는 당시의 검증 기준점이다.
현재 진입점은 이 문서와 [CURRENT](contrib/cosim/CURRENT.md)다.

## 기반 프로젝트와 라이선스

- [ns-3](https://www.nsnam.org/): classical network simulator. 원본 안내는 [README-NS3.md](README-NS3.md)에 보존한다.
- [Q2NS](https://github.com/QuantumInternet-it/q2ns): protocol 앱과 논리 자원 계층.
- [NetSquid](https://netsquid.org/): quantum state, components 및 timed execution.

이 저장소의 구현 기여는 세 시스템 사이의 시간·자원·실행 연결, Q2NS 외부 실행 adapter,
시나리오와 검증·평가 코드다. ns-3 기반 소스의 라이선스와 저작자 표기는 유지한다.
게시용 Git 이력은 프로젝트 snapshot에서 시작하며, 게시 commit 작성자가 upstream 소스 전체의
원저자라는 뜻은 아니다. [LICENSE](LICENSE)를 참고한다.
