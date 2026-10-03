# QuCl native-timed v3 원고 반영 메모

현재 표·그림은 native timed 실행으로 재평가한 산출물이다. `/home/ns3/QuCl.pdf`는 원본
manuscript이며 전체 LaTeX/BibTeX 소스가 없어 직접 재빌드하지 않았다.

## Architecture / implementation 수정

- A/R/B, local session start at R, 실제 R→B UDP 경로를 유지한다.
- BSM은 실제 NetSquid QuantumProgram의 CNOT → H → M0 → M1이다.
- Correction은 X/I → Z/I이며 identity에도 동일한 슬롯 duration을 부여한다.
- Native program-done callback이 R/B resource를 해제하고 Q2NS completion을 전달한다.
  BSM 완료 callback 이후 같은 시각에 실제 result packet이 생성된다.
- Native event calendar에 ns-3 next-event 경계를 등록한다. 내부 gate event는 NetSquid가 처리한다.
  ns-3에서 도착한 입력보다 quantum execution이 앞서 진행하지 않도록 경계를 유지한다.
- Atomic loop의 전역 COMMIT→INPUT 순서를 native 내부 event에 그대로 주장하지 않는다.
  동시 완료·도착은 FIFO와 callback 기반 release로 처리한다. 세부 계약은 SPEC-NATIVE.md를 인용한다.
- Native idle memory T1/T2는 active instruction 시간을 제외하므로 physical instruction에
  같은 T1/T2 모델을 따로 연결해 busy 구간 storage aging을 한 번 적용한다.
  Ideal gate는 instruction 완료 때 작용한다. Calibrated gate error/continuous pulse model은 아니다.
- 총 duration이 같은 atomic 모델과도 noise/gate ordering이 달라 state는 달라질 수 있다.
  현재 correctness 기준은 별도로 구현한 native timed NetSquid reference다.

## 평가·표·그림 수정

- Fig. 4–6, VI-D 수치, 기대 fidelity와 feasibility 판정은 native 확대 실험으로 교체한다.
- 32 traffic seeds × 2 quantum seeds × 3 loads × 2 intervals = 384 paired cases.
  1,152 model executions + calibration 6회; 모델별 1,536 transactions.
- 같은 calibration/test seed 분리, F_min=0.5, local-start deadline=5 ms를 유지했다.
  결과에 맞춰 threshold를 조정하지 않는다.
- Full/No-Dq/Fixed는 같은 gate duration/noise를 사용한다. No-Dq-R은 R 실행만 session별로 분리한다.
  B processor와 실제 packet path는 유지한다. Fixed-Dc만 가상 constant result delay를 사용한다.
- Decoupled는 R wait를 합성한 뒤 result packet을 재전송하지 않는 latency-only 근사다.
- Fig. 7(a)는 실제 native circuit의 완료시각과 독립 analytic FIFO를 비교한다.
  12 mixed workloads, 500 R/B requests다. 과거 atomic synthetic 2,500건을 합산하지 않는다.
- Fig. 7(b)는 12조건 각 10회 반복의 wall-clock/transaction이다. Gate state probe와 logging을
  포함하며 validation subprocess·disk I/O는 제외한다. 오차 막대는 host runtime 반복 변동이다.
- 수정할 위치: setup-and-metrics.tex, abstraction-results-insert.tex, validation-insert.tex.
  최종 값과 CI는 RESULTS.md 및 results-summary.json을 따른다.

## 해석 범위

- Fixed topology, pre-created resources, serial gate chain, capacity-one Full Sync만 평가했다.
- Duration은 illustrative parameter다. Gate-level 시간 배분의 hardware fidelity를 주장하지 않는다.
- P5-B에서는 B wait=0, 비용 측정의 Mixed에서는 B 경합을 허용한다.
- Traffic seed는 periodic background의 시작 phase만 바꾼다. CI는 이 family와 고정 calibration에 조건화한다.
- Model별 같은 seed는 동일 BSM branch 보장이 아니다. E[F]는 각 모델의 독립 reference에서
  네 branch를 Born probability로 가중한다. 실현된 branch fidelity와 구분한다.
- Feasibility 오판은 모든 paired transactions를 분모로 쓰며 conditional false-positive rate가 아니다.
  Deadline-only 오판은 서비스(fidelity+deadline) 오판과 구분한다.
- Atomic 수치는 baselines/atomic-v2-paper.tar.gz 및 direct-start-v2-results.tar.gz에 보존했다.
  Native backend가 속도를 개선했다고 결론내릴 통제된 A/B benchmark를 수행한 것은 아니다.
- 원본 PDF의 인용·참고문헌과 figure 번호/page budget은 전체 manuscript 소스에서 확인해야 한다.
