# P0 명세

P0는 시간 순서·자원 전이·후속 인과 이벤트에 대한 14개 테스트 통과로 종료했다.
이 명세와 테스트는 P1에서도 유지하며, 실제 패킷·보정 확장은 [SPEC-P1.md](SPEC-P1.md)에 정의한다.

## 1. 모델과 상태 소유권

- 하나의 Python 프로세스에서 NetSquid 엔진과 Federation Manager를 실행한다.
- 하나의 C++ 자식 프로세스에서 ns-3 이벤트 루프를 실행한다.
- NetSquid 엔진은 전역 singleton이다. 같은 Python 프로세스에서 federation 두 개를
  동시에 실행하지 않는다. 순차 실행은 새 시뮬레이션으로 초기화한다.
- 양자 상태·자원 소유권·요청 실행 상태의 권한은 QuantumScheduler에 있다.
- 모든 입력 EPR은 시각 0에 생성된다. 한 큐빗은 지정 프로세서 메모리 위치에,
  나머지는 해당 자원의 독립 endpoint memory에 둔다.
- BSM은 양의 정수 시간 동안 프로세서를 점유하는 원자적 연산이다. 효과는 완료 시점에
  적용된다. 실행 도중 다른 명령이 예약 자원에 접근할 수 없다.
- 시간 변화 잡음, 자율 생성/만료/실패, timed native program은 없다.

## 2. 시간과 진행 한계

- 모든 전송 시각·실행시간은 정수 ns다.
- 허용 시각은 `[0, 2^53-1]`. NetSquid의 double 시간으로 정수를 정확히 표현하기 위한 제한이다.
- 결과의 `snapshot.netsquid_time_ns`도 JSON 정수로 저장한다. 변환 전에 실제 시계의 유한성,
  허용 범위, 정확한 정수 여부와 경계 일치를 검사하며 반올림하거나 소수부를 버리지 않는다.
- operation duration은 `[1, 2^53-1]`이며 예약된 완료 시각이 범위를 넘으면 거절한다.
- 실행 중인 모든 프로세서의 다음 완료 시각 중 최소값이 quantum safe horizon이다.
- 실행 중인 요청이 없다면 horizon은 없음(`None`). 제한된 P0 모델에서만 무한대와 같다.
- 외부 입력을 반영할 때마다 horizon을 재계산한다.
- manager는 `min(ns-3 다음 이벤트 시각, quantum horizon)`으로 진행한다.
- timestamp 감소와 horizon을 건너뛰는 진행은 즉시 오류다.
- 각 라운드 종료 시 ns-3와 NetSquid의 시간이 일치해야 한다.

성능보다 검증 용이성을 우선해 ns-3의 모든 이벤트 시각에서 rendezvous한다.
동일 시각의 ns-3 이벤트들은 한 번에 배출한다. 일반 패킷망에서의 IPC 빈도 최적화는
P0 범위에 포함하지 않는다.

## 3. 동일 시각 t의 의미

한 라운드의 순서는 다음과 같다.

1. t에 완료되는 모든 quantum operation을 processor ID 순으로 commit한다.
2. 입력 자원은 `CONSUMED`로 바꾸고 프로세서를 비운다. 다음 작업은 아직 시작하지 않는다.
3. 이미 예약된 ns-3 이벤트들을 t에서 모두 실행하고 요청/취소를 모은다.
   ns-3 scheduler의 이벤트 UID 순서를 유지한다. 수집된 순서대로 입력을 처리한다.
4. 각 프로세서의 FIFO 대기열을 확인한다.
5. 비어 있는 프로세서마다 첫 요청 하나를 실행한다.
6. 접수 응답·상태 변화·완료 결과를 ns-3의 t 이벤트로 주입한다.

6에서 주입된 결과가 t의 후속 요청을 만들면 다음 인과적 라운드를 t에서 수행한다.
그 후속 요청은 이미 발생한 원인보다 앞서 처리되지 않는다. 기존 작업은 5에서 이미
시작했으므로, 결과 수신이 새로 유발한 취소로 그 작업을 되돌릴 수 없다.
같은 시각의 이벤트/라운드가 무한히 이어지는 구성은 상한에 의해 명시적으로 실패한다.

### ns-3 adapter

`DefaultSimulatorImpl::PreEventHook`에서 `Stop()`을 호출해 현재 이벤트 직후 `Run()`을
반환시킨다. `MapScheduler::PeekNext()`로 시각을 확인하면서 해당 시각을 모두 처리한다.
ns-3 코어를 수정하거나 private 멤버를 조작하지 않는다. 단일 스레드 참가자 전용이다.

### NetSquid adapter

P0의 native timeline에는 즉시 발생하는 memory notification만 존재한다.
미래 완료 이벤트는 QuantumScheduler가 보유한다. `sim_run(end_time=t)`로 빈 native
timeline의 시각을 이동한 다음, 명시적 완료 commit에서 즉시 BSM을 수행한다.
`sim_run()`으로 현재 시각의 notification을 배출하고 시각이 변하지 않았는지 확인한다.
`sim_stop()`, clock reset, `+1 ns`, epsilon은 사용하지 않는다.

이 기법을 미래 native 이벤트를 예약하는 모델에 적용하면 안 된다. 네이티브 timed
QuantumProgram을 도입하려면 별도의 정확한 경계 adapter 검증이 선행되어야 한다.

## 4. 요청과 자원

새 요청:

```text
RECEIVED → QUEUED → RUNNING → COMPLETED
    └────→ REJECTED
             QUEUED → CANCELLED
```

- 두 자원의 존재·위치·AVAILABLE 상태를 모두 검사한 뒤 한 번에 예약한다.
- 예약 충돌은 대기시키지 않고 `REJECTED / RESOURCE_CONFLICT`로 처리한다.
- processor별 FIFO는 예약에 성공한 요청만 포함한다.
- 대기 중 취소는 예약을 반환한다. 실행 중 취소는 `NOT_CANCELLABLE`로 거절하고 실행을 유지한다.
- 이미 terminal인 요청의 취소는 `ALREADY_TERMINAL` 응답이며 상태를 바꾸지 않는다.
- 알 수 없는 ID의 취소는 `UNKNOWN_REQUEST` 응답이며 새 요청 기록을 만들지 않는다.
- 자율 실행 실패는 P0에서 금지한다. 예상하지 못한 NetSquid/IPC 오류는 실행 전체를
  실패시키며 손상 가능성이 있는 자원으로 계속 진행하지 않는다.

자원:

```text
AVAILABLE → RESERVED → IN_USE → CONSUMED
              └──────→ AVAILABLE  (대기 중 취소만)
```

BSM 후 repeater의 측정된 큐빗은 메모리에서 제거·폐기한다. 원격 생존 큐빗은
NetSquid에 남고 `swap:<request_id>` 출력 handle과 Pauli frame 정보를 기록한다.
출력 handle 재사용과 실제 endpoint 보정은 P1로 미룬다.

### 멱등성

request ID 범위는 `[1, 2^63-1]`이다. ID는 전체 실행에서 유일해야 한다.
요청 내용은 `(processor_id, pair_a, pair_b, duration_ns)`이다. pair 순서는 측정 비트의
의미를 결정하므로 내용 비교에서 보존한다. 재시도의 도착 시각은 내용에 포함하지 않는다.

- 동일 ID, 동일 내용: 현재 상태와 기존 결과 비트를 `DUPLICATE`로 반환한다.
- 동일 ID, 다른 내용: `REQUEST_ID_REUSE`; 기존 요청은 변경하지 않는다.
- 완료, 거절, 취소 기록도 실행 종료까지 보존한다.

## 5. 외부 입력 JSON

`scenarios/queue-ordering.json`을 기준으로 한다. 최상위 필드:

- `name`, `seed`
- `processors`: 고유 uint32 ID 목록
- `resources`: `{pair_id, processor_id}` 목록
- `events`: 고정 도착 시각의 요청/취소 목록
- `followups`: 선택 사항. 완료 결과 수신이 유발하는 요청 목록

SUBMIT 입력:

```json
{"time_ns": 100, "request_id": 1, "processor_id": 0,
 "pair_a": 1, "pair_b": 2, "duration_ns": 100}
```

CANCEL 입력:

```json
{"time_ns": 150, "type": "CANCEL", "request_id": 1}
```

followup은 `time_ns` 대신 `after_request_id`, `delay_ns`를 쓴다. 해당 요청의 COMPLETED
결과를 ns-3가 처음 수신한 시각을 기준으로 한 번만 실행한다. 같은 시각의 외부 입력은
events 배열 등록 순서와 ns-3 UID를 따른다. followup도 ns-3에서 이벤트로 예약한다.

알 수 없는 모델 필드(예: `noise`, `expiry_ns`)는 조용히 무시하지 않고 거절한다.

## 6. IPC 프로토콜 v1

JSON은 사용자 입력/결과용이다. C++ 의존성을 줄이기 위해 내부 IPC는 명시적인 필드 수를
갖는 ASCII line protocol을 쓴다. 문자열은 고정된 토큰이며 임의 텍스트를 전송하지 않는다.
각 줄은 newline으로 끝난다. 줄 길이는 4096 bytes로 제한한다.

```text
worker → HELLO COSIM_P0 1
manager → CONFIG <processor_count> <event_count> <followup_count>
manager → PROCESSOR <id>                                     (반복)
manager → EVENT <time> <kind> <id> <processor> <a> <b> <duration>
manager → FOLLOWUP <after_id> <delay> <kind> <id> <processor> <a> <b> <duration>
worker → READY 0 <next_time_or_-1>

manager → ADVANCE <time>
worker → BOUNDARY <time> <next_time_or_-1> <input_count> <delivery_count>
worker → INPUT <kind> <id> <processor> <a> <b> <duration>        (반복)
worker → DELIVERED <id> <processor> <state> <code> <m1> <m2>    (반복)

manager → INJECT <time> <count>
manager → RESULT <id> <processor> <state> <code> <m1> <m2>     (반복)
worker → INJECTED <next_time_or_-1>

manager → QUIT
worker → BYE
```

초기 미정 비트는 -1이다. CANCEL의 a/b/duration은 0이다. 소켓 EOF, 잘못된 필드,
clock mismatch, 응답 시간 초과는 명시적 실패다. 종료 시 runner는 자신이 생성한
자식 프로세스만 종료한다. 파일 기반 소켓 경로나 TCP 포트는 사용하지 않는다.
