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
/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_chained.py -v
/home/ns3/qunet/bin/python contrib/cosim/experiments/run_chained_evaluation.py \
  contrib/cosim/scenarios/chained-evaluation.json \
  --output-dir contrib/cosim/results/chained-evaluation-new
```

## 확인할 결과

- 전체 **307개 테스트 PASS**: 새 chain 검증 16개 + 기존 회귀 291개.
- 5개 무잡음 입력 × 16개 joint BSM 분기: **80개 chain**, 최종 fidelity≈1.
- 48개 조건 / **192개 chain** 분석, 독립 reference와 최대 상태 오차 **5.00×10⁻¹⁶**.
- 혼잡 burst에서 A의 후속 Teleport FIFO 대기 **1.1 / 2.2 ms**를 확인했다.

- [명세](SPEC-CHAINED.md): 실제 packet/자원 전달, 상태 소유권, timing·reference 계약.
- [검증 요약](results/chained-validation-summary.json).
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

원자료·회귀 로그·표·그림은 [압축본](baselines/chained-v5-results.tar.gz)과
[파일별 해시](baselines/chained-v5-results.json)에 보존한다. 새 checkout에서 복원할 때:

```bash
sha256sum -c contrib/cosim/baselines/chained-v5-results.sha256
tar --skip-old-files -xzf contrib/cosim/baselines/chained-v5-results.tar.gz
```
