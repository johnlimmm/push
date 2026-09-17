# Swap/Teleport 공통 실행 참가자. 기존 milestone의 빌드 파일은 유지한다.
build_exec(
  EXECNAME cosim-hybrid
  SOURCE_FILES ${PROJECT_SOURCE_DIR}/contrib/cosim/examples/cosim-hybrid.cc
  LIBRARIES_TO_LINK ${libcosim} ${libq2ns} ${libinternet} ${libpoint-to-point} ${libtraffic-control}
  EXECUTABLE_DIRECTORY_PATH ${CMAKE_OUTPUT_DIRECTORY}/contrib/cosim/examples/
)
add_custom_target(cosim-hybrid DEPENDS scratch_cosim-hybrid_cosim-hybrid)
