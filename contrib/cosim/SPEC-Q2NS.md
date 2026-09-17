# Q2NS SwapApp 최소 연동

## 완료 목표

P5-A의 실제 packet/R FIFO와 native NetSquid memory aging을 유지하면서
Q2NS `SwapApp`의 요청·결과 송신·결과 수신·보정 완료까지 연결한다.
Q2NS의 전체 quantum backend를 교체하는 작업이 아니다.

```text
Controller CosimAgentApp ─UDP command→ R CosimAgentApp
                                         ↓ 실제 수신시각
                                  Q2NS SwapApp.RequestExternalBsm
                                         ↓ 논리 EPR 매핑
                                  Federation → NetSquid BSM
                                         ↓ 완료시각
                                  Q2NS SwapApp.CompleteExternalBsm
                                         ↓ 기존 AnnounceBsm/UDP socket
                                  실제 result link / packet FIFO
                                         ↓
                                  B Q2NS PacketSink → SwapApp.OnCtrlRx
                                         ↓ FrameResolved / TryApply
                                  Federation → NetSquid correction
                                         ↓ 완료시각
                                  Q2NS SwapApp.CompleteExternalCorrection
```

## 상태와 자원 소유권

- 실제 Q2NS `QNode`와 `SwapApp`을 사용한다.
- `AddExternalSession`은 session-local 논리 EPR handle만 등록한다.
  어댑터에서 `(sid,101/102/103)`을 NetSquid `(sid,1/2/3)`으로 매핑한다.
- NetSquid가 EPR 생성, memory aging, BSM, Pauli correction과 density matrix를 소유한다.
- 외부 session은 Q2NS의 `CreateBellPair`, `MeasureBell`, `Apply`를 호출하지 않는다.
  매 ns-3 boundary에서 Q2NS registry가 비어 있는지 검사하고 종료 시 state/qubit 수를 보고한다.
- mapping은 앱의 논리 handle이다. Q2NS 내장 Qubit ID라고 표현하지 않는다.
- 기존 Q2NS `AddSession`의 quantum 생성/연산 경로는 유지한다.

## 최소 API 계약

`SwapApp`에 opt-in API를 추가한다. 별도 co-sim 의존성은 Q2NS 라이브러리에 넣지 않는다.

- `SetExternalQuantumCallbacks`: BSM/correction 요청 callback 설치.
- `SetExternalPacketObservers`: 실제 송신 직전/수신 후 packet 관측. bridge metadata tag 부착용.
- `AddExternalSession`: 앱 시작 전 등록, 양수·서로 다른 EPR ID, 중복 session 금지.
- `RequestExternalBsm`: 실제 command 수신시각에 1회 요청. native quantum 실행은 하지 않는다.
- `CompleteExternalBsm`: pending 요청의 측정 bit를 받고 기존 Q2NS packet 송신 경로를 실행.
- `CompleteExternalCorrection`: pending 보정이 끝났을 때만 `CorrectionApplied` trace 발생.

외부 경로는 단일 repeater/IPv4/UDP/expectedMsgs=1만 허용한다.
quantum link 생성 플래그, 내장 fidelity verification, TCP/IPv6, 다중 repeater는 거절한다.
외부 요청은 command로 구동되므로 `SessionConfig.start`의 자동 quantum 실행을 사용하지 않는다.

중복 BSM 요청/같은 completion은 실행을 반복하지 않고 false를 반환한다.
다른 bit의 중복 completion, pending 없는 completion, 잘못된 역할/ID/bit는 예외다.
endpoint의 중복 결과 packet은 다시 XOR하거나 correction을 요청하지 않는다.
이 버전은 취소/실패 회복 프로토콜을 추가하지 않으며 drop은 correctness 실패로 보존한다.

## 실제 packet과 계측

- command/background는 P5와 동일한 참가자 형식이다.
- result payload는 **기존 Q2NS packed CtrlHeader(sid,m1,m2)** 10 bytes + padding이다.
- 동일 payload 크기일 때 wire bytes는 P5와 동일하다(IPv4/UDP/PPP 30 bytes 추가).
- ns-3 PacketTag에는 trace 식별자만 담는다. wire byte와 simulation delay에 포함되지 않는다.
  실제 payload를 다시 읽어 sid/bit가 tag 및 SwapApp 수신 callback과 일치하는지 검사한다.
- result 송수신을 CosimAgentApp에서 대신 수행하지 않는다. Q2NS의 UDP socket과 PacketSink를 통과한다.
- 기존 Q2NS header serialization은 유지한다. 이 범위는 동일 로컬 ns-3 프로세스의 simulation이다.

## federation과 결과 검증

P5-A 소스는 수정하지 않고 별도 `cosim-q2ns` 참가자/runner를 둔다.
quantum scheduler는 P3, packet/quantum FIFO 검증은 P5, 독립 state reference는 P2를 재사용한다.
BSM뿐 아니라 correction 완료도 같은 timestamp의 다음 ns-3 round로 주입한다.

기존 v1 `events`와 `packet_events`를 유지하고 `q2ns_events`를 추가한다:

1. Q2NS_BSM_REQUEST = COMMAND_RX
2. Q2NS_BSM_DONE = BSM completion
3. Q2NS_CTRL_SENT = 실제 result 송신
4. Q2NS_FRAME_RESOLVED = 실제 result 수신
5. Q2NS_CORRECTION_REQUEST = 실제 result 수신
6. Q2NS_CORRECTION_APPLIED = correction completion

session별 각 native event의 시각, 인과관계, bit, 논리 EPR mapping을 검사한다.
`q2ns_status`는 native state/qubit 수(0), session 수, correction 완료 횟수를 담는다.
`q2ns_validation.resource_mapping`은 양쪽 논리 ID와 NetSquid memory 위치의 관계를 기록한다.

정상 실행은 다음을 모두 만족해야 한다:

- P5의 독립 FIFO/자원/clock/reference 검증 PASS.
- 동일 설정 P5-A와 실제 packet 시각·quantum state·metric 일치.
- B correction wait=0, packet drop=0.
- 모든 session에서 Q2NS correction 완료가 정확히 1회, 즉시 보정 완료로 처리하지 않음.
- Q2NS state/qubit 0: NetSquid 외부에 중복 상태 없음.
- noise-off Bell 복원과 네 BSM branch의 native packet 전달 검증.
- 기존 Q2NS 내장 BSM/Pauli 경로와 P0–P5 회귀 검사 유지.

이 완료는 단일 repeater SwapApp 경계의 실제 연결이다. Q2NS topology helper, native quantum
channel, 동적 EPR 생성, TCP/IPv6 전체 통합 및 P5-B 단순화 비교는 별도 범위다.
