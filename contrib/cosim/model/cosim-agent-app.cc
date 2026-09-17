#include "cosim-agent-app.h"

#include "ns3/simulator.h"
#include "ns3/inet-socket-address.h"

#include <stdexcept>
#include <utility>

namespace ns3::cosim
{

// ns-3 객체 시스템에 등록해 Node에 설치할 수 있는 Application으로 사용한다.
NS_OBJECT_ENSURE_REGISTERED(CosimAgentApp);

TypeId
CosimAgentApp::GetTypeId()
{
    static TypeId tid = TypeId("ns3::cosim::CosimAgentApp")
                            .SetParent<Application>()
                            .SetGroupName("Cosim")
                            .AddConstructor<CosimAgentApp>();
    return tid;
}

void
CosimAgentApp::SetRequestCallback(RequestCallback callback)
{
    m_requestCallback = std::move(callback);
}

void
CosimAgentApp::SetResultCallback(ResultCallback callback)
{
    m_resultCallback = std::move(callback);
}

void
CosimAgentApp::ReceiveRequest(const Request& request)
{
    // 이 함수는 ns-3 이벤트로 호출된다. 콜백은 브리지의 현재 경계 입력 목록에 적재한다.
    if (!m_requestCallback)
    {
        throw std::logic_error("CosimAgentApp request callback is not installed");
    }
    m_requestCallback(Simulator::Now().GetNanoSeconds(), request);
}

void
CosimAgentApp::ReceiveResult(const Result& result)
{
    // 소켓으로 받은 순간이 아니라, ns-3의 결과 수신 이벤트가 실행된 순간을 기록한다.
    if (!m_resultCallback)
    {
        throw std::logic_error("CosimAgentApp result callback is not installed");
    }
    m_resultCallback(Simulator::Now().GetNanoSeconds(), result);
}

void
CosimAgentApp::BindUdp(uint16_t port, PacketCallback callback)
{
    if (m_socket)
    {
        throw std::logic_error("UDP socket already bound");
    }
    // InternetStack 설치는 시나리오가 담당한다. P0는 UDP factory를 필요로 하지 않는다.
    m_socket = Socket::CreateSocket(GetNode(), TypeId::LookupByName("ns3::UdpSocketFactory"));
    if (m_socket->Bind(InetSocketAddress(Ipv4Address::GetAny(), port)) != 0)
    {
        throw std::runtime_error("UDP bind failed");
    }
    m_packetCallback = std::move(callback);
    m_socket->SetRecvCallback(MakeCallback(&CosimAgentApp::HandleRead, this));
}

void
CosimAgentApp::SendUdp(Ptr<Packet> packet, const Address& destination)
{
    const auto bytes = packet->GetSize();
    if (!m_socket || m_socket->SendTo(packet, 0, destination) !=
                         static_cast<int>(bytes))
    {
        throw std::runtime_error("UDP send failed");
    }
}

void
CosimAgentApp::HandleRead(Ptr<Socket> socket)
{
    Address sender;
    while (auto packet = socket->RecvFrom(sender))
    {
        if (!m_packetCallback)
        {
            throw std::logic_error("UDP receive callback is not installed");
        }
        m_packetCallback(packet, sender);
    }
}

void
CosimAgentApp::DoDispose()
{
    if (m_socket)
    {
        m_socket->SetRecvCallback(MakeNullCallback<void, Ptr<Socket>>());
        m_socket->Close();
        m_socket = nullptr;
    }
    m_packetCallback = {};
    m_requestCallback = {};
    m_resultCallback = {};
    Application::DoDispose();
}

} // namespace ns3::cosim
