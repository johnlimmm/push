# QuCl 원고 보강 (2026-09-22)

검토 대상: `/home/ns3/QuCl.pdf` (8쪽). LaTeX/BibTeX 원본 경로는 아직 제공되지 않았다.
원본 PDF는 변경하지 않는다. 이 디렉터리에 교체용 그림, 수치 표와 VI-E 삽입문을 생성한다.
현재 구조는 A/R/B의 direct-session-start-v2다. 이전 Hybrid v1 archive는 보존하고,
Controller 경로를 제거한 현재 코드로 모든 표·그림·검증을 다시 생성한다.

## 원고에서 교정할 항목

1. 본문 인용이 `[?]`이며 References 목록이 비어 있다. 원본 `.tex/.bib`에서 citation key와
   bibliography build를 복구해야 한다. 이 보강 작업이 참고문헌을 복구한 것으로 간주하면 안 된다.
2. VI-A에 아래 parameter table을 추가한다. Pilot의 네 session과 50 us correction은
   Hybrid protocol validation의 500 us와 구분한다.
3. Fig. 4/6과 본문의 `latency deviation`을 **latency mean absolute error (MAE)**로 명확히 쓴다.
   각 transaction i에서 L_i = correction completion - local session start at R,
   MAE = mean_i |L_model,i - L_Full,i|이다. Signed bias는 별도 지표다.
4. 기대 fidelity는 동일 operation timestamps의 독립 reference에서 네 BSM branch를 열거하고
   E[F] = sum_b p_b F_b로 계산한다. E[F]_model - E[F]_Full을 평균한 것이 Fig. 5의 bias다.
   일반적으로 서로 다른 모델의 같은 seed가 같은 BSM branch를 보장하지 않는다.
5. Fig. 4–6에 traffic-cluster bootstrap 95% interval을 표시한다. 표본은 traffic phase seed이다.
   동일 phase 내 session과 quantum seed를 독립 traffic 표본으로 세지 않는다.
6. 6.25%와 CI를 disclosure했다는 이전 외부 평과 달리, 검토한 PDF에는 해당 footnote가 없다.
   확대 실험의 feasibility 결과는 결과의 유의성 여부와 관계없이 함께 기록한다.

## 고정한 실험 계획

### Native timing

- 1/4/8/16/32/64 requests, idle/saturated/simultaneous/burst/boundary 다섯 도착 패턴.
- Atomic BSM 1.6 ms, correction 0.5 ms와 0.05 ms, 두 correction duration의 교대 workload.
- 총 120조건/2,500 requests. Correction의 I/X/Z/ZX를 포함하며 I도 정해진 시간을 점유한다.
- Production `HybridExecutionCore`와 독립 `QuantumProcessor` dispatcher를 비교한다.
- Native 쪽은 `PhysicalInstruction`의 실제 program-done callback에서 다음 요청을 실행한다.
  QuCl의 완료시각 계산이나 scheduler 코드를 재사용하지 않는다.
- 같은 timestamp의 요청은 한 arrival batch로 넣고 입력 순서를 보존한다. PyDynAA가 개별
  동시 이벤트의 삽입 순서를 보장한다고 가정하지 않는다. Processor capacity=1, nonpreemptive FIFO.
- Memory/gate noise를 끈 timing fixture이며 state equivalence는 이 실험의 주장이 아니다.
- 추가로 scaling warmup의 실제 mixed-protocol trace 12개에서 R/B 요청 도착을 native timed
  processor에 재생한다. 시작/완료시각은 native에 전달하지 않고 비교에만 사용한다.
- Native duration +1 ns 및 completion 순서 오류를 주입했을 때 검증이 실패해야 한다.

### Simulation cost

- 1/4/8/16/32/64 sessions × background offered load 0/0.7 on R→B only.
- Swap/Teleport 교대. n=1은 Swap 하나이며 나머지는 1:1 비율이다.
- 각 cell 한 번의 warmup 후 10회 반복; 총 12 warmups와 120 measured runs.
- 요청 간격 0.8 ms, BSM 1.6 ms, correction 0.5 ms, T1=20 ms/T2=10 ms.
- Background payload=1,000 B. Wire serialization을 포함해 offered load를 정의한다.
  Seed=401로 시작 phase를 고정하고, N에 따라 traffic window를 늘려 batch 전체를 덮는다.
  종료 시 남은 background traffic까지 drain한다. Transaction 완료와 drain 완료시각을 모두 기록한다.
- 반복 순서는 고정 seed=7301로 섞는다. P5-B 확대 실행이 끝난 후 측정하며 다른 실험을 병행하지 않는다.
- 시간은 imported Python runtime에서 core/state 초기화, ns-3 startup/configuration,
  federation(기존 in-memory trace/snapshot 포함), status/teardown을 구분한다.
- Python import/build/config normalization, 사후 reference 검증 및 JSON file I/O는 main runtime에서 제외한다.
  사후 검증 시간은 별도 기록하며 모든 실행은 검증을 통과해야 한다.
- IPC는 양방향 실제 framed line/byte를 센다. recv syscall 횟수나 network packet 수와 혼동하지 않는다.
- 같은 timestamp의 여러 federation round가 있으므로 round 수와 unique timestamp 수를 따로 센다.
- 95% interval은 고정 workload의 runtime 반복 변동이다. Traffic 조건의 불확실성이나
  독립적으로 분리한 IPC overhead, multi-node topology scaling을 의미하지 않는다.

### P5-B 확대

- 기존 calibration seeds 100/101, quantum seeds 7/11, loads 0/0.35/0.7, intervals 0.8/2 ms 유지.
- 새 test traffic seeds 1000–1031 (32개), 4 sessions/case. Pilot seed 200–203과도 겹치지 않는다.
- 384 paired cases, 모델별 1,536 transactions, 1,152 simulation runs + 6 calibration runs.
- Bootstrap 10,000회. Calibration을 고정한 조건부 traffic-cluster confidence interval이다.
  Calibration 표본 두 개의 불확실성까지 포함하는 interval은 아니다.
- F_min=0.5, deadline=5 ms (local session start 기준) 유지. 결과를 보고 threshold를 변경하지 않는다.
- Periodic background의 시작 phase만 randomize한다. 확대 결과도 이 유한 workload family에 한정된다.
- 부하 0에서는 traffic phase가 영향을 주지 않는다. 이 조건의 축소된 CI를 추가 workload 다양성으로 해석하지 않는다.
- 현재 표본에서 오판 0건/degenerate bootstrap CI가 나와도 모집단 오판 확률이 0이라는 증명은 아니다.

## VI-A parameter table에 넣을 값

| Parameter | P5-B pilot/expanded | Hybrid cost experiment |
|---|---:|---:|
| Topology | fixed A/R/B, IPv4/UDP | same |
| Result link rate / propagation | 10 Mb/s / 0.2 ms | same |
| Result application payload | Swap 80 B | Swap 80 B / Teleport 2 B |
| Per-packet modeled headers | 30 B | 30 B |
| Background application payload | 1,000 B | 1,000 B |
| BSM duration | 1.6 ms | 1.6 ms |
| Correction duration | 0.05 ms | 0.5 ms |
| T1 / T2 | 20 ms / 10 ms | 20 ms / 10 ms |
| EPR/input creation | t=0 | t=0 |
| Shared processor capacity | R=1, B=1 in Full Sync | R=1, B=1 |
| Noise | native NetSquid T1T2NoiseModel, DM formalism | same |
| Normal-run packet drops | 0 required | 0 required |
| B wait | 0 required across P5-B variants | allowed and checked |

Fig. 3의 기존 `hybrid-mixed.json`은 T1=T2=10 ms를 사용한다. 위 P5-B 설정과 섞어 쓰지 않는다.
Operation duration은 설정값이며 이 실험으로 장비의 실제 duration을 검증하는 것은 아니다.

## 원고 반영 순서

1. VI-A parameter table 및 지표 정의를 보강한다.
2. VI-D의 pilot 수치/그림은 `expanded` 결과 및 CI로 교체하고 표본 수를 갱신한다.
3. `validation-insert.tex`의 VI-E와 Fig. 7을 추가한다.
4. V-B/V-D의 scope 제한은 유지한다. Native timing 비교가 runtime 자체의 native timed
   QuantumProcessor 지원이나 gate-level state equivalence를 의미하지 않는다.
5. Bibliography는 원본에서 복구하고 전체 PDF를 다시 빌드한다. Figure/table 번호와 page budget은
   해당 원고 소스에서 확인해야 한다.

## 구조 변경에 따른 원고 수정

- Controller 노드, C–R 링크, command packet/trace를 모든 architecture 그림에서 제거한다.
- Swap A–R–B 자원과 Teleport source=R, shared R/B FIFO를 유지한다.
- Session 시작 이벤트는 R의 Q2NS app에 대한 local 호출이다. Network TX/RX로 표현하지 않는다.
- Fixed-Dc calibration은 R→B 평균 지연 하나, Decoupled는 local-start R wait + No-Dq-R result delay다.
- 이전 논문의 C→R 포함 수치와 새 표를 혼합하지 않는다. 원본 PDF는 과거 구조를 설명하므로
  새 결과 삽입 외에도 본문/수식/그림 전체의 architecture 설명을 위 규약으로 바꿔야 한다.
