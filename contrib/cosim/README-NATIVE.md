# NetSquid-native timed Hybrid 실행

BSM 내부의 `CNOT → H → 측정 → 측정`과 correction의 `X/I → Z/I`를 실제
NetSquid `QuantumProgram`으로 실행한다. 각 instruction이 simulation time을
점유하고, native program-done callback이 Q2NS 완료와 실제 R→B packet 생성을
구동한다. Swap과 Teleportation은 동일한 R/B FIFO 및 resource core를 공유한다.

## 실행

기존 `cosim-hybrid` 참가자를 다시 빌드한다. NetSquid가 설치된 Python을 사용한다.

```bash
CCACHE_TEMPDIR=/tmp/cosim-ccache ./ns3 build cosim-hybrid -j 1
/home/ns3/qunet/bin/python contrib/cosim/python/run_native_hybrid.py \
  contrib/cosim/scenarios/native-mixed.json \
  --output /tmp/native-mixed.json

/home/ns3/qunet/bin/python -m unittest discover \
  -s contrib/cosim/tests -p test_native_hybrid.py -v
```

Teleport 단독 설정은 [native-teleport.json](scenarios/native-teleport.json)이다.
`native_instructions`로 각 gate 시간을 설정한다. 기본 합계는 기존과 같은
BSM 1.6 ms, correction 0.5 ms이며 각 숫자는 실측 하드웨어 parameter가 아니다.

전체 Python/Q2NS 회귀와 결과 요약은 다음 명령으로 재생성한다.
회귀 테스트가 쓰는 기존 atomic 결과 파일은 별도 사본을 저장한 뒤 원본을 복원한다.

```bash
/home/ns3/qunet/bin/python contrib/cosim/tools/validate_native_timed.py
/home/ns3/qunet/bin/python contrib/cosim/tools/summarize_native_timed.py
```

## 검증 결과

- 전체 **258개 PASS**: Python 159개(새 native 19개 포함), 평가·timing·계측 16개,
  Q2NS 자체 83개. 독립 reference 대비 최대 density-matrix error는 **4.44×10⁻¹⁶**이다.
- 새 native 테스트 19개: 실제 gate chain, mixed R/B 경합, 같은 시각의 요청,
  완료 callback, result delay, noise 누락·중복, 관측 영향 및 실패 검출.
- Noiseless 입력 `0 / 1 / + / - / +i` 각각 네 BSM branch를 32 seeds로 확인했다.
  총 160 transactions에서 최종 fidelity가 수치 정밀도 내에서 1이다.
- 독립 native reference가 각 gate 이후, frame, packet arrival, correction start,
  usable의 density matrix와 timing을 대조한다.

수치와 원본 trace: [native 검증 결과](paper/NATIVE-VALIDATION.md),
[summary](results/native-timed/summary.json), [전체 회귀](results/native-timed/regression-summary.json).

## 확인할 항목

- `native_instructions`: instruction별 시작·완료시각과 intermediate state.
- `events[].completion_source`: `netsquid_program_done`.
- `ns3_events`: BSM 완료시각에 실제 `RESULT_TX`, packet 수신 뒤 correction 요청.
- `snapshot.requests`: Swap/Teleport의 R/B FIFO 대기와 실제 완료시각.
- `cross_validation`: 독립 timed NetSquid reference와 단계별 state/time 비교.

Memory의 idle T1/T2와 instruction이 실행 중인 시간의 T1/T2를 모두 반영한다.
NetSquid가 busy 구간을 idle noise에서 제외하므로 physical instruction에도 동일
storage noise를 명시했다. 별도의 gate-error 모델은 추가하지 않았다.

## 기준점과 범위

[atomic v2](README-HYBRID.md)의 Python runner·모델은 유지한다.
Atomic 논문 산출물은 [별도 archive](baselines/atomic-v2-paper.tar.gz)에 보존했다.
현재 [논문 결과](paper/RESULTS.md)는 native 재평가를 따른다.
기능 검증은 `results/native-timed/`, 평가 방법은 [README-PAPER-VALIDATION](README-PAPER-VALIDATION.md)을 참조한다.

두 실행 경로의 합계 duration이 같으면 FIFO/packet 시각은 같을 수 있지만,
gate 사이의 noise 적용 순서가 달라져 quantum state는 달라질 수 있다.
Native correctness 기준은 같은 instruction 구성을 사용하는 **독립 native reference**다.

고정 A/R/B, pre-created EPR/input, shared capacity-one R/B, UDP만 지원한다.
동적 EPR, quantum channel, gate 병렬화나 calibrated hardware 모델까지 추가한 것은 아니다.
계약과 동기화 방식: [SPEC-NATIVE.md](SPEC-NATIVE.md).

평가용 No-Dq-R만 R 실행 엔진을 session별로 분리한다. Gate chain과 noise는 Full Sync와 같고
B FIFO는 유지한다. 세부 계약은 [SPEC-P5B](SPEC-P5B.md)를 따른다.
