# P5-B — Direct-start 구조의 단순화 모델 비교

**Controller 경로를 제거한 새 구조에서 pilot과 확대 평가를 다시 완료했다.**
Full Sync와 No-Dq-R은 R에서 직접 시작하는 실제 Q2NS 앱과 `cosim-hybrid`를 실행한다.
Full/No-Dq/Fixed는 동일 `HybridExecutionCore`/`HybridFederation`과 NetSquid adapter를 사용한다.

| 모델 | 적용한 단순화 |
|---|---|
| Full-Sync | Local start → R FIFO → BSM → 실제 R→B UDP → B FIFO → correction |
| Fixed-Dc | R FIFO 유지, result 전달만 별도 calibration의 평균 R→B delay로 대체 |
| No-Dq-R | R capacity 제약만 제거. 새 BSM 완료시각에 실제 Q2NS 결과 packet을 생성·재전송 |
| Decoupled | Local start의 독립 R FIFO wait + No-Dq-R 실측 result delay를 합성 |

**Latency = correction completion − local `session_start_ns`.**
Command delay/calibration 항은 없다. Decoupled는 latency/deadline만 정의하며 fidelity/service는 null이다.
정확한 범위·식·통계 계약은 [SPEC-P5B](SPEC-P5B.md)를 따른다.

## 재실행 규모

- P5-B 전용 18개 테스트. 전체 회귀는 Python 140 + timing/계측 7 + Q2NS native 83 = **230개 PASS**.
- Pilot: 48 paired cases, 144 model executions + 별도 calibration 6회.
- Expanded: 32 traffic seeds × 2 quantum seeds × 3 loads × 2 intervals = **384 paired cases**.
- Expanded: **1152 model executions + calibration 6회**, 모델별 **1536 transactions**.
- 모든 정상 실행에서 packet drop=0, B wait=0, native Q2NS state/qubit=0 (Fixed-Dc는 Q2NS 미실행).
- 최대 독립 reference density-matrix error: **2.78×10⁻¹⁶**.

[전체 검증](results/direct-start-validation-summary.json),
[pilot](results/direct-start-p5b-pilot/summary.json),
[expanded](results/direct-start-p5b-expanded/summary.json),
[원자료 errors.csv](results/direct-start-p5b-expanded/errors.csv).

## 새 결과

요청 간격 0.8 ms의 latency MAE, 단위 ms. 평균 [95% traffic-cluster bootstrap CI].

| R→B background load | Fixed-Dc | No-Dq-R | Decoupled |
|---:|---:|---:|---:|
| 0 | 0.000 [0.000, 0.000] | 1.200 [1.200, 1.200] | 0.000 [0.000, 0.000] |
| 0.35 | 0.174 [0.144, 0.206] | 1.188 [1.185, 1.191] | 0.117 [0.073, 0.165] |
| 0.7 | 0.242 [0.227, 0.258] | 1.188 [1.174, 1.208] | 0.223 [0.189, 0.260] |

같은 조건의 No-Dq-R 기대 fidelity bias:

| Load | E[F] bias [95% CI] | False service-feasible fraction [95% CI] |
|---:|---:|---:|
| 0 | 0.0435 [0.0435, 0.0435] | 0.2500 [0.2500, 0.2500] |
| 0.35 | 0.0423 [0.0419, 0.0426] | 0.1875 [0.1484, 0.2266] |
| 0.7 | 0.0409 [0.0403, 0.0415] | 0.0938 [0.0547, 0.1328] |

F_min=0.5와 local-start 기준 deadline=5 ms를 그대로 사용했다. 새 구조에서는 No-Dq-R의
service false-feasible이 관측된다. 이전 command-path 결과의 “service 오판 모두 0”을 재사용하지 않는다.
위 비율의 분모는 전체 paired transactions이며 conditional false-positive rate가 아니다.
무부하는 traffic phase가 비활성이므로 0-width CI를 일반적인 오류 확률의 확정값으로 해석하지 않는다.

2-ms 간격에서는 이 workload의 R wait가 없어 No-Dq-R/Decoupled의 latency 오차가 0이다.
Fidelity, deadline-only/service 판정을 구분한 모든 조건의 값은 [논문 결과 표](paper/RESULTS.md)에 있다.
CI는 고정 calibration 두 traffic seed와 periodic background phase family에 조건화된다.

P5-B의 correction은 50 μs, BSM은 1.6 ms다. Swap result 직렬화 88 μs보다 correction을 짧게
두어 B contention을 배제한다. Hybrid mixed의 500 μs correction/B FIFO 검증과 구분한다.
모든 EPR은 t=0에 생성하고 T1=20 ms, T2=10 ms native aging을 사용한다.

## 실행

```bash
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-hybrid -j 1
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_p5b.py \
  contrib/cosim/scenarios/p5b-paper-expanded.json \
  --output-dir contrib/cosim/results/direct-start-new-evaluation
/home/ns3/qunet/bin/python -m unittest discover -s contrib/cosim/tests -p test_p5b.py -v
```

완료 summary가 있는 출력 경로는 거절한다. 실패는 failure.json과 가능한 원본 report로 남긴다.
이전 구현/수치는 [Hybrid v1 archive](baselines/hybrid-v1-freeze.tar.gz)에 보존한다.
`max_density_matrix_error`는 각 모델 자체의 operation timing에서 reference와 일치한다는 검증값이며,
Full Sync와 단순화 모델 간 예측 오차가 0이라는 뜻이 아니다.
