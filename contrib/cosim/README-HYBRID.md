# QuCl Hybrid v2 — R에서 직접 시작하는 Swap + Teleportation

두 Q2NS 앱이 `session_start_ns`에 R에서 직접 external BSM request를 발생시킨다.
**실행 노드는 A=0, R=1, B=2**이며 Swap의 A–R / R–B EPR 구조를 유지한다.
Teleport의 source/Alice는 R이다. 결과 통신은 기존 Q2NS의 실제 R→B UDP 경로다.

```text
session_start_ns @ R
    Q2NS SwapApp / TeleportationApp
        → HybridExecutionCore: shared R FIFO
        → NetSquid BSM 완료
        → 해당 Q2NS app completion callback
        → 실제 R→B UDP result 생성 / queue / serialization / propagation
        → B의 Q2NS app에서 packet 수신 / correction request
        → HybridExecutionCore: shared B FIFO
        → NetSquid correction 완료 → Q2NS completion callback
```

Quantum-resource wait가 BSM 완료와 packet 생성시각을 바꾸고, 이동한 packet이 background와
만나는 시점에 따라 queueing, correction 시각, memory aging이 달라지는 인과관계를 평가한다.
`HybridFederation`/`HybridExecutionCore`, shared R/B FIFO, session/resource 격리와
NetSquid 단독 state ownership을 Swap과 Teleport가 함께 사용한다.

## 설정과 시간

```json
{
  "sessions": [
    {"session_id": 1, "protocol": "swap", "session_start_ns": 1000000},
    {"session_id": 2, "protocol": "teleport", "input_state": "+i", "session_start_ns": 1000000}
  ],
  "result_link": {"rate_bps": 10000000, "delay_ns": 200000},
  "background": {"result": {"start_ns": 2600000, "interval_ns": 1600000, "count": 4, "payload_bytes": 1000}}
}
```

같은 시각의 session은 목록 순서대로 R FIFO에 들어간다. `t=0` 시작도 지원한다.
Swap payload는 기본 80 bytes, Teleport payload는 기존 앱의 2 bytes다.
완료 전 result 전송과 packet 도착 전 correction은 허용하지 않는다.
`SESSION_START`는 local 이벤트이며 network packet으로 세지 않는다.
Latency는 `correction completion - session_start_ns`다.

구 설정의 per-session `command_time_ns` 값은 `session_start_ns`로 옮긴다.
`command_link`, `command_payload_bytes`, command background, `expected_queueing`은 제거한다.
구 command field를 새 runner에 넣으면 명시적으로 거절한다.
초기 시작시각 자체를 유지하므로 과거 C→R 지연을 포함한 결과와 수치가 달라지는 것이 정상이다.

## 실행과 검증

```bash
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-hybrid q2ns-test -j 1
/home/ns3/qunet/bin/python contrib/cosim/python/run_hybrid.py \
  contrib/cosim/scenarios/hybrid-mixed.json --output /tmp/hybrid-direct-mixed.json
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_direct_start.py
```

- [새 구조 전체 검증 요약](results/direct-start-validation-summary.json)
- [전체 회귀 기록](results/direct-start/regression-summary.json)
- [Teleport](results/direct-start/hybrid-teleport.json), [Mixed](results/direct-start/hybrid-mixed.json),
  [fast-BSM/B contention](results/direct-start/hybrid-mixed-fast-bsm.json)
- [P5-B 새 평가](README-P5B.md), [논문용 새 결과](paper/RESULTS.md)
- [시간·자원 계약](SPEC-HYBRID.md), [baseline 정의](SPEC-P5B.md)

검증은 local start, result FIFO의 app/queue/PHY timing, R/B FIFO, native callback routing,
noiseless 5개 입력×4개 branch, T1/T2 checkpoint, overflow/duplicate/late completion을 포함한다.
과거 Swap와의 비교는 과거 command 도착시각에 local start를 맞춘 제한된 동등성 검사다.
새 기본 설정을 과거 실행과 같은 값으로 간주하지 않는다.

## 범위와 과거 기준점

Fixed A/R/B, IPv4/UDP, pre-created input/EPR(t=0), atomic BSM/correction, shared R/B FIFO,
native T1/T2 aging, 최대 64 sessions. 임의 topology, dynamic EPR, quantum channel은 후속 범위다.
Q2NS native Qubit/QState는 외부 session에 생성하지 않는다. 실제 상태는 NetSquid만 가진다.

P0–P5-A와 초기 Q2NS runner는 과거 구조의 회귀 fixture로 보존한다. 현재 실행 및 P5-B의
진입점은 `run_hybrid.py`/`experiments/run_p5b.py`다. 이전 코드·수치는
[Hybrid v1 archive](baselines/hybrid-v1-freeze.tar.gz)에 보존되며 현재 source와의 일치를 주장하지 않는다.

```bash
python3 contrib/cosim/tools/verify_hybrid_v1.py --archive-only
```

Q2NS 자체 앱/patch는 이번 변경에서 수정하지 않았다. 새 checkout의 설치 절차는
[저장소 README](../../README.md) 및 [과거 release](RELEASE-HYBRID-V1.md)를 참고한다.
