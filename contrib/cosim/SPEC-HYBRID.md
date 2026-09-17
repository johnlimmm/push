# Multi-Protocol Hybrid Execution — Teleportation Integration

## 목표와 완료 조건

실제 Q2NS SwapApp과 TeleportationApp이 동일 federation, processor FIFO, 자원 예약 및
NetSquid 장치를 사용함을 검증한다. 단독 teleport 성공, 기존 Swap 기준과의 동등성,
두 protocol 혼합 실행이 모두 필요하다. 범용 topology/모든 Q2NS 예제 지원을 뜻하지 않는다.

## 실행 범위

- C(Controller), A, R, B 고정 배치. Teleport의 Alice 역할은 **R**에 둔다.
- Controller→R UDP command가 session 실행을 요청한다. R→B는 실제 Q2NS 결과 UDP다.
- Swap 결과 payload는 설정값(기본 80 bytes), Teleport는 기존 앱 그대로 2 bytes.
- IPv4/UDP, 미리 준비한 noiseless EPR, atomic BSM/correction. Memory noise만 native T1/T2.
- session ID는 실행 전체에서 유일한 양의 정수, logical resource handle은 session-local이다.
- `input_created_ns`와 `epr_created_ns`는 독립 필드지만 이번 범위에서는 각각 0만 허용한다.
- 세션별 두 R position과 한 B position을 배정한다. Swap은 A position도 하나 사용한다.
- shared R/B processor는 각각 capacity=1, FIFO이다. Mixed에서는 B FIFO 대기도 허용·검증한다.
- packet drop은 정상 결과로 받지 않는다. overflow 시 실패 report를 남긴다.

## Core / adapter 계약

`HybridExecutionCore`는 clock, processor FIFO, request identity, reservation, 완료와 로그를 담당한다.
`HybridFederation`은 두 protocol에 공통인 실행 루프 하나다. 두 adapter가 같은 인스턴스에 등록된다.

| Adapter | 입력 handle과 자원 | 출력 | Q2NS handle |
|---|---|---|---|
| SwapAdapter | left_pair + right_pair | A–B pair | 101/102/103 |
| TeleportAdapter | input qubit + epr pair | B qubit | 201/202/203 |

core의 request는 session, operation(BSM/CORRECTION), processor, resource handles,
physical targets, duration, cause, packet measurement bits로 구성된다.
(실제 자원 의미와 초기 상태/출력 검증은 adapter가 정의한다.)

자원은 AVAILABLE 또는 FRAME_PENDING → RESERVED → IN_USE → CONSUMED 또는 USABLE로 전이한다.
BSM이 소비한 입력과 생존 qubit의 output handle을 구분한다. 새로운 output state를 복사하거나
EPR을 재생성하지 않는다. 실제 NetSquid qubit identity와 native memory 위치를 유지한다.

현재 ns-3 trace wire framing은 기존 참가자의 포맷을 재사용한다. Teleport row의 legacy pair
필드는 0이며 quantum request에 사용하지 않는다. 공통 quantum log는 `resource_handles`를 쓴다.
별도 PacketTag는 계측에만 사용하며 bits는 Q2NS 실제 UDP payload에서 읽는다.
Teleport는 session별 포트를 사용한다. Swap의 기존 sid 포함 header는 변경하지 않는다.

## 시간 규약

각 경계 t에서:
1. t까지 quantum clock 진행, t의 실행 중 연산 완료를 commit.
2. ns-3의 t 이벤트를 모두 처리하고 실제 app request를 수집.
3. request 접수 및 자원 예약.
4. 각 processor의 FIFO dispatch.
5. completion을 해당 Q2NS 앱에 t로 주입. 같은 시각 다음 round에서 앱이 결과 packet/trace를 생성.

다음 경계는 min(ns-3 next event, quantum completion). 정수 ns, 최대 2^53−1.
자율적인 미래 NetSquid channel/program 이벤트는 지원하지 않으며 감지 시 실패한다.
실제 native timed QuantumProgram/gate noise가 아니다. 연산 duration 동안 memory noise가
누적되고, 완료 시 physical=False BSM 또는 Pauli를 한 번 적용한다.
00도 동일 correction duration을 차지하며 완료 시 memory를 peek해 aging을 반영한다.

## 실제 TeleportationApp 외부 실행

`ConfigureExternal`, `NotifyExternalResourcesReady`, `RequestExternalBsm`,
`CompleteExternalBsm`, `CompleteExternalCorrection`을 사용한다.
앱은 input/EPR 준비, 실행 요청, ctrl 수신, pending/done을 직접 관리한다.
Q2NS 외부 session은 native Qubit/QState를 만들지 않으며 `SetTeleportState`를 호출하지 않는다.
기존 native 모드는 유지한다.

- source: 실행 요청 + session active + resources ready → BSM request 1회.
- Bob: resources ready + 유효 ctrl 수신 → correction request 1회.
- ready와 ctrl은 독립 조건이며 어느 순서로 와도 동작한다.
- 알 수 없는 session, 잘못된 bit/role, unsolicited/duplicate completion은 거부한다.
- duplicate packet은 재보정을 만들지 않는다. stopped app은 late packet/completion을 무시한다.
- Rx callback 내부에서 StopApplication이 호출되는 경우에도 callback 해제를 안전하게 지연한다.
- 실제 correction 완료 통지 후에만 SinkCorrection trace가 발생한다.

BSM: CNOT(input, Alice_EPR), H(input), Z 측정(input,Alice_EPR).
m1=첫 번째 측정(Z frame), m2=두 번째 측정(X frame).
Bob correction: 00→I, 01→X, 10→Z, 11→X 다음 Z (행렬 ZX).

## 검증

- T1: |0>, |1>, |+>, |−>, |+i> 각각 모든 4개 측정 branch. Noise off F≈1, 허용 오차 1e−12.
- T2: 입력/EPR의 BSM start·end 상태, frame, packet arrival, correction start·완료 상태 비교.
  Native T1/T2 memory + Bell projection으로 계산하는 별도 NetSquid subprocess를 사용한다.
  Co-sim gate/measurement 함수를 재사용하지 않는다. 관측 branch에 조건화하여 비교한다.
  같은 seed로 branch가 같을 것이라 가정하지 않는다. 네 branch 확률 합도 확인한다.
- T3: 준비 순서, 실제 2-byte UDP timing, 잘못된 bit/session, 중복, stopped callback, native ownership=0.
- T4: 기존 122개 P0–P5-B/Q2NS Python 테스트와 기존 Q2NS native suite를 유지한다.
- 기존 Swap 세 시나리오를 새 core로 재실행: request/packet timing과 각 state checkpoint가 일치해야 한다.
- Mixed: 동일 R/B FIFO, 다른 memory positions, 올바른 adapter로 결과 반환, protocol 간 대기 영향.
- Packet enqueue/dequeue/PHY/app timing을 설정 기반 독립 FIFO와 비교한다.
- 결과는 correction 완료 시 저장한다. 후속 traffic drain으로 역사적 fidelity를 재평가하지 않는다.

기존 구현은 freeze archive에 보존한다. 신규 core는 두 구체 protocol에 필요한 공통부만 구현하며,
기존 frozen 실행기와 비교한다. 현재 결과만으로 임의 operation/topology 또는 모든 Q2NS 예제의
무수정 실행을 주장하지 않는다.
