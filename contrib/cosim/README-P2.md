# P2: 실제 패킷 시간과 quantum memory aging

P1에서 검증한 단일 A–R–B transaction에 NetSquid 내장 `T1T2NoiseModel`을 연결한다.
메모리의 경과 시간은 native component가 처리하며 bridge는 잡음을 직접 적용하지 않는다.
기본 검증 설정은 T1=20 ms, T2=10 ms다. 하드웨어 성능을 대표하는 설정은 아니다.

2026-09-16 기준 **P0/P1/P2 총 42개 테스트와 25조건 × noise off/on 50회 실행을 통과**했다.
전체 sweep의 최대 reference 밀도행렬 오차는 약 `2.22e-16`이다.

## 실행

ns-3 루트에서 실행한다. P2도 보존한 `cosim-p1` C++ 참가자와 UDP topology를 사용한다.

```bash
# 기존 binary가 없다면:
./ns3 build cosim-p0 cosim-p1 -j 2

~/qunet/bin/python contrib/cosim/python/run_p2.py \
  contrib/cosim/scenarios/p2-memory-aging.json \
  --output contrib/cosim/results/p2-memory-aging.json

~/qunet/bin/python contrib/cosim/python/run_p2_sweep.py \
  contrib/cosim/scenarios/p2-delay-sweep.json \
  --output-dir contrib/cosim/results/p2-delay-sweep

~/qunet/bin/python -m unittest discover -s contrib/cosim/tests -v
```

`p2-delay-sweep/summary.csv`와 `summary.json`에는 25개 지연 조합의 noise on/off 50회 결과가 있다.
각 transaction의 전체 로그와 reference는 `runs/`에 저장한다. 추가 Python 패키지는 필요 없다.

## 결과 읽기

- `snapshot.checkpoints.bsm_start`: BSM 시작 시 AR/RB 각각의 밀도행렬과 fidelity
- `bsm_end_inputs`: atomic BSM 회로 직전의 입력 상태, BSM duration의 aging 확인용
- `frame`: BSM 완료 직후 측정 비트에 대응하는 Bell frame과 비교한 상태
- `correction_start`: 실제 결과 패킷 수신 후, 보정 시작 시의 미보정 상태
- `usable`: 실제 보정 완료 후 고정 Phi+와 비교한 상태
- `cross_validation.observed_branch`: co-sim에서 실제로 측정한 m1m2
- `cross_validation.reference.branches`: 독립적으로 계산한 네 BSM 분기의 확률·상태
- `cross_validation.reference.ensemble`: 네 분기를 확률로 가중한 기대 출력 상태

CSV의 `co_sim_conditional_fidelity`는 이번 측정 분기의 값이다.
`reference_ensemble_fidelity`는 네 분기를 가중한 기대값이며 둘을 같은 평균으로 해석하지 않는다.
`USABLE`은 보정 완료를 뜻한다. 품질 임계값 통과나 얽힘 유지는 별도의 보장이 아니다.

## 파일

| 파일 | 역할 |
|---|---|
| `python/p2_quantum.py` | P1 연산 상속, 네 native memory position의 잡음 설정, 관측 |
| `python/run_p2.py` | P1에서 분리한 federation 실행 경로 |
| `python/p2_validation.py` | 설정·패킷 시간·자원·밀도행렬·로그 검증 |
| `python/netsquid_reference_p2.py` | 독립 native timer/메모리와 Bell projector 기준 모델 |
| `python/p2_reference_validation.py` | 실제 측정 분기에 맞춘 상태 비교 |
| `python/run_p2_sweep.py` | 두 링크의 지연 분리 sweep과 CSV/JSON |
| `tests/test_p2.py` | 시간 누적·분기·통계·누락 검출·P1 보존 검사 |

상세 모델과 합격 기준은 [SPEC-P2.md](SPEC-P2.md)에 있다.
P1 보존점은 Git tag `cosim-p1`이며 [해시 목록](baselines/p1-freeze.json)과
[코드·실행 결과 백업](baselines/p1-freeze.tar.gz)도 함께 보존했다.
