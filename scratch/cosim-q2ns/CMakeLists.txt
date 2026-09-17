# P5 보존 파일을 수정하지 않는 Q2NS 연결 빌드 진입점.
build_exec(
  EXECNAME cosim-q2ns
  SOURCE_FILES ${PROJECT_SOURCE_DIR}/contrib/cosim/examples/cosim-q2ns.cc
  LIBRARIES_TO_LINK ${libcosim} ${libq2ns} ${libinternet} ${libpoint-to-point} ${libtraffic-control}
  EXECUTABLE_DIRECTORY_PATH ${CMAKE_OUTPUT_DIRECTORY}/contrib/cosim/examples/
)
add_custom_target(cosim-q2ns DEPENDS scratch_cosim-q2ns_cosim-q2ns)
