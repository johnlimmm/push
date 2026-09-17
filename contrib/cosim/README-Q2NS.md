# Q2NS SwapApp ↔ NetSquid 연결

**상태: 단일 repeater의 실제 SwapApp 비동기 연결 PASS.**
기존 P5-A의 세 시나리오를 Q2NS 앱을 거쳐 실행했고 packet 시각, quantum state와
대기시간이 기존 P5-A 결과와 일치했다. P0–P5 소스는 유지했다.

## 현재 연결된 경로

```text
Controller UDP command → R CosimAgentApp → Q2NS SwapApp BSM 요청
    → NetSquid BSM → 완료시각에 SwapApp으로 결과 반환
    → Q2NS 기존 UDP 송신 → 실제 packet queue → B Q2NS PacketSink
    → SwapApp frame 해석 → NetSquid correction
    → 완료시각에 Q2NS CorrectionApplied
```

Q2NS는 실제 `QNode`/`SwapApp`과 결과 packet 송수신을 담당한다.
NetSquid는 EPR, memory noise, BSM/correction과 quantum state를 담당한다.
Q2NS의 논리 EPR handle `(session_id,101/102/103)`을 NetSquid의
`(session_id,1/2/3)`에 매핑한다. Q2NS 쪽에는 중복 Qubit/QState를 만들지 않는다.
연산 배정과 atomic duration은 기존 federation scheduler 규약을 사용한다.

## 검증 결과

- 연동 테스트 **12개** + P0–P5 회귀 **94개** = Python **106개 PASS**.
- Q2NS 기존 6개 suite의 72개 case + 새 SwapApp suite 4개 = **76개 PASS**.
- 32 seeds × 4 sessions = **128 transactions**에서 BSM `00/01/10/11` 전달 확인.
- 기본/noise-off/분기 실행의 최대 reference density-matrix error: **3.3306690738754696e-16**.
- 세 기본 시나리오 모두 기존 P5-A의 snapshot, packet timing, metric과 일치.
- 모든 정상 run에서 Q2NS native state/qubit=0, B correction wait=0, packet drop=0.
- 중복 요청/완료/결과 packet, 잘못된 config/bit/역할, 앱 종료 후 결과 도착을 검증.
- Q2NS 자체 quantum backend로 실행하는 기존 BSM/Pauli 경로도 통과.

근거: [검증 요약](results/q2ns-validation-summary.json),
[연동 테스트](results/q2ns-test-suite.log), [P0–P5 회귀](results/q2ns-regression-suite.log),
[Q2NS 자체 테스트](results/q2ns-native-test-suite.log).

| 시나리오 | R 대기시간 (session 1–4, ms) | 최종 transaction 완료 (ms) |
|---|---|---|
| quantum-only | 0, 0.8, 1.6, 2.4 | 8.298080 |
| joint-result | 0, 0.8, 1.6, 2.4 | 9.012000 |
| joint-both | 0, 1.112, 1.912, 2.712 | 9.012000 |

## 실행

ns-3 루트에서 NetSquid가 설치된 Python으로 실행한다.

```bash
./ns3 configure
./ns3 build cosim-q2ns q2ns-test
/home/ns3/qunet/bin/python contrib/cosim/python/run_q2ns.py \
  contrib/cosim/scenarios/p5-joint-both.json \
  --output contrib/cosim/results/q2ns-joint-both.json

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_q2ns.py -v
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p 'test_p[0-5].py' -v
build/utils/ns3.47-test-runner-default --suite=q2ns-swap-external --verbose
```

현재 환경에서는 ccache 임시 경로 문제를 피하려고 build 앞에
`CCACHE_TEMPDIR=/tmp/cosim-ccache`를 사용했다.
새 환경에서 전체 회귀를 실행하려면 기존 P0–P5 참가자와 ns-3 `test-runner`도 빌드되어 있어야 한다.

## 파일과 로그

- [SPEC-Q2NS](SPEC-Q2NS.md): 소유권, 지원 범위와 비동기 API 계약.
- [cosim-q2ns.cc](examples/cosim-q2ns.cc): 실제 Q2NS 앱, 논리 ID 매핑, native packet/trace 연결.
- [run_q2ns.py](python/run_q2ns.py): BSM 및 correction 완료를 ns-3에 같은 시각으로 반환.
- [q2ns_validation.py](python/q2ns_validation.py): native trace/완료시각/자원 소유권 검사.
- [test_q2ns.py](tests/test_q2ns.py): P5-A 동등성, 분기, session 격리와 실패 검출.

기존 `events`, `packet_events`, `snapshot`, `metrics`에 `q2ns_events`,
`q2ns_status`, `q2ns_validation`을 추가했다. `Q2NS_FRAME_RESOLVED`는 결과 수신시각,
`Q2NS_CORRECTION_APPLIED`는 실제 correction 완료시각이다.
둘의 차이는 이 설정에서 500,000 ns다.

result packet은 Q2NS 기존 10-byte CtrlHeader와 padding을 사용한다.
관측용 PacketTag는 wire bytes/전송 지연에 포함되지 않으며, 측정 bit는 실제 payload로 전달된다.

## Q2NS 별도 저장소 변경 보존

`contrib/q2ns`는 별도 Git 저장소다. 부모 ns-3 저장소에서 변경분을 놓치지 않도록
[patch](integrations/q2ns-swap-external.patch)와
[원본 commit·파일 해시](integrations/q2ns-swap-external.json)를 보존했다.
원본 commit의 파일에 patch를 적용한 결과가 현재 파일들과 byte 단위로 일치함을 확인했다.

아래 명령은 **변경이 아직 없는 원본 Q2NS checkout**에서만 사용한다.
현재 workspace에는 이미 적용되어 있다.

```bash
git -C contrib/q2ns apply --check ../cosim/integrations/q2ns-swap-external.patch
git -C contrib/q2ns apply ../cosim/integrations/q2ns-swap-external.patch
```

이번 완료 범위는 단일 repeater, IPv4/UDP, 미리 생성한 EPR의 SwapApp 연결이다.
Q2NS topology helper/quantum channel/동적 EPR 생성까지 연결한 것은 아니다.
**다음 단계는 이 연결을 유지한 P5-B 단순화 모델 비교 평가**이며, 현재 결과는 correctness 검증이다.
