# P0–P3의 보존된 CMake 파일을 수정하지 않는 P4 빌드 진입점.
build_exec(
  EXECNAME cosim-p4
  SOURCE_FILES ${PROJECT_SOURCE_DIR}/contrib/cosim/examples/cosim-p4.cc
  LIBRARIES_TO_LINK ${libcosim} ${libinternet} ${libpoint-to-point} ${libtraffic-control}
  EXECUTABLE_DIRECTORY_PATH ${CMAKE_OUTPUT_DIRECTORY}/contrib/cosim/examples/
)
# ns3 wrapper가 출력 파일명으로 찾는 간단한 target 별칭.
add_custom_target(cosim-p4 DEPENDS scratch_cosim-p4_cosim-p4)
