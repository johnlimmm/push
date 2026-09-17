# P1: 하나의 A–R–B noiseless swapping transaction

P0의 시간 경계·FIFO·자원 규약을 유지하면서 실제 UDP 패킷 경로와 endpoint 보정을
연결한다. P0 회귀 테스트 14개와 `tests/test_p1.py`를 함께 실행한다.

**상태: P1 종료.** 2026-09-16에 로그 자원 의미와 정수 시각 저장을 정리한 뒤
P0 14개 + P1 13개, 총 27개 테스트를 다시 실행해 모두 통과했다.
P1 테스트에는 32회 transaction의 네 BSM 분기와 각 실행의 독립 reference 비교가 포함된다.

## 실행

ns-3 루트에서 NetSquid 가상환경의 Python을 사용한다.

```bash
./ns3 configure --enable-examples --enable-tests
./ns3 build cosim-p0 cosim-p1 -j 2
~/qunet/bin/python contrib/cosim/python/run_p1.py \
  contrib/cosim/scenarios/p1-swapping.json \
  --output contrib/cosim/results/p1-swapping.json
~/qunet/bin/python -m unittest discover -s contrib/cosim/tests -v
```

`run_p1.py`는 transaction 실행, 독립 시간 검증, 별도 프로세스의 NetSquid-only
reference 비교를 모두 수행한다. 어느 단계든 실패하면 정상 결과로 보고하지 않는다.
다른 빌드 경로는 `--ns3-binary /절대/경로/cosim-p1`로 지정한다.

## 1. 고정한 범위와 소유권

- 노드 ID: Controller=0, A=1, R=2, B=3. 양자 프로세서 ID는 R=2, B=3.
- session마다 BSM request=1, correction request=2, 입력 AR pair=1, RB pair=2, 출력 AB pair=3.
  ID의 범위는 session 안이다. 여러 transaction을 한 번에 실행하는 모델은 지원하지 않는다.
- 두 입력 EPR은 시각 0에 실제 NetSquid Bell 상태 `Phi+`로 생성한다.
- AR 위치: A memory의 0번과 R processor의 0번. RB 위치: R processor의 1번과 B processor의 0번.
- 실제 양자 상태는 NetSquid가 소유한다. ns-3는 요청·결과 비트만 다룬다.
- A는 자신의 큐빗을 보관한다. B만 `X`(m2=1), 이어서 `Z`(m1=1)를 수행한다.
- BSM과 correction은 각각 **양의 고정 정수 ns 동안 점유한 뒤 완료 시 상태를 바꾸는 원자적 연산**이다.
  `00`도 같은 correction duration을 소비한다. native timed QuantumProgram은 co-sim에서 사용하지 않는다.
- 메모리/게이트/채널 잡음, EPR 생성 프로토콜, 만료, 손실, background traffic은 없다.
- Q2NS QState/SwapApp과 q2nsviz 연결은 포함하지 않는다.

## 2. 실제 고전 경로

```text
Controller -- IPv4/UDP, PointToPoint --> R CosimAgentApp
                                          |
                                    BSM request/complete
                                          |
R CosimAgentApp -- IPv4/UDP, PointToPoint --> B CosimAgentApp
                                                 |
                                       correction request/complete
                                                 |
                                             AB: USABLE
```

두 링크는 직접 연결하며 UDP port는 9000이다. A로의 결과 통지와 Controller ACK는 없다.
P1의 session 완료는 **B 보정 완료**로 정의한다. A/Controller가 완료를 알고 있다는 보장은 하지 않는다.

앱의 `SendUdp()`/UDP 수신 콜백과 장치의 `PhyTxBegin`/`PhyRxEnd`를 기록한다.
`COMMAND_RX`와 `RESULT_RX`는 앱 콜백 시각이다. 최초 명령 송신만 시나리오가 예약한다.
명령 도착과 결과 도착은 실제 ns-3 protocol stack과 링크가 결정한다.
양자 완료의 IPC 전달 시간은 simulation time에 더하지 않는다.

Packet header는 60 bytes이며 version, kind, session, BSM request, message, AR/RB/AB ID,
m1/m2, 송신 이벤트 sequence를 포함한다. padding을 포함한 앱 payload는 60~1400 bytes다.
IPv4 options/fragmentation 없이 UDP 8 + IPv4 20 + PPP 2 bytes가 추가된다.
`PHY_TX`/`PHY_RX`에 기록한 크기로 실제 헤더 포함 길이도 검사한다.

장치는 128-packet DropTail FIFO, interframe gap=0을 사용한다. 주소 할당이 자동 설치하는
상위 AQM은 제거한다. 원본 결과 1개 + 최대 재전송 100개가 큐 용량을 넘지 않는다.
이는 혼잡 실험이 아니라, P1의 명시적인 무손실 경로를 유지하기 위한 제한이다.

## 3. 시간 규약과 독립 예상값

P0의 처리 단계는 유지한다.

1. 현재 경계의 BSM/correction 완료 확정
2. 해당 시각의 ns-3 이벤트를 UID 순서로 모두 처리
3. 도착한 BSM/correction 입력 반영
4. 빈 프로세서 배정
5. BSM 결과를 같은 시각의 R 앱 이벤트로 주입

같은 시각의 추가 이벤트는 다음 causal round로 처리한다. 시각을 1 ns 밀지 않는다.
진행 한계는 모든 BSM 완료와 correction 완료 중 최소값이며, 현재까지 받은 입력으로 매번 갱신한다.
NetSquid native timeline의 미래 이벤트가 비어 있다는 P0 어댑터 전제를 유지한다.

무부하 단일 패킷의 전송시간은 `8 * (payload_bytes + 30) / rate_bps` 초다.
`p1_validation.py`는 설정값만으로 정수 ns 예상값을 계산하며, ns-3 trace로 정답을 만들지 않는다.
소수 ns는 반올림한다. Q64 표현에서 반올림 방향이 모호해지는 정확한 half-ns 입력과
0 ns로 반올림되는 전송시간은 P1 설정 단계에서 거절한다.
모든 경계는 `[0, 2^53-1]` 안에 있어야 한다.
보고서의 `snapshot.netsquid_time_ns`는 유한성·허용 범위·정확한 정수 여부와 경계 일치를
검사한 뒤 JSON 정수로 저장한다. 소수 시각을 반올림하거나 잘라내지 않는다.
독립 reference도 실제 native 시각이 검증된 정수 연산 시각과 일치하는지 먼저 검사한다.

기본 시나리오:

| 사건 | 시각 (ns) | 시각 (ms) |
|---|---:|---:|
| Controller 명령 송신 | 1,000,000 | 1.000000 |
| R 명령 수신 = BSM 시작 | 1,110,080 | 1.110080 |
| BSM 완료 = R 결과 송신 | 2,710,080 | 2.710080 |
| B 결과 수신 = correction 시작 | 2,998,080 | 2.998080 |
| correction 완료 = session 완료 | 3,498,080 | 3.498080 |

명령 payload=96 bytes, 링크=100 Mbps/100 us; 결과 payload=80 bytes, 링크=10 Mbps/200 us.
직렬화 시간은 각각 10,080 ns, 88,000 ns다. BSM=1,600,000 ns, correction=500,000 ns다.

## 4. 자원 전이와 중복 처리

```text
AR/RB: AVAILABLE → RESERVED → IN_USE → CONSUMED
AB:                        생성 → FRAME_PENDING → CORRECTING → USABLE
```

BSM 후 R에서 측정한 두 큐빗은 제거·폐기한다. 입력 pair의 CONSUMED는 원래 EPR을 더 이상
사용할 수 없다는 뜻이며, A/B의 살아 있는 큐빗은 AB pair의 위치로 이어진다.
보정 요청을 받은 뒤 같은 시각의 모든 입력을 반영하고 B를 배정한다.

중복 판별은 `(session, BSM request, AR/RB IDs, AB ID)` 및 측정 비트를 기준으로 한다.
새 message ID의 재전송도 같은 작업으로 처리한다. 첫 패킷의 비트를 저장하고 실제 보정에 사용한다.
같은 작업의 다른 비트는 `RESULT_MISMATCH`로 거절한다. 실행 중과 완료 후 모두 재적용하지 않는다.
최초 패킷을 평가기의 숨은 측정 결과/fidelity로 자동 수정하지 않는다.

`result_replays`는 검증용 실제 UDP 재전송 설정이다. 각 항목의 `delay_ns`는 BSM 완료 이후 송신 지연이며,
선택적인 `xor_m1`/`xor_m2`(0 또는 1)는 변경된 결과 비트의 거절을 검사한다.
재전송이 겹치면 시간 기준식에도 실제 직렬화 대기를 포함한다.
보정 이후 늦게 도착한 재전송까지 검사하므로 최종 엔진 시각은 `session_completion_ns`보다 클 수 있다.

## 5. 양자 검증과 독립 reference

- `F_usable = <Phi+|rho_AB|Phi+>`이며 NetSquid의 `squared=True`를 사용한다.
- 보정 전 frame 진단값과 구별하고, 보정 후 고정된 Phi+를 target으로 쓴다.
- `abs(1 - F_usable) <= 1e-12` 및 고정 Bell 밀도행렬과의 원소별 최대 오차 `<= 1e-12`.
- 저장한 밀도행렬 순서는 `[A, B]`; JSON은 실수부와 허수부를 별도로 기록한다.
- `netsquid_reference.py`는 co-sim 모듈을 import하지 않는다. 순수 NetSquid Protocol timer,
  직접 qubit 연산, 합성 Pauli 보정 연산자를 사용한다. co-sim은 QuantumProcessor instruction을 쓴다.
- 실제 co-sim 연산 시각을 reference에 주고 최종 밀도행렬 오차 `<= 1e-12`를 검사한다.
  시간 자체의 정당성은 앞의 독립 계산으로 별도 확인한다.
- reference는 별도 Python 프로세스로 실행해 NetSquid의 전역 reset이 co-sim 상태를 바꾸지 않게 한다.
- 측정 비트가 두 실행에서 동일해야 한다고 가정하지 않는다. 각 경로의 비트로 보정한 최종 상태를 비교한다.

## 6. 로그 schema v1

기계 판독 형식은 [event-v1.schema.json](schema/event-v1.schema.json)에 정의한다.
모든 사건은 다음 공통 필드를 갖고 해당하지 않는 값은 `null` 또는 빈 목록/객체로 둔다.

```text
schema_version, session_id, event_id, event_type, sim_time_ns
sequence, source, source_sequence, round, phase, caused_by_event_id
node_id, processor_id, request_id, message_id
input_pair_ids, output_pair_id, request_state, resource_state
measurement_bits, fidelity, fidelity_kind, details
```

`n:<번호>`는 ns-3 참가자 이벤트, `p:<번호>`는 Python 쪽 이벤트 ID다.
`sequence`는 합쳐진 전체 순서, `source_sequence`는 ns-3 내부 순서다. 두 값은 ns-3 Event UID 자체가 아니다.
같은 timestamp도 `round`/`phase`/`sequence`와 원인 ID로 구분한다.
`request_id=2`인 correction 입력의 원래 BSM request ID는 `details.bsm_request_id`에 있다.

연산 로그의 자원 입력과 생성 이력을 다음과 같이 구분한다.

| 이벤트 | `input_pair_ids` | `output_pair_id` | `details.ancestor_pair_ids` |
|---|---|---|---|
| `BSM_COMPLETE`, `AB_CREATED` | `[1, 2]` | `3` | 없음 |
| 모든 `CORRECTION_*`, `PAIR_USABLE` | `[3]` | `3` | `[1, 2]` |

보정은 기존 AB pair에 적용하므로 입력과 출력 ID가 같다. ns-3 `CORRECTION_REQUEST`와
양자 보정의 대기·시작·완료·중복·거절 로그에 같은 의미를 사용한다.
명령/BSM 결과 패킷의 전송·수신 로그는 원래 BSM의 `[1, 2] → 3` 정보를 유지한다.
`snapshot.ab_pair.input_pair_ids=[1, 2]`는 AB를 만든 입력 EPR의 이력이며 그대로 보존한다.
기존 v1의 필드 구성을 유지하고 의미를 명확히 한 것으로, 이전 결과 파일은 실행기로 재생성한다.

`resource_state`는 양자 전이 이벤트에서 pair ID별 상태를 담는다. ns-3가 양자 상태를 안다고 가정하지 않는다.
Fidelity는 평가용 기록에만 존재하고 IPC/UDP 제어 메시지에는 없다.

## 7. 종료 기준 및 테스트

- 실제 두 UDP 경로와 앱/장치 Tx/Rx trace
- 헤더 포함 직렬화·전파 지연과 BSM/correction 시간의 독립 계산 일치
- 네 측정 분기를 모두 거치는 32회 transaction, 각 보정 후 Bell 상태 복원
- 진행 중/완료 후 결과 중복 및 변경된 비트, 느린 링크의 재전송 FIFO
- 소모된 EPR 재사용 거절, 보정 horizon 건너뛰기 거절, 정확한 완료 경계
- 완전한 fidelity가 있어도 잘못된 timestamp를 잡아내는 검증
- 보정 대상/생성 이력의 로그 의미와 JSON 정수 시각 검증, 잘못된 native 시각의 절삭 방지
- 잘못된 최종 Bell 상태를 잡아내는 독립 reference 비교
- 기존 P0 14개 회귀 테스트 통과

P1은 이 무잡음 모델의 end-to-end correctness를 검증한다. P2에서 잡음과 시간에 따른
상태 감쇠를 추가하면 해당 연산·잡음 적용 시점에 대한 교차 검증이 추가로 필요하다.
