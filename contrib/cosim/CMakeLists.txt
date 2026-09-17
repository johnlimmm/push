# ns-3의 모듈 빌드 규칙으로 앱 라이브러리와 공개 헤더를 등록한다.
# examples/CMakeLists.txt는 ns-3 빌드 시스템이 예제 활성화 시 자동으로 읽는다.
build_lib(
  LIBNAME cosim
  SOURCE_FILES model/cosim-agent-app.cc
  HEADER_FILES model/cosim-agent-app.h
  LIBRARIES_TO_LINK ${libcore} ${libnetwork}
)
