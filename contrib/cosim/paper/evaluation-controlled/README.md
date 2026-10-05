# 논문용 그림 — 두 장만

**[FIGURES.pdf](FIGURES.pdf)**: 2페이지. 결과 요약은 [RESULTS.md](RESULTS.md).

| 그림 | 비교 방식 |
|---|---|
| 조건별 latency | 하나의 0 기준축에서 시작 간격 × 부하 네 조건을 나란히 비교 |
| 단순화 모델 오차 | 왼쪽 latency MAE, 오른쪽 fidelity bias. 같은 load의 모델을 나란히 비교 |

- 평균값을 막대에 직접 표기했습니다.
- 첫 그림의 whisker는 관측 min–max, 둘째는 95% traffic-cluster bootstrap CI입니다.
- Fidelity는 모델을 별도 축으로 나누지 않습니다. 단위는 **percentage points = 100 × ΔE[F]**이며, 상대 변화율이 아닙니다.
- 민감도는 원고 한 문단으로 요약했습니다. 세부 결과는 CSV로 보존합니다.
- 벡터 PDF와 450 dpi PNG를 함께 제공합니다.

## 논문에 사용

이 디렉터리를 논문 루트의 `evaluation/`에 복사합니다.

```latex
\usepackage{graphicx,amsmath,amssymb,booktabs}
\newcommand{\quclevalpath}{evaluation}
% body
\input{evaluation/evaluation.tex}
% At the end of the main paper, once (merge with an existing bibliography):
\bibliographystyle{IEEEtran}
\bibliography{evaluation/references}
```

[원고](evaluation.tex)는 검증 표 하나, 파라미터 출처 표 하나와 그림 두 장으로 구성했습니다.
수치는 `numbers.tex`에서 생성됩니다.
환경에 LaTeX compiler가 없어 전체 원고 컴파일은 수행하지 않았습니다. Figure PDF는 생성·시각 확인했습니다.

## 문헌 기반 파라미터와 인용

[physical-model.tex](physical-model.tex)를 setup에 포함했습니다. 출처 표는 **현재 실험값**과
**후속 평가용 문헌 profile**을 구분합니다. 문헌 profile로 재실험한 결과는 아직 없습니다.
현재 그림이나 `numbers.tex`의 수치를 문헌 profile의 결과로 바꿔 읽으면 안 됩니다.

| BibTeX key | 논문 | 인용 위치와 용도 |
|---|---|---|
| `liao2022benchmarking` | Liao et al., *Benchmarking of quantum protocols*, Scientific Reports 12, 5298 (2022), [DOI](https://doi.org/10.1038/s41598-022-08901-x) | Table 3: single-qubit 5 ns, CNOT 20 μs, 측정 3.7 μs |
| `iqbal2023cloning` | Iqbal et al., *Investigating Imperfect Cloning for Extending Quantum Communication Capabilities*, Sensors 23(18), 7891 (2023), [DOI](https://doi.org/10.3390/s23187891) | Table 3: H/X/Z 명시; Section 4: T1=10 h, T2=1 s, gate depolarization 0.01 |
| `campbell2025qdc` | Campbell et al., *Quantum data centres: a simulation-based comparative noise analysis*, Quantum Science and Technology 10, 015052 (2025), [DOI](https://doi.org/10.1088/2058-9565/ad9cb8) | Table 1: 별도 trapped-ion 모델; 135/600 μs gate와 추정 측정 6 ms |

[references.bib](references.bib)에 저자·제목·연도·학술지·DOI를 저장했습니다.
기존 bibliography가 있으면 `\bibliography{references,evaluation/references}`처럼 합치고,
같은 DOI의 기존 entry가 있으면 citation key를 통일합니다. 문헌 번호는 BibTeX가 배정하므로
본문에 `[1]` 같은 고정 번호를 직접 쓰지 않습니다.
Campbell 논문은 2024년 12월 온라인 출판, 2025년 journal volume 기준으로 인용합니다.

후속 문헌 profile의 직렬 BSM 시간은 **27.405 μs**로 계산됩니다. 이는 회로 합계이며
실측 BSM 시간이 아닙니다. 현재 1.6 ms와 함께 명확히 구분합니다.
상세 조사 기록은 [PHYSICAL-MODEL.md](../PHYSICAL-MODEL.md)에 있습니다.

## 데이터와 재생성

- [data/](data/): 전 조건의 수치, 기존 민감도 결과 포함.
- [provenance.json](provenance.json): 원본/출력 해시 및 검산 범위.
- 첫 그림은 v5 Swap→Teleport 연쇄 실행, 둘째는 별도 v4 swapping 비교입니다. 같은 workload의 결과로 합쳐 해석하지 않습니다.

ns-3 루트에서:

```bash
/tmp/qucl-native-plot-env/bin/python contrib/cosim/tools/render_evaluation_package.py
```

원본 실험은 수정하지 않습니다. 변경은 그래프와 문서 구성에 한정됩니다.
