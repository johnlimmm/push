# Python runner가 자식 프로세스로 실행할 cosim-p0 예제를 빌드한다.
build_lib_example(
  NAME cosim-p0
  SOURCE_FILES cosim-p0.cc
  LIBRARIES_TO_LINK ${libcosim} ${libcore} ${libnetwork}
)

# 실제 IPv4/UDP와 두 PointToPoint 링크를 사용하는 P1 참가자.
build_lib_example(
  NAME cosim-p1
  SOURCE_FILES cosim-p1.cc
  LIBRARIES_TO_LINK ${libcosim} ${libinternet} ${libpoint-to-point} ${libtraffic-control}
)
