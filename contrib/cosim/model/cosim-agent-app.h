#ifndef COSIM_AGENT_APP_H
#define COSIM_AGENT_APP_H

#include "ns3/application.h"
#include "ns3/socket.h"

#include <cstdint>
#include <functional>
#include <string>

namespace ns3::cosim
{

// 브리지의 모든 시각·지속시간은 정수 ns다. 요청 도착 시각은 ns-3 이벤트가 결정한다.
struct Request
{
    std::string kind;      // SUBMIT: BSM 요청, CANCEL: 대기 요청 취소
    uint64_t id{};         // 재전송을 구별하는 요청 ID. 재사용 규칙은 양자 스케줄러가 검사한다.
    uint32_t processor{};  // BSM을 실행할 프로세서 ID
    uint64_t pairA{};      // 두 입력 EPR의 자원 ID이며, 큐빗의 메모리 위치 번호가 아니다.
    uint64_t pairB{};
    int64_t durationNs{};  // 프로세서 점유 시간. 게이트별 native 실행시간은 P0 범위 밖이다.
};

// ns-3가 받을 수 있는 상태·결과만 담는다. 양자 상태와 진단용 fidelity는 전송하지 않는다.
struct Result
{
    uint64_t id{};
    uint32_t processor{};
    std::string state;  // QUEUED, RUNNING, COMPLETED, REJECTED, CANCELLED 등
    std::string code;   // OK, DUPLICATE, RESOURCE_CONFLICT 등 응답 사유
    int m1{-1};        // BSM 측정 비트. 완료 전의 -1은 아직 결과가 없다는 뜻이다.
    int m2{-1};
};

// P0는 ns-3에 예약한 도착 이벤트로 이 앱을 구동한다.
// 역할은 현재 ns-3 시각과 함께 요청/결과를 전달하는 것이며, 양자 예약 정책은 두지 않는다.
// 이후 실제 패킷 수신 경로도 같은 ReceiveRequest() 인터페이스를 호출할 수 있다.
class CosimAgentApp : public Application
{
  public:
    static TypeId GetTypeId();
    // 콜백의 첫 인자는 ns-3 이벤트가 실제 처리된 시각(ns)이다.
    using RequestCallback = std::function<void(int64_t, const Request&)>;
    using ResultCallback = std::function<void(int64_t, const Result&)>;

    void SetRequestCallback(RequestCallback callback);
    void SetResultCallback(ResultCallback callback);
    void ReceiveRequest(const Request& request);
    void ReceiveResult(const Result& result);

    // P1의 실제 UDP 경로. 콜백은 앱에서 패킷을 수신한 ns-3 이벤트 안에서 호출된다.
    using PacketCallback = std::function<void(Ptr<Packet>, const Address&)>;
    void BindUdp(uint16_t port, PacketCallback callback);
    void SendUdp(Ptr<Packet> packet, const Address& destination);

  private:
    void HandleRead(Ptr<Socket> socket);
    void DoDispose() override;
    Ptr<Socket> m_socket;
    PacketCallback m_packetCallback;
    RequestCallback m_requestCallback;
    ResultCallback m_resultCallback;
};

} // namespace ns3::cosim

#endif
