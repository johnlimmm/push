# ns-3 ↔ NetSquid 공동 시뮬레이션

두 프로세스의 시간 순서와 양자 자원 예약을 검증하는 첫 구현입니다.
ns-3.47 / NetSquid 1.1.7 / Python 3.7.17 환경을 대상으로 합니다.

## P1: 실제 UDP와 endpoint 보정

P0 위에 하나의 A–R–B swapping transaction을 연결했습니다.
Controller→R 명령과 R→B 결과는 실제 ns-3 IPv4/UDP/PointToPoint를 통과하며,
B의 보정 후 고정 Bell 상태와 독립 NetSquid-only reference를 확인합니다.

```bash
./ns3 configure --enable-examples --enable-tests
./ns3 build cosim-p0 cosim-p1 -j 2
~/qunet/bin/python contrib/cosim/python/run_p1.py \
  contrib/cosim/scenarios/p1-swapping.json \
  --output contrib/cosim/results/p1-swapping.json
~/qunet/bin/python -m unittest discover -s contrib/cosim/tests -v
```

기본 예제는 **3.498080 ms에 AB pair가 USABLE**이 됩니다. 자세한 범위, 예상 시각,
로그 schema 및 검증 기준은 [SPEC-P1.md](SPEC-P1.md)에 있습니다.

**P1은 종료했습니다.** 2026-09-16에 로그 정리 후 P0 14개 + P1 13개 테스트가 모두 통과했습니다.
보정 이벤트는 대상 AB를 `input_pair_ids=[3]`으로, AR/RB 생성 이력을
`details.ancestor_pair_ids=[1, 2]`로 기록합니다. `snapshot.netsquid_time_ns`는
실제 시각의 정확한 정수 여부와 범위를 확인한 뒤 JSON 정수로 저장합니다.

| P1 파일 | 역할 |
|---|---|
| `examples/cosim-p1.cc` | 실제 UDP 경로와 앱/장치 trace |
| `model/cosim-bridge.h` | P0/P1 공통 시간 경계·IPC 어댑터 |
| `python/run_p1.py` | federation, 실행 검증, reference 자식 프로세스 |
| `python/p1_quantum.py` | P0 BSM 확장, B 보정, AB 자원·공통 로그 |
| `python/p1_validation.py` | 설정값만으로 독립 시간 계산, 결과 검증 |
| `python/netsquid_reference.py` | 독립 NetSquid Protocol 기반 기준 모델 |
| `tests/test_p1.py` | P1 통합·양자 경계·검증 실패 검출 테스트 |

아래는 종료된 **P0 단계의 명세와 실행 방법**입니다. P0 회귀 테스트 14개는 계속 유지합니다.

## 빠른 실행

ns-3 루트에서:

```bash
./ns3 configure --enable-examples --enable-tests
./ns3 build cosim-p0 -j 2

~/qunet/bin/python contrib/cosim/python/run_p0.py \
  contrib/cosim/scenarios/queue-ordering.json \
  --output contrib/cosim/results/queue-ordering.json

~/qunet/bin/python -m unittest discover -s contrib/cosim/tests -v
```

NetSquid 가상환경의 Python을 사용해야 합니다. 패키지 추가 설치는 필요하지 않습니다.
다른 ns-3 빌드 디렉터리를 쓰면 `run_p0.py --ns3-binary /절대/경로/실행파일`을 지정합니다.
`cosim-p0` 실행파일은 runner가 제공하는 소켓이 필요하므로 직접 실행하지 않습니다.

예제의 예상 시각:

| 요청 | 프로세서 | 도착 (ms) | 실행 시작 (ms) | 완료 (ms) |
|---|---|---:|---:|---:|
| 101 | 0 | 37.4 | 37.4 | 39.0 |
| 102 | 0 | 38.0 | 39.0 | 40.6 |
| 201 | 1 | 38.0 | 38.0 | 39.6 |

요청 102의 대기는 1 ms입니다. 요청 201은 다른 프로세서에서 병렬로 실행됩니다.

## 구현 범위

구현된 것:

- 실제 ns-3 `Application`에 예약된 요청 도착과 결과 수신 이벤트
- ns-3 C++ 프로세스와 NetSquid Python 프로세스 사이의 Unix stream socketpair
- Python 프로세스 안의 `FederationManager`와 `QuantumScheduler`
- 정수 나노초, 진행 한계, 동일 시각의 인과적 처리 라운드
- 프로세서별 FIFO, 두 자원의 원자적 예약, 중복 요청, 대기 중 취소
- NetSquid `QuantumProcessor`/`QuantumMemory`에 저장된 실제 Bell pair와 BSM
- 결과 비트의 ns-3 이벤트 전달, JSON 실행 기록

**P0의 물리 모델은 `atomic-noiseless-bsm`입니다.** 요청의 `duration_ns` 동안
프로세서와 자원을 점유한 뒤 완료 시각에 CNOT, H, 두 Z 측정을 순간적으로
수행합니다. 대기/실행시간은 `QuantumScheduler`가 관리합니다. NetSquid 호출의
`physical=False`는 의도된 것으로, 네이티브 `PhysicalInstruction`의 시간·잡음을
실행하는 모델이 아닙니다. 상태는 밀도행렬(DM)이며 Q2NS `QState`는 사용하지 않습니다.

P0 실행기에 포함하지 않는 것(P1 확장은 위 문서 참조):

- UDP/TCP 패킷 경로, 라우팅·혼잡: P0 입력은 ns-3의 예약된 도착 이벤트
- A–R–B 프로토콜과 endpoint 보정, usable fidelity: P1
- 메모리/게이트 잡음, 자율 EPR 생성·만료·실행 중 실패
- 네이티브 timed `QuantumProgram`의 일반적인 경계 이벤트 처리
- Q2NS `SwapApp` 통합, q2nsviz 연결, P2–P4 실험

`frame_fidelity`는 측정 결과의 Pauli 보정 정보를 반영한 **BSM 완료 시점의 진단값**입니다.
보정이 수행되거나 사용 가능한 얽힘이 서비스에 전달됐다는 뜻이 아닙니다.
ns-3에는 이 진단값을 보내지 않으며 상태/결과 비트만 전달합니다.

## 파일 구조

| 파일 | 역할 |
|---|---|
| `model/cosim-agent-app.*` | ns-3 요청·결과 수신 인터페이스 |
| `examples/cosim-p0.cc` | ns-3 시간 진행 어댑터, 소켓 프로토콜 |
| `python/quantum_scheduler.py` | 실제 양자 상태, 예약, FIFO, BSM |
| `python/run_p0.py` | 두 프로세스 실행·종료와 federation loop |
| `tests/test_p0.py` | 통합 검증과 경계 검증 |
| `scenarios/queue-ordering.json` | 실행 가능한 두 프로세서 예제 |
| `SPEC-P0.md` | 시간·자원·프로토콜 명세 |

코드를 설명할 때는 다음 순서로 읽으면 됩니다. 주요 함수와 처리 단계에 한글 주석을 달았습니다.

1. `run_p0.py`의 `main()`과 `FederationManager.run()`: 전체 실행과 시간 경계 선택
2. `quantum_scheduler.py`의 `submit_request()` → `schedule_queued()` →
   `advance_to_boundary()`: 예약, 실행 시작, 완료 처리
3. `cosim-p0.cc`의 `RunParticipant()`: `ADVANCE`로 이벤트 실행, `INJECT`로 결과 예약
4. `test_p0.py`: 각 규칙의 기대 동작과 검증 사례

## 결과 읽기

`run_p0.py`는 지정한 JSON 파일을 생성합니다.

- `quantum_events`: 접수·대기·실행·측정·완료·취소 순서
- `ns3_inputs`: ns-3에서 실제 처리한 입력 시각과 순서
- `ns3_results`: ns-3 이벤트로 실제 수신한 응답
- `bridge_steps`: 매 라운드 시각, 진행 한계, 다음 이벤트
- `snapshot`: 최종 요청·자원 상태와 양자 진단값

통합 테스트별 기록은 `results/tests/*.json`에 저장됩니다.
동일 seed와 입력의 실행 기록은 재현 가능해야 합니다. BSM 비트 자체는 확률적입니다.

## 검증 범위

기본 6개 시나리오는 FIFO 순서, 동일 timestamp, 자원 충돌, 독립 프로세서,
중복 요청, 취소입니다. 추가로 완료 경계에서의 취소, 결과가 같은 시각 또는
지연 후의 후속 요청을 만드는 경우(프로세서 유휴·점유 상태 모두), 잘못된 요청,
해석적으로 계산한 FIFO 일정과의 비교,
시간 역행·진행 한계 초과·정수 정밀도 범위를 검사합니다.

이 검증은 제한된 P0 모델에 대한 것입니다. 두 프로세스의 IPC wall-clock 시간은
시뮬레이션 시간에 더하지 않습니다. Full Sync의 물리적 타당성이나 P1의
NetSquid 단독 모델과의 교차 검증은 별도 단계입니다.
