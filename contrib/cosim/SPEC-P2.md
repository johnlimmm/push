# P2 — Time-Dependent Quantum Memory Aging

## 검증 결과 (2026-09-16)

- P0 14개 + P1 13개 + P2 15개, 총 **42개 테스트 통과** (46.879 s).
- 지연 25조건 × noise off/on = **50회 모두 시간·조건부 reference 검증 통과**.
- Sweep 전체의 최대 밀도행렬 오차: `2.220446049250313e-16`.
- 기본 run: 3,498,080 ns에 보정 완료, 측정 분기 01, usable fidelity `0.534522155608756`.
- 256회 실제 transaction의 분기 빈도: 00=64, 01=63, 10=64, 11=65. 분포 검사 통과.
- P0/P1 보존 파일 해시 검사 통과.

실행 증거는 `results/p2-test-suite.log`, `results/p2-memory-aging.json`,
`results/p2-delay-sweep/summary.json`, `results/tests/p2-outcome-distribution.json`에 있다.

Sweep의 인접 조건 비교에서 기대 fidelity가 증가한 구간도 13개 관찰됐다.
예를 들어 result delay=0.2 ms에서 command delay를 10→20 ms로 늘리면 reference 기대 fidelity는
0.31544395→0.33047051로 증가한다. 각 조건의 co-sim 상태가 해당 분기의 reference와 일치하므로
감쇠 모델과 분기 가중치에 따른 결과로 기록한다. fidelity 증가를 얽힘 개선으로 해석하지 않는다.

## 1. 목적과 범위

**ns-3의 실제 UDP packet timing이 NetSquid의 native memory elapsed time에 정확히 연결되는지 검증한다.**
P1 tag `cosim-p1`의 Python/C++ 구현, 테스트, 명세, schema는 수정하지 않는다.
P2는 별도 실행기와 P1 양자 어댑터의 서브클래스로 구현한다.

- 단일 Controller–R 명령 경로와 R–B 결과 경로, 하나의 A–R–B swapping transaction.
- t=0에 두 Phi+ EPR 생성. R processor에서 BSM, B processor에서 실제 X/Z correction.
- P1의 packet header, 직렬화·전파 지연, FIFO, session/request/pair ID, 자원 전이를 유지.
- background traffic, packet loss, 여러 session, processor contention, expiry, 자율 생성은 없다.
- 연산은 고정된 양의 정수 ns 동안 저장 후 완료 시 이상적인 회로를 순간 적용한다.
- native timed QuantumProgram, gate error, gate 수행 중의 세부 물리 과정은 모델링하지 않는다.
- 결과 재전송 시험은 P1 회귀 테스트에 남긴다. P2 설정의 `result_replays`는 빈 목록이어야 한다.

P2는 memory aging과 bridge 시간의 결합을 검증하는 단계다. 혼잡이나 하드웨어 성능 실험은 아니다.

## 2. 내장 물리 모델

환경: ns-3.47, NetSquid 1.1.7, Python 3.7.17. 상태 표현은 **DM(밀도행렬)**이다.

```json
"memory_noise": {
  "model": "T1T2NoiseModel",
  "T1_ns": 20000000,
  "T2_ns": 10000000
}
```

A memory position 0, R processor positions 0/1, B processor position 0에 각각
NetSquid의 `T1T2NoiseModel(T1=..., T2=...)` 인스턴스를 연결한다.
시간이 흐르기 전 t=0에 연결하며, 네 position에 같은 파라미터를 사용한다.
모델을 상속해서 decay 식을 재구현하거나 bridge에서 `error_operation`을 직접 호출하지 않는다.

파라미터는 `[0, 2^53-1]` 범위의 정수 ns다. 설치된 모델은 두 값이 양수일 때 `T2 <= T1`을 요구한다.
이 버전의 0은 해당 성분 비활성화라는 API 규약이다. `T1_ns=T2_ns=0`은 noise off이며
물리적으로 수명이 0이라는 뜻이 아니다. 검증에는 T1만 사용, T2만 사용, 강한 감쇠도 포함한다.

T1=20 ms, T2=10 ms는 변화가 보이는 검증용 설정이다. 특정 하드웨어를 대표한다고 주장하지 않는다.

## 3. 물리적 저장시간과 논리 자원

| 실제 큐빗 | 저장 구간 | 종료 처리 |
|---|---|---|
| R_AR, R_RB | 생성 0 → BSM 완료 | 측정 후 pop/discard |
| A, B | 생성 0 → correction 완료 | 같은 메모리·같은 큐빗 유지 |

BSM duration 동안 네 큐빗 모두 aging한다. BSM 후 결과 전달과 correction duration 동안
A/B도 계속 aging한다. `00`은 gate 실행이 없어도 양의 correction duration을 전부 소비한다.
AB pair 등록은 논리적 자원 생성이다. A/B를 새로 생성하거나 pop/put하여 저장 이력을 초기화하지 않는다.

메모리는 접근 시 마지막 접근 이후의 잡음을 반영한다. 평가할 때는 native `peek`를 통해 접근하며,
cached raw qubit만 읽어서 아직 반영되지 않은 noise를 빠뜨리지 않는다.
`physical=False`인 이상적 processor instruction도 메모리 접근에 따른 memory noise는 적용한다.
gate noise를 사용하지 않는 것과 memory noise를 끄는 것은 다르다.

`USABLE`은 실제 correction 완료라는 프로토콜 상태다. fidelity 임계값이나 얽힘 존재를 보장하지 않는다.

## 4. 시간 동기화

P1의 처리 순서를 그대로 유지한다.

1. 해당 경계의 quantum completion 확정
2. 같은 시각의 ns-3 이벤트 처리
3. 외부 BSM/correction 입력 접수
4. quantum dispatch
5. BSM 결과를 같은 시각의 R 앱 이벤트로 주입

새로운 미래 native quantum 이벤트를 만들지 않는 내장 memory noise이므로 horizon은
실행 중인 BSM/correction의 가장 이른 완료다. 다음 경계는 이 horizon과 ns-3 next event의 최소값이다.
native future event 부재와 두 엔진의 정확한 시각 일치 검사를 유지한다. epsilon은 사용하지 않는다.

고전 시간은 보존된 `p1_validation.analytic_timing()`으로 설정값에서 독립 계산한다.
P2에서도 실제 C++ 참가자는 `cosim-p1`이다. binary 이름과 IPC의 `COSIM_P1`은 의도적으로 동일하다.

## 5. 관측과 공통 로그

공통 event envelope v1, correction의 `[3] → 3`, `details.ancestor_pair_ids=[1,2]` 규약을 유지한다.
보고서의 `snapshot.checkpoints`에 다음 평가용 기록을 추가한다. fidelity는 모두 squared fidelity다.

| checkpoint | 시각 | 대상 |
|---|---|---|
| `bsm_start.AR/RB` | BSM 시작 | 각 입력 pair와 Phi+ |
| `bsm_end_inputs.AR/RB` | BSM 완료, 회로 적용 직전 | 각 입력 pair와 Phi+ |
| `frame` | BSM 완료, 측정 직후 | 실제 측정 비트에 대응하는 Bell frame |
| `correction_start` | 결과 패킷 도착, 보정 시작 | 같은 frame의 현재 상태 |
| `usable` | 실제 correction 완료 | 고정 Phi+ |

각 항목은 정수 `sim_time_ns`, `fidelity`, `density_matrix`를 갖는다.
밀도행렬 순서는 AR=`[A,R_AR]`, RB=`[R_RB,B]`, 출력=`[A,B]`다.
실수부·허수부를 따로 기록한다. 중간 관측값은 제어 패킷이나 dispatch 결정에 사용하지 않는다.

## 6. 독립 reference와 조건부 비교

`netsquid_reference_p2.py`는 별도 Python 프로세스로 실행되며 co-sim 모듈을 import하지 않는다.
같은 내장 noise class를 사용하되 자기 QuantumMemory와 native Protocol timer로 시간을 진행한다.
입력은 검증된 실제 BSM/correction 시작·완료 timestamp와 물리 모델 파라미터뿐이다.
seed나 co-sim 밀도행렬·fidelity·측정 비트를 reference 생성에 전달하지 않는다.

Reference는 t=0 EPR의 복제본 네 개를 독립적으로 보관한다. BSM 직전의 joint density matrix에
네 Bell bra/ket을 각각 수축하여 분기 확률 `p_m`과 정규화 조건부 상태 `rho_AB|m`을 구한다.
이는 co-sim의 CNOT/H/측정 circuit과 다른 검증 경로이며 새로운 noise model이 아니다.
조건부 상태를 같은 A/B 큐빗에 배정한다. memory position과 last-access time은 유지한다.
확률 0인 분기는 정규화하지 않고 기대값에서 제외한다.

각 분기를 native memory에 계속 저장하고, correction 완료 때 해당 비트의 합성 Pauli를 적용한다.
reference는 다음을 반환한다.

- BSM 시작·완료 직전의 입력 상태
- 네 분기의 확률과 frame/correction-start/usable 상태
- 확률 가중 기대 상태 `rho_ensemble = sum_m p_m rho_usable|m`

Co-sim은 실제로 관측한 분기에 대응하는 reference와 비교한다. 다른 분기끼리 상태 일치를 요구하지 않는다.
모든 비교점에서 최대 밀도행렬 원소 오차와 fidelity 오차는 `<= 1e-12`여야 한다.
확률은 유한한 `[0,1]` 값이고 합은 1이어야 한다. 표본이 확률 0인 분기를 택하면 실패다.
Reference 시각, 파라미터, 큐빗 순서도 별도로 확인한다.

반복 분포 시험은 동일 설정에서 256개 seed의 실제 co-sim transaction을 실행한다.
reference는 결정론적으로 네 분기를 전부 계산하므로, 같은 설정·시각에서 결과 표를 재사용할 수 있다.
재사용 시에도 매 run의 설정·시각·조건부 상태를 모두 검사한다.
네 outcome 빈도는 유의수준 1%의 Hoeffding union bound로 검사한다. 통계 허용오차는
`sqrt(log(8/0.01)/(2N))`이며 단일 상태 비교의 `1e-12` 허용오차와 혼용하지 않는다.

## 7. Delay sweep

Command propagation delay: 0.1 / 1 / 5 / 10 / 20 ms.
Result propagation delay: 0.2 / 1 / 5 / 10 / 20 ms.
25개 조합마다 noise on/off를 실행한다. 링크 rate, payload, 연산 duration, seed는 고정한다.
각 run은 실제 UDP 경로와 독립 reference를 통과해야 한다.

`summary.csv`의 두 fidelity 열을 구분한다.

- `co_sim_conditional_fidelity`: 해당 run이 실제 선택한 측정 분기의 fidelity
- `reference_ensemble_fidelity`: 네 분기를 정확한 확률로 가중한 기대 fidelity

Noise on/off는 같은 packet/operation timing을 가져야 한다. Off에서는 P1의 Bell 상태를 복원해야 한다.
Result delay만 바꾸면 BSM 시작·완료 상태는 유지되고 이후 A/B 저장 시간이 달라진다.
Command delay를 늘리면 BSM 시작 시각과 session 완료 시각이 그만큼 증가한다.

T1/T2 amplitude relaxation과 분기 확률 변화 때문에 고정 Phi+ fidelity는 일반적으로
모든 지연 구간에서 감소한다고 보장할 수 없다. `monotonic_sanity`에 기대값의 증가 구간을 기록하되
그 자체를 bridge 실패로 판정하지 않는다. 합격 기준은 정확한 시간과 같은 조건의 reference 상태 일치다.

## 8. 검증

- P0/P1 27개 회귀 테스트와 보존 파일 해시 검사
- Noise off의 P1 상태·event timing·bridge steps 재현
- 32회 실제 transaction으로 네 BSM 분기와 조건부 reference 비교
- 256회 실제 transaction의 outcome 빈도 및 표본 평균 상태 검사
- Command/result 지연과 BSM/correction duration 구간별 aging
- `00` correction duration의 noise 반영
- 동일 총 저장시간에서 경계 분할·반복 peek·snapshot 횟수에 대한 상태 불변성
- Native 모델 부착과 A/B 큐빗 객체 보존
- 결과 패킷 대기 aging을 의도적으로 건너뛰면 reference가 실패하는 검사
- 잘못된 분기의 상태 및 checkpoint 시각 검출
- 모델·시간·범위·단일 transaction 설정 검증
- T1-only, T2-only, 확률 0인 분기가 생기는 강한 감쇠
- 작은 sweep의 파일/행 검증과 전체 25조건 noise on/off sweep

## 근거

- [NetSquid 논문](https://www.nature.com/articles/s42005-021-00647-8): component 접근 시 elapsed-time decoherence와 측정 분기 처리.
- 설치된 NetSquid 1.1.7 `components/models/qerrormodels.py`의 `T1T2NoiseModel`: 파라미터 제약, 0 비활성화 규약, DM의 amplitude damping/dephasing 구현.
- 설치된 `QuantumMemory.peek` 문서: noise 적용과 last-access 갱신.

이 검증은 선택한 atomic memory 모델과 범위에 대한 것이다. P3의 quantum contention,
P4의 classical contention, P5의 두 부하 결합은 이후 별도 milestone으로 진행한다.
