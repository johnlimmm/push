# QuCl 현재 구현과 보존 자료

현재 구현은 **실제 Q2NS SwapApp과 TeleportationApp이 공통 ns-3↔NetSquid 실행 기반을 사용하고,
swapping으로 만든 얽힘을 teleportation이 소비하는 hybrid simulator**다.
고정 topology에서 실행·시간·자원 연결을 구현하고 검증한 단계이며, 임의 양자 네트워크의 모든 기능을 지원하는 단계는 아니다.

## 구현에서 연결된 것

1. **실제 quantum component와 자원 준비:** NetSquid node/channel을 통해 전달된 EPR half가 memory에 들어와야 연산할 수 있다.
2. **Native timed operation:** CNOT, H, 측정과 correction을 native instruction chain으로 실행한다. 내부 event와 program 완료가 federation 경계에 반영된다.
3. **실제 classical protocol:** Q2NS 앱이 ns-3 UDP packet을 생성·수신한다. 연산 완료 이전에 결과 packet을 만들거나 결과 수신 이전에 correction을 실행하지 않는다.
4. **Protocol 간 자원 연결:** R의 Swap 출력 A–B qubit을 A의 Teleport에 그대로 넘긴다. B의 correction processor는 두 protocol이 공유한다.
5. **시간에 따른 상태 변화:** idle·active storage에 native T1/T2를 적용한다. Q2NS에는 중복 quantum state를 만들지 않는다.
6. **검증·평가:** 실제 FIFO, 자원 단일 소비와 독립 reference의 density matrix를 검사한다. 단순화 모델의 예측 오차는 별도로 측정한다.

현재 경로에는 별도 Controller와 synthetic C→R command가 없다. 초기 EPR delivery를 R에 알리는 통지는
지연 0 가정이고, swapping 이후 A로 보내는 준비 완료 통지는 실제 B→R→A UDP다.
이 차이는 [실행 계약](SPEC-CHAINED.md)에 명시되어 있다.

## 어디서 시작할 것인가

| 목적 | 위치 |
|---|---|
| 설치 및 첫 실행 | [저장소 README](../../README.md), [chain 실행](README-CHAINED.md) |
| C++/Python 연결 | [cosim-chained.cc](examples/cosim-chained.cc), [participant](python/chained_participant.py), [runner](python/run_chained.py) |
| 시간·processor·resource 실행 | [native core](python/native_core.py), [chained core](python/chained_core.py), [quantum backend](python/quantum_network_backend.py) |
| 최신 물리 파라미터와 출처 | [물리 모델](paper/PHYSICAL-MODEL.md), [실험 설정](scenarios/memory-evaluation.json) |
| 최신 논문·그림·수치 | [평가절](paper/evaluation/evaluation.tex), [결과](paper/evaluation/RESULTS.md), [Fig. 3–5](paper/evaluation/FIGURES.pdf) |
| 변경 전 결과 | [이전 평가](paper/evaluation-controlled/RESULTS.md), [long-memory 평가](paper/evaluation-long-memory/RESULTS.md), [기준점 목록](baselines/) |

기본 chain 예제의 파라미터와 최신 논문 파라미터는 다르다. 최신 평가는
[문헌 gate/noise 구현](experiments/literature_physics.py)을 사용하는
[memory 평가 runner](experiments/run_memory_evaluation.py)로 실행한다.
기존 core를 재사용하며 고정된 과거 실행 코드를 바꾸지 않는다.

## 이번 정리에서 보존하는 것

- 문헌 gate/noise 설정, 여섯 입력 전체 평가, 독립 reference, native fidelity API 검증 코드.
- 원고의 inline 표, Fig. 3–5 PDF/PNG, CSV와 해시. 원고는 저자 편집본으로 보존한다.
- 현재 20/10-ms memory와 이전 long-memory 실험의 원자료·설정·보고서.
- 새로운 전체 회귀 로그와 Q2NS native 검사, 과거 기준점·patch 해시 대조 결과.

현재 그림의 source는 147개 workload 조건에서 실행한 1,323회 평가와 별도 calibration 13회다.
이번 게시 준비에서는 그 실험을 다시 돌렸다고 표현하지 않는다. 기존 raw report·source·그림의 해시를 확인하고
현재 checkout의 전체 회귀를 새로 실행했다. Fidelity API 변경은 저장된 출력 상태에 대한 metric 재계산이며,
그 변경 내역도 [provenance](paper/evaluation/provenance.json)에 보존했다.

**2026-10-05 게시 검증:** 구현 Python 196개, 평가 Python 44개, Q2NS native 83개로
총 **323개를 한 차례의 전체 회귀에서 새로 통과**했다.
[새 검증 요약](releases/current-validation.json)과 [원자료 대조 결과](releases/current-evaluation-audit.json)를 보존한다.
최신 평가의 원보고서 1,402개 해시, 원고·그림 ZIP, v3/v4 frozen source와 Q2NS patch/source 해시가 일치한다.
LaTeX 원고는 조각 문서로 제공하며 이번 환경에서 전체 논문을 컴파일한 결과는 아니다.

### 원자료 복원

[압축본 manifest](baselines/literature-memory-evidence.json)에 각 archive와 모든 파일의 SHA-256을 기록했다.
현재 memory 평가, 이전 long-memory 평가, 두 평가가 참조하는 회귀 로그와 새 323개 검증 로그를 포함한다.
각 archive를 열어 저장 전후 byte 일치를 확인했다. 새 checkout에서 ns-3 루트 기준:

```bash
sha256sum -c contrib/cosim/baselines/literature-memory-evidence.sha256
for archive in contrib/cosim/baselines/literature-memory-evidence-*.tar.gz; do
  tar --skip-old-files -xzf "$archive"
done
```

새 자료 묶음을 만드는 도구는 [archive_current.py](tools/archive_current.py)다.
기존 압축본을 덮어쓰지 않으며, 새 run을 보존할 때에는 입력 경로와 archive 이름을 별도로 정한다.

## 회귀 재실행

ns-3 루트에서 실행한다. 먼저 Q2NS patch와 NetSquid 환경을 준비해야 한다.
모든 과거 참가자와 test-runner가 필요하므로 새 checkout에서는 전체 빌드를 한다.

```bash
./ns3 configure --enable-examples --enable-tests
./ns3 build -j 1
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_current.py \
  --output-dir contrib/cosim/results/current-regression-new
```

출력 디렉터리는 새 경로여야 한다. Runner는 기존 Python·평가·Q2NS native suite를 실행하고
과거 Git에 게시한 result fixture를 원래 byte로 복원한다. 재실행 중 달라진 사본은 별도 보존한다.
로컬 IPC socket 사용이 허용된 실행 환경이 필요하다.

최신 실험 재실행과 그림 생성 명령은 [평가 패키지 안내](paper/evaluation/README.md)를 따른다.
NetSquid Python과 plotting Python은 별도 환경이다. 현재 그림의 provenance에 기록된 plotting 환경은
Python 3.10.12, Matplotlib 3.8.4, NumPy 1.26.4다. 임시 디렉터리의 Python 경로에 의존하지 않도록
별도 환경을 다음과 같이 준비할 수 있다.

```bash
python3 -m venv .cache/qucl-plot
.cache/qucl-plot/bin/python -m pip install -r contrib/cosim/paper/plot-requirements.txt
.cache/qucl-plot/bin/python contrib/cosim/tools/render_memory_evaluation.py \
  --source contrib/cosim/results/memory-evaluation-v1
```

원자료와 provenance가 참조하는 로그를 먼저 복원해야 한다. 새 실험을 그릴 때에는
`--source`를 그 출력 경로로 지정한다. 원고의 수치·해석은 renderer가 자동으로 바꾸지 않는다.

## 남아 있는 범위

현재 평가의 quantum transit은 무손실·무잡음이고 input/EPR은 t=0에 준비한다.
여러 문헌의 gate·memory 수치를 결합한 추상 모델이며 특정 장치의 보정 모델은 아니다.
확률적 entanglement generation/heralding, loss/retry, configurable topology/routing은 후속 구현 범위다.
이전 P0–P5/v1–v4 문서는 당시 구조와 검증 기록이므로 현재 안내로 읽지 않는다.
