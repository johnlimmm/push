> 이전 T1=10 h, T2=1 s 평가의 문서입니다. 현재 설정은 [PHYSICAL-MODEL.md](PHYSICAL-MODEL.md)를 참조하세요.

# 물리 모델의 근거와 문헌 기반 재평가

작성일: 2026-10-04; 적용·재평가 완료: 2026-10-05.
**상태: Liao–Iqbal nominal profile 적용 및 새 실험 완료.**

논문 반영: [영문 설명·출처 비교 표](evaluation-long-memory/physical-model.tex)를
[평가 원고](evaluation-long-memory/evaluation.tex)의 setup에 포함했고,
[references.bib](evaluation-long-memory/references.bib)에 Liao/Iqbal/Campbell 3편을 등록했다.
문헌 profile로 평가 588회와 별도 calibration 13회를 실행했다.
6개 입력 × 16개 joint branch를 검증했고, 최대 density-matrix error는
7.22×10⁻¹⁶이다. [새 결과·그래프](evaluation-long-memory/RESULTS.md)에서 확인할 수 있다.

채택값은 CNOT 20 μs, H/X/Z 5 ns, measurement 3.7 μs,
T1=10 h, T2=1 s, gate depolarization parameter 0.01이다.
BSM 27.405 μs와 correction 10 ns는 현재 직렬 회로에서 유도했다.
Gate noise를 각 operand에 독립적으로 적용하는 위치, 이상적 readout/초기화와
무손실 quantum transit은 QuCl 가정으로 명시했다. 상세 NV 장비 재현은 아니다.

## 판단

현실적인 장비의 latency/fidelity를 주장하려면 gate, 측정, memory를 함께 설명하는
물리 모델이 필요하다. NetSquid native component 사용과 독립 reference 일치는
지정한 모델의 실행 정확성을 검증한다. 그 파라미터가 실제 장비를 대표한다는 검증은 별개다.

이전 controlled 결과는 [별도 패키지](evaluation-controlled/RESULTS.md)로 보존한다.
새 결과는 문헌 기반 nominal model의 실행 평가이며, 장비 calibration에 의한 예측은 아니다.

## 이전 controlled 기본값 — 회귀 baseline으로 보존

| 항목 | 현재 설정/의미 | 코드 근거 |
|---|---|---|
| BSM | CNOT 600 μs + H 200 μs + 직렬 측정 400 μs × 2 = 1.6 ms | [native_config.py](../python/native_config.py) |
| Correction | X 또는 I, Z 또는 I에 각각 고정 시간; 기본 합계 500 μs | [native_programs.py](../python/native_programs.py) |
| Memory | 기본 T1=20 ms, T2=10 ms; qubit 종류 구분 없음 | [p2_validation.py](../python/p2_validation.py), [chained_core.py](../python/chained_core.py) |
| Gate/readout 오류 | active 시간의 T1/T2 noise 후 ideal gate/measurement; 별도 오류 파라미터 없음 | [native_programs.py](../python/native_programs.py) |
| 자원 용량 | chain 수에 따라 memory 위치를 미리 할당; operation FIFO와 물리 memory 입장 제약은 다름 | [chained_core.py](../python/chained_core.py) |

`native_config.py` 자체도 시간을 illustrative로 명시한다. **1.6 ms를 선택한
하드웨어 문헌 근거는 현재 설정에 없다.** P5-B의 50 μs correction은 B contention을
제외하기 위한 별도 실험 설정이며 기본 500 μs와 구분해야 한다.

## 이전 수치에 대한 문헌 확인 결과

| 확인 대상 | 확인 결과 | 뒷받침할 수 있는 범위 |
|---|---|---|
| T1=20 ms, T2=10 ms | Bugalho et al. (2023), Fig. 3a에서 같은 값 사용 | NetSquid 기반 시뮬레이션의 사용 선례 |
| CNOT 600 μs | Campbell et al. (2025)의 CNOT에 사용하는 two-qubit gate 시간과 일치 | 수치의 문헌 사용 선례; QuCl의 원래 선택 근거였다는 뜻은 아님 |
| CNOT 600 μs, H 200 μs, 측정 400 μs 조합 | 확인한 문헌의 완전한 시간표와 일치하지 않음 | 현재는 illustrative 설정 |
| X/Z 각 250 μs 또는 P5-B의 각 25 μs | 현재 설정에 하드웨어 출처가 명시되지 않음 | 고정 correction slot을 둔 실험 가정 |
| BSM 1.6 ms | 현재 instruction 합계에서 유도 | 시간 합산의 정확성; 장비 측정값은 아님 |

Bugalho et al., *Resource-efficient simulation of noisy quantum circuits and application
to network-enabled QRAM optimization*, npj Quantum Information 9, 105 (2023):
[본문 및 Fig. 3](https://www.nature.com/articles/s41534-023-00773-x).
이 논문은 전자/핵스핀의 coherence time을 구분하고 파라미터를 sweep한다.
따라서 동일한 20/10 ms 수치가 등장한다는 사실만으로 QuCl의 균일 memory와
gate 시간 전체가 해당 장비를 재현한다고 할 수 없다. QuCl이 처음부터 이 논문을
근거로 값을 정했다는 provenance도 확인되지 않았다.

**문헌에 근거한 추상 processor 모델을 채택하는 것도 가능하다.** 예를 들어
Avis et al.의 Supplementary Note 1G는 CNOT–H–Z 측정의 abstract node를 명시하고,
NV 모델에서 유도한 Table 3에 swap 503.7 μs, swap quality 0.83,
T1=10 h, T2=1 s를 함께 제시한다. 이는 물리 NV 모델을 직접 구현하는 것과 다른
선택지다. 다만 503.7 μs는 aggregate swap 시간이며 CNOT/H/개별 측정 시간표가 아니다.
이를 임의로 분할하거나 swap quality를 CNOT fidelity로 대체하면 새로운 가정이 된다.

결론: 현재 memory와 CNOT 수치에는 각각 문헌 사용 선례가 있지만 현재 instruction
시간표 전체를 정당화하지는 않는다. 아래에는 실제로 함께 보고된 시간표를 정리했다.
NV 구현 확장을 시간표 채택의 선행 조건으로 삼지 않는다.

## 직접 대응되는 문헌 시간표

### A. Liao (2022) 및 Iqbal (2023): CNOT/H/measurement를 명시한 NetSquid 모델

Liao, Bahrani, Ferreira da Silva, Kashefi, *Benchmarking of quantum protocols*,
Scientific Reports **12, 5298 (2022)**의 **Table 3, 본문 p.8**은
NetSquid VBQC 평가에서 single-qubit gate 5 ns, CNOT/CZ 20 μs,
measurement 3.7 μs를 사용한다. 저자들은 NV 기반 nominal model로 설명한다.
출처: [논문](https://www.nature.com/articles/s41598-022-08901-x),
[출판본 PDF](https://pure.tudelft.nl/ws/portalfiles/portal/117148149/s41598_022_08901_x.pdf).

Iqbal et al., *Investigating Imperfect Cloning for Extending Quantum Communication
Capabilities*, Sensors **23(18), 7891 (2023)**의 **Table 3, 본문 p.10**은
Liao 논문을 reference 34로 인용하며 single-qubit 항목에 **X/Z/H를 직접 명시**한다.
같은 Section 4에서 memory **T1=10 h, T2=1 s**, gate depolarization probability
**0.01**을 사용한다. 따라서 서로 다른 논문에서 memory와 gate를 임의로 조합할
필요 없이 한 평가의 설정을 확인할 수 있다.
출처: [논문](https://doi.org/10.3390/s23187891),
[출판본 PDF](https://inspirehep.net/files/4e6558720f78bce1169da5bccca62e92).

| 항목 | 문헌 시간 | NetSquid ns 단위 |
|---|---:|---:|
| H / X / Z | 5 ns | 5 |
| CNOT | 20 μs | 20,000 |
| 개별 measurement | 3.7 μs | 3,700 |

현재의 직렬 BSM 회로에 적용하면 `20,000 + 5 + 2 × 3,700 = 27,405 ns`다.
**27.405 μs는 QuCl 회로에서 계산한 값이며 문헌이 보고한 BSM 실측값이 아니다.**
시간만 채택할 경우 memory/gate/readout 모델까지 원 논문을 재현했다고 쓰지 않는다.
이 표는 논문 기반 추상 processor 설정의 근거다. 아래 Avis의 상세 NV 모델과는
연산 추상화가 다르므로 CNOT 20 μs를 모든 NV 장비의 native gate 시간으로 일반화하지 않는다.

### B. Campbell (2025): 600 μs two-qubit gate를 포함한 trapped-ion 모델

Campbell, Lawey, Razavi, *Quantum data centres: a simulation-based comparative noise
analysis*, Quantum Science and Technology **10, 015052 (2025)**,
**Table 1, 본문 p.9 및 Section 4.1–4.2**는 NetSquid/nuqasm2 평가에 아래 시간을 사용한다.
출처: [DOI](https://doi.org/10.1088/2058-9565/ad9cb8),
[출판본 PDF](https://eprints.whiterose.ac.uk/id/eprint/220694/1/Campbell_2025_Quantum_Sci._Technol._10_015052.pdf).

| 항목 | 문헌 시간 | 근거의 성격 |
|---|---:|---|
| Single-qubit gate | 135 μs | IonQ Aria 자료 [46]; H 개별 시간을 별도로 표기하지 않음 |
| Two-qubit gate (시뮬레이션의 CNOT) | 600 μs | IonQ Aria 자료 [46] |
| Measurement | 6 ms | 저자 추정값: two-qubit 시간의 10배, 각주 a |

135/600 μs는 [IonQ 원 자료](https://www.ionq.com/resources/ionq-aria-practical-performance)
에서도 확인된다. 업체의 two-qubit gate 시간을 native CNOT의 직접 실측값으로
바꾸어 표현하지 않는다. Measurement 6 ms 역시 실측값으로 쓰지 않는다.
이 시간표를 현재 직렬 회로에 대응시키면 BSM은 **12.735 ms**로 계산된다.

이 논문의 memory는 depolarization 모델이다. Table 1의 T1=10–100 s는
`r=1/T1`의 lifetime이며 대표 rate는 0.055 s⁻¹이다.
이를 현재 T1T2NoiseModel의 amplitude-relaxation T1과 같은 의미로 복사하면 안 된다.

### 적용 판단

**이번 재평가는 A의 시간·memory·gate-noise 파라미터를 채택했다.**
B는 기존 600 μs의 사용 선례와
다른 하드웨어 시간 척도를 확인하는 근거다. 두 모델의 값을 섞지 않는다.
채택한 시간표에서 BSM 처리시간을 유도하고 요청 간격을 다시 설계한다.
원 모델에 포함된 noise를 생략한 controlled 조건은 그 생략을 명시한다.

## 하드웨어 모델 후보: Avis 등의 NV processing-node 모델

하드웨어 구체성이 필요할 때 검토할 후보는 **Avis et al. (2023)의 NV/color-center 모델**이다.
통신용 전자스핀과 저장용 핵스핀, gate/readout, memory, 허용 회로를 함께 제시하며
NetSquid로 모델링한 선행연구다. 아래는 해당 논문의 Supplementary Note 1E,
Supplementary Table 1, PDF p.5에서 확인한 일부 값이다.

| 문헌의 물리 항목 | 시간 | 문헌 표의 fidelity/정확도 |
|---|---:|---:|
| Electron single-qubit gate | 5 ns | 0.995 |
| Carbon Z rotation | 20 μs | 0.999 |
| Electron–carbon controlled X rotation | 500 μs | 0.97 |
| Electron readout | 3.7 μs | 0일 때 0.93, 1일 때 0.995 |
| Electron initialization | 2 μs | 0.995 |
| Carbon initialization | 300 μs | 0.99 |
| Electron memory | T1=1 h, T2=0.5 s | — |
| Carbon memory | T1=10 h, T2=1 s | — |

출처: [논문](https://www.nature.com/articles/s41534-023-00765-x),
[보충자료](https://media.springernature.com/original/springer-static/esm/art%3A10.1038%2Fs41534-023-00765-x/MediaObjects/41534_2023_765_MOESM1_ESM.pdf).
보충 PDF SHA-256: `c26d6fbfe36fa51fb1b78642f8b33f91d173f41c7925e6870a503a52814fab42`.

이것은 여러 실험을 인용해 구성한 **한 논문의 일관된 시뮬레이션 모델**이다.
동일 장비에서 동시에 측정한 calibration dataset이나 최신 장비의 대표값은 아니다.
표의 fidelity를 근거 없이 `depolarization_probability = 1 - fidelity`로 변환해서도 안 된다.
사용한 fidelity 정의, noise channel 및 적용 순서를 원 모델과 대조해야 한다.

## 상세 NV 장비 재현을 할 경우 별도로 필요한 구현

1. **물리 qubit 배치:** A의 input/EPR, R의 두 EPR half, B의 output을 전자/핵스핀
   위치에 매핑한다. 핵스핀끼리 임의의 CNOT을 허용하는 현재 추상 회로를 그대로
   NV 회로라고 부를 수 없다. 다중 chain에는 memory 개수, 이동 연산, 재사용 조건도 필요하다.
2. **회로 변환:** 문헌의 controlled rotation은 현재 `INSTR_CNOT`과 동일하지 않다.
   BSM 및 correction을 허용 gate와 readout/mapping 과정으로 구성하고,
   그 NetSquid 실행 일정에서 시간을 산출한다. 따라서 위 표만으로 새 BSM 시간을 확정하지 않는다.
3. **Noise 일치:** qubit별 memory와 gate/readout 오류를 구분한다.
   coherence time의 정의와 active/idle noise 적용을 확인해 중복 계산을 피한다.
4. **자원 제공 범위:** 현재 이상적인 EPR/손실 없는 quantum delivery는
   NV의 photon emission–interference–heralding을 재현한 것이 아니다.
   첫 장비 기반 실행 평가는 이미 제공된 EPR을 조건으로 할 수 있지만,
   이 경우 entanglement-generation rate나 전체 NV network 성능을 주장하지 않는다.

이는 물리 모델에 맞추기 위한 변경이다. federation, ns-3 packet path,
completion callback, 논리 resource ownership은 유지할 수 있다.

## 평가 절차와 범위

1. **모델 표와 회로 고정:** 위 기준 모델의 원 회로/오류 정의를 확인하고,
   채택값·유도값·추가 가정을 구분한다. 임의로 좋은 수치를 다른 장비에서 가져오지 않는다.
2. **작은 검증:** gate/측정 및 memory decay를 먼저 확인한다. 이어 단일 Swap→Teleport에서
   6개 입력 상태, branch, 시각, 최종 density matrix를 독립 reference와 비교한다.
   읽기 오류를 추가하면 실제 측정 outcome과 packet으로 전달한 bit도 구분한다.
3. **Workload 설계:** 확인된 processor 처리시간과 자원 준비/용량을 기준으로 요청 간격을 정한다.
   `처리 가능한 간격`과 `요청이 더 빨리 도착하는 간격`을 비교하고,
   표에는 실제 단위와 선택 근거를 함께 쓴다. 한 BSM 시간만으로 A/R/B 전체 병목을 단정하지 않는다.
4. **Classical 부하 설계:** 배경 부하율은 `배경 wire bits / (주기 × link rate)`로 정의한다.
   control traffic을 포함한 실제 이용률과 queueing을 별도로 확인한다.
   gate 문헌은 classical link rate, packet 크기, 부하율 0.7의 근거가 되지 않는다.
5. **재평가:** 하나의 설정표를 Full Sync와 모든 baseline에 적용해 새 결과를 생성한다.
   해당 장비 모델에서 차이가 작아져도 그대로 보고한다. 큰 차이가 나오도록 memory를
   짧게 바꾼 조건은 별도 sensitivity/stress 조건으로만 표시한다.

이번에 완료한 범위는 A의 nominal profile이다. 위 상세 NV gate mapping과
하드웨어별 readout/generation 모델까지 구현한 것은 아니다.
현재 [evaluation/](evaluation-long-memory/README.md)의 그래프는 새 profile로 실행한 결과이며,
이전 controlled 결과를 새 caption 아래 재사용하지 않았다.
