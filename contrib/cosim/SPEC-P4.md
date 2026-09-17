# P4 — Classical Packet Queueing → Native Memory Aging

## 목적과 범위

실제 ns-3 packet queueing이 추가 quantum 저장시간으로 반영되는지 검증한다.
P3 보존 commit `8ac3fe3c5`, tag `cosim-p3`; 코드·결과와 scratch 빌드 진입점을
`baselines/p3-freeze.tar.gz` 및 manifest에 보존했다. P0–P3 파일은 변경하지 않는다.

- P2와 동일한 단일 A–R–B transaction, t=0 EPR, native T1T2NoiseModel/DM.
- P2Quantum과 독립 netsquid_reference_p2.py를 그대로 사용한다.
- Controller→R 명령, R→B 결과는 각각 기존 P2P 링크를 통과한다.
- 각 송신 방향에 독립된 유한 UDP background flow 하나를 둘 수 있다.
- Control port=9000, background port=9001. 모든 packet에 고유 message ID와 종류를 넣는다.
- Background RX는 quantum request를 생성하지 않는다.
- DropTail device queue=128 packets 기본값; queue 크기를 명시하고 QueueDisc는 제거한다.
- IFG=0, IPv4/UDP/PPP, fragmentation 없음, IPv6/receive error model 없음.
- Quantum processor wait는 BSM/correction 모두 정확히 0. Control/background 모두 drop=0.
- 위반 run은 실패로 기록하며 통과 결과에서 조용히 제외하지 않는다.
- P4는 선택한 모델의 correctness와 유한 traffic 특성 확인이다. 정상상태 성능/논문 통계를 주장하지 않는다.
- Q2NS SwapApp 직접 통합은 후속 필수 작업으로 유지한다. P4 자체는 독립 cosim 참가자다.

## A. 독립 FIFO accounting — 모든 시나리오의 공통 기준

각 background 설정은 start_ns, interval_ns, count, payload_bytes다. 정확한 정수 ns로 유한 개 packet을 보낸다.
Packet payload에는 식별용 header가 포함된다. 실제 wire bytes는 payload+UDP 8+IPv4 20+PPP 2다.
Serialization의 ns 반올림 규칙과 half-ns 경계 제외는 P1과 동일하다.

설정의 송신시각과 wire bytes로 각 링크의 FIFO를 독립 계산한다:

    expected_phy_tx[i] = max(app_tx[i], previous_phy_tx_end)
    expected_phy_tx_end[i] = expected_phy_tx[i] + serialization[i]
    expected_app_rx[i] = expected_phy_tx_end[i] + propagation

Command의 예상 수신시각으로 BSM start/end와 result의 송신시각을 계산한 뒤,
result 링크 FIFO를 계산한다. 실제 PHY trace를 정답 생성에 사용하지 않는다.
동일 송신시각이면 background를 control보다 먼저 enqueue한다. Background 내부는 생성 순서다.
C++의 초기 스케줄 등록 순서와 completion 결과 주입 round가 이 규약을 보장한다.

각 packet에서 별도로 확인한다:

    APP_TX = Enqueue
    Dequeue = PHY_TX_BEGIN
    queue_wait = Dequeue - Enqueue
    serialization = PHY_TX_END - PHY_TX_BEGIN
    APP_RX = PHY_RX_END
    APP_RX - APP_TX = queue_wait + serialization + propagation

전체 지연과 queue 지연은 같은 값이 아니다. 각 관측값을 독립 FIFO 예상값과 대조한다.
Queue의 enqueue/dequeue/drop callback에서 실제 packet 수를 기록한다. FIFO 순서, 잔여 queue,
packet count, queue occupancy 적분 = 모든 packet의 waiting time 합을 검사한다.
QueueDisc 제거 후에도 device flow control이 전송을 막을 때 TrafficControlLayer가 버릴 수 있으므로
TcDrop도 연결한다. 이 trace의 packet 크기는 PPP가 붙기 전인 payload+28 bytes다.

## 기본 사례

기존 command time=1 ms, command link=100 Mbps/0.1 ms, result link=10 Mbps/0.2 ms,
command payload=96 bytes, result payload=80 bytes, BSM=1.6 ms, correction=0.5 ms를 유지한다.

| 사례 | Command background | Result background | 기대 queue delay |
|---|---|---|---|
| Zero | 없음 | 없음 | command=0, result=0 |
| B: command-only | 0.9 ms 시작, 20 us 간격, 1000-byte payload 5개 | 없음 | command=312,000 ns, result=0 |
| C: result-only | 없음 | 2.6 ms 시작, 50 us 간격, 1000-byte payload 3개 | command=0, result=2,361,920 ns |
| D: both | B와 동일 | C와 동일 | command=312,000 ns, result=2,049,920 ns |

D에서 command 대기가 result packet의 도착 위상을 바꾸므로 result 대기는 C와 다르다.
두 링크의 queue delay를 고정값처럼 합성하지 않는다. 위 값은 전체 FIFO 계산으로 검증한다.

B에서는 BSM 이후 모든 절대 시각이 command queue만큼 늦어진다. 유지되는 것은 result 링크의 전달 지연이다.
C에서는 BSM 시각/입력/frame 상태가 동일하고 correction 시작과 완료가 result queue만큼 늦어진다.
Noise off에서는 지연이 달라도 최종 Phi+를 복원한다. Noise on의 각 checkpoint는 관측 분기의
독립 reference와 밀도행렬/fidelity 오차 <=1e-12로 일치해야 한다. Fidelity 단조 감소는 강제하지 않는다.

## 로그와 종료

- events: 기존 v1 quantum/control 인과 로그. Background와 장치 queue 부가 trace는 여기에 섞지 않는다.
- packet_events: control/background 모두의 APP TX/RX, enqueue/dequeue/drop, PHY begin/end/RX.
  event ID와 sequence는 C++ trace 전체에서 고유하다. packet_id, traffic_class, link, wire/payload bytes를 명시한다.
- packets: packet별 실제 시각과 queue/serialization/propagation/total delay.
- metrics: 두 control packet의 Dc 분해, quantum wait, 링크별 queue peak/적분/평균, 송수신/drop, utilization.
- session_completion_ns: correction 완료시각. F_usable은 이 순간의 저장된 값이다.
- traffic_drain_completion_ns: 마지막 실제 packet RX시각.
- simulation_completion_ns: 위 두 시각의 최대. Background가 끝날 때까지 NetSquid 시계도 동기화하되
  과거 F_usable을 나중 시각의 상태로 덮어쓰지 않는다.

Link metric의 관측 구간은 공통 [0, traffic_drain_completion_ns]. Utilization은 이 구간에서
실제 PHY serialization 시간의 합/구간 길이다. Queue 평균도 같은 구간의 시간 가중 평균이다.
설정상의 background offered load(실제 wire bits/interval/capacity)와 관측 utilization을 구분한다.
Queue peak는 callback에서 관측한 packet 수의 최대이며, 즉시 dequeue되는 순간의 enqueue도 포함한다.

## 부하율 characterization

기본 검증 후 0 / 0.25 / 0.50 / 0.75 / 0.90 / 0.95의 wire offered load를 검사한다.
Command-only/result-only/both 각각에서 noise off/on을 실행한다. Flow당 32개 packet으로 유한하게 종료한다.
시작 위상과 payload를 고정하며 interval의 정수 ns 반올림 후 실제 offered load를 보고한다.
이 sweep에서는 양의 부하가 양의 control queue delay를 보장한다고 가정하지 않는다.
모든 run은 FIFO accounting, no loss, zero quantum wait, 독립 quantum reference를 통과해야 한다.

## 검증 항목

- Zero background의 P2 상태·operation timing 재현
- B/C/D의 정확한 ns queue delay, A의 모든 packet FIFO/trace accounting
- Result-only의 BSM checkpoint 격리, command-only의 downstream 절대 시각 이동
- Noise off/on packet timing 일치, 네 BSM 분기 검증
- Background port/ID 분리, background 수신이 quantum request를 만들지 않음
- Transaction 종료 후 traffic drain에서 F_usable 보존
- Quantum wait=0, control/background 모두 no loss
- Queue overflow run의 명시적 실패 및 원본 trace 보존
- 잘못된 FIFO 순서·queue timestamp·크기·drop·quantum timing·state 변조 검출
- P0–P3 58개 회귀 테스트와 보존 해시 검사
