# Hybrid v5 — Swapping으로 만든 얽힘을 A→B Teleportation에 사용

A=Alice, R=repeater, B=Bob이다. **R의 SwapApp 출력 A–B pair를 A의
TeleportationApp이 실제로 소비한다.** A/B qubit 객체와 quantum state를 그대로
이어받으며, teleportation용 EPR을 새로 만들지 않는다.

```text
A–R / R–B EPR 전달
 → R swapping BSM
 → R→B 실제 UDP 결과
 → B swapping correction
 → B→R→A 실제 준비 완료 UDP
 → A teleportation BSM
 → A→R→B 실제 UDP 결과
 → B teleportation correction
```

A/R/B 각각 native QuantumProcessor와 FIFO를 사용한다. B의 correction FIFO는
Swap과 Teleport가 공유하고, 여러 chain은 R·A·B와 classical links를 함께 사용한다.
공통 NativeExecutionCore와 기존 ProvisionedFederation을 재사용한다.
기존 R→B mixed 실험은 v4 회귀 기준으로 보존했다.

## 실행

ns-3 루트에서 실행한다. Q2NS external Swap/Teleport patch와 NetSquid 설치는
[기존 v4 실행 환경](README-PROVISIONED.md)을 사용한다.

```bash
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 configure
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-chained
/home/ns3/qunet/bin/python contrib/cosim/python/run_chained.py \
  contrib/cosim/scenarios/chained-single.json \
  --output contrib/cosim/results/chained-single-new.json.gz --enumerate-branches
/home/ns3/qunet/bin/python contrib/cosim/python/run_chained.py \
  contrib/cosim/scenarios/chained-contention.json \
  --output contrib/cosim/results/chained-contention-new.json.gz
/home/ns3/qunet/bin/python contrib/cosim/python/run_chained.py \
  contrib/cosim/scenarios/chained-minus-i.json \
  --output contrib/cosim/results/chained-minus-i-new.json.gz --enumerate-branches
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_chained.py -v
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_chained_evaluation.py \
  contrib/cosim/scenarios/chained-evaluation.json \
  --output-dir contrib/cosim/results/chained-evaluation-new
```

## 확인할 결과

- 통과 기록 **308개**: 이번에 chain 검증 **17개를 재실행**, 변경 없는 기존 회귀 291개 결과는 보존.
- 6개 무잡음 입력 `0, 1, +, -, +i, -i` × 16개 joint BSM 분기: **96개 chain**을 새로 실행, 최종 fidelity≈1.
- Native T1/T2를 켠 **6개 입력 × A–R 지연 2조건 = 12회** 추가 검증:
  관측 분기의 native checkpoint/state 비교와 조건별 reference 16분기 열거, 최대 오차 **3.33×10⁻¹⁶**.
- `+i/-i`의 복소 위상 부호가 서로 반대임을 BSM 시작 시점에 검증했다.
- 기존 `+i` workload의 48개 조건 / **192개 chain** 분석은 유지하며, 여섯 입력 평균으로 해석하지 않는다.
  보존된 분석까지 포함한 독립 reference 최대 상태 오차는 **5.00×10⁻¹⁶**.
- 혼잡 burst에서 A의 후속 Teleport FIFO 대기 **1.1 / 2.2 ms**를 확인했다.

- [명세](SPEC-CHAINED.md): 실제 packet/자원 전달, 상태 소유권, timing·reference 계약.
- [검증 요약](results/chained-validation-summary.json).
- [여섯 입력 noise-on 결과](results/chained-tests/noise-inputs.json)와
  [이번 실행 로그](results/chained-regression/chained-six-inputs-tests.log).
- [분석 결과](paper/chained-v5/RESULTS.md).
- [평가 summary](results/chained-evaluation/summary.json)와 session별 `chains.csv`.
- `snapshot.handoffs`: 같은 A/B 객체를 넘겼는지와 pair provenance.
- `metrics.chains`: 전체 latency 및 resource/R/A/B wait와 각 packet 지연.
- `cross_validation.chains`: 두 BSM/두 correction의 독립 reference 상태 비교.

기본 입력 qubit과 elementary EPR은 t=0에 생성한다. 첫 quantum-link delivery의
준비 지식은 기존과 같이 R에 이상적인 지연 0 통지이며, swapping이 만든 pair의
준비 지식은 새 B→R→A packet으로 전달한다. 이 둘을 구분한다.
무손실·고정 topology이며 photon generation, heralding, retry, 임의 protocol DAG는
지원 범위에 포함되지 않는다. 세부 제한과 분석 해석은 명세에 고정했다.

## 원자료 보존

여섯 입력 검증을 포함한 원자료·회귀 로그·표·그림은
[새 압축본](baselines/chained-v5-six-inputs-results.tar.gz)과
[파일별 해시](baselines/chained-v5-six-inputs-results.json)에 보존한다.
기존 5개 입력의 `chained-v5-results.tar.gz`도 그대로 보존했다. 새 checkout에서 최신 자료를 복원할 때:

```bash
sha256sum -c contrib/cosim/baselines/chained-v5-six-inputs-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/chained-v5-six-inputs-results.tar.gz
```
