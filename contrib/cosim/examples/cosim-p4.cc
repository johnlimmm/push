// P4: 유한 background UDP와 device FIFO를 계측한다. 양자 경로는 P2와 같다.
#include "../model/cosim-bridge.h"
#include "ns3/cosim-agent-app.h"
#include "ns3/core-module.h"
#include "ns3/internet-module.h"
#include "ns3/network-module.h"
#include "ns3/point-to-point-module.h"
#include "ns3/traffic-control-helper.h"
#include "ns3/traffic-control-layer.h"

#include <iostream>
#include <map>
#include <vector>

using namespace ns3;
using namespace ns3::cosim;
using namespace ns3::cosim::bridge;

namespace
{
constexpr uint32_t CONTROLLER = 0, A = 1, R = 2, B = 3;
constexpr uint16_t PORT = 9000, BG_PORT = 9001;

// 고정 길이 60-byte 헤더. fidelity나 양자 상태는 패킷에 싣지 않는다.
// txSequence는 패킷 수신을 송신 이벤트에 연결하는 인과관계 식별자다.
class P4Header : public Header
{
  public:
    uint8_t kind{1}; // 1: 명령, 2: 결과, 3: command-link 배경, 4: result-link 배경
    uint64_t session{1}, request{1}, message{1}, pairA{1}, pairB{2}, output{3};
    int m1{-1}, m2{-1};
    uint64_t txSequence{0};

    static TypeId GetTypeId()
    {
        static TypeId tid = TypeId("ns3::cosim::P4Header")
                                .SetParent<Header>().AddConstructor<P4Header>();
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
        Require(kind >= 1 && kind <= 4, "invalid packet kind");
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

struct Flow
{
    int64_t start, interval;
    uint32_t count, bytes;
};

struct TraceBuffer
{
    uint64_t sequence{0};
    std::vector<std::string> rows;
    uint64_t Add(const std::string& type, uint32_t node, const P4Header& h,
                 const std::string& cause, uint32_t bytes = 0, int64_t depth = -1)
    {
        uint64_t id = sequence++;
        std::ostringstream out;
        out << "TRACE " << id << ' ' << Simulator::Now().GetNanoSeconds() << ' '
            << type << ' ' << node << ' ' << h.message << ' ' << cause << ' '
            << h.session << ' ' << h.request << ' ' << h.pairA << ' ' << h.pairB
            << ' ' << h.output << ' ' << h.m1 << ' ' << h.m2 << ' ' << bytes
            << ' ' << unsigned(h.kind) << ' ' << depth;
        rows.push_back(out.str());
        return id;
    }
};

std::string EventIdString(uint64_t id) { return "n:" + std::to_string(id); }

P4Header ReadMessage(Ptr<Packet> packet)
{
    P4Header h;
    Require(packet->GetSize() >= h.GetSerializedSize(), "short UDP payload");
    packet->RemoveHeader(h);
    return h;
}

// Queue/PHY 패킷에는 PPP/IP/UDP가 붙어 있다. port와 종류를 함께 검증한다.
P4Header ReadWire(Ptr<const Packet> packet, bool hasPpp = true)
{
    auto copy = packet->Copy();
    PppHeader ppp;
    Ipv4Header ipv4;
    UdpHeader udp;
    if (hasPpp) copy->RemoveHeader(ppp);
    copy->RemoveHeader(ipv4);
    Require(ipv4.GetProtocol() == 17, "P4 expects UDP only");
    copy->RemoveHeader(udp);
    auto h = ReadMessage(copy);
    Require(udp.GetDestinationPort() == (h.kind <= 2 ? PORT : BG_PORT), "kind/port mismatch");
    return h;
}

void TracePhy(TraceBuffer* trace, std::string type, uint32_t node, Ptr<const Packet> packet)
{
    auto h = ReadWire(packet);
    trace->Add(type, node, h, EventIdString(h.txSequence), packet->GetSize());
}

void TraceQueue(TraceBuffer* trace, std::string type, uint32_t node,
                Queue<Packet>* queue, Ptr<const Packet> packet)
{
    auto h = ReadWire(packet);
    // ns-3 queue는 상태 갱신 후 callback을 호출하므로 event 직후의 길이다.
    trace->Add(type, node, h, EventIdString(h.txSequence), packet->GetSize(), queue->GetNPackets());
}

void TraceTcDrop(TraceBuffer* trace, uint32_t node, Ptr<const Packet> packet)
{
    // QueueDisc가 없어도 device flow control이 송신을 막으면 TC에서 버린다.
    // 이 시점에는 IPv4/UDP만 있고 PPP header는 아직 붙지 않았다.
    auto h = ReadWire(packet, false);
    trace->Add("TC_DROP", node, h, EventIdString(h.txSequence), packet->GetSize());
}

void RunParticipant(Wire& wire)
{
    Time::SetResolution(Time::NS);
    Simulator::SetImplementation(CreateObject<SteppingSimulator>());
    ObjectFactory factory;
    factory.SetTypeId(VisibleScheduler::GetTypeId());
    Simulator::SetScheduler(factory);
    wire.Send("HELLO COSIM_P4 1");
    std::string tag, rootCause;
    uint64_t session, commandRate, resultRate;
    int64_t commandAt, commandDelay, resultDelay;
    uint32_t commandBytes, resultBytes;
    uint32_t queuePackets;
    Parse(wire.Read(), tag, session, commandAt, commandRate, commandDelay,
          resultRate, resultDelay, commandBytes, resultBytes, queuePackets, rootCause);
    Require(tag == "CONFIG" && session > 0 && commandAt >= 0 && commandAt <= MAX_TIME &&
            commandRate > 0 && resultRate > 0 && commandDelay >= 0 && resultDelay >= 0 &&
            commandBytes >= 60 && commandBytes <= 1400 && resultBytes >= 60 &&
            resultBytes <= 1400 && queuePackets > 0 && queuePackets <= 65536, "invalid P4 CONFIG");
    std::vector<Flow> flows;
    for (const auto& side : {"command", "result"})
    {
        Flow flow;
        std::string name;
        Parse(wire.Read(), tag, name, flow.start, flow.interval, flow.count, flow.bytes);
        Require(tag == "FLOW" && name == side && flow.start >= 0 && flow.start <= MAX_TIME &&
                flow.interval > 0 && flow.interval <= MAX_TIME && flow.count <= 2000 &&
                flow.bytes >= 60 && flow.bytes <= 1400, "invalid FLOW");
        Require(flow.count == 0 || (flow.count - 1) <= (MAX_TIME - flow.start) / flow.interval,
                "background time overflow");
        flows.push_back(flow);
    }

    NodeContainer nodes;
    nodes.Create(4); // 0=Controller, 1=A, 2=R, 3=B
    InternetStackHelper internet;
    internet.SetIpv6StackInstall(false);
    internet.Install(nodes);
    TraceBuffer trace;
    for (auto node : {CONTROLLER, R, B})
    {
        nodes.Get(node)->GetObject<TrafficControlLayer>()->TraceConnectWithoutContext("TcDrop",
            MakeBoundCallback(&TraceTcDrop, &trace, node));
    }
    auto link = [&](uint32_t from, uint32_t to, uint64_t rate, int64_t delay,
                    const char* subnet) {
        PointToPointHelper helper;
        helper.SetDeviceAttribute("DataRate", DataRateValue(DataRate(rate)));
        helper.SetDeviceAttribute("InterframeGap", TimeValue(NanoSeconds(0)));
        helper.SetChannelAttribute("Delay", TimeValue(NanoSeconds(delay)));
        helper.SetQueue("ns3::DropTailQueue<Packet>", "MaxSize", QueueSizeValue(QueueSize(std::to_string(queuePackets) + "p")));
        auto devices = helper.Install(NodeContainer(nodes.Get(from), nodes.Get(to)));
        Ipv4AddressHelper address;
        address.SetBase(subnet, "255.255.255.0");
        auto interfaces = address.Assign(devices);
        // 단일 FIFO 대기시간을 분리하기 위해 자동 설치되는 QueueDisc를 제거한다.
        TrafficControlHelper traffic;
        traffic.Uninstall(devices);
        for (uint32_t i = 0; i < 2; ++i)
        {
            uint32_t node = i == 0 ? from : to;
            devices.Get(i)->TraceConnectWithoutContext("PhyTxBegin",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_TX"), node));
            devices.Get(i)->TraceConnectWithoutContext("PhyTxEnd",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_TX_END"), node));
            devices.Get(i)->TraceConnectWithoutContext("PhyTxDrop",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_TX_DROP"), node));
            devices.Get(i)->TraceConnectWithoutContext("PhyRxDrop",
                MakeBoundCallback(&TracePhy, &trace, std::string("PHY_RX_DROP"), node));
            auto queue = DynamicCast<PointToPointNetDevice>(devices.Get(i))->GetQueue();
            for (const auto& entry : std::vector<std::pair<std::string, std::string>>{
                     {"Enqueue", "QUEUE_ENQUEUE"}, {"Dequeue", "QUEUE_DEQUEUE"}, {"Drop", "QUEUE_DROP"}})
            {
                queue->TraceConnectWithoutContext(entry.first,
                    MakeBoundCallback(&TraceQueue, &trace, entry.second, node, PeekPointer(queue)));
            }
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
    // 별도 UDP port로 수신한 background는 trace만 남기며 양자 요청을 만들지 않는다.
    std::map<uint32_t, Ptr<CosimAgentApp>> background;
    for (auto node : {CONTROLLER, R, B})
    {
        auto app = CreateObject<CosimAgentApp>();
        nodes.Get(node)->AddApplication(app);
        background[node] = app;
        app->BindUdp(BG_PORT, [&, node](Ptr<Packet> packet, const Address&) {
            auto bytes = packet->GetSize();
            auto h = ReadMessage(packet);
            Require(h.session == 0 && ((node == R && h.kind == 3) ||
                    (node == B && h.kind == 4)), "unexpected background destination");
            trace.Add("BACKGROUND_RX", node, h, EventIdString(h.txSequence), bytes);
        });
    }
    auto send = [&](uint32_t from, const Address& destination, P4Header h,
                    uint32_t bytes, const std::string& cause) {
        h.txSequence = trace.Add(h.kind > 2 ? "BACKGROUND_TX" :
                                  (h.kind == 1 ? "COMMAND_TX" : "RESULT_TX"), from, h, cause, bytes);
        auto packet = Create<Packet>(bytes - h.GetSerializedSize());
        packet->AddHeader(h);
        (h.kind > 2 ? background : agents).at(from)->SendUdp(packet, destination);
    };
    // 같은 시각이면 background를 먼저 enqueue한다. 모든 유한 입력을 먼저 등록한다.
    for (uint32_t side = 0; side < flows.size(); ++side)
    {
        const auto flow = flows[side];
        for (uint32_t i = 0; i < flow.count; ++i)
        {
            P4Header h;
            h.kind = side + 3;
            h.session = h.request = h.pairA = h.pairB = h.output = 0;
            h.message = (side == 0 ? 1000 : 100000) + i;
            Simulator::Schedule(NanoSeconds(flow.start + i * flow.interval), [&, h, side, flow] {
                auto to = side == 0 ? cr.GetAddress(1) : rb.GetAddress(1);
                send(side == 0 ? CONTROLLER : R, InetSocketAddress(to, BG_PORT), h, flow.bytes, rootCause);
            });
        }
    }
    P4Header command;
    command.session = session;
    Simulator::Schedule(NanoSeconds(commandAt), [&, command] {
        send(CONTROLLER, InetSocketAddress(cr.GetAddress(1), PORT), command, commandBytes, rootCause);
    });
    // 양자 완료 응답을 R 앱에 전달한 뒤 실제 결과 패킷을 송신한다.
    std::map<uint64_t, std::string> completionCauses;
    agents[R]->SetResultCallback([&](int64_t at, const Result& result) {
        Require(result.state == "COMPLETED", "unexpected quantum response");
        P4Header h;
        h.session = session;
        h.kind = 2;
        h.request = result.id;
        h.m1 = result.m1;
        h.m2 = result.m2;
        h.message = 0;
        auto local = trace.Add("BSM_RESULT_LOCAL", R, h, completionCauses.at(result.id));
        auto cause = EventIdString(local);
        h.message = 2;
        send(R, InetSocketAddress(rb.GetAddress(1), PORT), h, resultBytes, cause);

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
        else throw std::runtime_error("unknown P4 command");
    }
    Simulator::Destroy();
}
} // namespace

int main(int argc, char** argv)
{
    int bridgeFd = -1;
    CommandLine cmd(__FILE__);
    cmd.AddValue("bridgeFd", "Inherited Unix socket from run_p4.py", bridgeFd);
    cmd.Parse(argc, argv);
    try
    {
        Require(bridgeFd >= 0, "launch with contrib/cosim/python/run_p4.py");
        Wire wire(bridgeFd);
        RunParticipant(wire);
        close(bridgeFd);
        return 0;
    }
    catch (const std::exception& error)
    {
        std::cerr << "cosim-p4: " << error.what() << '\n';
        Simulator::Destroy();
        return 1;
    }
}
