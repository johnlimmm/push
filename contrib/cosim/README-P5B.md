# P5-B — 단순화 모델 비교 평가

**평가 코드와 첫 pilot sweep을 완료했다.** Q2NS Full Sync를 기준으로
Fixed-Dc, No-Dq-R, Decoupled의 예측을 비교한다.
기존 P0–P5-A/Q2NS 소스는 수정하지 않았으며
[freeze manifest](baselines/q2ns-freeze.json)와 archive로 보존했다.

## 구현된 baseline

| 모델 | 적용한 단순화 |
|---|---|
| Full-Sync | 기존 Q2NS/ns-3 실제 packet + 공유 R FIFO + NetSquid aging |
| Fixed-Dc | 별도 calibration의 command/result 평균 지연 + quantum FIFO/NetSquid 재실행 |
| No-Dq-R | R 실행 capacity 제약만 제거하고 실제 Q2NS/ns-3 packet을 새 완료시각에 재전송 |
| Decoupled | No-Dq-R의 실측 classical delay와 무부하 command 도착에 대한 R FIFO wait를 합성 |

Decoupled는 latency/deadline만 예측한다. fidelity/service feasibility 값은 null이다.
상세 정의와 Q-run 도착시각은 [SPEC-P5B](SPEC-P5B.md)에 고정했다.

## 검증과 실행 규모

- P5-B 테스트 **16개**, P0–P5-A 회귀 **94개**, Q2NS 연동 회귀 **12개**: **122개 PASS**.
- 3 classical loads × 2 request intervals × 4 traffic seeds × 2 quantum seeds = **48 paired cases**.
- 별도 calibration **6회**, 평가 시뮬레이션 **144회**, Decoupled 합성 **48회**.
- 모델별 평가 transaction **192개**. 모든 정상 실행에서 packet drop=0, B wait=0.
- Full/No-Dq/Fixed의 독립 quantum reference 대비 최대 density-matrix error: **3.33×10⁻¹⁶**.
- B 경합, calibration/test seed 중복, 잘못된 packet/resource/clock/reference는 검출한다.

요약: [validation](results/p5b-validation-summary.json), [pilot summary](results/p5b-pilot/summary.json).
로그: [P5-B](results/p5b-test-suite.log), [P0–P5-A](results/p5b-regression-suite.log),
[Q2NS](results/p5b-q2ns-regression-suite.log).

이번 pilot은 모든 모델의 correction duration을 **50 μs**로 설정했다.
최소 result packet serialization 88 μs보다 짧게 두어 No-Dq-R에서도 B contention을 배제했다.
기존 P5-A의 500 μs 설정은 보존했다. BSM은 계속 1.6 ms다.

## 첫 결과

요청 간격 0.8 ms에서 Full Sync 대비 **latency MAE**는 다음과 같다. 단위는 ms다.

| Background offered load / link | Fixed-Dc | No-Dq-R | Decoupled |
|---|---:|---:|---:|
| 0 | 0 | 1.2000 | 0 |
| 0.35 | 0.1915 | 1.2100 | 0.1611 |
| 0.7 | 0.2438 | 1.1717 | 0.2285 |

같은 조건에서 No-Dq-R의 **기대 fidelity bias**는 각각 +0.04188 / +0.04140 / +0.03863이다.
R 대기가 양자 저장시간뿐 아니라 result packet의 queue phase에도 영향을 주기 때문에
No-Dq-R을 Full의 완료시각에서 R wait를 빼는 것으로 대신할 수 없다.

요청 간격 2 ms에서는 이 workload의 R wait가 없어서 No-Dq-R과 Decoupled의 latency 오차가 0이다.
Fixed-Dc는 혼잡 조건에서 각각 0.2078 / 0.2546 ms의 latency MAE를 보였다.

현재 미리 설정한 F_min=0.5, command TX 기준 deadline=5 ms에서는
**service false feasible/infeasible은 모두 0건**이었다.
일부 혼잡 조건의 deadline-only false feasible은 6.25%였지만,
이를 fidelity까지 포함한 서비스 오판으로 표현하지 않는다.
이 설정으로 service feasibility 오차가 입증됐다고 주장하지 않는다.

신뢰구간은 session/quantum 반복을 traffic seed 안에서 평균낸 뒤 traffic seed를 재표집했다.
독립 traffic 조건은 cell마다 4개뿐이다. 따라서 현재 결과는 **유한 workload pilot**이며
논문용 성능 일반화에는 사전에 확대할 seed/부하/서비스 기준을 정한 별도 실험이 필요하다.

## 결과 확인

- [errors.csv](results/p5b-pilot/errors.csv): session별 Δlatency, Δfidelity, ΔE[F], 성공확률 오차와 오판.
- [calibration.json](results/p5b-pilot/calibration.json): test와 분리된 원시 지연, 평균과 provenance.
- `results/p5b-pilot/runs/<조건>/`: Full-Sync / No-Dq-R / Fixed-Dc 원본 trace·state와 comparison.
- `summary.groups`: 모델·부하·요청 간격별 bias/MAE 및 traffic-cluster bootstrap 95% interval.
- `comparison.models`: 관측 fidelity와 branch 확률 가중 기대 fidelity/성공확률을 구분.
- `comparison.batch_rates`: 첫 command TX부터 마지막 correction까지의 유한 batch throughput/goodput.

`max_density_matrix_error`는 각 모델 구현이 그 모델의 operation timing에서 독립 reference와
일치한다는 검증값이다. Full Sync와 단순화 모델 사이의 예측 오차가 0이라는 의미가 아니다.

## 실행

ns-3 루트에서 실행한다. 기존 `cosim-q2ns` 참가자 바이너리를 그대로 사용한다.

```bash
./ns3 build cosim-q2ns
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_p5b.py \
  contrib/cosim/scenarios/p5b-pilot.json \
  --output-dir contrib/cosim/results/p5b-new-run

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_p5b.py -v
```

완료된 summary가 있는 출력 경로는 덮어쓰지 않는다. 다른 경로를 사용한다.
calibration/test traffic seed가 겹치면 시작 전에 거절한다.
실행 실패는 failure.json에 기록하며, 참가자가 제공한 실패 report도 함께 저장한다.

평가 코드는 `experiments/`에 모았다.
`p5b_nodq.py`와 `p5b_nodq_validation.py`는 frozen Q2NS runner/P5 validator에서 분리한 평가용 fork다.
원본을 monkey patch하지 않으며 baseline 때문에 원래 federation 동작을 바꾸지 않는다.
