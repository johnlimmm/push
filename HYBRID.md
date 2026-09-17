# Q2NS / ns-3 + NetSquid hybrid simulator

현재 개발 기준점은 **Hybrid v1: Swap + Teleportation + Mixed execution**이다.
실제 Q2NS 앱의 classical protocol/UDP packet 실행과 NetSquid quantum state evolution을
공통 federation, R/B FIFO, 자원 예약으로 연결한다.

- [현재 구조·실행 방법](contrib/cosim/README-HYBRID.md)
- [v1 보존·새 checkout 재현·후속 범위](contrib/cosim/RELEASE-HYBRID-V1.md)
- [지원 범위와 시간/자원 계약](contrib/cosim/SPEC-HYBRID.md)
- [P5-B 단순화 모델 평가 pilot](contrib/cosim/README-P5B.md)

검증 기준은 Python 136개 + Q2NS native 83개 = **219개 test cases**다.
v1은 고정 C/A/R/B 배치, IPv4/UDP, t=0에 준비한 input/EPR, atomic BSM/correction을 지원한다.
동적 EPR·임의 topology·모든 Q2NS 예제의 무수정 실행은 후속 범위다.

저장소의 [첫 화면 README](README.md)는 이 hybrid 구현을 소개한다.
기존 ns-3 안내는 [README-NS3.md](README-NS3.md)에 보존한다. `contrib/cosim/README.md`와
이전 milestone README는 각 freeze 시점의 문서이며 현재 상세 진입점은 README-HYBRID다.
