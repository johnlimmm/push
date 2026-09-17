# Hybrid v1 — 보존 및 재현

## 완료 범위

**실제 Q2NS SwapApp과 TeleportationApp이 공통 quantum execution 기반을 사용한다.**
두 프로토콜의 혼합 실행에서 R의 BSM 및 B의 correction FIFO를 공유하며,
각 session의 quantum state와 memory position은 격리한다. NetSquid가 quantum state를 단독 소유한다.
Q2NS에는 논리 handle을 두고 실제 UDP payload로 측정 결과를 전달한다.

| 경계 | v1 계약 |
|---|---|
| Classical execution | ns-3/Q2NS 앱, IPv4/UDP, 실제 packet queue/serialization/propagation |
| Federation | 정수 ns, 안전한 다음 경계, 동일 시각 commit → 입력 → dispatch → 완료 통지 |
| Quantum execution | 공통 R/B capacity=1 FIFO, 자원 예약, atomic BSM/correction |
| Quantum state | NetSquid native memory와 T1/T2 aging; input/EPR은 t=0 생성 |
| Protocol adapter | Swap: pair+pair→pair, Teleport: qubit+pair→qubit |
| 배치 | 고정 C/A/R/B; Teleport의 Alice는 R; 최대 64 sessions |

일반 timed QuantumProgram, gate noise, dynamic EPR, physical quantum channel, 임의 topology와
기존 Q2NS 예제의 무수정 실행은 지원하지 않는다. NetSquid의 미래 자율 이벤트도 현재는 거부한다.

## 검증 근거와 주장 범위

- Python 136개: P0–P5-B/Q2NS 회귀 122개 + Hybrid 14개.
- Q2NS native 83개: 기존 76개 + Teleport 외부/native 경로 7개.
- 다섯 입력 상태 × 32 seeds = 160 noiseless teleport transactions; 각 상태의 네 BSM branch 확인.
- 기존 Swap 세 조건과 packet/request timing 일치; 최대 checkpoint 차이 8.33×10⁻¹⁷.
- 단독/혼합 실행의 독립 NetSquid reference 대비 최대 density-matrix error 2.22×10⁻¹⁶.
- Mixed R contention, fast-BSM의 B contention, late/duplicate completion 및 overflow 실패 검출.

[기능 검증 요약](releases/hybrid-v1/validation-summary.json)과
[release 재검증](releases/hybrid-v1/release-checks.json)에 로그와 결과를 기록한다.
상태 오차는 **동일 operation timestamps에서의 correctness**를 검증한다.
P5-B의 48 paired cases는 유한 workload pilot이며 통계적 성능 일반화나 service feasibility
오판을 입증한 결과가 아니다. [P5-B 문서](README-P5B.md)의 제한을 유지한다.

## 보존 구성

[hybrid-v1-freeze.json](baselines/hybrid-v1-freeze.json)은 소스, 설정, 결과, 로그, 실행 환경,
Q2NS base/local commit 및 두 patch의 SHA-256을 기록한다.
같은 디렉터리의 `hybrid-v1-freeze.tar.gz`에 해당 파일을 보관한다.
이전 milestone archive는 중복으로 넣지 않고 별도 hash 목록으로 연결한다.
생성 파일인 `results/`는 일반 Git 추적 대상이 아니므로 결과 공유는 이 archive를 기준으로 한다.
GitHub에서 바로 확인할 수 있는 주요 요약의 사본은 [releases/hybrid-v1](releases/hybrid-v1/README.md)에 둔다.

Q2NS는 별도 Git 저장소다. 부모 저장소에 Q2NS repository 전체를 복제하지 않으며,
정확한 upstream base와 **Swap 및 Teleport 두 patch**로 변경을 재현한다.
NetSquid 배포 파일, Python 가상환경, 빌드 바이너리, 인증 정보는 archive에 포함하지 않는다.

ns-3 작업 브랜치의 release commit에는 `cosim-hybrid-v1` tag를 사용한다.
commit의 자신의 hash를 manifest에 넣어 순환 참조를 만들지 않는다. Manifest는 변경 전
ns-3 HEAD와 파일별 hash를 기록하며, 실제 release commit은 Git tag로 식별한다.

2026-09-17 게시 정리에서 Git 이력을 `johnlimmm` 작성의 단일 snapshot으로 구성하고,
root README를 hybrid 구현 중심으로 바꿨다. 원본 ns-3 README는 `README-NS3.md`에 보존했다.
이에 맞춰 v1 archive의 문서와 manifest를 갱신했으며 구현·설정·검증 결과의 bytes는 동일하다.
이전 archive와 commit 이력은 로컬 Git bundle에 보존하고, 문서 갱신 전후 hash와 변경 목록은
manifest의 `publication_refresh`에 기록한다. 이전 P1–P4 Git tag는 원격에서 제거했지만,
각 단계의 freeze archive 및 manifest는 이 snapshot에 계속 포함한다.

## 새 checkout에서 준비

ns-3 release checkout의 루트에서 실행한다. 아래 clone/patch 명령은 **Q2NS가 아직 없는
새 checkout**을 위한 것이다. 이미 적용된 workspace에 patch를 재적용하지 않는다.

```bash
git clone https://github.com/QuantumInternet-it/q2ns.git contrib/q2ns
git -C contrib/q2ns checkout --detach f22ba28f437099ba3cf9956ca332ba5ce8bb14fd
git -C contrib/q2ns apply --check ../cosim/integrations/q2ns-swap-external.patch
git -C contrib/q2ns apply ../cosim/integrations/q2ns-swap-external.patch
git -C contrib/q2ns apply --check ../cosim/integrations/q2ns-teleport-external.patch
git -C contrib/q2ns apply ../cosim/integrations/q2ns-teleport-external.patch

python3 contrib/cosim/tools/verify_hybrid_v1.py
./ns3 configure --enable-examples --enable-tests
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build \
  cosim-p0 cosim-p1 cosim-p3 cosim-p4 cosim-p5 cosim-q2ns cosim-hybrid q2ns-test test-runner -j 1
```

검증 환경은 ns-3.47, Python 3.7.17, NetSquid 1.1.7, NumPy 1.21.6이다.
NetSquid가 설치된 Python을 별도로 준비한다. 전체 설치 package 목록 및 build tool 버전은
freeze manifest의 environment에 기록한다. 패키지 목록은 호환성 정보이며 설치 스크립트가 아니다.

```bash
COSIM_PYTHON=/home/ns3/qunet/bin/python
"$COSIM_PYTHON" contrib/cosim/python/run_hybrid.py \
  contrib/cosim/scenarios/hybrid-mixed.json \
  --output /tmp/hybrid-v1-mixed.json
"$COSIM_PYTHON" -m unittest discover -s contrib/cosim/tests -v

for suite in q2ns-analysis q2ns-netcontroller q2ns-qchannel q2ns-qnode \
  q2ns-qstate-interface q2ns-qstate-registry q2ns-swap-external q2ns-teleport-external; do
  build/utils/ns3.47-test-runner-default --suite="$suite" --verbose || exit 1
done
```

동일한 219개 테스트를 로그와 JSON 요약까지 기록하며 실행하려면 위 수동 테스트 명령 대신
`"$COSIM_PYTHON" contrib/cosim/tools/validate_hybrid_v1.py`를 사용한다.

보존한 결과를 새 실행 결과와 구분해 확인하려면 archive를 빈 디렉터리에 풀어 확인한다.
아래 명령은 현재 workspace의 결과를 덮어쓰지 않는다.

```bash
mkdir /tmp/hybrid-v1-evidence
tar -xzf contrib/cosim/baselines/hybrid-v1-freeze.tar.gz -C /tmp/hybrid-v1-evidence
```

`verify_hybrid_v1.py`는 archive의 모든 파일 hash와 현재 소스/설정을 검사한다.
재실행으로 변할 수 있는 workspace의 `results/`는 비교하지 않으며 archive 안의 원본을 검사한다.
Git commit/tag를 이동하거나 기존 archive를 재생성하지 않는다.

## 다음 단계: E1 (아직 미구현)

일반 hybrid simulator라는 목표를 유지하며 다음 확장은 **고정 topology의 scheduled EPR provisioning**이다.

1. 요청한 EPR이 정해진 미래 시각에 생성되고, 실제 생성시각부터 memory aging을 시작한다.
2. `state_created_at`과 앱에 통지되는 `resource_ready_at`을 별도로 표현한다.
3. 자원을 기다리는 요청은 processor를 점유하지 않는다. 준비된 요청이 FIFO에 진입한다.
4. `resource_wait`와 `processor_wait`를 분리한다. Teleport input은 자신의 생성시각을 유지한다.
5. generation completion을 federation의 다음 경계에 포함하고, 동일 시각 처리 순서를 명세한다.

첫 acceptance는 command-first/ready-first, 두 Swap EPR의 서로 다른 준비시각, 동일 timestamp,
지정된 생성 실패, delay=0의 v1 동등성, Mixed 및 독립 reference 비교다.
자동 retry/expiry 정책과 photon/channel 모델은 함께 추가하지 않는다.

E1 → configurable topology → native quantum channel/generation → multi-hop 순으로 확장한다.
이번 release에는 E1 구현이나 E1 PASS 주장이 포함되지 않는다.
