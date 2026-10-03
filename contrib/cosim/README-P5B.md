# P5-B — Native timed 모델 비교 평가

**Native Full Sync, No-Dq-R, Fixed-Dc로 pilot과 확대 평가를 다시 완료했다.**
실제 NetSquid QuantumProgram의 내부 gate 시간과 idle/active T1/T2를 세 모델에 동일하게 적용했다.
R의 local session start, 실제 Q2NS R→B UDP, shared B FIFO는 유지한다.

| 모델 | 실행 의미 |
|---|---|
| Full-Sync | Shared R FIFO → native BSM → 실제 result UDP → B FIFO → native correction |
| Fixed-Dc | 동일 native quantum 실행; result 전달만 별도 calibration 평균 지연으로 대체 |
| No-Dq-R | Session별 native R 실행 엔진으로 R 대기만 제거; 실제 완료시각에 UDP 재전송, B 공유 |
| Decoupled | Local-start R FIFO wait + No-Dq-R 실측 result delay를 합성; state 예측 없음 |

No-Dq-R은 실행 capacity만 늘리고 quantum state를 복제하지 않는다. Fixed-Dc의 가상 도착을
실제 ns-3 packet으로 기록하지 않는다. Native baseline 정의는 [SPEC-P5B](SPEC-P5B.md)를 따른다.

## 재실행 규모

- 전체 회귀 **258개 PASS**: Python 159, 평가/timing/계측 16, Q2NS native 83.
- Pilot **48 paired cases**, 144 model executions + calibration 6회.
- Expanded **384 paired cases**, **1,152 model executions + calibration 6회**, 모델별 **1,536 transactions**.
- 32 traffic seeds × 2 quantum seeds × 3 loads × 2 request intervals. Calibration/test seed 분리를 유지했다.
- 모든 정상 실행에서 drop=0, B wait=0, Q2NS state/qubit=0 (Fixed-Dc는 Q2NS 미실행).
- Expanded 최대 독립 native reference density-matrix error: **3.89e-16**.

[Pilot](results/native-p5b-pilot/summary.json) · [Expanded](results/native-p5b-expanded/summary.json) ·
[errors.csv](results/native-p5b-expanded/errors.csv) · [전체 회귀](results/native-timed/regression-summary.json)

## 확대 결과

요청 간격 0.8 ms의 latency MAE. 단위 ms, 평균 [95% traffic-cluster bootstrap CI].

| R→B load | Fixed-Dc | No-Dq-R | Decoupled |
|---:|---:|---:|---:|
| 0.0 | 0.000 [0.000, 0.000] | 1.200 [1.200, 1.200] | 0.000 [0.000, 0.000] |
| 0.35 | 0.174 [0.144, 0.206] | 1.188 [1.185, 1.191] | 0.117 [0.073, 0.165] |
| 0.7 | 0.242 [0.227, 0.258] | 1.188 [1.174, 1.208] | 0.223 [0.189, 0.260] |

같은 조건의 No-Dq-R 기대 fidelity bias와 실현된 service false-feasible fraction:

| Load | E[F] bias [95% CI] | False service feasible [95% CI] |
|---:|---:|---:|
| 0.0 | 0.0486 [0.0486, 0.0486] | 0.2500 [0.2500, 0.2500] |
| 0.35 | 0.0472 [0.0467, 0.0476] | 0.2344 [0.2109, 0.2500] |
| 0.7 | 0.0456 [0.0449, 0.0462] | 0.1875 [0.1484, 0.2188] |

**Latency는 atomic v2와 같지만, fidelity·service 판정은 새 native 회로 결과다.** 총 operation duration과
packet 조건은 같고, 내부 gate/noise의 순서가 바뀌었기 때문이다. 이전 fidelity 수치를 재사용하지 않았다.
이는 설정한 native model에서 R 대기 생략의 낙관 편향을 보여주며, 실제 장비의 오차율을 뜻하지 않는다.

F_min=0.5, local-start deadline=5 ms를 유지했다. 비율의 분모는 전체 paired transactions이며
conditional false-positive rate가 아니다. CI가 퇴화하거나 오판이 0건이어도 모집단 확률을 확정하지 않는다.
CI는 두 calibration seed를 고정한 periodic traffic-phase workload에 조건화된다.
2-ms 간격에서 이 workload의 R wait는 0이므로 No-Dq-R/Decoupled latency 오차도 0이다.
모든 조건의 fidelity 및 deadline-only/service 판정은 [RESULTS.md](paper/RESULTS.md)에 있다.

## Physical timing / noise

BSM은 CNOT/H/M0/M1 = 600/200/400/400 μs, correction은 X/I와 Z/I 각 25 μs다.
Gate 합계는 기존 BSM 1.6 ms, correction 50 μs와 같다. T1=20 ms, T2=10 ms이며 모든 EPR은 t=0에 생성한다.
Idle와 active storage aging을 각각 한 번 적용하고 ideal gate는 instruction 완료 때 실행한다.
Gate duration은 illustrative parameter다. Calibration된 hardware gate model이라고 주장하지 않는다.
별도 mixed/cost 실험은 correction 각 슬롯 250 μs(합계 500 μs)를 쓰고 B 경합을 허용한다.

## 실행

```bash
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_native_p5b.py \
  contrib/cosim/scenarios/native-p5b-paper-expanded.json \
  --output-dir contrib/cosim/results/native-expanded-new
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/experiments/tests -p test_native_evaluation.py -v
```

완료 summary가 있는 경로는 거절한다. 실패는 failure.json과 가능한 원본 report로 남긴다.
기존 `run_p5b.py`는 atomic v2 재현용이다. [과거 논문 산출물](baselines/atomic-v2-paper.tar.gz)과
[과거 실행 원자료](baselines/direct-start-v2-results.tar.gz)는 보존한다.
`max_density_matrix_error`는 각 모델 자체의 timing에서 독립 reference와 일치한다는 검증값이다.
Full Sync와 단순화 모델 사이의 예측 오차가 0이라는 뜻이 아니다.
