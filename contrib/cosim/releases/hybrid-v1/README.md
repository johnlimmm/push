# Hybrid v1 검증 기록

GitHub에서 조회할 수 있도록 완료 시점의 주요 요약을 보존한다.
이 사본은 새 실험 결과로 갱신하지 않는다.

- [기능·시나리오·reference 검증](validation-summary.json)
- [219개 release 재검증](release-checks.json)
- [Q2NS 두 patch의 원본 재현](patch-reproduction.json)
- [P5-B 평가 검증](p5b-validation-summary.json)
- [P5-B 유한 workload pilot](p5b-pilot-summary.json)

JSON 안의 상대 report/log 경로는 원래 `contrib/cosim/results/`를 기준으로 한다.
상세 trace·로그·상태와 pilot 원본은 [Hybrid v1 archive](../../baselines/hybrid-v1-freeze.tar.gz)에 있다.
원본을 빈 디렉터리에 풀거나 hash를 검증하는 방법은
[release 문서](../../RELEASE-HYBRID-V1.md)를 따른다.

현재 지원 범위는 fixed topology, pre-created input/EPR, IPv4/UDP, atomic operations다.
P5-B는 pilot이며 대규모 통계 실험을 완료했다는 뜻이 아니다. E1은 다음 단계의 계획이다.
