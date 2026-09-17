// P0/P1이 공유하는 단일 스레드 ns-3 시간 경계와 IPC 어댑터.
#ifndef COSIM_BRIDGE_H
#define COSIM_BRIDGE_H
#include "ns3/default-simulator-impl.h"
#include "ns3/map-scheduler.h"
#include "ns3/simulator.h"
#include <sys/socket.h>
#include <unistd.h>
#include <cerrno>
#include <cstring>
#include <sstream>
#include <stdexcept>
#include <string>
namespace ns3::cosim::bridge
{
// 양쪽 엔진이 정수 ns를 정확히 공유하도록 NetSquid double의 정수 정밀도에 맞춘다.
constexpr int64_t MAX_TIME = 9007199254740991LL;
// 같은 시각에 끝없이 이벤트가 생기거나 과도한 메시지가 들어오면 명시적으로 실패한다.
constexpr size_t MAX_BATCH = 100000;

inline void Require(bool condition, const std::string& message)
{
    if (!condition)
    {
        throw std::runtime_error(message);
    }
}

// PreEventHook에서 Stop()을 호출해도 현재 이벤트는 실행되고, 그 직후 Run()이 반환된다.
// 다음 Run()은 남은 큐를 이어서 처리하므로 공개 hook만으로 한 이벤트씩 진행할 수 있다.
class SteppingSimulator : public DefaultSimulatorImpl
{
  public:
    void PreEventHook(const EventId&) override
    {
        Stop();
    }
};

// 설치한 스케줄러를 보관해 공개 PeekNext()로 다음 이벤트 시각을 확인한다.
// 단일 참가자·단일 스레드 전용이며, ns-3의 private 이벤트 큐에는 접근하지 않는다.
class VisibleScheduler : public MapScheduler
{
  public:
    inline static VisibleScheduler* instance = nullptr;
    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::cosim::VisibleScheduler")
                                .SetParent<MapScheduler>()
                                .AddConstructor<VisibleScheduler>();
        return tid;
    }
    VisibleScheduler()
    {
        instance = this;
    }
};

inline int64_t NextTime()
{
    // -1은 이벤트 없음이다. Python Participant는 이를 None으로 해석한다.
    auto* scheduler = VisibleScheduler::instance;
    return scheduler->IsEmpty() ? -1 : static_cast<int64_t>(scheduler->PeekNext().key.m_ts);
}

// Python 부모에게서 상속받은 Unix 소켓의 줄 단위 IPC.
// 이 소켓의 실제 통신 시간은 시뮬레이션 시간이나 UDP/TCP 링크 지연에 더하지 않는다.
class Wire
{
  public:
    explicit Wire(int fd) : m_fd(fd) {}
    std::string Read()
    {
        // stream 소켓에는 메시지 경계가 없으므로 줄바꿈까지 모은다.
        std::string line;
        char ch;
        while (true)
        {
            auto n = recv(m_fd, &ch, 1, 0);
            if (n < 0 && errno == EINTR)
            {
                continue;
            }
            Require(n == 1, n < 0 ? std::string("bridge read: ") + std::strerror(errno)
                                  : "bridge closed while reading");
            if (ch == '\n')
            {
                return line;
            }
            Require(line.size() < 4096, "bridge line exceeds 4096 bytes");
            line += ch;
        }
    }
    void Send(const std::string& line)
    {
        // send()가 일부 바이트만 보낼 수 있으므로 전체 줄이 전달될 때까지 반복한다.
        std::string data = line + "\n";
        size_t offset = 0;
        while (offset < data.size())
        {
            auto n = send(m_fd, data.data() + offset, data.size() - offset, MSG_NOSIGNAL);
            if (n < 0 && errno == EINTR)
            {
                continue;
            }
            Require(n > 0, std::string("bridge write: ") + std::strerror(errno));
            offset += static_cast<size_t>(n);
        }
    }

  private:
    int m_fd;
};

template <typename... Args>
void Parse(const std::string& line, Args&... args)
{
    // Python과 합의한 필드 개수·순서를 강제해 프로토콜 불일치를 즉시 발견한다.
    std::istringstream stream(line);
    Require(static_cast<bool>((stream >> ... >> args)), "malformed bridge line: " + line);
    std::string extra;
    Require(!(stream >> extra), "unexpected bridge fields: " + line);
}

}
#endif
