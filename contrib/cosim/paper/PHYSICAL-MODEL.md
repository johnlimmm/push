# 현재 평가의 물리 모델: 문헌 gate 시간 + 20/10 ms memory

현재 설정은 **T1=20 ms, T2=10 ms**와 새로 확인한 문헌의 gate 시간이다.
이전 T1=10 h, T2=1 s 평가와 출처 검토는
[이전 모델 문서](PHYSICAL-MODEL-long-memory.md)에 보존했다.
현재 실행 계획은 [memory-evaluation.json](../scenarios/memory-evaluation.json),
결과와 그림은 [evaluation/RESULTS.md](evaluation/RESULTS.md)를 기준으로 읽는다.

## 채택값·출처·유도값

| 항목 | 현재 값 | 근거 |
|---|---:|---|
| CNOT | 20 μs | Liao et al. (2022), Table 3; Iqbal et al. (2023), Table 3 |
| H / X / Z | 각각 5 ns | 위 single-qubit 시간표; Iqbal은 H/X/Z를 명시 |
| 개별 측정 | 3.7 μs | 위 두 문헌의 Table 3 |
| Memory T1 / T2 | 20 / 10 ms | Bugalho et al. (2023), Fig. 3a의 사용 선례 |
| Gate depolarization | p=0.01 | Iqbal et al., Section 4; 아래 noise 구현 가정 참조 |
| BSM | 27.405 μs | QuCl 직렬 CNOT–H–M–M: 20,000+5+3,700+3,700 ns |
| Correction | 10 ns | QuCl의 X-or-I, Z-or-I 고정 slot: 각각 5 ns |

BSM과 correction 합계는 현재 회로에서 계산한 값이며 문헌의 장비 실측값이 아니다.
T1/T2 수치는 이전 QuCl 설정을 유지한 것이다. 문헌에서 같은 수치를 확인했다는
사실을 QuCl이 처음부터 그 논문을 근거로 선택했다는 뜻으로 쓰지 않는다.

### 논문에 인용할 문헌

1. Liao et al., *Benchmarking of quantum protocols*, Scientific Reports 12,
   5298 (2022), [DOI](https://doi.org/10.1038/s41598-022-08901-x), Table 3.
2. Iqbal et al., *Investigating Imperfect Cloning for Extending Quantum
   Communication Capabilities*, Sensors 23(18), 7891 (2023),
   [DOI](https://doi.org/10.3390/s23187891), Table 3 및 Section 4.
3. Bugalho et al., *Resource-efficient simulation of noisy quantum circuits
   and application to network-enabled QRAM optimization*, npj Quantum
   Information 9, 105 (2023),
   [DOI](https://doi.org/10.1038/s41534-023-00773-x), Fig. 3a.

영문 원고의 [evaluation.tex](evaluation/evaluation.tex)와
[references.bib](evaluation/references.bib)에 출처를 함께 제공한다.

## 무엇을 모델링했는가

각 항목에 문헌 사용 선례가 있는 **조합형 추상 모델**이다. 한 하드웨어의
calibration이나 원 논문 전체의 재현을 의미하지 않는다. 특히 Bugalho 논문은
전자/핵스핀을 구분하지만, QuCl은 20/10 ms를 모든 memory 위치에 균일하게 적용한다.
Liao/Iqbal의 gate 시간과 Bugalho의 memory 수치를 결합했다는 점을 명시한다.

- NetSquid native T1T2NoiseModel이 idle/active 저장시간을 반영한다.
- 현재 co-simulation과 평가 reference 모두 NetSquid
  `qapi.fidelity(qubits, target, squared=True)`로 충실도를 계산한다.
  별도 평가 코드는 분기 확률 가중, 입력·session 평균과 신뢰구간만 집계한다.
- 입력 qubit은 t=0부터 저장된다. EPR half는 전송 중 quantum channel 모델을 따르고,
  목적지 memory에 들어온 뒤 해당 memory의 noise가 적용된다.
- p=0.01은 각 gate operand에 독립 depolarization으로 적용한다.
  실제 CNOT/H/X/Z 직전에, active memory noise 이후에 적용하는 순서는 QuCl 가정이다.
- 측정은 ideal readout이며, 측정 시간과 사용하지 않는 correction slot에는
  storage noise만 적용한다. 초기 상태는 이상적이고 quantum transit은 무손실·무잡음이다.
- 연산과 packet 크기가 고정되어 memory 수치를 바꿔도 실행 일정은 바뀌지 않는다.
  달라지는 것은 그 일정에 따라 진화하는 quantum state다.

## Fig. 3–5의 비교 설계

- Workflow 시작 간격: 13.703 / 27.405 / 54.810 μs.
  BSM 실행시간 27.405 μs를 기준으로 각각 **0.5× / 1× / 2× 간격**이라고 부른다.
  바뀌는 것은 시작 간격이며, 각 workflow의 BSM은 항상 온전히 실행된다.
  0.5× 간격은 정수 ns로 올림했다. 유한 4-session batch이며 정상상태 부하율 주장이 아니다.
- R→B background offered load: 0 / 0.25 / 0.50 / 0.75.
  Classical 100 Mb/s, propagation 100 μs/hop은 실험 가정으로 gate 문헌과 구분한다.
- 매 조건에서 입력 0, 1, +, −, +i, −i를 각각 별도의 4-session batch로 실행한다.
  각 입력의 16개 joint measurement branch를 확률 가중해 최종 fidelity를 계산한다.
- 입력과 session을 traffic phase 안에서 평균한 뒤 phase를 bootstrap한다.
  여섯 입력을 여섯 개의 독립 traffic 표본으로 세지 않는다.
- Fig. 3은 Swap→Teleport 완료시간, Fig. 4는 같은 chain의 최종 fidelity다.
  Fig. 5는 swapping 구간의 단순화 모델 오차이며 전체 chain ablation과 구분한다.

모든 자원이 t=0에 생성되므로 요청 간격을 늘리면 시작 전 저장시간도 늘어난다.
따라서 간격 간 fidelity 차이를 quantum queue만의 효과로 해석하지 않는다.
네트워크 부하 효과는 요청 간격을 고정해 비교한다.

이전 1초 T2 결과는 [evaluation-long-memory](evaluation-long-memory/RESULTS.md),
더 이른 controlled 결과는 [evaluation-controlled](evaluation-controlled/RESULTS.md)에
보존한다. 현재 profile의 수치와 혼합하지 않는다.
