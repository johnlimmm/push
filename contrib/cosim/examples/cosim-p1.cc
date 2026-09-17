// P1: Controller → R → B의 실제 UDP 경로. 양자 상태는 Python 참가자만 소유한다.
#include "../model/cosim-bridge.h"
#include "ns3/cosim-agent-app.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-helper.h"

#include <iostream>
#include <map>
#include <vector>

using namespace ns3;
using namespace ns3::cosim;
using namespace ns3::cosim::bridge;

namespace
{
constexpr uint32_t CONTROLLER = 0, A = 1, R = 2, B = 3;
constexpr uint16_t PORT = 9000;

// 고정 길이 60-byte 헤더. fidelity나 양자 상태는 패킷에 싣지 않는다.
// txSequence는 패킷 수신을 송신 이벤트에 연결하는 인과관계 식별자다.
class SwapHeader : public Header
{
  public:
    uint8_t kind{1}; // 1: BSM 명령, 2: BSM 결과
    uint64_t session{1}, request{1}, message{1}, pairA{1}, pairB{2}, output{3};
    int m1{-1}, m2{-1};
    uint64_t txSequence{0};

    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::cosim::SwapHeader")
                                .SetParent<Header>().AddConstructor<SwapHeader>();
        return tid;
    }
    TypeId GetInstanceTypeId() const override { return GetTypeId(); }
    uint32_t GetSerializedSize() const override { return 60; }
    void Serialize(Buffer::Iterator i) const override
    {
        i.WriteU8(1);
        i.WriteU8(kind);
        for (auto v : {session, request, message, pairA, pairB, output})
        {
            i.WriteHtonU64(v);
        }
        i.WriteU8(m1 < 0 ? 255 : m1);
        i.WriteU8(m2 < 0 ? 255 : m2);
        i.WriteHtonU64(txSequence);
    }
    uint32_t Deserialize(Buffer::Iterator i) override
    {
        Require(i.ReadU8() == 1, "invalid packet version");
        kind = i.ReadU8();
        Require(kind == 1 || kind == 2, "invalid packet kind");
        session = i.ReadNtohU64();
        request = i.ReadNtohU64();
        message = i.ReadNtohU64();
        pairA = i.ReadNtohU64();
        pairB = i.ReadNtohU64();
        output = i.ReadNtohU64();
        auto a = i.ReadU8(), b = i.ReadU8();
        m1 = a == 255 ? -1 : a;
        m2 = b == 255 ? -1 : b;
        txSequence = i.ReadNtohU64();
        return GetSerializedSize();
    }
    void Print(std::ostream& os) const override { os << session << '/' << request << '/' << message; }
};

struct Replay
{
    int64_t delay;
    int xor1, xor2;
};

struct TraceBuffer
{
    uint64_t sequence{0};
    std::vector<std::string> rows;
    uint64_t Add(const std::string& type, uint32_t node, const SwapHeader& h,
                 const std::string& cause, uint32_t bytes = 0)
    {
        uint64_t id = sequence++;
        std::ostringstream out;
        out << "TRACE " << id << ' ' << Simulator::Now().GetNanoSeconds() << ' '
            << type << ' ' << node << ' ' << h.message << ' ' << cause << ' '
            << h.session << ' ' << h.request << ' ' << h.pairA << ' ' << h.pairB
            << ' ' << h.output << ' ' << h.m1 << ' ' << h.m2 << ' ' << bytes;
        rows.push_back(out.str());
        return id;
    }
};

std::string EventIdString(uint64_t id) { return "n:" + std::to_string(id); }

SwapHeader ReadMessage(Ptr<Packet> packet)
{
    SwapHeader h;
    Require(packet->GetSize() >= h.GetSerializedSize(), "short UDP payload");
    packet->RemoveHeader(h);
    return h;
}

// PHY trace의 크기는 UDP payload + UDP/IP/PPP 헤더를 모두 포함한다.
void TracePhy(TraceBuffer* trace, std::string type, uint32_t node, Ptr<const Packet> packet)
{
    auto copy = packet->Copy();
    PppHeader ppp;
    Ipv4Header ipv4;
    UdpHeader udp;
    copy->RemoveHeader(ppp);
    copy->RemoveHeader(ipv4);
    Require(ipv4.GetProtocol() == 17, "P1 expects only UDP data packets");
    copy->RemoveHeader(udp);
    auto h = ReadMessage(copy);
    trace->Add(type, node, h, EventIdString(h.txSequence), packet->GetSize());
}

void RunParticipant(Wire& wire)
{
    Time::SetResolution(Time::NS);
    Simulator::SetImplementation(CreateObject<SteppingSimulator>());
    ObjectFactory factory;
    factory.SetTypeId(VisibleScheduler::GetTypeId());
    Simulator::SetScheduler(factory);
    wire.Send("HELLO COSIM_P1 1");
    std::string tag, rootCause;
    uint64_t session, commandRate, resultRate;
    int64_t commandAt, commandDelay, resultDelay;
    uint32_t commandBytes, resultBytes;
    size_t replayCount;
    Parse(wire.Read(), tag, session, commandAt, commandRate, commandDelay,
          resultRate, resultDelay, commandBytes, resultBytes, replayCount, rootCause);
    Require(tag == "CONFIG" && session > 0 && commandAt >= 0 && commandAt <= MAX_TIME &&
            commandRate > 0 && resultRate > 0 && commandDelay >= 0 && resultDelay >= 0 &&
            commandBytes >= 60 && commandBytes <= 1400 && resultBytes >= 60 &&
            resultBytes <= 1400 && replayCount <= 100, "invalid P1 CONFIG");
    std::vector<Replay> replays;
    for (size_t i = 0; i < replayCount; ++i)
    {
        Replay replay;
        Parse(wire.Read(), tag, replay.delay, replay.xor1, replay.xor2);
        Require(tag == "REPLAY" && replay.delay >= 0 && replay.delay <= MAX_TIME &&
                (replay.xor1 == 0 || replay.xor1 == 1) &&
                (replay.xor2 == 0 || replay.xor2 == 1), "invalid REPLAY");
        replays.push_back(replay);
    }

    NodeContainer nodes;
    nodes.Create(4); // 0=Controller, 1=A, 2=R, 3=B
    InternetStackHelper internet;
    internet.SetIpv6StackInstall(false);
    internet.Install(nodes);
    TraceBuffer trace;
    auto link = [&](uint32_t from, uint32_t to, uint64_t rate, int64_t delay,
                    const char* subnet) {
        PointToPointHelper helper;
        helper.SetDeviceAttribute("DataRate", DataRateValue(DataRate(rate)));
        helper.SetChannelAttribute("Delay", TimeValue(NanoSeconds(delay)));
        helper.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", QueueSizeValue(QueueSize("128p")));
        auto devices = helper.Install(NodeContainer(nodes.Get(from), nodes.Get(to)));
        Ipv4AddressHelper address;
        address.SetBase(subnet, "255.255.255.0");
        auto interfaces = address.Assign(devices);
        // 주소 할당이 자동 설치하는 AQM을 제거한다. P1은 최대 101개 결과 패킷을
        // 128-packet FIFO로 수용하며, 혼잡 제어에 의한 임의 drop을 모델에 섞지 않는다.
        TrafficControlHelper traffic;
        traffic.Uninstall(devices);
        for (uint32_t i = 0; i < 2; ++i)
        {
            uint32_t node = i == 0 ? from : to;
            devices.Get(i)->TraceConnectWithoutContext("PhyTxBegin",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_TX"), node));
            devices.Get(i)->TraceConnectWithoutContext("PhyRxEnd",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_RX"), node));
        }
        return interfaces;
    };
    auto cr = link(CONTROLLER, R, commandRate, commandDelay, "10.1.1.0");
    auto rb = link(R, B, resultRate, resultDelay, "10.1.2.0");
    std::map<uint32_t, Ptr<CosimAgentApp>> agents;
    for (auto node : {CONTROLLER, R, B})
    {
        auto app = CreateObject<CosimAgentApp>();
        nodes.Get(node)->AddApplication(app);
        agents[node] = app;
    }
    auto receive = [&](uint32_t node, Ptr<Packet> packet, const Address&) {
        uint32_t bytes = packet->GetSize();
        auto h = ReadMessage(packet);
        Require(h.session == session && ((node == R && h.kind == 1) ||
                (node == B && h.kind == 2)), "unexpected UDP destination/session");
        auto rx = trace.Add(h.kind == 1 ? "COMMAND_RX" : "RESULT_RX", node, h,
                            EventIdString(h.txSequence), bytes);
        // 이 이벤트가 Python의 양자 요청을 만든다. 송신 시각을 도착 시각으로 대신 쓰지 않는다.
        trace.Add(h.kind == 1 ? "BSM_REQUEST" : "CORRECTION_REQUEST", node, h,
                  EventIdString(rx));
    };
    agents[CONTROLLER]->BindUdp(PORT, [](Ptr<Packet>, const Address&) {
        throw std::runtime_error("unexpected packet at Controller");
    });
    agents[R]->BindUdp(PORT, [&](Ptr<Packet> p, const Address& a) { receive(R, p, a); });
    agents[B]->BindUdp(PORT, [&](Ptr<Packet> p, const Address& a) { receive(B, p, a); });
    uint64_t nextMessage = 1;
    auto send = [&](uint32_t from, const Address& destination, SwapHeader h,
                    uint32_t bytes, const std::string& cause) {
        h.message = nextMessage++;
        h.txSequence = trace.Add(h.kind == 1 ? "COMMAND_TX" : "RESULT_TX", from, h, cause, bytes);
        auto packet = Create<Packet>(bytes - h.GetSerializedSize());
        packet->AddHeader(h);
        agents.at(from)->SendUdp(packet, destination);
    };
    SwapHeader command;
    command.session = session;
    Simulator::Schedule(NanoSeconds(commandAt), [&, command] {
        send(CONTROLLER, InetSocketAddress(cr.GetAddress(1), PORT), command, commandBytes, rootCause);
    });
    // 양자 완료 응답을 R 앱에 전달한 뒤 실제 결과 패킷을 송신한다.
    std::map<uint64_t, std::string> completionCauses;
    agents[R]->SetResultCallback([&](int64_t at, const Result& result) {
        Require(result.state == "COMPLETED", "unexpected quantum response");
        SwapHeader h;
        h.session = session;
        h.kind = 2;
        h.request = result.id;
        h.m1 = result.m1;
        h.m2 = result.m2;
        h.message = 0;
        auto local = trace.Add("BSM_RESULT_LOCAL", R, h, completionCauses.at(result.id));
        auto cause = EventIdString(local);
        send(R, InetSocketAddress(rb.GetAddress(1), PORT), h, resultBytes, cause);
        for (const auto& replay : replays)
        {
            Require(replay.delay <= MAX_TIME - at, "replay time overflow");
            // 검증용 재전송도 실제 UDP를 통과한다. 새 message ID, 동일 논리 작업 ID를 쓴다.
            Simulator::Schedule(NanoSeconds(replay.delay), [&, h, replay, cause] {
                auto copy = h;
                copy.m1 ^= replay.xor1;
                copy.m2 ^= replay.xor2;
                send(R, InetSocketAddress(rb.GetAddress(1), PORT), copy, resultBytes, cause);
            });
        }
    });

    wire.Send("READY 0 " + std::to_string(NextTime()));
    while (true)
    {
        auto line = wire.Read();
        if (line == "QUIT")
        {
            wire.Send("BYE");
            break;
        }
        std::istringstream prefix(line);
        prefix >> tag;
        if (tag == "ADVANCE")
        {
            int64_t at;
            Parse(line, tag, at);
            auto now = Simulator::Now().GetNanoSeconds();
            Require(at >= now && at <= MAX_TIME, "time reversal or overflow");
            Require(NextTime() == -1 || NextTime() >= at, "ADVANCE skips ns-3 event");
            if (at > now) Simulator::Schedule(NanoSeconds(at - now), [] {});
            size_t count = 0;
            while (NextTime() == at)
            {
                Require(++count <= MAX_BATCH, "same-timestamp event limit");
                Simulator::Run();
            }
            Require(Simulator::Now().GetNanoSeconds() == at, "ns-3 boundary mismatch");
            wire.Send("BOUNDARY " + std::to_string(at) + " " + std::to_string(NextTime()) +
                      " " + std::to_string(trace.rows.size()));
            for (const auto& row : trace.rows) wire.Send(row);
            trace.rows.clear();
        }
        else if (tag == "INJECT")
        {
            int64_t at;
            size_t count;
            Parse(line, tag, at, count);
            Require(at == Simulator::Now().GetNanoSeconds() && count <= 1, "invalid INJECT");
            for (size_t i = 0; i < count; ++i)
            {
                Result result;
                std::string cause;
                Parse(wire.Read(), tag, result.id, result.m1, result.m2, cause);
                Require(tag == "RESULT" && result.m1 >= 0 && result.m1 <= 1 &&
                        result.m2 >= 0 && result.m2 <= 1, "invalid BSM result");
                result.processor = R;
                result.state = "COMPLETED";
                result.code = "OK";
                completionCauses[result.id] = cause;
                Simulator::ScheduleNow(&CosimAgentApp::ReceiveResult, agents[R], result);
            }
            wire.Send("INJECTED " + std::to_string(NextTime()));
        }
        else throw std::runtime_error("unknown P1 command");
    }
    Simulator::Destroy();
}
} // namespace

int main(int argc, char** argv)
{
    int bridgeFd = -1;
    CommandLine cmd(__FILE__);
    cmd.AddValue("bridgeFd", "Inherited Unix socket from run_p1.py", bridgeFd);
    cmd.Parse(argc, argv);
    try
    {
        Require(bridgeFd >= 0, "launch with contrib/cosim/python/run_p1.py");
        Wire wire(bridgeFd);
        RunParticipant(wire);
        close(bridgeFd);
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "cosim-p1: " << error.what() << '\n';
        Simulator::Destroy();
        return 1;
    }
}
